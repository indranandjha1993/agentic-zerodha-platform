import ipaddress
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings


class ResearchToolError(RuntimeError):
    """Raised when a research tool operation fails."""


def _is_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.hostname is None:
        return False

    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        # Host is a domain name.
        pass

    return True


class GoogleSearchTool:
    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        if query.strip() == "":
            raise ResearchToolError("Search query cannot be empty.")

        if settings.SERPER_API_KEY:
            return self._search_serper(query=query, limit=limit)
        if settings.GOOGLE_CSE_API_KEY and settings.GOOGLE_CSE_ENGINE_ID:
            return self._search_google_cse(query=query, limit=limit)

        raise ResearchToolError(
            "No search provider configured. "
            "Set SERPER_API_KEY or GOOGLE_CSE_API_KEY+GOOGLE_CSE_ENGINE_ID."
        )

    @staticmethod
    def _search_serper(query: str, limit: int) -> list[dict[str, str]]:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": settings.SERPER_API_KEY},
            json={"q": query, "num": max(1, min(limit, 10))},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        results: list[dict[str, str]] = []
        for item in payload.get("organic", [])[:limit]:
            results.append(
                {
                    "title": str(item.get("title", "")),
                    "url": str(item.get("link", "")),
                    "snippet": str(item.get("snippet", "")),
                }
            )
        return results

    @staticmethod
    def _search_google_cse(query: str, limit: int) -> list[dict[str, str]]:
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": settings.GOOGLE_CSE_API_KEY,
                "cx": settings.GOOGLE_CSE_ENGINE_ID,
                "q": query,
                "num": max(1, min(limit, 10)),
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        results: list[dict[str, str]] = []
        for item in payload.get("items", [])[:limit]:
            results.append(
                {
                    "title": str(item.get("title", "")),
                    "url": str(item.get("link", "")),
                    "snippet": str(item.get("snippet", "")),
                }
            )
        return results


class OpenWebpageTool:
    def open(self, url: str, max_chars: int = 6000) -> dict[str, Any]:
        if not _is_public_url(url):
            raise ResearchToolError("Only public http(s) URLs are allowed.")

        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": settings.WEB_TOOL_USER_AGENT},
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            return {
                "url": url,
                "title": "",
                "content_type": content_type,
                "content": response.text[:max_chars],
            }

        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = " ".join(part.strip() for part in soup.stripped_strings)
        normalized_text = " ".join(text.split())

        return {
            "url": url,
            "title": title,
            "content_type": content_type,
            "content": normalized_text[:max_chars],
        }
