"""Phone number lookup - validation, carrier, type, and web search for the number."""

from tools import register


@register("phone_lookup")
def lookup(phone: str) -> dict:
    results = {}
    errors = []

    parsed = _validate(phone)
    if isinstance(parsed, str):
        errors.append(parsed)
    else:
        results["validation"] = parsed

    # search the web for the number to find who it belongs to
    web_hits = _web_search_number(phone)
    if web_hits:
        results["web_mentions"] = web_hits

    output = {
        "tool": "phone",
        "query": phone,
        "results": results,
        "has_data": bool(results),
    }
    if errors:
        output["warnings"] = errors
    return output


def _validate(phone: str) -> dict | str:
    try:
        import phonenumbers
    except ImportError:
        return "phonenumbers not installed. Run: pip install phonenumbers"

    try:
        from phonenumbers import carrier, geocoder, timezone

        parsed = phonenumbers.parse(phone, "US")

        if not phonenumbers.is_valid_number(parsed):
            return {"valid": False, "note": "Number does not appear to be valid"}

        return {
            "valid": True,
            "formatted": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "country": geocoder.description_for_number(parsed, "en"),
            "carrier": carrier.name_for_number(parsed, "en") or "unknown",
            "type": _number_type(phonenumbers.number_type(parsed)),
            "timezones": list(timezone.time_zones_for_number(parsed)),
        }

    except Exception as e:
        return f"Phone validation failed: {e}"


def _number_type(t) -> str:
    import phonenumbers
    types = {
        phonenumbers.PhoneNumberType.MOBILE: "mobile",
        phonenumbers.PhoneNumberType.FIXED_LINE: "landline",
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "landline or mobile",
        phonenumbers.PhoneNumberType.TOLL_FREE: "toll-free",
        phonenumbers.PhoneNumberType.PREMIUM_RATE: "premium rate",
        phonenumbers.PhoneNumberType.VOIP: "voip",
        phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "personal",
    }
    return types.get(t, "unknown")


def _web_search_number(phone: str) -> list:
    """Search the web for mentions of this phone number."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    clean = "".join(c for c in phone if c.isdigit() or c == "+")
    # try a few formats people might list numbers under
    queries = [
        f'"{clean}"',
        f'"{phone}"',
        f'"{clean}" site:whitepages.com OR site:truecaller.com OR site:whocalld.com',
        f'"{clean}" spam OR scam OR caller',
    ]

    results = []
    seen = set()
    for q in queries:
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(q, max_results=5):
                    url = r.get("href", "")
                    if url and url not in seen:
                        seen.add(url)
                        results.append({
                            "title": r.get("title", ""),
                            "url": url,
                            "snippet": r.get("body", ""),
                        })
        except Exception:
            continue

    return results
