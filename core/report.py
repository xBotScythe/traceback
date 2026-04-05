"""Generate text reports from session data. Only runs when the user asks."""

import os
import re
from datetime import datetime


REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")


def _ensure_dir():
    os.makedirs(REPORT_DIR, exist_ok=True)


def _safe_filename(name: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", name).strip()
    clean = re.sub(r"\s+", "_", clean)
    return clean[:50] or "report"


def generate(session) -> str:
    """Build a plain text report from everything in the session.

    Returns the file path of the saved report.
    """
    _ensure_dir()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # figure out a name from the targets
    targets = list(session._lookups.keys())
    if targets:
        label = _safe_filename(targets[0])
    else:
        label = "session"

    filename = f"{label}_{timestamp}.txt"
    filepath = os.path.join(REPORT_DIR, filename)

    lines = []
    lines.append("=" * 60)
    lines.append(f"Traceback Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)

    # dump all lookups
    for target, entries in session._lookups.items():
        lines.append("")
        lines.append(f"Target: {target}")
        lines.append("-" * 40)

        for entry in entries:
            tool_type = entry["type"]
            result = entry["result"]
            lines.append(f"  Tool: {tool_type}")

            results_data = result.get("results", [])
            if isinstance(results_data, list):
                lines.append(f"  Results ({len(results_data)}):")
                for item in results_data:
                    if isinstance(item, str):
                        lines.append(f"    - {item}")
                    elif isinstance(item, dict):
                        parts = []
                        for k in ("service", "title", "url", "snippet", "username",
                                  "carrier", "country", "formatted", "type", "valid", "status"):
                            if item.get(k):
                                parts.append(f"{k}: {item[k]}")
                        if parts:
                            lines.append(f"    - {', '.join(parts)}")
                        else:
                            lines.append(f"    - {item}")

            elif isinstance(results_data, dict):
                for section, content in results_data.items():
                    if isinstance(content, dict):
                        lines.append(f"  {section}:")
                        for k, v in content.items():
                            if v:
                                lines.append(f"    {k}: {v}")
                    elif isinstance(content, list):
                        lines.append(f"  {section}:")
                        for sub in content[:30]:
                            lines.append(f"    - {sub}")
                    elif content:
                        lines.append(f"  {section}: {content}")

            if result.get("warnings"):
                lines.append(f"  Warnings: {', '.join(result['warnings'])}")

            lines.append("")

    # conversation summary
    lines.append("")
    lines.append("Conversation Log")
    lines.append("-" * 40)
    for turn in session._conversation:
        role = turn["role"].upper()
        content = turn["content"]
        # trim long tool outputs in the log
        if role == "TOOL" and len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"[{role}] {content}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("End of report")
    lines.append("=" * 60)

    with open(filepath, "w") as f:
        f.write("\n".join(lines))

    return filepath
