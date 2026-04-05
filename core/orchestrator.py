"""Plans and executes tool runs, with concurrent execution and web enrichment."""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from tools import call_tool
from tools.websearch import lookup as web_search


# which intents get a supplementary web search and what query to use
_WEB_ENRICHABLE = {
    "username_lookup": lambda v: f'"{v}" social media accounts profile',
    "email_lookup": lambda v: f'"{v}" email account breach',
    "domain_lookup": lambda v: f'"{v}" website company',
    "phone_lookup": None,  # phone.py already does its own web search
}

# friendly names for progress messages
_FRIENDLY_LABELS = {
    "username_lookup": "Searching for username",
    "email_lookup": "Checking email",
    "domain_lookup": "Looking up domain",
    "phone_lookup": "Investigating number",
    "person_lookup": "Searching for person",
    "web_search": "Searching the web",
    "_web_enrich": "Gathering extra info",
}


def _friendly(job_type: str) -> str:
    return _FRIENDLY_LABELS.get(job_type, "Working")


def _progress(msg: str):
    sys.stdout.write(f"\r  [...] {msg}   ")
    sys.stdout.flush()


def _clear_progress():
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def plan(intent: dict) -> list[dict]:
    """Decide which tools to run for a given intent."""
    intent_type = intent["type"]
    value = intent["value"]

    jobs = [{"type": intent_type, "value": value, "label": intent_type}]

    if intent_type == "person_lookup":
        return jobs

    if intent_type not in _WEB_ENRICHABLE:
        return jobs

    if not config.TIER_WEB_ENRICH.get(config.TIER, False):
        return jobs

    query_fn = _WEB_ENRICHABLE[intent_type]
    if query_fn is None:
        return jobs

    jobs.append({
        "type": "_web_enrich",
        "value": query_fn(value),
        "label": "web_search",
        "original_value": value,
    })

    return jobs


def execute(jobs: list[dict], session_hints: list = None, progress=True) -> list[dict]:
    """Run a list of jobs concurrently."""
    max_workers = config.TIER_MAX_WORKERS.get(config.TIER, 2)
    results = []

    if len(jobs) == 1:
        job = jobs[0]
        if progress:
            _progress(f"{_friendly(job['type'])}...")
        result = _run_job(job, session_hints=session_hints)
        if progress:
            _progress("Processing results...")
        return [result]

    if progress:
        labels = [_friendly(j["type"]) for j in jobs]
        _progress(f"{labels[0]}...")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_job, job, session_hints): job for job in jobs}
        done_count = 0
        total = len(jobs)

        for future in as_completed(futures):
            done_count += 1
            if progress:
                if done_count < total:
                    _progress(f"Still working ({done_count}/{total} done)...")
                else:
                    _progress("Processing results...")

            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append({
                    "job": futures[future],
                    "result": {"error": str(e)},
                })

    return results


def _run_job(job: dict, session_hints: list = None) -> dict:
    """Execute a single job and return tagged result."""
    job_type = job["type"]
    value = job["value"]

    if job_type == "_web_enrich":
        result = web_search(value)
        result["_enrichment"] = True
        result["_original_value"] = job.get("original_value", value)
    elif job_type == "person_lookup" and session_hints:
        result = call_tool(job_type, value, session_hints=session_hints)
    else:
        result = call_tool(job_type, value)

    return {"job": job, "result": result}


def merge_results(executed: list[dict]) -> tuple[dict, list[dict]]:
    """Split into primary result and supplementary results."""
    primary = None
    supplementary = []

    for item in executed:
        result = item["result"]
        if result.get("_enrichment"):
            supplementary.append(result)
        elif primary is None:
            primary = result
        else:
            supplementary.append(result)

    return primary, supplementary


def run(intent: dict, session_hints: list = None, progress=True) -> tuple[dict, list[dict]]:
    """Plan, execute, and merge."""
    jobs = plan(intent)
    executed = execute(jobs, session_hints=session_hints, progress=progress)
    primary, supplementary = merge_results(executed)

    if progress:
        _clear_progress()

    return primary, supplementary
