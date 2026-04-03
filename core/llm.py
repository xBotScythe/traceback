"""Ollama interface with automatic setup."""

import json
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error

import config


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
    print("[setup] Starting Ollama server...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server to come up
    for _ in range(15):
        if _is_server_running():
            print("[setup] Ollama server ready.")
            return
        time.sleep(1)
    print("[error] Ollama server failed to start.")
    sys.exit(1)


def _model_available() -> bool:
    """Check if the configured model is already pulled."""
    try:
        req = urllib.request.Request(f"{config.OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            names = [m["name"] for m in data.get("models", [])]
            # Match with or without :latest tag
            return any(
                n == config.OLLAMA_MODEL or n == f"{config.OLLAMA_MODEL}:latest"
                or config.OLLAMA_MODEL in n
                for n in names
            )
    except (urllib.error.URLError, OSError):
        return False


def _pull_model():
    """Pull the configured model."""
    print(f"[setup] Pulling model '{config.OLLAMA_MODEL}' (this may take a few minutes)...")
    try:
        subprocess.run(["ollama", "pull", config.OLLAMA_MODEL], check=True)
        print(f"[setup] Model '{config.OLLAMA_MODEL}' ready.")
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


def ask(prompt: str, system: str = "") -> str:
    """Send a prompt to Ollama and return the response text."""
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": config.OLLAMA_OPTIONS,
    }
    if system:
        payload["system"] = system

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{config.OLLAMA_BASE_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result.get("response", "").strip()
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama not reachable: {e}") from e
    except json.JSONDecodeError:
        raise RuntimeError("Ollama returned invalid JSON")
