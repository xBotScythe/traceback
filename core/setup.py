"""First-run setup: model selection based on system specs + dependency install."""

import json
import os
import platform
import re
import subprocess
import sys

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".traceback_config.json")

TIERS = {
    "low": {
        "model": "gemma4:e4b",
        "label": "Low",
        "desc": "Baseline. ~10GB download, 128K context. Works on 8GB+ RAM.",
        "options": {"temperature": 0.1, "num_ctx": 16384, "num_predict": 4096},
    },
    "mid": {
        "model": "gemma4:26b",
        "label": "Mid",
        "desc": "Recommended. MoE ~18GB download, 256K context. 16GB+ RAM.",
        "options": {"temperature": 0.1, "num_ctx": 32768, "num_predict": 4096},
    },
    "high": {
        "model": "gemma4:31b",
        "label": "High",
        "desc": "Best accuracy. Dense 31B, ~20GB download, 256K context. 24GB+ RAM.",
        "options": {"temperature": 0.1, "num_ctx": 65536, "num_predict": 8192},
    },
}

REQUIRED_PACKAGES = [
    "sherlock-project",
    "holehe",
    "python-whois",
    "phonenumbers",
    "ddgs",
    "googlesearch-python",
]


def _get_ram_gb() -> float:
    try:
        if platform.system() == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            return int(out.strip()) / (1024 ** 3)
        elif platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        return int(line.split()[1]) / (1024 ** 2)
        elif platform.system() == "Windows":
            out = subprocess.check_output(
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                text=True,
            )
            for line in out.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line) / (1024 ** 3)
    except Exception:
        pass
    return 0


def _get_gpu_info() -> dict:
    """Detect GPU type and VRAM where possible.

    Returns dict with:
        type: 'apple_silicon' | 'nvidia' | 'amd' | 'intel_integrated' | 'unknown'
        name: human readable GPU name
        vram_gb: dedicated VRAM in GB (0 if shared/unknown)
        chip: specific chip name for apple silicon (e.g. 'M4')
    """
    info = {"type": "unknown", "name": "Unknown", "vram_gb": 0, "chip": ""}
    system = platform.system()

    # apple silicon - unified memory means RAM = VRAM effectively
    if system == "Darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
            if "Apple" in out:
                info["type"] = "apple_silicon"
                info["name"] = out
                # figure out which chip (M1, M2, M3, M4, etc.)
                chip_match = re.search(r"(M\d+(?:\s+(?:Pro|Max|Ultra))?)", out)
                if chip_match:
                    info["chip"] = chip_match.group(1)
                # apple silicon shares RAM as VRAM, so report total RAM
                info["vram_gb"] = _get_ram_gb()
                return info
        except Exception:
            pass

        # intel mac, check for discrete GPU
        try:
            out = subprocess.check_output(["system_profiler", "SPDisplaysDataType"], text=True)
            if "NVIDIA" in out.upper():
                info["type"] = "nvidia"
            elif "AMD" in out.upper() or "RADEON" in out.upper():
                info["type"] = "amd"
            else:
                info["type"] = "intel_integrated"

            for line in out.splitlines():
                if "Chipset Model" in line:
                    info["name"] = line.split(":", 1)[-1].strip()
                elif "VRAM" in line:
                    vram_str = line.split(":", 1)[-1].strip()
                    vram_match = re.search(r"(\d+)\s*(MB|GB)", vram_str, re.IGNORECASE)
                    if vram_match:
                        val = int(vram_match.group(1))
                        if vram_match.group(2).upper() == "MB":
                            val /= 1024
                        info["vram_gb"] = val
        except Exception:
            pass
        return info

    # linux - check nvidia first, then AMD, then fallback
    if system == "Linux":
        # nvidia
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                text=True, stderr=subprocess.DEVNULL,
            )
            for line in out.strip().splitlines():
                parts = line.split(",")
                if len(parts) >= 2:
                    info["type"] = "nvidia"
                    info["name"] = parts[0].strip()
                    info["vram_gb"] = float(parts[1].strip()) / 1024
                    return info
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # AMD via rocm-smi
        try:
            out = subprocess.check_output(["rocm-smi", "--showmeminfo", "vram"], text=True, stderr=subprocess.DEVNULL)
            info["type"] = "amd"
            info["name"] = "AMD GPU"
            for line in out.splitlines():
                if "Total" in line:
                    nums = re.findall(r"(\d+)", line)
                    if nums:
                        # rocm reports in bytes usually
                        total = int(nums[0])
                        if total > 1_000_000:
                            info["vram_gb"] = total / (1024 ** 3)
                        else:
                            info["vram_gb"] = total / 1024
            return info
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # check lspci for what GPU is present
        try:
            out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                lower = line.lower()
                if "vga" in lower or "3d" in lower or "display" in lower:
                    if "nvidia" in lower:
                        info["type"] = "nvidia"
                        info["name"] = line.split(":", 2)[-1].strip()
                    elif "amd" in lower or "radeon" in lower:
                        info["type"] = "amd"
                        info["name"] = line.split(":", 2)[-1].strip()
                    elif "intel" in lower:
                        info["type"] = "intel_integrated"
                        info["name"] = line.split(":", 2)[-1].strip()
                    break
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        return info

    # windows
    if system == "Windows":
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM"],
                text=True,
            )
            for line in out.strip().splitlines()[1:]:
                line = line.strip()
                if not line:
                    continue
                # AdapterRAM is first (bytes), Name is second
                parts = re.split(r"\s{2,}", line)
                if len(parts) >= 2:
                    try:
                        vram_bytes = int(parts[0])
                        info["vram_gb"] = vram_bytes / (1024 ** 3)
                    except ValueError:
                        pass
                    gpu_name = parts[-1] if len(parts) > 1 else parts[0]
                    info["name"] = gpu_name
                    name_lower = gpu_name.lower()
                    if "nvidia" in name_lower or "geforce" in name_lower or "rtx" in name_lower or "gtx" in name_lower:
                        info["type"] = "nvidia"
                    elif "amd" in name_lower or "radeon" in name_lower:
                        info["type"] = "amd"
                    elif "intel" in name_lower:
                        info["type"] = "intel_integrated"
                    break
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        # also try nvidia-smi on windows since wmic can underreport VRAM
        if info["type"] == "nvidia":
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                    text=True, stderr=subprocess.DEVNULL,
                )
                parts = out.strip().split(",")
                if len(parts) >= 2:
                    info["name"] = parts[0].strip()
                    info["vram_gb"] = float(parts[1].strip()) / 1024
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass

        return info

    return info


def detect_tier() -> str:
    """Pick a tier based on GPU and RAM.
    Gemma 4 models are much smaller than the old llama lineup:
      e4b ~10GB, 26b MoE ~18GB, 31b dense ~20GB
    """
    gpu = _get_gpu_info()
    ram = _get_ram_gb()

    # apple silicon shares RAM as VRAM
    # gemma4:31b (dense ~20GB) needs 32GB+ to avoid swap on apple silicon
    # gemma4:26b (MoE ~16GB active) runs well on 20GB+
    if gpu["type"] == "apple_silicon":
        if ram >= 32:
            return "high"
        elif ram >= 20:
            return "mid"
        return "low"

    # nvidia
    if gpu["type"] == "nvidia":
        vram = gpu["vram_gb"]
        if vram >= 24:
            return "high"
        elif vram >= 12:
            return "mid"
        return "low"

    # amd
    if gpu["type"] == "amd":
        vram = gpu["vram_gb"]
        if vram >= 24:
            return "high"
        elif vram >= 12:
            return "mid"
        return "low"

    # intel integrated or unknown - go by RAM
    if ram >= 32:
        return "mid"
    return "low"


def _format_specs(ram: float, gpu: dict) -> str:
    """One-line summary of detected hardware."""
    parts = []
    if ram > 0:
        parts.append(f"{ram:.0f}GB RAM")

    if gpu["type"] == "apple_silicon":
        chip = gpu["chip"] or "Apple Silicon"
        parts.append(f"{chip} (unified memory)")
    elif gpu["type"] == "nvidia":
        label = gpu["name"] or "NVIDIA GPU"
        if gpu["vram_gb"] > 0:
            label += f" ({gpu['vram_gb']:.0f}GB VRAM)"
        parts.append(label)
    elif gpu["type"] == "amd":
        label = gpu["name"] or "AMD GPU"
        if gpu["vram_gb"] > 0:
            label += f" ({gpu['vram_gb']:.0f}GB VRAM)"
        parts.append(label)
    elif gpu["type"] == "intel_integrated":
        parts.append(f"{gpu['name'] or 'Intel integrated graphics'} (no dedicated VRAM)")
    else:
        parts.append("GPU not detected")

    return ", ".join(parts)


def load_config() -> dict | None:
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_config(tier: str, old_model: str = None):
    data = {"tier": tier, "model": TIERS[tier]["model"]}
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)

    # clean up the old model if switching to a different one
    new_model = TIERS[tier]["model"]
    if old_model and old_model != new_model:
        _remove_model(old_model)


def _remove_model(model: str):
    """Delete a model from Ollama to free disk space."""
    print(f"  Removing old model '{model}' to save space...")
    try:
        subprocess.run(
            ["ollama", "rm", model],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        print(f"  Removed '{model}'.")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print(f"  Could not remove '{model}'. You can do it manually: ollama rm {model}")


def prompt_user_for_tier(old_model: str = None) -> str:
    auto_tier = detect_tier()
    ram = _get_ram_gb()
    gpu = _get_gpu_info()

    print("\n  First time setup - let's pick a model for your system.")
    specs = _format_specs(ram, gpu)
    if specs:
        print(f"  Detected: {specs}")
    print()

    print("  Available profiles:\n")
    for key in ("low", "mid", "high"):
        tier = TIERS[key]
        rec = " (recommended)" if key == auto_tier else ""
        print(f"    [{key}] {tier['label']}{rec}")
        print(f"          {tier['desc']}")
        print(f"          Model: {tier['model']}\n")

    print(f"    [auto] Let Traceback pick (would choose: {auto_tier})\n")

    while True:
        choice = input("  Pick a profile [low/mid/high/auto]: ").strip().lower()
        if choice == "auto":
            choice = auto_tier
        if choice in TIERS:
            save_config(choice, old_model=old_model)
            tier = TIERS[choice]
            print(f"\n  Using {tier['model']}. You can change this later by deleting .traceback_config.json\n")
            return choice
        print("  Invalid choice. Try low, mid, high, or auto.")


def get_model_config() -> dict:
    saved = load_config()
    if saved and saved.get("tier") in TIERS:
        tier_name = saved["tier"]
        tier = TIERS[tier_name]
        # if model changed (e.g. upgraded to gemma4), re-prompt
        if saved.get("model") and saved["model"] != tier["model"]:
            print(f"\n  Models have been updated. Old: {saved['model']} -> New: {tier['model']}")
            old_model = saved["model"]
            choice = prompt_user_for_tier(old_model=old_model)
            tier = TIERS[choice]
            return {"model": tier["model"], "options": tier["options"], "tier": choice}
        return {"model": tier["model"], "options": tier["options"], "tier": tier_name}

    # pass the old model name so it can be cleaned up if switching
    old_model = saved.get("model") if saved else None
    choice = prompt_user_for_tier(old_model=old_model)
    tier = TIERS[choice]
    return {"model": tier["model"], "options": tier["options"], "tier": choice}


def install_packages():
    missing = []
    for pkg in REQUIRED_PACKAGES:
        import_name = pkg.replace("-", "_")
        import_map = {
            "sherlock_project": "sherlock",
            "python_whois": "whois",
            "ddgs": "ddgs",
            "googlesearch_python": "googlesearch",
        }
        check_name = import_map.get(import_name, import_name)

        try:
            __import__(check_name)
        except ImportError:
            missing.append(pkg)

    if not missing:
        return

    print(f"  Installing missing packages: {', '.join(missing)}")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + missing,
            stdout=subprocess.DEVNULL,
        )
        print("  Packages installed.")
    except subprocess.CalledProcessError:
        print(f"  [!] Failed to install: {', '.join(missing)}")
        print(f"      Try manually: pip install {' '.join(missing)}")
