"""Email lookup via Holehe and XposedOrNot (free breach check)."""

import subprocess
import shutil
import json
import re
import urllib.request
import urllib.error

from tools import register


@register("email_lookup")
def lookup(email: str) -> dict:
    """Check which services an email is registered on and if it's been breached."""
    results = []
    errors = []

    # Holehe — service registration check
    holehe_results = _holehe_lookup(email)
    if isinstance(holehe_results, str):
        errors.append(holehe_results)
    else:
        results.extend(holehe_results)

    # XposedOrNot — free breach check (no API key needed)
    breach_results = _xposed_lookup(email)
    if isinstance(breach_results, str):
        errors.append(breach_results)
    else:
        results.extend(breach_results)

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
            if "[+]" in line:
                clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
                service = clean.replace("[+]", "").strip().split()[0] if clean else line
                found.append({"source": "holehe", "service": service, "status": "registered"})

        return found

    except subprocess.TimeoutExpired:
        return "Holehe timed out after 120 seconds"
    except subprocess.CalledProcessError as e:
        return f"Holehe failed: {e.stderr or str(e)}"


def _xposed_lookup(email: str) -> list[dict] | str:
    """Check XposedOrNot for breaches (free, no API key)."""
    try:
        req = urllib.request.Request(
            f"https://api.xposedornot.com/v1/check-email/{email}",
            headers={"user-agent": "traceback-osint"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        breaches = data.get("breaches", [])
        if not breaches:
            return []

        # XposedOrNot returns breach names in a list
        results = []
        for breach in breaches:
            if isinstance(breach, str):
                results.append({
                    "source": "xposedornot",
                    "service": breach,
                    "status": "breached",
                })
            elif isinstance(breach, dict):
                results.append({
                    "source": "xposedornot",
                    "service": breach.get("domain", breach.get("name", "unknown")),
                    "status": "breached",
                    "date": breach.get("date", ""),
                })

        return results

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # no breaches — clean
        return f"XposedOrNot error: HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return f"XposedOrNot unreachable: {e}"
