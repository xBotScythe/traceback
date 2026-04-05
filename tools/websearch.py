"""Web search via DuckDuckGo with OSINT dork-style queries."""

import re
import sys
import time

from tools import register


# dorks applied after the broad search to find more specific results
# {query} is the user's search terms, {subject} is the main name/username extracted
_DORKS = [
    '"{subject}"',
    '"{subject}" site:linkedin.com',
    '"{subject}" site:github.com',
    '"{subject}" site:reddit.com',
    '"{subject}" site:twitter.com OR site:x.com',
]

# person-specific dorks
_PERSON_DORKS = [
    '"{query}"',
    '{query}',
    '"{subject}" site:linkedin.com',
    '"{subject}" site:facebook.com',
    '"{subject}" site:twitter.com OR site:x.com',
    '"{subject}" site:instagram.com',
    '"{subject}" site:github.com',
    '"{subject}" site:reddit.com',
    '"{subject}" site:youtube.com',
]


def _extract_subject(query: str) -> str:
    """Pull the main subject (name/username) from a search query.

    'Jane Doe Acme Magazine writer' -> 'Jane Doe'
    'johndoe reddit' -> 'johndoe'
    """
    # strip common context words to find the core subject
    context_words = {
        "site", "reddit", "tiktok", "instagram", "youtube", "github",
        "twitter", "facebook", "linkedin", "discord", "twitch",
        "writer", "author", "developer", "engineer", "designer",
        "programmer", "researcher", "journalist", "editor", "reporter",
        "magazine", "newspaper", "publication", "blog", "forum",
        "account", "profile", "activity",
        "posts", "history", "info", "information", "about",
    }
    words = query.split()
    # take the leading words that aren't context
    subject_words = []
    for w in words:
        if w.lower().rstrip(",.;:") in context_words:
            break
        subject_words.append(w)
    return " ".join(subject_words) if subject_words else query.split()[0] if query.split() else query


@register("web_search")
def lookup(query: str, person_mode: bool = False) -> dict:
    """Layered web search: broad first, then targeted dorks."""
    DDGS = _get_ddgs()
    if DDGS is None:
        return {
            "tool": "web_search",
            "query": query,
            "error": "ddgs not installed. Run: pip install ddgs",
        }

    results = []
    seen_urls = set()
    url_hit_count = {}  # track how many searches found each URL
    errors = []
    subject = _extract_subject(query)

    # phase 1: broad search with the full query as-is
    sys.stdout.write(f"\r  [...] Searching: {query[:50]}   ")
    sys.stdout.flush()
    broad = _search(DDGS, query, seen_urls, errors, max_results=10)
    for r in broad:
        url_hit_count[r.get("url", "")] = url_hit_count.get(r.get("url", ""), 0) + 1
    results.extend(broad)

    # also try quoted subject
    if subject != query:
        quoted = _search(DDGS, f'"{subject}"', seen_urls, errors, max_results=10)
        for r in quoted:
            url_hit_count[r.get("url", "")] = url_hit_count.get(r.get("url", ""), 0) + 1
        results.extend(quoted)

    # phase 2: targeted dorks from the standard list
    dorks = _PERSON_DORKS if person_mode else _DORKS
    for i, template in enumerate(dorks, 1):
        dork = template.format(query=query, subject=subject)
        if dork.strip('"') == query or dork.strip('"') == subject:
            continue
        sys.stdout.write(f"\r  [...] Narrowing down ({i}/{len(dorks)})...   ")
        sys.stdout.flush()
        hits = _search(DDGS, dork, seen_urls, errors, max_results=5)
        for r in hits:
            url_hit_count[r.get("url", "")] = url_hit_count.get(r.get("url", ""), 0) + 1
        results.extend(hits)

    # phase 3: dork against domains we already found in broad results
    # e.g. if broad found acmemag.com, search "Jane Doe" site:acmemag.com
    # to find more content on that site (like individual articles)
    found_domains = _unique_domains(results)
    for i, domain in enumerate(found_domains[:4]):
        sys.stdout.write(f"\r  [...] Checking {domain}...   ")
        sys.stdout.flush()
        hits = _search(DDGS, f'"{subject}" site:{domain}', seen_urls, errors, max_results=5)
        for r in hits:
            url_hit_count[r.get("url", "")] = url_hit_count.get(r.get("url", ""), 0) + 1
        results.extend(hits)

    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()

    # sort: results found in multiple searches are likely more relevant
    results.sort(key=lambda r: url_hit_count.get(r.get("url", ""), 0), reverse=True)

    output = {
        "tool": "web_search",
        "query": query,
        "results": results,
        "has_data": bool(results),
        "total_results": len(results),
    }
    if errors:
        output["warnings"] = errors
    return output


def _unique_domains(results: list) -> list:
    """Extract unique domains from results, skipping generic ones."""
    from urllib.parse import urlparse
    skip = {"google.com", "duckduckgo.com", "wikipedia.org", "youtube.com",
            "facebook.com", "twitter.com", "x.com", "instagram.com",
            "linkedin.com", "github.com", "reddit.com", "tiktok.com",
            "pinterest.com", "amazon.com", "yelp.com"}
    seen = set()
    domains = []
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        try:
            domain = urlparse(url).netloc.lower()
            if domain and domain not in seen and domain not in skip:
                seen.add(domain)
                domains.append(domain)
        except Exception:
            continue
    return domains


def person_search(name: str, extra_context: str = "", session_hints: list = None) -> dict:
    """Person search. Just calls lookup() in person_mode with combined query."""
    query = f"{name} {extra_context}".strip() if extra_context else name
    return lookup(query, person_mode=True)


def _get_ddgs():
    """Import DDGS from whichever package name is installed."""
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        pass
    try:
        from duckduckgo_search import DDGS
        return DDGS
    except ImportError:
        pass
    return None


def _has_googlesearch():
    """Check if googlesearch-python is available."""
    try:
        from googlesearch import search as _gsearch
        return True
    except ImportError:
        return False


def _search(ddgs_cls, query: str, seen: set, errors: list, max_results: int = 10) -> list:
    """Search using Google first, fall back to DuckDuckGo."""
    hits = []

    if _has_googlesearch():
        hits = _search_google(query, seen, errors, max_results)

    # fall back to ddgs if google returned nothing or isn't installed
    if not hits and ddgs_cls is not None:
        hits = _search_ddgs(ddgs_cls, query, seen, errors, max_results)

    return hits


def _clean_text(text: str) -> str:
    """Basic cleanup of search result text."""
    if not text:
        return text
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _search_ddgs(ddgs_cls, query: str, seen: set, errors: list, max_results: int = 10) -> list:
    hits = []
    try:
        with ddgs_cls() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                url = r.get("href", "")
                if url and url not in seen:
                    seen.add(url)
                    hits.append({
                        "title": _clean_text(r.get("title", "")),
                        "url": url,
                        "snippet": _clean_text(r.get("body", "")),
                        "dork": query,
                        "engine": "duckduckgo",
                    })
    except Exception as e:
        errors.append(f"DuckDuckGo failed for '{query}': {e}")
    return hits


def _search_google(query: str, seen: set, errors: list, max_results: int = 10) -> list:
    """Search using googlesearch-python as fallback."""
    hits = []
    try:
        from googlesearch import search as gsearch
        for url in gsearch(query, num_results=max_results, sleep_interval=1):
            if url and url not in seen:
                seen.add(url)
                hits.append({
                    "title": "",
                    "url": url,
                    "snippet": "",
                    "dork": query,
                    "engine": "google",
                })
    except Exception as e:
        errors.append(f"Google failed for '{query}': {e}")
    return hits
