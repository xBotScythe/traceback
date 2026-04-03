"""Email lookup via Holehe and optional HIBP."""

import subprocess
import shutil
import json
import re
import urllib.request
import urllib.error

import config
from tools import register


@register("email_lookup")
def lookup(email: str) -> dict:
    """Check which services an email is registered on."""
    results = []
    errors = []

    # Holehe lookup
    holehe_results = _holehe_lookup(email)
    if isinstance(holehe_results, str):
        errors.append(holehe_results)
    else:
        results.extend(holehe_results)

    # HIBP lookup (optional)
    if config.HIBP_API_KEY:
        hibp_results = _hibp_lookup(email)
        if isinstance(hibp_results, str):
            errors.append(hibp_results)
        else:
            results.extend(hibp_results)

    output = {
        "tool": "email",
        "query": email,
        "results": results,
        "count": len(results),
    }
    if errors:
        output["warnings"] = errors
    return output


def _holehe_lookup(email: str) -> list[dict] | str:
    """Run Holehe and parse results."""
    if not shutil.which("holehe"):
        return "Holehe not installed. Run: pip install holehe"

    try:
        result = subprocess.run(
            ["holehe", email],
            capture_output=True,
            text=True,
            timeout=120,
        )

        found = []
        for line in result.stdout.splitlines():
            line = line.strip()
            # Holehe marks found services with [+]
            if "[+]" in line:
                # Extract service name — typically format: "[+] ServiceName"
                clean = re.sub(r"\x1b\[[0-9;]*m", "", line)  # strip ANSI codes
                service = clean.replace("[+]", "").strip().split()[0] if clean else line
                found.append({"source": "holehe", "service": service, "status": "registered"})

        return found

    except subprocess.TimeoutExpired:
        return "Holehe timed out after 120 seconds"
    except subprocess.CalledProcessError as e:
        return f"Holehe failed: {e.stderr or str(e)}"


def _hibp_lookup(email: str) -> list[dict] | str:
    """Check HaveIBeenPwned for breaches."""
    try:
        req = urllib.request.Request(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}?truncateResponse=false",
            headers={
                "hibp-api-key": config.HIBP_API_KEY,
                "user-agent": "osint-cli",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            breaches = json.loads(resp.read())
            return [
                {
                    "source": "hibp",
                    "service": b["Name"],
                    "status": "breached",
                    "date": b.get("BreachDate", "unknown"),
                }
                for b in breaches
            ]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # no breaches found — that's fine
        return f"HIBP error: HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return f"HIBP unreachable: {e}"
