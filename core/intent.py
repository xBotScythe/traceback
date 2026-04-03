"""Parse natural language input into structured intent via LLM."""

import json
import re

from core import llm


SYSTEM_PROMPT = """You are an intent parser for an OSINT tool. Given a user's request, return ONLY a JSON object with two fields:
- "type": one of "username_lookup", "email_lookup", "domain_lookup", or "unknown"
- "value": the target username, email, or domain extracted from the request

Rules:
- If the request is about finding accounts/profiles for a username → username_lookup
- If the request is about an email address → email_lookup
- If the request is about a domain or website → domain_lookup
- If unclear, return {"type": "unknown", "value": ""}
- Return ONLY valid JSON. No explanation, no markdown, no extra text."""

EXAMPLES = """
User: find accounts for username johndoe
{"type": "username_lookup", "value": "johndoe"}

User: check what services are registered to test@example.com
{"type": "email_lookup", "value": "test@example.com"}

User: whois example.com
{"type": "domain_lookup", "value": "example.com"}

User: what's the weather today
{"type": "unknown", "value": ""}
"""


def parse(user_input: str) -> dict:
    """Parse user input into a structured intent dict."""
    prompt = f"{EXAMPLES}\nUser: {user_input}"

    try:
        raw = llm.ask(prompt, system=SYSTEM_PROMPT)

        # Strip markdown fences if the LLM wraps output
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())

        # Find the first JSON object in the response
        match = re.search(r"\{[^}]+\}", raw)
        if not match:
            return {"type": "unknown", "value": ""}

        intent = json.loads(match.group())

        # Validate shape
        if intent.get("type") not in ("username_lookup", "email_lookup", "domain_lookup", "unknown"):
            return {"type": "unknown", "value": ""}

        return {
            "type": intent.get("type", "unknown"),
            "value": intent.get("value", "").strip(),
        }

    except (json.JSONDecodeError, ConnectionError, RuntimeError):
        return {"type": "unknown", "value": ""}
