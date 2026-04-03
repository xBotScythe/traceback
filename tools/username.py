"""Username lookup via Sherlock."""

import json
import subprocess
import shutil
import sys

from tools import register


@register("username_lookup")
def lookup(username: str) -> dict:
    """Search for accounts matching a username across platforms."""
    if not shutil.which("sherlock"):
        return {
            "tool": "sherlock",
            "query": username,
            "error": "Sherlock not installed. Run: pip install sherlock-project",
        }

    try:
        result = subprocess.run(
            [
                "sherlock", username,
                "--print-found",
                "--no-color",
                "--timeout", "15",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Parse found URLs from stdout
        urls = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("http://") or line.startswith("https://"):
                urls.append(line)
            elif ": http" in line:
                # Format: "SiteName: https://..."
                url = line.split(": ", 1)[-1].strip()
                if url.startswith("http"):
                    urls.append(url)

        return {
            "tool": "sherlock",
            "query": username,
            "results": urls,
            "count": len(urls),
        }

    except subprocess.TimeoutExpired:
        return {
            "tool": "sherlock",
            "query": username,
            "error": "Search timed out after 120 seconds",
        }
    except subprocess.CalledProcessError as e:
        return {
            "tool": "sherlock",
            "query": username,
            "error": f"Sherlock failed: {e.stderr or str(e)}",
        }
