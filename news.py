"""
F.R.I.D.A.Y. News Module
Fetches headlines from Fox News, cybersecurity sources, and ESPN via RSS.
No API keys required.
"""

import requests
import xml.etree.ElementTree as ET
import time
from datetime import datetime

# ── RSS FEEDS ─────────────────────────────────────────────────────────────────
FEEDS = {
    "fox":    "https://moxie.foxnews.com/google-publisher/latest.xml",
    "fox_tech": "https://moxie.foxnews.com/google-publisher/tech.xml",
    "cyber":  "https://feeds.feedburner.com/TheHackersNews",
    "cyber2": "https://www.bleepingcomputer.com/feed/",
    "espn":   "https://www.espn.com/espn/rss/news",
    "espn_nfl": "https://www.espn.com/espn/rss/nfl/news",
}

_cache: dict = {}
CACHE_TTL = 600   # 10 minutes


def _fetch_rss(url: str) -> list:
    """Fetch and parse an RSS feed. Returns list of {title, link, published}."""
    now = time.time()
    if url in _cache and now - _cache[url]["ts"] < CACHE_TTL:
        return _cache[url]["items"]

    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)

        items = []
        # Handle both RSS and Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            if title:
                items.append({"title": title, "link": link, "published": pub})

        # Atom fallback
        if not items:
            for entry in root.findall(".//atom:entry", ns):
                title = entry.findtext("atom:title", "", ns).strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.attrib.get("href", "") if link_el is not None else ""
                items.append({"title": title, "link": link, "published": ""})

        _cache[url] = {"ts": now, "items": items[:20]}
        return items[:20]

    except Exception as e:
        print(f"[News] Feed error ({url}): {e}")
        return []


def get_fox_headlines(count: int = 5) -> list:
    items = _fetch_rss(FEEDS["fox"])
    return items[:count]


def get_cyber_headlines(count: int = 5) -> list:
    items = _fetch_rss(FEEDS["cyber"])
    if len(items) < count:
        items += _fetch_rss(FEEDS["cyber2"])
    return items[:count]


def get_espn_headlines(count: int = 5) -> list:
    items = _fetch_rss(FEEDS["espn"])
    if len(items) < count:
        items += _fetch_rss(FEEDS["espn_nfl"])
    return items[:count]


def get_all_headlines(count_each: int = 3) -> dict:
    return {
        "fox":   get_fox_headlines(count_each),
        "cyber": get_cyber_headlines(count_each),
        "espn":  get_espn_headlines(count_each),
    }


def format_headlines(headlines: dict, max_each: int = 3) -> str:
    """Format headlines dict into readable string for FRIDAY to speak."""
    lines = []

    if headlines.get("fox"):
        lines.append("Fox News:")
        for h in headlines["fox"][:max_each]:
            lines.append(f"  • {h['title']}")

    if headlines.get("cyber"):
        lines.append("Cybersecurity:")
        for h in headlines["cyber"][:max_each]:
            lines.append(f"  • {h['title']}")

    if headlines.get("espn"):
        lines.append("Sports:")
        for h in headlines["espn"][:max_each]:
            lines.append(f"  • {h['title']}")

    return "\n".join(lines) if lines else "No headlines available right now."


def get_news_brief() -> str:
    """Short spoken summary of top headlines."""
    all_h = get_all_headlines(2)
    parts  = []

    fox = all_h.get("fox", [])
    if fox:
        parts.append(f"Top story from Fox News: {fox[0]['title']}.")

    cyber = all_h.get("cyber", [])
    if cyber:
        parts.append(f"In cybersecurity: {cyber[0]['title']}.")

    espn = all_h.get("espn", [])
    if espn:
        parts.append(f"In sports: {espn[0]['title']}.")

    return " ".join(parts) if parts else "No news available right now."
