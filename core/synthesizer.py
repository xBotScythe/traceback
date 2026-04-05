"""Formats tool output and handles conversation."""

import json

import config
from core import llm


# context budgets per tier (characters, not tokens - rough approximation)
# keeps prompts from overwhelming smaller models
_CONTEXT_BUDGETS = {
    "low": {"system": 1000, "results": 4000, "conversation": 2000, "knowledge": 2000},
    "mid": {"system": 1500, "results": 6000, "conversation": 3000, "knowledge": 3000},
    "high": {"system": 2000, "results": 8000, "conversation": 4000, "knowledge": 4000},
}


def _budget(key: str) -> int:
    tier = getattr(config, "TIER", "low")
    return _CONTEXT_BUDGETS.get(tier, _CONTEXT_BUDGETS["low"]).get(key, 1000)


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n  ... (trimmed)"


_BASE_RULES = "Answer what was asked — do not repeat prior findings. No markdown. Raw URLs only. Be brief. Only state NEW facts from these results."

TOOL_PROMPTS = {
    "sherlock": f"""Traceback, an OSINT tool. Summarize which platforms this username was found on.
Group by category (social media, dev, gaming, etc). {_BASE_RULES}
End with Sources: listing profile URLs.""",

    "email": f"""Traceback, an OSINT tool. Summarize what services this email is registered on and any breaches found.
{_BASE_RULES} End with Sources: listing relevant URLs.""",

    "domain": f"""Traceback, an OSINT tool. Summarize the domain info: registrar, owner, DNS, tech stack, security posture.
{_BASE_RULES}""",

    "phone": f"""Traceback, an OSINT tool. Summarize the phone number: carrier, type, location, and any web mentions.
{_BASE_RULES} End with Sources: listing relevant URLs.""",

    "web_search": f"""Traceback, an OSINT tool. Summarize what these search results reveal about the subject.
IMPORTANT: Results marked [low] are likely about a DIFFERENT person — do NOT include them.
If a result's job title, location, or employer contradicts prior findings, it's a different person. Skip it entirely.
Use prior findings to confirm identity before including new info.
{_BASE_RULES} End with Sources: listing URLs you used.""",

    "person": f"""Traceback, an OSINT tool. Summarize what these results reveal about this person.
IMPORTANT: Results marked [low] are likely about a DIFFERENT person — do NOT include them.
If a result's job title, location, or employer contradicts prior findings, it's a different person. Skip it entirely.
{_BASE_RULES} End with Sources: listing URLs you used. Use [1] [2] [3] for next steps.""",
}

SUMMARY_FALLBACK = f"""Traceback, an OSINT tool. Summarize the results.
Skip wrong-person results. {_BASE_RULES} End with Sources: listing URLs."""

CHAT_SYSTEM = """Traceback, an OSINT tool in a terminal. Be brief.
Only reference what you've actually found. No markdown. Plain text only."""

INVESTIGATE_SYSTEM = f"""Traceback, investigating a person in a terminal.
Results marked [low] are about a DIFFERENT person — do NOT include them.
If a result contradicts known facts (wrong job, wrong location), skip it entirely.
{_BASE_RULES} End with Sources: listing URLs. Use [1] [2] [3] for next steps."""



def _simplify_results(results: list, limit: int = 20) -> str:
    """Turn a list of result dicts into compact data for the LLM to interpret.

    Gives the LLM enough to summarize from, but keeps it compact so it doesn't
    just regurgitate raw text.
    """
    if not results:
        return "(no results)"

    lines = []
    for i, item in enumerate(results[:limit], 1):
        if isinstance(item, str):
            lines.append(f"  {i}. {item}")
        elif isinstance(item, dict):
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("snippet", item.get("body", ""))
            service = item.get("service", "")
            status_val = item.get("status", "")

            if title and url:
                conf = item.get("_confidence", "")
                tag = f" [{conf}]" if conf else ""
                line = f"  {i}.{tag} {title} | {url}"
                if snippet:
                    line += f" | {snippet[:150].strip()}"
                lines.append(line)
            elif service:
                line = f"  {i}. {service}"
                if status_val:
                    line += f" [{status_val}]"
                if url:
                    line += f" | {url}"
                lines.append(line)
            elif url:
                lines.append(f"  {i}. {url}")
            else:
                lines.append(f"  {i}. {json.dumps(item)}")

    if len(results) > limit:
        lines.append(f"  ... and {len(results) - limit} more results")

    return "\n".join(lines)


def _simplify_dict_results(data: dict) -> str:
    """Turn nested dict results (like domain/phone) into readable text."""
    lines = []
    for section, content in data.items():
        if isinstance(content, dict):
            lines.append(f"  {section}:")
            for k, v in content.items():
                if v:
                    lines.append(f"    {k}: {v}")
        elif isinstance(content, list):
            lines.append(f"  {section}:")
            for item in content[:20]:
                if isinstance(item, dict):
                    parts = [f"{k}: {v}" for k, v in item.items() if v]
                    lines.append(f"    - {', '.join(parts)}")
                else:
                    lines.append(f"    - {item}")
        elif content:
            lines.append(f"  {section}: {content}")
    return "\n".join(lines)



def _relevance_filter(results: list, query: str, user_input: str,
                      full_knowledge: str) -> list:
    """Score and filter results so the LLM only sees relevant ones.

    Splits terms into "name" (the person's name) and "context" (everything
    else like job title, school, company). Results that match the name but
    zero context terms are likely a different person with the same name
    and get dropped.
    """
    if not results or not isinstance(results, list):
        return results

    from tools.websearch import _extract_subject

    filler = {"the", "and", "for", "that", "this", "with", "from", "about",
              "what", "their", "they", "them", "some", "have", "has", "been",
              "are", "was", "were", "will", "can", "not", "but", "also",
              "more", "into", "give", "using", "check", "look", "find",
              "info", "information", "well", "little", "bit",
              "site", "com", "www", "https", "http", "html",
              "linkedin", "github", "twitter", "reddit", "facebook",
              "instagram", "tiktok", "youtube", "pinterest", "medium",
              "articles", "career", "staff", "bio", "profile", "website",
              "online", "post", "posts", "account", "accounts", "page",
              "user", "username", "does", "what", "who", "where", "how",
              "participate", "activity", "content", "social", "media"}

    def _extract_terms(text):
        terms = set()
        for word in text.lower().split():
            clean = word.strip(".,;:()[]\"'/")
            if len(clean) >= 3 and clean not in filler:
                terms.add(clean)
        return terms

    # separate name terms from context terms
    subject = _extract_subject(query)
    name_terms = _extract_terms(subject)
    all_terms = _extract_terms(f"{query} {user_input} {full_knowledge}")
    context_terms = all_terms - name_terms

    if not all_terms:
        return results

    scored = []
    for r in results:
        if isinstance(r, str):
            text = r.lower()
        elif isinstance(r, dict):
            text = " ".join(str(v) for v in r.values()).lower()
        else:
            text = str(r).lower()

        name_hits = sum(1 for t in name_terms if t in text)
        context_hits = sum(1 for t in context_terms if t in text)
        score = name_hits + (context_hits * 3)

        # for single-word subjects (usernames), check the URL directly —
        # if the URL contains a similar-but-different handle, drop it
        if isinstance(r, dict) and len(name_terms) == 1 and " " not in subject:
            url = r.get("url", "").lower()
            if subject.lower() not in url and name_hits == 0:
                continue

        # partial name match = likely a different person
        if name_terms and name_hits < len(name_terms):
            score = max(0, context_hits)

        # name match but zero context = almost certainly a different person
        if name_hits > 0 and context_hits == 0 and len(context_terms) >= 2:
            continue

        # no name match and no context match = completely irrelevant
        if name_hits == 0 and context_hits == 0:
            continue

        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    # tag results with confidence for the LLM
    max_score = scored[0][0] if scored else 1
    for score, r in scored:
        if isinstance(r, dict):
            if max_score > 0:
                ratio = score / max_score
                if ratio >= 0.6:
                    r["_confidence"] = "high"
                elif ratio >= 0.3:
                    r["_confidence"] = "medium"
                else:
                    r["_confidence"] = "low"
            else:
                r["_confidence"] = "low"

    # drop low confidence results entirely — don't let the LLM see them
    relevant = [r for score, r in scored if score > 0]
    relevant = [r for r in relevant
                if not isinstance(r, dict) or r.get("_confidence") != "low"]
    if not relevant:
        relevant = [r for _, r in scored[:10]]

    # dedup LinkedIn profiles: multiple /in/ URLs = different people, keep best only
    best_linkedin = None
    deduped = []
    for r in relevant:
        url = r.get("url", "") if isinstance(r, dict) else str(r)
        if "linkedin.com/in/" in url:
            if best_linkedin is None:
                best_linkedin = r
                deduped.append(r)
            # skip other linkedin profile URLs (they're different people)
        else:
            deduped.append(r)

    return deduped[:15]


def format(tool_output: dict, user_input: str = "",
           conversation: str = "", full_knowledge: str = "",
           web_enrichment: list = None) -> str:
    results = tool_output.get("results", [])
    tool_name = tool_output.get("tool", "unknown")
    query = tool_output.get("query", "")

    # filter out irrelevant results before the LLM sees them
    if isinstance(results, list):
        results = _relevance_filter(results, query, user_input, full_knowledge)
        data_text = _simplify_results(results)
    elif isinstance(results, dict):
        data_text = _simplify_dict_results(results)
    else:
        data_text = str(results)

    data_text = _trim(data_text, _budget("results"))

    prompt = f"Question: {user_input}\n\nResults:\n{data_text}"

    if web_enrichment:
        for enrichment in web_enrichment:
            enrich_results = enrichment.get("results", [])
            if enrich_results:
                prompt += f"\n\n{_trim(_simplify_results(enrich_results, limit=10), _budget('results') // 2)}"

    if full_knowledge:
        prompt += f"\n\nPrior findings:\n{_trim(full_knowledge, _budget('knowledge'))}"
    if conversation:
        prompt += f"\n\nConversation:\n{_trim(conversation, _budget('conversation'))}"

    system = TOOL_PROMPTS.get(tool_name, SUMMARY_FALLBACK)

    try:
        return llm.ask(prompt, system=system)
    except (ConnectionError, RuntimeError):
        return _fallback_format(tool_output)


def investigate(results: dict, name: str, user_input: str = "",
                conversation: str = "") -> str:
    """Present person search results as numbered picks."""
    result_list = results.get("results", [])
    result_list = _relevance_filter(result_list, name, user_input, conversation)
    data_text = _simplify_results(result_list, limit=15)
    data_text = _trim(data_text, _budget("results"))

    prompt = f"Target: {name}"
    if user_input:
        prompt += f"\nUser said: {user_input}"
    prompt += f"\n\nSearch results:\n{data_text}"

    if conversation:
        prompt += f"\n\nConversation so far:\n{_trim(conversation, _budget('conversation'))}"

    try:
        return llm.ask(prompt, system=INVESTIGATE_SYSTEM)
    except (ConnectionError, RuntimeError):
        return _fallback_format(results)



def chat(user_input: str, conversation: str) -> str:
    conv = _trim(conversation, _budget("conversation"))
    prompt = f"Conversation:\n{conv}\n\nUser: {user_input}"
    try:
        response = llm.ask(prompt, system=CHAT_SYSTEM)
        return response if response.strip() else "Not sure what to make of that. Try a username, email, or domain lookup."
    except (ConnectionError, RuntimeError):
        return "Something went wrong. Try again."


def _fallback_format(tool_output: dict) -> str:
    tool = tool_output.get("tool", "unknown")
    query = tool_output.get("query", "")
    results = tool_output.get("results", [])

    if not results:
        return f"No results found for '{query}' using {tool}."

    lines = [f"Found {len(results)} result(s) for '{query}':"]
    for item in results[:20]:
        if isinstance(item, str):
            lines.append(f"  - {item}")
        elif isinstance(item, dict):
            title = item.get("title", item.get("service", ""))
            url = item.get("url", "")
            if title and url:
                lines.append(f"  - {title} ({url})")
            elif title:
                lines.append(f"  - {title}")
            elif url:
                lines.append(f"  - {url}")
    return "\n".join(lines)
