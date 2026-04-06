"""Ollama interface with automatic setup."""

import json
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error

import config

_we_started_server = False
_server_process = None


def _ollama_bin() -> str | None:
    """Return path to ollama binary, or None."""
    return shutil.which("ollama")


def _is_server_running() -> bool:
    """Check if Ollama server is responding."""
    try:
        req = urllib.request.Request(f"{config.OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _install_ollama():
    """Install Ollama via the official install script (macOS/Linux)."""
    print("[setup] Ollama not found. Installing...")
    try:
        subprocess.run(
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            check=True,
        )
        print("[setup] Ollama installed.")
    except subprocess.CalledProcessError:
        print("[error] Failed to install Ollama automatically.")
        print("        Install manually: https://ollama.com/download")
        sys.exit(1)


def _start_server():
    """Start Ollama server in the background."""
    global _we_started_server, _server_process
    print("[setup] Starting Ollama server...")
    _server_process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # give it a sec to boot
    for _ in range(15):
        if _is_server_running():
            _we_started_server = True
            print("[setup] Ollama server ready.")
            return
        time.sleep(1)
    print("[error] Ollama server failed to start.")
    sys.exit(1)


def stop_server():
    """Stop the Ollama server."""
    global _server_process

    # if we spawned the process, terminate it directly
    if _server_process is not None:
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_process.kill()
        _server_process = None

    # also shut down any running ollama serve process
    try:
        subprocess.run(
            ["pkill", "-f", "ollama serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def _model_available() -> bool:
    """Check if the configured model is already pulled."""
    try:
        req = urllib.request.Request(f"{config.OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            names = [m["name"] for m in data.get("models", [])]
            # ollama sometimes appends :latest
            return any(
                n == config.OLLAMA_MODEL or n == f"{config.OLLAMA_MODEL}:latest"
                or config.OLLAMA_MODEL in n
                for n in names
            )
    except (urllib.error.URLError, OSError):
        return False


def _update_ollama():
    """Re-run the install script to update Ollama."""
    print("[setup] Updating Ollama...")
    try:
        subprocess.run(
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            check=True,
        )
        print("[setup] Ollama updated.")
    except subprocess.CalledProcessError:
        print("[error] Failed to update Ollama.")
        print("        Update manually: https://ollama.com/download")
        sys.exit(1)


def _pull_model():
    """Pull the configured model, updating Ollama if needed."""
    print(f"[setup] Pulling model '{config.OLLAMA_MODEL}' (this may take a few minutes)...")
    try:
        # let output flow through so the user sees download progress
        result = subprocess.run(["ollama", "pull", config.OLLAMA_MODEL])

        if result.returncode == 0:
            print(f"[setup] Model '{config.OLLAMA_MODEL}' ready.")
            return

        # re-run with capture just to read the error message and decide what to do
        check = subprocess.run(
            ["ollama", "pull", config.OLLAMA_MODEL],
            capture_output=True, text=True,
        )
        if "newer version" in (check.stderr or "").lower():
            _update_ollama()
            _start_server()
            subprocess.run(["ollama", "pull", config.OLLAMA_MODEL], check=True)
            print(f"[setup] Model '{config.OLLAMA_MODEL}' ready.")
            return

        print(f"[error] Failed to pull '{config.OLLAMA_MODEL}'. Try: ollama pull {config.OLLAMA_MODEL}")
        sys.exit(1)
    except subprocess.CalledProcessError:
        print(f"[error] Failed to pull model '{config.OLLAMA_MODEL}'.")
        sys.exit(1)


def ensure_ready():
    """Make sure Ollama is installed, running, and has the model."""
    if not _ollama_bin():
        _install_ollama()

    if not _is_server_running():
        _start_server()

    if not _model_available():
        _pull_model()


def ask(prompt: str, system: str = "", format: str = "",
        stream_to=None) -> str:
    """Send a prompt to Ollama and return the response text.

    stream_to: optional callable that receives each text chunk as it arrives.
               The full text is still returned at the end.
    format: set to "json" to force JSON output from the model.
    """
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": stream_to is not None,
        "options": config.OLLAMA_OPTIONS,
    }
    if system:
        payload["system"] = system
    if format:
        payload["format"] = format

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{config.OLLAMA_BASE_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            if stream_to is not None:
                return _read_stream(resp, stream_to)
            result = json.loads(resp.read())
            text = result.get("response", "").strip()
            return _strip_markdown(text)
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama not reachable: {e}") from e
    except json.JSONDecodeError:
        raise RuntimeError("Ollama returned invalid JSON")


def _read_stream(resp, callback) -> str:
    """Read a streaming Ollama response, calling back with each chunk."""
    full_text = []
    for line in resp:
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
            token = chunk.get("response", "")
            if token:
                full_text.append(token)
                callback(token)
            if chunk.get("done"):
                break
        except json.JSONDecodeError:
            continue
    return _strip_markdown("".join(full_text).strip())


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting that local models love to add despite being told not to."""
    import re
    # convert markdown links [text](url) to just the url
    text = re.sub(r'\[([^\]]*)\]\((https?://[^)]+)\)', r'\2', text)
    # remove bold **text** and __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    # remove italic *text* and _text_ (but not dashes like - item)
    text = re.sub(r'(?<!\w)\*([^*\n]+?)\*(?!\w)', r'\1', text)
    # remove headers ## Header
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # convert * bullets to dashes
    text = re.sub(r'^(\s*)\* ', r'\1- ', text, flags=re.MULTILINE)
    return text
