"""Session memory for conversation history, lookups, and escalation."""

import json
import re
from collections import defaultdict

ESCALATION_LIMIT = 5     # max distinct tool types on one target before blocking
SEARCH_SPAM_LIMIT = 20   # max total lookups on one target before blocking
WEB_SEARCH_LIMIT = 8     # max web searches referencing a blocked/heavy target before warning

ESCALATION_WARNING = (
    "[notice] You've used a lot of different tools on this target. "
    "Try narrowing your focus or moving on to a different lead."
)

SPAM_WARNING = (
    "[notice] You've run a lot of searches on this target. "
    "Try a different approach or look into a different lead."
)

WEB_SEARCH_WARNING = (
    "[notice] You've run a lot of web searches on this target already. "
    "Consider looking into a different lead."
)

MAX_CONVERSATION_TURNS = 20


class Session:

    def __init__(self):
        self._lookups: dict[str, list[dict]] = defaultdict(list)
        self._blocked: set[str] = set()
        self._conversation: list[dict] = []
        self._investigation: dict | None = None
        self._last_target: str | None = None

    def _normalize(self, value: str) -> str:
        return value.strip().lower()

    # conversation

    def add_user_message(self, text: str):
        self._conversation.append({"role": "user", "content": text})
        self._trim()

    def add_assistant_message(self, text: str):
        self._conversation.append({"role": "assistant", "content": text})
        self._trim()

    @property
    def last_target(self) -> str | None:
        return self._last_target

    def add_tool_result(self, intent_type: str, value: str, result: dict):
        key = self._normalize(value)
        # store the clean target name, not search operators like site:reddit.com
        clean_target = re.sub(r'\s*site:\S+', '', value).strip()
        self._last_target = clean_target if clean_target else value
        self._lookups[key].append({"type": intent_type, "result": result})

        # build a useful summary the LLM can actually reference later
        summary = f"[Tool: {intent_type} | Target: {value}]"
        results_data = result.get("results", [])

        if isinstance(results_data, list):
            summary += f" ({len(results_data)} results)"
            for item in results_data[:40]:
                if isinstance(item, str):
                    summary += f"\n  - {item}"
                elif isinstance(item, dict):
                    parts = []
                    for k in ("service", "title", "url", "snippet", "username", "carrier", "country"):
                        if item.get(k):
                            parts.append(f"{k}: {item[k]}")
                    if parts:
                        summary += f"\n  - {' | '.join(parts)}"
                    else:
                        summary += f"\n  - {json.dumps(item)}"
            if len(results_data) > 40:
                summary += f"\n  ... and {len(results_data) - 40} more"

        elif isinstance(results_data, dict):
            summary += f"\n{json.dumps(results_data, indent=2, default=str)}"

        if result.get("warnings"):
            summary += f"\n  Warnings: {', '.join(result['warnings'])}"

        self._conversation.append({"role": "tool", "content": summary})
        self._trim()

    def _trim(self):
        if len(self._conversation) > MAX_CONVERSATION_TURNS * 2:
            self._conversation = self._conversation[-MAX_CONVERSATION_TURNS * 2:]

    # context

    def get_conversation_context(self) -> str:
        if not self._conversation:
            return ""
        lines = []
        for turn in self._conversation:
            role = turn["role"].upper()
            lines.append(f"[{role}]: {turn['content']}")
        return "\n\n".join(lines)

    def has_history(self) -> bool:
        return len(self._conversation) > 0

    def has_lookups(self) -> bool:
        return len(self._lookups) > 0

    def get_context_summary(self, value: str) -> str:
        key = self._normalize(value)
        entries = self._lookups.get(key, [])
        if not entries:
            return ""
        types = [e["type"] for e in entries]
        return f"Prior lookups on this target: {', '.join(types)}."

    def get_intent_context(self) -> str:
        """Short context string for the intent parser so it can build
        better search queries using known names/aliases."""
        if not self._last_target:
            return ""
        parts = [f"Target: {self._last_target}"]
        hints = self.get_session_hints()
        if len(hints) > 1:
            parts.append(f"Also known: {', '.join(hints[1:5])}")
        return ". ".join(parts)

    def get_full_knowledge(self) -> str:
        """Build a summary of everything we've found across all targets."""
        if not self._lookups:
            return ""

        sections = []
        for target, entries in self._lookups.items():
            lines = [f"Target: {target}"]
            for entry in entries:
                tool_type = entry["type"]
                result = entry["result"]
                lines.append(f"  [{tool_type}]")

                results_data = result.get("results", [])
                if isinstance(results_data, list):
                    for item in results_data[:20]:
                        if isinstance(item, str):
                            lines.append(f"    - {item}")
                        elif isinstance(item, dict):
                            parts = []
                            for k in ("service", "title", "url", "snippet", "username",
                                      "carrier", "country", "formatted", "type", "valid"):
                                if item.get(k):
                                    parts.append(f"{k}: {item[k]}")
                            if parts:
                                lines.append(f"    - {' | '.join(parts)}")
                elif isinstance(results_data, dict):
                    for k, v in results_data.items():
                        if isinstance(v, dict):
                            for k2, v2 in v.items():
                                if v2:
                                    lines.append(f"    {k2}: {v2}")
                        elif v:
                            lines.append(f"    {k}: {v}")

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    # investigation (multi-step person lookups)

    def start_investigation(self, name: str, initial_results: dict):
        flat_results = []
        for source_data in initial_results.values():
            if isinstance(source_data, dict):
                for item in source_data.get("results", []):
                    flat_results.append(item)

        self._investigation = {"name": name, "all_results": flat_results}

    def pick_result(self, number: int) -> dict | None:
        """User picked a numbered result. Returns the result dict or None."""
        if not self._investigation:
            return None
        results = self._investigation.get("all_results", [])
        if 1 <= number <= len(results):
            return results[number - 1]
        return None

    def add_investigation_results(self, results: dict):
        if self._investigation:
            new_items = results.get("results", [])
            if isinstance(new_items, list):
                self._investigation["all_results"].extend(new_items)

    def get_investigation(self) -> dict | None:
        return self._investigation

    def end_investigation(self):
        self._investigation = None

    @property
    def investigating(self) -> bool:
        return self._investigation is not None

    def get_session_hints(self) -> list[str]:
        """Pull usernames, emails, domains, etc. from prior lookups to help narrow searches."""
        hints = []
        for target, entries in self._lookups.items():
            hints.append(target)
            for entry in entries:
                results_data = entry["result"].get("results", [])
                if isinstance(results_data, list):
                    for item in results_data[:10]:
                        if isinstance(item, dict):
                            for k in ("username", "service", "email"):
                                if item.get(k):
                                    hints.append(str(item[k]))
        seen = set()
        unique = []
        for h in hints:
            if h not in seen:
                seen.add(h)
                unique.append(h)
        return unique[:20]

    # escalation

    def _target_for_query(self, query: str) -> str | None:
        """If a web search query mentions a known tracked target, return that target's key."""
        lower = query.lower()
        for key in self._lookups:
            if len(key) >= 3 and key in lower:
                return key
        return None

    def check_escalation(self, value: str, tool_type: str = "") -> str | None:
        key = self._normalize(value)

        # for web searches, check if the query is about a known target
        target_key = key
        if tool_type == "web_search":
            target_key = self._target_for_query(value) or key

        # blocked target: hard stop for tool lookups, soft warn for web searches
        if target_key in self._blocked:
            if tool_type == "web_search":
                web_count = sum(
                    1 for e in self._lookups.get(target_key, [])
                    if e["type"] == "web_search"
                )
                if web_count >= WEB_SEARCH_LIMIT:
                    return WEB_SEARCH_WARNING
                return None
            return ESCALATION_WARNING

        entries = self._lookups.get(target_key, [])
        tool_types = {entry["type"] for entry in entries}

        if len(tool_types) >= ESCALATION_LIMIT:
            self._blocked.add(target_key)
            return ESCALATION_WARNING

        if len(entries) >= SEARCH_SPAM_LIMIT:
            self._blocked.add(target_key)
            return SPAM_WARNING

        # web searches on a non-blocked target get their own softer cap
        if tool_type == "web_search" and target_key != key:
            web_count = sum(1 for e in entries if e["type"] == "web_search")
            if web_count >= WEB_SEARCH_LIMIT:
                return WEB_SEARCH_WARNING

        return None


def parse_number_pick(text: str) -> int | None:
    """Try to extract a number selection from user input.

    Handles: "1", "number 1", "they are number 1", "#1", "the first one",
    "option 2", "pick 3", "[1]", "result 1", etc.
    """
    text = text.strip().lower()

    # direct number: "1", "2", "3"
    if text.isdigit() and 1 <= int(text) <= 20:
        return int(text)

    # [1], #1
    m = re.match(r'^\[?#?(\d+)\]?$', text)
    if m:
        return int(m.group(1))

    # "number X", "option X", "pick X", "result X", "#X"
    m = re.search(r'(?:number|option|pick|result|choice|#)\s*(\d+)', text)
    if m:
        return int(m.group(1))

    # "they are X", "it's X", "its X", "that's X", "thats X"
    m = re.search(r"(?:they are|it'?s|that'?s|i pick|i choose|go with)\s+(?:number\s+)?(\d+)", text)
    if m:
        return int(m.group(1))

    # "the first/second/third one"
    ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    for word, num in ordinals.items():
        if word in text:
            return num

    return None
