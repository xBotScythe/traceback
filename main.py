#!/usr/bin/env python3
"""Traceback — local AI-powered OSINT tool."""

import config
from core import llm
from core.intent import parse
from core.safety import SafetyFilter
from core.session import Session
from core.synthesizer import format as summarize, followup
from core.ui import *
from data.finetune.finetune import auto_finetune
from tools import dispatch
import tools.username  # register tools
import tools.email
import tools.domain


BANNER = f"""
{DIM}┌──────────────────────────────────────────────────────────┐{RESET}
{DIM}│{RESET}                                                          {DIM}│{RESET}
{DIM}│{RESET}  {BOLD}{CYAN} ▀▀█▀▀ █▀▀█ █▀▀█ █▀▀ █▀▀ █▀▀▄ █▀▀█ █▀▀ █ █  {RESET}  {DIM}│{RESET}
{DIM}│{RESET}  {BOLD}{CYAN}   █   █▄▄▀ █▄▄█ █   █▀▀ █▀▀▄ █▄▄█ █   █▀▄  {RESET}  {DIM}│{RESET}
{DIM}│{RESET}  {BOLD}{CYAN}   █   ▀ ▀▀ ▀  ▀ ▀▀▀ ▀▀▀ ▀▀▀  ▀  ▀ ▀▀▀ ▀ ▀  {RESET}  {DIM}│{RESET}
{DIM}│{RESET}                                                          {DIM}│{RESET}
{DIM}│{RESET}  {DIM}Local AI-powered OSINT reconnaissance tool{RESET}              {DIM}│{RESET}
{DIM}│{RESET}  {DIM}Type 'help' for usage, 'quit' to exit{RESET}                  {DIM}│{RESET}
{DIM}│{RESET}                                                          {DIM}│{RESET}
{DIM}└──────────────────────────────────────────────────────────┘{RESET}
"""

HELP_TEXT = f"""
{BOLD}Commands:{RESET}
  {CYAN}help{RESET}              Show this message
  {CYAN}quit / exit{RESET}       Exit the tool

{BOLD}Examples:{RESET}
  {GREEN}find accounts for username johndoe{RESET}
  {GREEN}check what services use this email test@example.com{RESET}
  {GREEN}whois example.com{RESET}

{BOLD}Follow-up:{RESET}
  {DIM}After a lookup, ask questions about the results:{RESET}
  {GREEN}which of those are social media?{RESET}
  {GREEN}categorize the results{RESET}
"""


def main():
    print(BANNER)

    # Auto-setup: install Ollama, start server, pull model
    print(status("Checking Ollama setup..."))
    llm.ensure_ready()

    # Auto fine-tune: train + import on first run, skip if already done
    finetuned = auto_finetune()
    if finetuned:
        config.OLLAMA_MODEL = finetuned
        print(success(f"Using fine-tuned model: {finetuned}"))
    else:
        print(status(f"Using base model: {config.OLLAMA_MODEL}"))

    print(success("Ready.") + "\n")

    safety = SafetyFilter()
    session = Session()

    while True:
        try:
            user_input = input(prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Bye.{RESET}")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print(f"{DIM}Bye.{RESET}")
            break

        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        # Safety filter runs first — no exceptions
        decline = safety.check(user_input)
        if decline:
            print(f"\n{blocked(decline)}\n")
            continue

        try:
            # Parse natural language into structured intent
            intent = parse(user_input)

            if intent["type"] == "unknown":
                # If we have session history, treat as a follow-up question
                all_context = session.get_all_context()
                if all_context:
                    print()
                    answer = followup(user_input, all_context)
                    print(f"{answer}\n")
                else:
                    print(f"\n{warn('Could not parse that request.')}")
                    print(f"  {DIM}Try something like: 'find accounts for username johndoe'{RESET}\n")
                continue

            value = intent["value"]

            # Check session escalation on this target
            escalation = session.check_escalation(value)
            if escalation:
                print(f"\n{blocked(escalation)}\n")
                continue

            print(f"\n{status(intent['type'])} {BOLD}{value}{RESET}")
            print(working())

            result = dispatch(intent)

            if "error" in result:
                print(f"{error(result['error'])}\n")
            else:
                # Record in session memory
                session.record(intent["type"], value, result)

                # Get prior context for richer summaries
                context = session.get_context_summary(value)
                summary = summarize(result, prior_context=context, user_input=user_input)
                print(f"\n{summary}\n")

        except (ConnectionError, RuntimeError) as e:
            print(f"{error(str(e))}\n")


if __name__ == "__main__":
    main()
