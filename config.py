"""Configuration for Traceback OSINT CLI."""

OLLAMA_BASE_URL = "http://localhost:11434"

# these get overwritten by setup.py on first run
OLLAMA_MODEL = "gemma4:e4b"
OLLAMA_OPTIONS = {
    "temperature": 0.1,
    "num_ctx": 16384,
    "num_predict": 4096,
}

# hardware tier - controls concurrency and supplementary searches
TIER = "low"

# how many tools can run at once per tier
TIER_MAX_WORKERS = {
    "low": 2,
    "mid": 3,
    "high": 4,
}

# all tiers get web enrichment now since smallest model is 8b
TIER_WEB_ENRICH = {
    "low": True,
    "mid": True,
    "high": True,
}


def apply_model_config(model_config: dict):
    """Apply model settings from first-run setup."""
    global OLLAMA_MODEL, OLLAMA_OPTIONS, TIER
    OLLAMA_MODEL = model_config["model"]
    OLLAMA_OPTIONS = model_config["options"]
    TIER = model_config.get("tier", "low")
