"""Person/name lookup - searches the web for a real name using OSINT dorks."""

from tools import register
from tools.websearch import person_search


@register("person_lookup")
def lookup(name: str, session_hints: list = None) -> dict:
    result = person_search(name, session_hints=session_hints)
    result["tool"] = "person"
    result["query"] = name
    return result
