"""Domain lookup via python-whois and optional Shodan."""

import json
import urllib.request
import urllib.error

import config
from tools import register


@register("domain_lookup")
def lookup(domain: str) -> dict:
    """Get WHOIS info and optional Shodan data for a domain."""
    results = {}
    errors = []

    # WHOIS lookup
    whois_data = _whois_lookup(domain)
    if isinstance(whois_data, str):
        errors.append(whois_data)
    else:
        results["whois"] = whois_data

    # Shodan lookup (optional)
    if config.SHODAN_API_KEY:
        shodan_data = _shodan_lookup(domain)
        if isinstance(shodan_data, str):
            errors.append(shodan_data)
        else:
            results["shodan"] = shodan_data

    output = {
        "tool": "domain",
        "query": domain,
        "results": results,
        "has_data": bool(results),
    }
    if errors:
        output["warnings"] = errors
    return output


def _whois_lookup(domain: str) -> dict | str:
    """Run python-whois on a domain."""
    try:
        import whois
    except ImportError:
        return "python-whois not installed. Run: pip install python-whois"

    try:
        w = whois.whois(domain)

        # Convert to a clean dict — whois objects can be messy
        data = {}
        for key in ["domain_name", "registrar", "creation_date", "expiration_date",
                     "name_servers", "org", "country", "state", "city", "emails"]:
            val = getattr(w, key, None)
            if val is None:
                continue
            # Dates and lists need string conversion
            if isinstance(val, list):
                val = [str(v) for v in val]
            else:
                val = str(val)
            data[key] = val

        return data if data else "No WHOIS data found"

    except Exception as e:
        return f"WHOIS lookup failed: {e}"


def _shodan_lookup(domain: str) -> dict | str:
    """Query Shodan for domain/host info."""
    try:
        req = urllib.request.Request(
            f"https://api.shodan.io/dns/resolve?hostnames={domain}&key={config.SHODAN_API_KEY}",
            headers={"user-agent": "osint-cli"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resolved = json.loads(resp.read())
            ip = resolved.get(domain)
            if not ip:
                return "Could not resolve domain IP via Shodan"

        # Now get host info
        req2 = urllib.request.Request(
            f"https://api.shodan.io/shodan/host/{ip}?key={config.SHODAN_API_KEY}",
            headers={"user-agent": "osint-cli"},
        )
        with urllib.request.urlopen(req2, timeout=15) as resp2:
            host = json.loads(resp2.read())
            return {
                "ip": ip,
                "org": host.get("org", "unknown"),
                "os": host.get("os"),
                "ports": host.get("ports", []),
                "vulns": host.get("vulns", []),
            }

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ip": ip, "note": "No Shodan data for this host"}
        return f"Shodan error: HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return f"Shodan unreachable: {e}"
