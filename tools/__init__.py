"""Tool registry and dispatcher."""


TOOL_REGISTRY = {}


def register(intent_type: str):
    """Decorator to register a tool function for an intent type."""
    def wrapper(fn):
        TOOL_REGISTRY[intent_type] = fn
        return fn
    return wrapper


def dispatch(intent: dict) -> dict:
    """Look up and call the tool for a parsed intent."""
    intent_type = intent.get("type", "unknown")
    value = intent.get("value", "")

    if intent_type not in TOOL_REGISTRY:
        return {"tool": None, "query": value, "error": f"No tool for intent type: {intent_type}"}

    fn = TOOL_REGISTRY[intent_type]
    return fn(value)
