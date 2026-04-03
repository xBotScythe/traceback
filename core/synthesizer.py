"""Format raw tool output as readable prose via LLM."""

import json

from core import llm


SYSTEM_PROMPT = """You are an OSINT analyst writing a report. The user asked a question and a tool returned results as JSON. Write a detailed synopsis.

Your response MUST include:

1. An opening statement summarizing the overall finding (e.g. "The username X has a significant online presence across N platforms.")

2. A numbered list of EVERY platform/URL/service found. For each one, include the platform name and full URL. Do not skip any.

3. A breakdown by category. Group the results into categories like:
   - Social media (Twitter, TikTok, Instagram, etc.)
   - Developer/tech (GitHub, GitLab, Stack Overflow, etc.)
   - Gaming (Steam, Roblox, Xbox, etc.)
   - Content/media (YouTube, Twitch, SoundCloud, etc.)
   - Forums/communities (Reddit, Discord, etc.)
   - Other
   Only include categories that have results.

4. A brief analytical closing — what this footprint suggests about the target (active user, niche interests, broad presence, etc.)

Additional rules:
- Only describe what is in the data. Do not invent results.
- If the user asked for a specific tone or style in their original request, follow it throughout.
- If prior session context is provided, weave it into the analysis.
- Plain text only, no markdown formatting."""

FOLLOWUP_SYSTEM = """You are an OSINT analyst assistant. The user is asking a follow-up question about results from a previous lookup. Give a detailed answer based ONLY on the data provided. If the answer isn't in the data, say so. Do not make anything up. If the user asks for a specific tone or style, follow it. Plain text only."""


def format(tool_output: dict, prior_context: str = "", user_input: str = "") -> str:
    """Send raw tool results to LLM and return a prose summary."""
    data_str = json.dumps(tool_output, indent=2)
    prompt = f"User's original request: {user_input}\n\nTool results:\n{data_str}"
    if prior_context:
        prompt += f"\n\nPrior session context: {prior_context}"

    try:
        return llm.ask(prompt, system=SYSTEM_PROMPT)
    except (ConnectionError, RuntimeError):
        return _fallback_format(tool_output)


def followup(question: str, session_data: str) -> str:
    """Answer a follow-up question using session context."""
    prompt = f"Session data:\n{session_data}\n\nUser question: {question}"
    try:
        return llm.ask(prompt, system=FOLLOWUP_SYSTEM)
    except (ConnectionError, RuntimeError):
        return "[error] Couldn't process follow-up. Try again."


def _fallback_format(tool_output: dict) -> str:
    """Plain text fallback if LLM summary fails."""
    tool = tool_output.get("tool", "unknown")
    query = tool_output.get("query", "")
    results = tool_output.get("results", [])

    if not results:
        return f"No results found for '{query}' using {tool}."

    lines = [f"Found {len(results)} result(s) for '{query}' using {tool}:"]
    for item in results:
        lines.append(f"  - {item}")
    return "\n".join(lines)
