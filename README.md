# Traceback

```
 ▀▀█▀▀ █▀▀█ █▀▀█ █▀▀ █▀▀ █▀▀▄ █▀▀█ █▀▀ █ █
   █   █▄▄▀ █▄▄█ █   █▀▀ █▀▀▄ █▄▄█ █   █▀▄
   █   ▀ ▀▀ ▀  ▀ ▀▀▀ ▀▀▀ ▀▀▀  ▀  ▀ ▀▀▀ ▀ ▀
```

A terminal-based OSINT reconnaissance tool that runs entirely on your machine. Ask questions in plain English — Traceback figures out what to look up, runs the right tool, and gives you a readable report.

No cloud APIs. No accounts. No data leaves your machine unless a tool explicitly queries a public service.

---

## What It Does

- **Username lookup** — scans hundreds of platforms for matching profiles (via Sherlock)
- **Email lookup** — checks which services an email is registered on (via Holehe), with optional breach checking
- **Domain lookup** — pulls WHOIS registration data for any domain
- **Follow-up questions** — ask about your results without re-running tools ("which of those were gaming platforms?")
- **Session memory** — Traceback remembers prior lookups and connects the dots across queries
- **Safety guardrails** — declines requests that cross into doxxing, hacking, or accessing private records

## Requirements

- Python 3.11+
- macOS or Linux
- ~4GB free disk space (for the local AI model)

That's it. Everything else is handled automatically on first run.

## Install

```bash
git clone https://github.com/yourusername/traceback.git
cd traceback
pip install -r requirements.txt
```

## Usage

```bash
python3 main.py
```

On first launch, Traceback will:
1. Install Ollama (if not present)
2. Download the language model (~2GB)
3. Optionally fine-tune a local model for better accuracy

This is a one-time setup. Subsequent launches are instant.

### Examples

```
traceback> find accounts for username johndoe
traceback> what services is test@example.com signed up for
traceback> whois example.com
traceback> which of those results were social media platforms?
traceback> tell me more about the github account
```

### Commands

| Command | Description |
|---------|-------------|
| `help` | Show usage info |
| `quit` / `exit` | Exit the tool |

## How It Works

```
user input → safety filter → intent parser → tool dispatch → result summary
                                                    ↓
                                            session memory
```

1. **Safety filter** checks for disallowed request patterns
2. **Intent parser** uses a local LLM to determine what you're asking for
3. **Tool dispatch** runs the appropriate OSINT tool
4. **Synthesizer** writes a detailed report from the raw results
5. **Session memory** tracks lookups so follow-up questions work and cross-query analysis is possible

If no tool matches, but you've already run a lookup, Traceback treats your input as a follow-up question about prior results.

## Project Structure

```
traceback/
├── main.py              # CLI entry point
├── config.py            # Model and API settings
├── core/
│   ├── llm.py           # Ollama interface + auto-setup
│   ├── intent.py        # Natural language → structured intent
│   ├── safety.py        # Ethics filter
│   ├── session.py       # Session memory + escalation detection
│   ├── synthesizer.py   # Results → prose report
│   └── ui.py            # Terminal colors and formatting
├── tools/
│   ├── username.py      # Sherlock wrapper
│   ├── email.py         # Holehe + HIBP wrapper
│   └── domain.py        # WHOIS + Shodan wrapper
└── data/finetune/
    ├── train.jsonl       # Training examples
    └── finetune.py       # Auto fine-tuning script
```

## Optional API Keys

These are **not required**. The core tool works without any API keys. If you want extended coverage, set them in `config.py`:

- `HIBP_API_KEY` — [HaveIBeenPwned](https://haveibeenpwned.com/API/Key) for email breach data
- `SHODAN_API_KEY` — [Shodan](https://shodan.io) for domain/IP scanning

## License

MIT
