"""Parse natural language input into structured intent via LLM."""

import json
import re

import config
from core import llm


SYSTEM_PROMPT = """You are the intent parser for Traceback, an OSINT tool. Read the user's message and return a single JSON object. No other output.

JSON fields:
- "type": one of: "username_lookup", "email_lookup", "domain_lookup", "person_lookup", "phone_lookup", "web_search", "clarify", "chat"
- "value": the search query to use. Build a good search query from the user's message. Empty string if not applicable.
- "message": a short response for "chat" type only. Empty string otherwise.

ROUTING RULES (in priority order):
1. Contains email (has @) -> email_lookup, value = the email
2. Contains phone number (digits with +, dashes, parens) -> phone_lookup, value = the number
3. Contains domain (.com, .org, etc. but no @) -> domain_lookup, value = the domain
4. ONLY use username_lookup when the user explicitly says "find accounts for username X" or "what platforms is X on". value = the username
5. "who is Firstname Lastname" with no other context -> person_lookup, value = the name
6. For EVERYTHING else that involves looking something up -> web_search. value = a simple search query.
7. Follow-up about previous results with no new lookup needed -> chat with empty message
8. Vague or needs more info -> clarify with a message asking what they want
9. Off-topic or greeting -> chat with a short response

IMPORTANT:
- Return ONLY the JSON object.
- web_search is the DEFAULT for any investigation request. Use it liberally.
- For web_search value: keep it SIMPLE. Use the key subject and relevant context words. Do NOT add site: operators or advanced dork syntax - the search tool handles that automatically.
  Good: "Jane Doe Acme Magazine writer"
  Good: "johndoe reddit"
  Bad: "Jane Doe site:acmemag.com job title writings" (too specific, will miss results)
- Only use username_lookup when the user specifically wants to scan platforms for account existence."""

# compact examples: 1 per type to save tokens on small models
EXAMPLES_COMPACT = """User: find accounts for johndoe
{"type": "username_lookup", "value": "johndoe", "message": ""}

User: check test@example.com
{"type": "email_lookup", "value": "test@example.com", "message": ""}

User: whois example.com
{"type": "domain_lookup", "value": "example.com", "message": ""}

User: who is John Smith
{"type": "person_lookup", "value": "John Smith", "message": ""}

User: look up 555-123-4567
{"type": "phone_lookup", "value": "555-123-4567", "message": ""}

User: look at johndoe's reddit activity
{"type": "web_search", "value": "johndoe reddit", "message": ""}

User: which of those are social media
{"type": "chat", "value": "", "message": ""}

User: hello
{"type": "chat", "value": "", "message": "Hey. I'm Traceback, an OSINT recon tool. What do you want to investigate?"}

User: look into this for me
{"type": "clarify", "value": "", "message": "Look into what? Give me a username, email, domain, phone number, or name."}"""

# full examples with more edge cases for bigger models
EXAMPLES_FULL = """User: find accounts for username johndoe
{"type": "username_lookup", "value": "johndoe", "message": ""}

User: what platforms is darkphoenix99 on
{"type": "username_lookup", "value": "darkphoenix99", "message": ""}

User: check what services are registered to test@example.com
{"type": "email_lookup", "value": "test@example.com", "message": ""}

User: has someone@protonmail.com been in any breaches
{"type": "email_lookup", "value": "someone@protonmail.com", "message": ""}

User: whois example.com
{"type": "domain_lookup", "value": "example.com", "message": ""}

User: who owns shadysite.net
{"type": "domain_lookup", "value": "shadysite.net", "message": ""}

User: who is John Smith
{"type": "person_lookup", "value": "John Smith", "message": ""}

User: find info on Jane Doe
{"type": "person_lookup", "value": "Jane Doe", "message": ""}

User: look up 555-123-4567
{"type": "phone_lookup", "value": "555-123-4567", "message": ""}

User: who owns this number +1 (212) 555-0199
{"type": "phone_lookup", "value": "+1 (212) 555-0199", "message": ""}

User: look at nightowl_42's reddit
{"type": "web_search", "value": "nightowl_42 reddit", "message": ""}

User: investigate johndoe's github projects
{"type": "web_search", "value": "johndoe github", "message": ""}

User: check their LinkedIn, real name is Jane Doe
{"type": "web_search", "value": "Jane Doe linkedin", "message": ""}

User: what does darkphoenix99 post on tiktok
{"type": "web_search", "value": "darkphoenix99 tiktok", "message": ""}

User: search the web for johndoe hacker forum
{"type": "web_search", "value": "johndoe hacker forum", "message": ""}

User: give me some info on Jane Doe the writer for Acme Magazine
{"type": "web_search", "value": "Jane Doe Acme Magazine writer", "message": ""}

User: look into this for me
{"type": "clarify", "value": "", "message": "Look into what? Give me a username, email, domain, phone number, or name."}

User: which of those are social media
{"type": "chat", "value": "", "message": ""}

User: tell me more about the github one
{"type": "chat", "value": "", "message": ""}

User: what can you do
{"type": "chat", "value": "", "message": "I'm Traceback, a local OSINT recon tool. I can look up usernames, emails, domains, phone numbers, people by name, and search the web. Just ask in plain English."}

User: hello
{"type": "chat", "value": "", "message": "Hey. I'm Traceback, an OSINT recon tool. What do you want to investigate?"}

User: what's the weather today
{"type": "chat", "value": "", "message": "Weather isn't my thing. I'm built for OSINT. What can I help you find?"}"""


def _get_examples() -> str:
    """Pick examples based on model tier. All tiers can handle full examples now
    since the smallest model is 8b with 8192 context."""
    return EXAMPLES_FULL


def parse(user_input: str) -> dict:
    """Parse user input into a structured intent dict."""
    examples = _get_examples()
    prompt = f"{examples}\n\nUser: {user_input}"

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
