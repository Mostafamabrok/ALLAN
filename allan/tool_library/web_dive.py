import re
from html import unescape
from urllib.request import Request, urlopen


def _strip_tags(raw_text):
    cleaned = re.sub(r"<script.*?</script>", " ", raw_text or "", flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def run(url="", max_chars=2500, **kwargs):
    """Fetch a page and extract the main readable content without an API key."""
    if not url:
        return "Error: No target URL provided."

    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    try:
        with urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return f"Web dive failed: {exc}"

    if not html:
        return f"No content was returned from: {url}"

    text = _strip_tags(html)
    if len(text) > max_chars:
        text = text[: max_chars].rsplit(" ", 1)[0] + "..."

    if not text:
        return f"No readable text was found on: {url}"

    return f"Web Dive Result for: {url}\n\n{text}"
