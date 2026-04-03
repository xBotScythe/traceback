"""Terminal colors and UI helpers for Traceback."""

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

BG_RED = "\033[41m"


def prompt() -> str:
    """Colored prompt string."""
    return f"{BOLD}{CYAN}traceback{RESET}{DIM}>{RESET} "


def status(msg: str) -> str:
    """Status/info message."""
    return f"  {BLUE}{BOLD}[*]{RESET} {msg}"


def success(msg: str) -> str:
    """Success message."""
    return f"  {GREEN}{BOLD}[+]{RESET} {GREEN}{msg}{RESET}"


def warn(msg: str) -> str:
    """Warning message."""
    return f"  {YELLOW}{BOLD}[?]{RESET} {YELLOW}{msg}{RESET}"


def error(msg: str) -> str:
    """Error message."""
    return f"  {RED}{BOLD}[!]{RESET} {RED}{msg}{RESET}"


def blocked(msg: str) -> str:
    """Blocked/safety message."""
    return f"  {RED}{BOLD}[BLOCKED]{RESET} {DIM}{msg}{RESET}"


def working() -> str:
    """Working/loading indicator."""
    return f"  {DIM}[...] Working...{RESET}"
