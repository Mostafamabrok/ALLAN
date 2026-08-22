import re
from html import unescape
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


def _strip_tags(raw_text):
    cleaned = re.sub(r"<[^>]+>", " ", raw_text or "")
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_url(raw_url, base_url="https://html.duckduckgo.com/"):
    if not raw_url:
        return ""

    href = raw_url.strip()
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(base_url, href)

    parsed = urlsplit(href)
    if parsed.netloc and "duckduckgo.com" in parsed.netloc:
        query = parse_qs(parsed.query)
        if "uddg" in query:
            return unquote(query["uddg"][0])

    return href


def run(query="", max_results=5, **kwargs):
    """Search the web using DuckDuckGo's HTML endpoint without requiring an API key."""
    if not query:
        return "Error: No search query provided."

    safe_query = quote(query.strip())
    search_url = f"https://html.duckduckgo.com/html/?q={safe_query}"
    request = Request(
        search_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            html_content = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return f"Web search failed: {exc}"

    links = re.findall(
        r'<a[^>]*class="[^"]*(?:result-link|result__a|result--a)[^"]*"[^>]*href="(.*?)"[^>]*>(.*?)</a>',
        html_content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r'<a[^>]*class="[^"]*(?:result__snippet|result-snippet)[^"]*"[^>]*>(.*?)</a>',
        html_content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    results = []
    seen_urls = set()
    for index, (raw_url, raw_title) in enumerate(links[: max_results * 5]):
        url = _normalize_url(raw_url)
        title = _strip_tags(raw_title)
        if not url or not title:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        snippet = ""
        if index < len(snippets):
            snippet = _strip_tags(snippets[index])

        results.append(f"{title}\n{url}\n{snippet}" if snippet else f"{title}\n{url}")

        if len(results) >= max_results:
            break

    if not results:
        return f"No search results found for: '{query}'."

    return (
        f"Web Search Results for: '{query}'\n"
        + "\n\n".join(f"{idx + 1}. {entry}" for idx, entry in enumerate(results))
    )