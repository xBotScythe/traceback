"""Formats tool output and handles conversation."""

import json

import config
from core import llm


# context budgets per tier (characters, not tokens - rough approximation)
# gemma 4 has much larger context windows so we can be more generous
_CONTEXT_BUDGETS = {
    "low": {"system": 1500, "results": 6000, "conversation": 3000, "knowledge": 3000},
    "mid": {"system": 2000, "results": 10000, "conversation": 5000, "knowledge": 5000},
    "high": {"system": 2500, "results": 14000, "conversation": 6000, "knowledge": 6000},
}


def _budget(key: str) -> int:
    tier = getattr(config, "TIER", "low")
    return _CONTEXT_BUDGETS.get(tier, _CONTEXT_BUDGETS["low"]).get(key, 1000)


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n  ... (trimmed)"


_BASE_RULES = "Use prior findings as context to interpret new results. No markdown. Raw URLs only. Be brief."

# max tokens per response type — summaries don't need 4096
_NUM_PREDICT = {
    "sherlock": 512,
    "email": 512,
    "domain": 768,
    "phone": 512,
    "web_search": 768,
    "person": 768,
    "chat": 256,
    "investigate": 768,
}

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
If results don't answer the question, say so. Do NOT guess or fill in gaps with unrelated results.
If a result contradicts prior findings, skip it — it's about a different person.
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



def _simplify_results(results: list, limit: int = 20, subject: str = "") -> str:
    """Turn a list of result dicts into compact data for the LLM."""
    if not results:
        return "(no results)"

    subject_lower = subject.lower() if subject else ""

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
                # only include snippet if it mentions the subject —
                # search engine snippets often contain text about
                # other users/accounts on the same page
                if snippet and subject_lower and subject_lower in snippet.lower():
                    line += f" | {snippet[:150].strip()}"
                elif snippet and not subject_lower:
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
    """Filter results to only those that actually mention the subject.

    Simple approach: the subject (name or username) must appear in the
    result text or URL. Context terms from session knowledge boost score
    but aren't required.
    """
    if not results or not isinstance(results, list):
        return results

    from tools.websearch import _extract_subject

    subject = _extract_subject(query).lower()
    subject_parts = subject.split()
    is_username = len(subject_parts) == 1

    # pull useful context from prior findings
    filler = {"the", "and", "for", "that", "this", "with", "from", "about",
              "what", "their", "they", "them", "some", "have", "has", "been",
              "are", "was", "were", "will", "can", "not", "but", "also",
              "more", "into", "give", "using", "check", "look", "find",
              "info", "information", "online", "post", "posts", "account",
              "user", "username", "does", "who", "where", "how",
              "participate", "activity", "content", "social", "media",
              "site", "com", "www", "https", "http", "html",
              "linkedin", "github", "twitter", "reddit", "facebook",
              "instagram", "tiktok", "youtube", "pinterest", "medium",
              "articles", "career", "staff", "bio", "profile", "website"}

    def _get_context_terms():
        terms = set()
        for word in f"{query} {user_input} {full_knowledge}".lower().split():
            clean = word.strip(".,;:()[]\"'/")
            if len(clean) >= 3 and clean not in filler and clean not in subject_parts:
                terms.add(clean)
        return terms

    context_terms = _get_context_terms()

    scored = []
    for r in results:
        if isinstance(r, dict):
            text = " ".join(str(v) for v in r.values()).lower()
            url = r.get("url", "").lower()
        elif isinstance(r, str):
            text = r.lower()
            url = ""
        else:
            text = str(r).lower()
            url = ""

        # primary check: does the subject appear in the result?
        if is_username:
            # for usernames, require it in the URL path or title —
            # snippets often mention the username in passing on unrelated pages
            has_subject = subject in url or subject in (r.get("title", "") if isinstance(r, dict) else "").lower()
        else:
            # for multi-word names, all parts must appear
            has_subject = all(part in text for part in subject_parts)

        if not has_subject:
            continue

        # score by context matches
        context_hits = sum(1 for t in context_terms if t in text)
        score = 1 + (context_hits * 2)

        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    # tag with confidence
    if scored:
        max_score = scored[0][0]
        for score, r in scored:
            if isinstance(r, dict):
                ratio = score / max_score if max_score > 0 else 0
                r["_confidence"] = "high" if ratio >= 0.5 else "medium"

    relevant = [r for _, r in scored]

    # if nothing passed the filter, return empty — better than
    # giving the LLM random garbage to hallucinate from
    if not relevant:
        return []

    # dedup linkedin profiles
    best_linkedin = None
    deduped = []
    for r in relevant:
        url = r.get("url", "") if isinstance(r, dict) else str(r)
        if "linkedin.com/in/" in url:
            if best_linkedin is None:
                best_linkedin = r
                deduped.append(r)
        else:
            deduped.append(r)

    return deduped[:15]


def format(tool_output: dict, user_input: str = "",
           conversation: str = "", full_knowledge: str = "",
           web_enrichment: list = None, stream_to=None) -> str:
    results = tool_output.get("results", [])
    tool_name = tool_output.get("tool", "unknown")
    query = tool_output.get("query", "")

    from tools.websearch import _extract_subject
    subject = _extract_subject(query)

    # filter out irrelevant results before the LLM sees them
    if isinstance(results, list):
        results = _relevance_filter(results, query, user_input, full_knowledge)
        data_text = _simplify_results(results, subject=subject)
    elif isinstance(results, dict):
        data_text = _simplify_dict_results(results)
    else:
        data_text = str(results)

    data_text = _trim(data_text, _budget("results"))

    # prior findings go FIRST so the model has context for interpreting new results
    prompt = f"Question: {user_input}\n"
    if full_knowledge:
        prompt += f"\nWhat we already know:\n{_trim(full_knowledge, _budget('knowledge'))}\n"
    if conversation:
        prompt += f"\nConversation:\n{_trim(conversation, _budget('conversation'))}\n"

    prompt += f"\nNew results:\n{data_text}"

    if web_enrichment:
        for enrichment in web_enrichment:
            enrich_results = enrichment.get("results", [])
            if enrich_results:
                prompt += f"\n\n{_trim(_simplify_results(enrich_results, limit=10, subject=subject), _budget('results') // 2)}"

    system = TOOL_PROMPTS.get(tool_name, SUMMARY_FALLBACK)
    predict = _NUM_PREDICT.get(tool_name, 768)

    try:
        return llm.ask(prompt, system=system, stream_to=stream_to,
                       options={"num_predict": predict})
    except (ConnectionError, RuntimeError):
        return _fallback_format(tool_output)


def investigate(results: dict, name: str, user_input: str = "",
                conversation: str = "", stream_to=None) -> str:
    """Present person search results as numbered picks."""
    result_list = results.get("results", [])
    result_list = _relevance_filter(result_list, name, user_input, conversation)
    data_text = _simplify_results(result_list, limit=15, subject=name)
    data_text = _trim(data_text, _budget("results"))

    prompt = f"Target: {name}"
    if user_input:
        prompt += f"\nUser said: {user_input}"
    prompt += f"\n\nSearch results:\n{data_text}"

    if conversation:
        prompt += f"\n\nConversation so far:\n{_trim(conversation, _budget('conversation'))}"

    try:
        return llm.ask(prompt, system=INVESTIGATE_SYSTEM, stream_to=stream_to,
                       options={"num_predict": _NUM_PREDICT["investigate"]})
    except (ConnectionError, RuntimeError):
        return _fallback_format(results)


def chat(user_input: str, conversation: str, stream_to=None) -> str:
    conv = _trim(conversation, _budget("conversation"))
    prompt = f"Conversation:\n{conv}\n\nUser: {user_input}"
    try:
        response = llm.ask(prompt, system=CHAT_SYSTEM, stream_to=stream_to,
                           options={"num_predict": _NUM_PREDICT["chat"]})
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
