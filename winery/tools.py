"""Winery research tools.

These are the instruments Nanofossil uses to gather evidence.
The model decides what it needs; Winery executes.
"""

import re
import time
from typing import List, Optional, Dict
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str):
        self.title = title
        self.url = url
        self.snippet = snippet

    def to_dict(self) -> Dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class PageContent:
    def __init__(self, url: str, title: str, text: str, meta: Dict = None):
        self.url = url
        self.title = title
        self.text = text
        self.meta = meta or {}

    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text[:5000],
            "meta": self.meta
        }


def search_web(query: str, max_results: int = 6) -> List[SearchResult]:
    """Search the web using DuckDuckGo."""
    results = []

    if not HAS_DDGS:
        print("[Winery] duckduckgo-search not installed. Skipping web search.")
        return results

    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", "")
                ))
        print(f"[Winery] Search returned {len(results)} results for: {query}")
    except Exception as e:
        print(f"[Winery] Search failed for '{query}': {e}")

    return results


def fetch_page(url: str, timeout: int = 15) -> Optional[PageContent]:
    """Fetch and extract text content from a URL."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type:
            return PageContent(
                url=url, title="[PDF]",
                text="[PDF document — text extraction not available in V2]",
                meta={"type": "pdf"}
            )

        soup = BeautifulSoup(resp.text, "html.parser")

        for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script.decompose()

        title = ""
        if soup.title:
            title = soup.title.get_text(strip=True)
        elif soup.h1:
            title = soup.h1.get_text(strip=True)

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)

        if len(text) > 50000:
            text = text[:50000] + "\n...[content truncated]"

        meta = {}
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag:
            meta["description"] = meta_tag.get("content", "")

        date_tag = soup.find("meta", attrs={"property": "article:published_time"})
        if date_tag:
            meta["published"] = date_tag.get("content", "")

        return PageContent(url=url, title=title, text=text, meta=meta)

    except requests.exceptions.Timeout:
        print(f"[Winery] Timeout fetching {url}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[Winery] Failed to fetch {url}: {e}")
        return None
    except Exception as e:
        print(f"[Winery] Error processing {url}: {e}")
        return None


def is_valid_source(url: str) -> bool:
    """Basic source quality check."""
    parsed = urlparse(url)
    low_quality = [
        "reddit.com", "twitter.com", "x.com", "facebook.com",
        "youtube.com", "tiktok.com", "instagram.com",
        "quora.com", "pinterest.com"
    ]
    domain = parsed.netloc.lower()
    if any(lq in domain for lq in low_quality):
        return False
    return True


def classify_source(url: str, title: str = "") -> str:
    """Classify a source as primary or secondary."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    primary_indicators = [
        ".gov", ".edu", "arxiv.org", "doi.org", "ncbi.nlm.nih.gov",
        "ieee.org", "acm.org", "springer.com", "nature.com",
        "science.org", "cell.com", "thelancet.com",
        "sec.gov", "who.int", "un.org", "worldbank.org",
        "oecd.org", "imf.org"
    ]

    secondary_indicators = [
        "wikipedia.org", "medium.com", "substack.com",
        "blog.", "news.", "forbes.com", "cnn.com",
        "bbc.com", "reuters.com", "apnews.com",
        "techcrunch.com", "theverge.com", "wired.com"
    ]

    for ind in primary_indicators:
        if ind in domain:
            return "primary"

    for ind in secondary_indicators:
        if ind in domain:
            return "secondary"

    return "secondary"
