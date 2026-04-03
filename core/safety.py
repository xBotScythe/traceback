"""Ethics filter — blocks hard-banned queries and detects escalation patterns."""

# Always blocked, no matter what
HARD_BLOCKED = [
    "dox",
    "doxx",
    "swat",
    "ssn",
    "social security",
    "credit card",
    "bank account",
    "medical record",
    "hack into",
    "break into",
    "password for",
]

# Sensitive but allowed occasionally — flagged if repeated
SOFT_FLAGGED = [
    "home address",
    "where does",
    "where do they live",
    "phone number",
    "real name",
    "physical location",
    "gps location",
    "track their location",
    "find their house",
    "find where they live",
    "stalk",
]

HARD_DECLINE = (
    "[blocked] That request is off-limits. This tool doesn't assist with "
    "hacking, doxxing, or accessing private records."
)

SOFT_DECLINE = (
    "[blocked] You've made several sensitive requests in a row. "
    "Take it easy — this tool is for public-data recon, not profiling. "
    "Try a different kind of query."
)

# How many soft-flagged queries in a row before blocking
SOFT_LIMIT = 2


class SafetyFilter:
    """Stateful safety filter that tracks escalation patterns."""

    def __init__(self):
        self._soft_streak = 0

    def check(self, user_input: str) -> str | None:
        """Check input for safety. Returns None if safe, or a decline message string."""
        lower = user_input.lower()

        # Hard block — always rejected
        if any(phrase in lower for phrase in HARD_BLOCKED):
            self._soft_streak = 0
            return HARD_DECLINE

        # Soft flag — allowed unless repeated
        if any(phrase in lower for phrase in SOFT_FLAGGED):
            self._soft_streak += 1
            if self._soft_streak >= SOFT_LIMIT:
                return SOFT_DECLINE
            return None  # first one is fine

        # Clean query resets the streak
        self._soft_streak = 0
        return None
