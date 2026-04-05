#!/usr/bin/env python3
"""Traceback - local AI-powered OSINT tool."""

import sys

import config
from core import llm
from core.intent import parse
from core.orchestrator import run as orchestrate
from core.safety import SafetyFilter
from core.session import Session, parse_number_pick
from core.setup import get_model_config, install_packages
from core.report import generate as generate_report
from core.synthesizer import format as summarize, chat, investigate
from core.ui import *
import tools.username
import tools.email
import tools.domain
import tools.person
import tools.phone
import tools.websearch


def _thinking(msg="Thinking..."):
    sys.stdout.write(f"\r  {DIM}[...] {msg}{RESET}   ")
    sys.stdout.flush()

def _clear():
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def _resolve_pronouns(text: str, session) -> str:
    """Replace the first pronoun reference with the last target.

    Only replaces once to avoid garbling sentences where the user
    is providing new info about the person.
    """
    import re
    if not session.last_target:
        return text

    lower = text.lower()
    pronouns = ["their", "them", "they", "his", "her", "this user", "that user"]
    if not any(p in lower for p in pronouns):
        return text

    target = session.last_target
    resolved = re.sub(r"\b(their|them|they|his|her|this user|that user)('s)?\b",
                      target, text, count=1, flags=re.IGNORECASE)
    return resolved


def _extract_target(text: str) -> dict | None:
    """Fast regex extraction so obvious inputs skip the LLM entirely."""
    import re
    lower = text.lower().strip()

    # email
    m = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)
    if m:
        return {"type": "email_lookup", "value": m.group()}

    # phone number (7+ digits with optional +, dashes, parens, spaces)
    m = re.search(r'(\+?[\d][\d\s\-().]{6,}\d)', text)
    if m:
        digits = re.sub(r'[^\d+]', '', m.group(1))
        if len(digits) >= 7:
            return {"type": "phone_lookup", "value": m.group(1).strip()}

    # domain (has a dot, looks like a domain, not an email)
    m = re.search(r'\b([\w-]+\.(?:com|org|net|io|dev|co|me|info|edu|gov)\b)', text, re.IGNORECASE)
    if m:
        return {"type": "domain_lookup", "value": m.group(1)}

    # "who is Firstname Lastname" -> person lookup
    m = re.match(r'(?:who\s+is|find\s+info\s+on|look\s+up|investigate)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*$', text.strip())
    if m:
        return {"type": "person_lookup", "value": m.group(1)}

    # "find accounts for X" / "what platforms is X on" -> username lookup
    m = re.match(r'(?:find\s+accounts?\s+for(?:\s+username)?\s+|what\s+platforms?\s+is\s+)(\w{3,30})', lower)
    if m:
        return {"type": "username_lookup", "value": m.group(1)}

    # "X is a username" / "username is X" / "alias is X"
    _stop = {"the", "a", "an", "is", "its", "about", "called", "named", "and", "or", "but", "for", "with", "they", "their", "them"}
    m = re.search(r'(\w{3,30})\s+is\s+(?:a\s+)?(?:user\s*name|alias|handle)', lower)
    if m and m.group(1) not in _stop:
        return {"type": "username_lookup", "value": m.group(1)}
    m = re.search(r'(?:user\s*name|alias|handle)\s+is\s+(\w{3,30})', lower)
    if m and m.group(1) not in _stop:
        return {"type": "username_lookup", "value": m.group(1)}

    # @username
    m = re.search(r'@(\w{3,30})\b', text)
    if m:
        return {"type": "username_lookup", "value": m.group(1).lstrip("@")}

    # "search for X" / "search the web for X" / "google X" -> web search
    m = re.match(r'(?:search\s+(?:the\s+web\s+)?for|google)\s+(.+)', lower)
    if m:
        return {"type": "web_search", "value": m.group(1).strip()}

    return None


BANNER = f"""
{BOLD}{CYAN}  ████████╗██████╗  █████╗  ██████╗███████╗██████╗  █████╗  ██████╗██╗  ██╗
  ╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║ ██╔╝
     ██║   ██████╔╝███████║██║     █████╗  ██████╔╝███████║██║     █████╔╝
     ██║   ██╔══██╗██╔══██║██║     ██╔══╝  ██╔══██╗██╔══██║██║     ██╔═██╗
     ██║   ██║  ██║██║  ██║╚██████╗███████╗██████╔╝██║  ██║╚██████╗██║  ██╗
     ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═════╝ ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝{RESET}

  {DIM}Local AI-powered OSINT reconnaissance tool{RESET}
  {DIM}Type 'help' for usage, 'quit' to exit{RESET}

  {YELLOW}Disclaimer: This tool uses a local AI model to interpret search results.
  Some information may be inaccurate or outdated. Always verify findings
  with your own research before drawing conclusions.{RESET}
"""

HELP_TEXT = f"""
{BOLD}Commands:{RESET}
  {CYAN}help{RESET}              Show this message
  {CYAN}export / report{RESET}   Save findings to a text file
  {CYAN}quit / exit{RESET}       Exit the tool

{BOLD}Examples:{RESET}
  {GREEN}find accounts for username johndoe{RESET}
  {GREEN}check what services use this email test@example.com{RESET}
  {GREEN}whois example.com{RESET}
  {GREEN}who is John Smith{RESET}
  {GREEN}look up +1-555-123-4567{RESET}
  {GREEN}search the web for johndoe security researcher{RESET}

{BOLD}Follow-up:{RESET}
  {DIM}After a lookup, ask questions about the results:{RESET}
  {GREEN}which of those are social media?{RESET}
  {GREEN}categorize the results{RESET}
  {GREEN}export{RESET}
"""


def run_lookup(intent: dict, session, user_input: str):
    """Run primary tool + any supplementary web searches, then summarize."""
    value = intent["value"]

    escalation = session.check_escalation(value)
    if escalation:
        print(f"\n{blocked(escalation)}\n")
        return

    print(f"\n{status(intent['type'])} {BOLD}{value}{RESET}")

    hints = session.get_session_hints()
    primary, enrichment = orchestrate(intent, session_hints=hints)

    if "error" in primary:
        print(f"{error(primary['error'])}")
        return

    session.add_tool_result(intent["type"], value, primary)

    for enrich in enrichment:
        if enrich.get("results"):
            session.add_tool_result("web_search", value, enrich)

    _thinking("Generating response...")

    conversation = session.get_conversation_context()
    knowledge = session.get_full_knowledge()

    response = summarize(
        primary,
        user_input=user_input,
        conversation=conversation,
        full_knowledge=knowledge,
        web_enrichment=enrichment,
    )
    _clear()
    session.add_assistant_message(response)
    print(f"\n{response}\n")


def handle_person_lookup(name: str, user_input: str, session):
    """Search for a real person by name, then start interactive investigation."""
    escalation = session.check_escalation(name)
    if escalation:
        print(f"\n{blocked(escalation)}\n")
        return

    print(f"\n{status('person lookup')} {BOLD}{name}{RESET}")

    hints = session.get_session_hints()
    primary, _ = orchestrate({"type": "person_lookup", "value": name}, session_hints=hints)

    result_data = primary if "error" not in primary else {"tool": "person", "query": name, "results": []}
    session.add_tool_result("person_lookup", name, result_data)
    session.start_investigation(name, {"web": result_data})

    _thinking("Analyzing results...")

    conversation = session.get_conversation_context()
    response = investigate(result_data, name, user_input=user_input, conversation=conversation)
    _clear()
    session.add_assistant_message(response)
    print(f"\n{response}\n")


def handle_investigation_reply(user_input: str, session, resolved: str):
    """Handle user's reply during an ongoing investigation.

    Most replies get routed through the normal LLM intent parser now.
    This just handles number picks and context refinement.
    """
    investigation = session.get_investigation()
    name = investigation["name"]

    # number pick: "1", "they are number 2", "the first one"
    pick = parse_number_pick(user_input)
    if pick is not None:
        picked = session.pick_result(pick)
        if not picked:
            print(f"\n{warn(f'No result #{pick}. Pick a number from the list above.')}\n")
            return

        # build a focused web search from the picked result
        from urllib.parse import urlparse
        url = picked.get("url", "")
        domain = urlparse(url).netloc if url else ""
        query = f"{name} site:{domain}" if domain else f'"{name}" {picked.get("title", "")}'
        run_lookup({"type": "web_search", "value": query}, session, user_input)
        return

    # everything else: let the LLM figure out the intent
    _thinking("Processing...")
    intent = parse(resolved, session_context=session.get_intent_context())
    _clear()

    # lookups get run directly
    if intent["type"] not in ("chat", "clarify"):
        run_lookup(intent, session, user_input)
        session.add_investigation_results(intent)
        return

    # conversational follow-up about the investigation
    _thinking("Thinking...")
    conversation = session.get_conversation_context()
    response = chat(user_input, conversation)
    _clear()
    session.add_assistant_message(response)
    print(f"\n{response}\n")


def main():
    print(BANNER)

    model_config = get_model_config()
    config.apply_model_config(model_config)
    install_packages()

    print(status("Checking Ollama setup..."))
    llm.ensure_ready()
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

        if user_input.lower() in ("export", "report", "save report", "generate report"):
            if not session.has_lookups():
                print(f"\n{warn('Nothing to export yet. Run some lookups first.')}\n")
            else:
                filepath = generate_report(session)
                print(f"\n{success(f'Report saved to {filepath}')}\n")
            continue

        if user_input.lower() in ("quit", "exit"):
            print(f"{DIM}Bye.{RESET}")
            break

        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        decline = safety.check(user_input)
        if decline:
            print(f"\n{blocked(decline)}\n")
            continue

        session.add_user_message(user_input)

        try:
            resolved = _resolve_pronouns(user_input, session)

            # mid-investigation: number picks and follow-ups
            if session.investigating:
                handle_investigation_reply(user_input, session, resolved)
                continue

            # fast path: obvious emails, domains, @mentions
            fast_intent = _extract_target(resolved)
            if fast_intent:
                intent = fast_intent
            else:
                _thinking("Processing...")
                intent = parse(resolved, session_context=session.get_intent_context())
                _clear()

            # conversational responses
            if intent["type"] in ("chat", "clarify"):
                if intent.get("message", "").strip():
                    answer = intent["message"]
                else:
                    _thinking("Thinking...")
                    conversation = session.get_conversation_context()
                    answer = chat(user_input, conversation)
                    _clear()
                session.add_assistant_message(answer)
                print(f"\n{answer}\n")
                continue

            # person lookup starts an investigation
            if intent["type"] == "person_lookup":
                handle_person_lookup(intent["value"], user_input, session)
                continue

            # everything else goes through run_lookup
            run_lookup(intent, session, user_input)

        except (ConnectionError, RuntimeError) as e:
            print(f"{error(str(e))}\n")

    llm.stop_server()


if __name__ == "__main__":
    main()
