"""Session memory — tracks lookups per target and flags escalation."""

from collections import defaultdict

# Max distinct tool types allowed on a single target before blocking
ESCALATION_LIMIT = 3

ESCALATION_WARNING = (
    "[notice] You've run several different lookups on this target. "
    "This tool is meant for general reconnaissance, not building a profile on one person. "
    "Further lookups on this target are blocked for this session."
)


class Session:
    """Tracks queries and results within a single CLI session."""

    def __init__(self):
        # target_name -> list of {"type": ..., "result": ...}
        self._history: dict[str, list[dict]] = defaultdict(list)
        self._blocked: set[str] = set()

    def _normalize(self, value: str) -> str:
        """Normalize a target identifier for grouping."""
        return value.strip().lower()

    def is_blocked(self, value: str) -> bool:
        """Check if a target has been blocked due to escalation."""
        return self._normalize(value) in self._blocked

    def record(self, intent_type: str, value: str, result: dict):
        """Record a lookup. Returns None normally, or a warning string on first escalation."""
        key = self._normalize(value)
        self._history[key].append({"type": intent_type, "result": result})

    def check_escalation(self, value: str) -> str | None:
        """Check if the next lookup on this target should be blocked.
        Returns a warning message if blocked, None if OK."""
        key = self._normalize(value)

        if key in self._blocked:
            return ESCALATION_WARNING

        # Count distinct tool types used on this target
        tool_types = {entry["type"] for entry in self._history[key]}
        if len(tool_types) >= ESCALATION_LIMIT:
            self._blocked.add(key)
            return ESCALATION_WARNING

        return None

    def get_context(self, value: str) -> list[dict]:
        """Get all prior results for a target, for richer summaries."""
        key = self._normalize(value)
        return list(self._history[key])

    def get_context_summary(self, value: str) -> str:
        """Return a short text summary of prior lookups on this target."""
        entries = self.get_context(value)
        if not entries:
            return ""

        types = [e["type"] for e in entries]
        return f"Prior lookups on this target: {', '.join(types)}."

    def get_all_context(self) -> str:
        """Return a text dump of all session results for follow-up questions."""
        if not self._history:
            return ""

        import json
        lines = []
        for target, entries in self._history.items():
            for entry in entries:
                lines.append(f"Target: {target} | Tool: {entry['type']}")
                lines.append(json.dumps(entry["result"], indent=2))
                lines.append("")
        return "\n".join(lines)
