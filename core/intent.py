"""Parse natural language input into structured intent via LLM."""

import json
import re

import config
from core import llm


SYSTEM_PROMPT = """Intent parser for an OSINT tool. Return a single JSON object, nothing else.

Fields: "type", "value", "message"
Types: username_lookup, email_lookup, domain_lookup, person_lookup, phone_lookup, web_search, clarify, chat

Rules:
- Any investigation/lookup request -> web_search with a short search query as value
- Use "Known info" to build better queries. If the user asks about a real person, use their real name in the query, not just their username.
- Follow-up about previous results -> chat, empty message
- Vague request -> clarify with a message asking what they want
- Greeting or off-topic -> chat with a short response
- web_search value: keep SIMPLE. Just the subject + context. No site: operators."""

# only examples the LLM actually needs to see — the fast-path handles
# emails, phones, domains, @mentions, "who is X", "find accounts for X",
# and explicit "search for X" before this ever runs
EXAMPLES = """User: look at johndoe's reddit activity
{"type": "web_search", "value": "johndoe reddit", "message": ""}

User: check their linkedin, real name is Jane Doe
{"type": "web_search", "value": "Jane Doe linkedin", "message": ""}

User: what does darkphoenix99 post on tiktok
{"type": "web_search", "value": "darkphoenix99 tiktok", "message": ""}

User: give me some info on Jane Doe the writer for Acme Magazine
{"type": "web_search", "value": "Jane Doe Acme Magazine writer", "message": ""}

User: which of those are social media
{"type": "chat", "value": "", "message": ""}

User: tell me more about the github one
{"type": "chat", "value": "", "message": ""}

User: hello
{"type": "chat", "value": "", "message": "Hey. I'm Traceback, an OSINT recon tool. What do you want to investigate?"}

User: look into this for me
{"type": "clarify", "value": "", "message": "Look into what? Give me a username, email, domain, phone number, or name."}"""


def parse(user_input: str, session_context: str = "") -> dict:
    """Parse user input into a structured intent dict."""
    prompt = f"{EXAMPLES}\n\n"
    if session_context:
        prompt += f"Known info: {session_context}\n"
    prompt += f"User: {user_input}"

    try:
        raw = llm.ask(prompt, system=SYSTEM_PROMPT)

        # strip markdown fences if the LLM wraps output
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())

        # find the first JSON object in the response
        match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if not match:
            return {"type": "chat", "value": "", "message": raw}

        intent = json.loads(match.group())

        valid_types = ("username_lookup", "email_lookup", "domain_lookup",
                       "person_lookup", "phone_lookup", "web_search", "clarify", "chat")
        if intent.get("type") not in valid_types:
            return {"type": "chat", "value": "", "message": raw}

        # clean up value
        value = intent.get("value", "").strip()
        if intent.get("type") == "username_lookup":
            value = value.lstrip("@")
        elif intent.get("type") == "domain_lookup":
            value = re.sub(r"^https?://", "", value)

        return {
            "type": intent.get("type", "chat"),
            "value": value,
            "message": intent.get("message", ""),
        }

    except (json.JSONDecodeError, ConnectionError, RuntimeError):
        return {"type": "chat", "value": "", "message": ""}
