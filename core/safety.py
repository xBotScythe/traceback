"""Safety filter for blocking harmful queries."""

import re

# always blocked — checked against normalized input
HARD_BLOCKED = [
    "dox", "doxx",
    "swat",
    "ssn", "social security",
    "credit card", "bank account", "medical record",
    "hack into", "break into", "get into their", "access their account",
    "password for", "passwd for", "pw for", "credentials for", "login for",
    "track location", "track their location", "gps location", "real time location",
    "find their house", "find where they live",
]

# allowed once, blocked if repeated without enough clean queries in between
SOFT_FLAGGED = [
    "home address",
    "where does",
    "where do they live",
    "phone number",
    "real name",
    "physical location",
    "find their address",
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

# how many soft flags before cutting off
SOFT_LIMIT = 2


def _normalize(text: str) -> str:
    """Collapse whitespace and strip punctuation for pattern matching."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SafetyFilter:
    """Tracks repeated sketchy queries and blocks when needed."""

    def __init__(self):
        self._soft_streak = 0

    def check(self, user_input: str) -> str | None:
        """Check input for safety. Returns None if safe, or a decline message string."""
        normalized = _normalize(user_input)

        if any(phrase in normalized for phrase in HARD_BLOCKED):
            return HARD_DECLINE

        if any(phrase in normalized for phrase in SOFT_FLAGGED):
            self._soft_streak += 1
            if self._soft_streak >= SOFT_LIMIT:
                return SOFT_DECLINE
            return None

        # clean query bleeds off the streak one step at a time
        if self._soft_streak > 0:
            self._soft_streak -= 1
        return None
