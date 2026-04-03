"""Configuration for OSINT CLI."""

# Ollama settings
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_BASE_URL = "http://localhost:11434"

# Inference tuning (conservative for local hardware)
OLLAMA_OPTIONS = {
    "temperature": 0.1,
    "num_ctx": 4096,
    "num_predict": 2048,
}

# Optional API keys — leave empty to skip those tools
HIBP_API_KEY = ""
SHODAN_API_KEY = ""
