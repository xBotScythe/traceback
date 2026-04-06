# Traceback

```
 ▀▀█▀▀ █▀▀█ █▀▀█ █▀▀ █▀▀ █▀▀▄ █▀▀█ █▀▀ █ █
   █   █▄▄▀ █▄▄█ █   █▀▀ █▀▀▄ █▄▄█ █   █▀▄
   █   ▀ ▀▀ ▀  ▀ ▀▀▀ ▀▀▀ ▀▀▀  ▀  ▀ ▀▀▀ ▀ ▀
```

A terminal-based OSINT reconnaissance tool that runs entirely on your machine. Ask questions in plain English — Traceback figures out what to look up, runs the right tools, and gives you a readable summary.

No cloud APIs. No accounts. No data leaves your machine unless a tool explicitly queries a public service.

---

## What It Does

- **Username lookup** — scans hundreds of platforms for matching profiles (via Sherlock)
- **Email lookup** — checks which services an email is registered on (via Holehe) + breach checking (XposedOrNot)
- **Domain lookup** — WHOIS, DNS records, and HTTP tech detection
- **Phone lookup** — validates numbers, identifies carriers, and searches for web mentions
- **Person search** — finds info on a real name using layered web search with OSINT dorks
- **Web search** — broad + targeted searches with automatic dorking across social platforms
- **Follow-up questions** — ask about your results without re-running tools
- **Session memory** — remembers prior lookups and connects the dots across queries
- **Report export** — save all findings to a text file
- **Safety guardrails** — declines requests that cross into doxxing, hacking, or accessing private records

## Requirements

- Python 3.11+
- macOS, Linux, or Windows
- 8GB+ RAM (16GB+ recommended for mid-tier model)

## Install

```bash
git clone https://github.com/xBotScythe/traceback.git
cd traceback
pip install -r requirements.txt
```

## Usage

```bash
python3 main.py
```

On first launch, Traceback will:
1. Install Ollama (if not present)
2. Auto-detect your hardware and recommend a model tier
3. Download the language model

This is a one-time setup. Subsequent launches are instant.

### Model Tiers

| Tier | Model | Size | RAM | Notes |
|------|-------|------|-----|-------|
| Low | gemma4:e4b | ~10GB | 8GB+ | 128K context, native JSON output |
| Mid | gemma4:26b (MoE) | ~18GB | 16GB+ | 256K context, fast despite size |
| High | gemma4:31b (Dense) | ~20GB | 24GB+ | 256K context, best accuracy |

### Examples

```
traceback> find accounts for username johndoe
traceback> check what services use test@example.com
traceback> whois example.com
traceback> who is Jane Doe
traceback> look up +1-555-123-4567
traceback> search the web for johndoe security researcher
traceback> which of those are social media?
traceback> export
```

### Commands

| Command | Description |
|---------|-------------|
| `help` | Show usage info |
| `export` / `report` | Save findings to a text file |
| `quit` / `exit` | Exit the tool |

## How It Works

```
user input → safety filter → fast-path regex / LLM intent parser → orchestrator → tools (concurrent) → synthesizer → response
                                                                        ↓
                                                                  session memory
```

1. **Safety filter** blocks disallowed request patterns
2. **Fast-path regex** catches obvious inputs (emails, domains, @mentions) without hitting the LLM
3. **Intent parser** uses a local LLM for ambiguous inputs
4. **Orchestrator** plans and runs tools concurrently, adding supplementary web searches where useful
5. **Synthesizer** turns raw tool output into a readable summary
6. **Session memory** tracks everything for follow-ups and cross-query analysis

## Project Structure

```
traceback/
├── main.py              # CLI loop
├── config.py            # Model and tier settings
├── core/
│   ├── llm.py           # Ollama interface + auto-setup
│   ├── intent.py        # Natural language → structured intent
│   ├── orchestrator.py  # Plans and runs tool jobs concurrently
│   ├── safety.py        # Ethics filter
│   ├── session.py       # Session memory + escalation detection
│   ├── synthesizer.py   # Tool results → readable summary
│   ├── report.py        # Export session to text file
│   ├── setup.py         # Hardware detection + model selection
│   └── ui.py            # Terminal colors and formatting
├── tools/
│   ├── __init__.py      # Tool registry and dispatch
│   ├── username.py      # Sherlock wrapper
│   ├── email.py         # Holehe + XposedOrNot
│   ├── domain.py        # WHOIS + DNS + HTTP probe
│   ├── phone.py         # Phone validation + web search
│   ├── person.py        # Person search via web dorks
│   └── websearch.py     # Layered web search engine
└── data/
    └── __init__.py
```

## License

MIT
