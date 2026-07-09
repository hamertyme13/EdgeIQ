"""NewsAPI context provider for player/team recommendation signals."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from data.providers.cache import get_json


_BASE = "https://newsapi.org/v2/everything"


def fetch_context(query: str, days: int = 7, page_size: int = 5) -> list[dict]:
    api_key = os.getenv("NEWSAPI_KEY", "").strip()
    if not api_key or not query.strip():
        return []

    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    url = (
        f"{_BASE}?q={quote_plus(query)}"
        f"&from={since}&language=en&sortBy=publishedAt&pageSize={page_size}"
    )
    try:
        data = get_json(
            url,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=12,
            ttl_seconds=1800,
        ).data
    except RuntimeError:
        return []

    return [
        {
            "title": article.get("title", ""),
            "description": article.get("description", ""),
            "source": (article.get("source") or {}).get("name", ""),
            "url": article.get("url", ""),
            "published_at": article.get("publishedAt", ""),
        }
        for article in data.get("articles", [])
        if article.get("title")
    ]


def risk_terms(articles: list[dict]) -> list[str]:
    terms = []
    needles = {
        "injury": ["injury", "injured", "questionable", "doubtful", "out"],
        "rest": ["rest", "resting", "minutes restriction", "load management"],
        "weather": ["weather", "wind", "rain", "snow", "storm"],
        "role": ["bench", "starter", "lineup", "usage", "rotation"],
    }
    haystack = " ".join(
        f"{article.get('title', '')} {article.get('description', '')}".lower()
        for article in articles
    )
    for label, words in needles.items():
        if any(word in haystack for word in words):
            terms.append(label)
    return terms
