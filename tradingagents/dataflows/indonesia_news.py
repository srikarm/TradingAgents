"""Indonesian financial news source via RSS aggregation.

Wired up so that News Analyst calls with a `.JK` ticker get Indonesian-context
news rather than the global English-language feeds. Two free public sources
(Detik Finance + Bisnis Indonesia), stdlib-only RSS parsing — no new deps.

Why not just rely on the global news vendor: Yahoo Finance and Alpha Vantage
both undercover Indonesian equities. For LQ45 majors (BBCA, TLKM, BMRI, ASII,
UNVR) Indonesian-language sources publish 10–50x more articles per week than
the English feeds and surface earnings, regulator filings, and local political
context the global feeds miss entirely.

The news is in Bahasa Indonesia. Modern LLMs (DeepSeek, Claude, GPT-4 class)
handle bilingual financial reasoning competently, so we pass raw Indonesian
text through to the analyst without translation. If output quality on this
falls short, the next step would be a translation pass before the LLM hop.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

# Free RSS feeds. Publicly published and meant for syndication; no auth
# required, no rate limit beyond reasonable polling. We give a clear
# User-Agent so the publishers can identify the source of traffic.
#
# URL provenance: empirically probed live from inside the worker container
# on 2026-05-19 — the original URLs shipped with PR #17 (rss.detik.com/...
# and bisnis.com/rss/...) both returned 404 / closed-connection in
# practice. The replacements below return 100-item feeds with current
# Indonesian financial coverage including ticker-specific articles (e.g.
# "Mandiri Sekuritas..." for BMRI.JK).
_RSS_SOURCES: list[tuple[str, str]] = [
    ("Detik Finance",      "https://finance.detik.com/rss"),
    ("CNBC Indonesia",     "https://www.cnbcindonesia.com/market/rss"),
]

_USER_AGENT = "TradingAgents/0.2 (+https://github.com/TauricResearch/TradingAgents)"
_FETCH_TIMEOUT_S = 10

# Common IDX LQ45 / blue-chip tickers → company name aliases. Used to widen
# relevance matching: a Detik article titled "Bank Central Asia laporkan laba
# bersih Q1 naik 12%" should match BBCA even though the headline doesn't carry
# the ticker symbol. Stays small and Indonesian-financial-relevant; we don't
# try to be exhaustive — the LLM sorts noise.
_TICKER_ALIASES: dict[str, list[str]] = {
    "BBCA": ["Bank Central Asia", "BCA"],
    "BBRI": ["Bank Rakyat Indonesia", "BRI"],
    "BMRI": ["Bank Mandiri", "Mandiri"],
    "BBNI": ["Bank Negara Indonesia", "BNI"],
    "TLKM": ["Telkom Indonesia", "Telkom"],
    "ASII": ["Astra International", "Astra"],
    "UNVR": ["Unilever Indonesia"],
    "GOTO": ["GoTo Gojek Tokopedia", "GoTo", "Gojek", "Tokopedia"],
    "GGRM": ["Gudang Garam"],
    "HMSP": ["HM Sampoerna", "Sampoerna"],
    "INDF": ["Indofood Sukses Makmur", "Indofood"],
    "ICBP": ["Indofood CBP", "ICBP"],
    "KLBF": ["Kalbe Farma"],
    "ANTM": ["Aneka Tambang", "Antam"],
    "PGAS": ["Perusahaan Gas Negara", "PGN"],
    "PTBA": ["Bukit Asam", "PT Bukit Asam"],
    "ADRO": ["Adaro Energy", "Adaro"],
    "MEDC": ["Medco Energi", "Medco"],
    "BRPT": ["Barito Pacific"],
}


def _strip_suffix(ticker: str) -> str:
    """Drop the `.JK` (or any other) suffix so 'BBCA.JK' becomes 'BBCA'."""
    ticker = ticker.upper()
    return ticker.split(".", 1)[0] if "." in ticker else ticker


def _aliases_for(ticker: str) -> list[str]:
    """Return [ticker_stem] + any known company name aliases for matching."""
    stem = _strip_suffix(ticker)
    return [stem] + _TICKER_ALIASES.get(stem, [])


def _fetch_rss(url: str) -> bytes | None:
    """GET an RSS feed body. Returns None on any network/HTTP error.

    Defensive: any single bad source must not block the analyst — the News
    Analyst still gets whatever the other feeds returned, and downstream the
    LLM proceeds with partial data rather than failing the whole run.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.warning("indonesia_news: failed to fetch %s: %s", url, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        # SSL errors, DNS failures, etc. — same defensive behavior.
        logger.warning("indonesia_news: unexpected error fetching %s: %s", url, exc)
        return None


def _parse_rss(body: bytes) -> list[dict]:
    """Parse RSS 2.0 / Atom into a list of dicts with title/desc/link/pub_date.

    Tolerant: missing fields become empty strings, malformed pub dates become
    None. Never raises.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        logger.warning("indonesia_news: RSS parse error: %s", exc)
        return []

    items: list[dict] = []
    # RSS 2.0: //channel/item; Atom: //entry. We accept either.
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1].lower()  # strip namespace
        if tag not in ("item", "entry"):
            continue

        def _text(child_tag: str) -> str:
            for child in el:
                if child.tag.split("}", 1)[-1].lower() == child_tag:
                    return (child.text or "").strip()
            return ""

        title = _text("title")
        desc = _text("description") or _text("summary") or _text("content")
        link = _text("link")
        pub_raw = _text("pubdate") or _text("published") or _text("updated")
        pub: datetime | None = None
        if pub_raw:
            try:
                pub = parsedate_to_datetime(pub_raw)
            except (TypeError, ValueError):
                pub = None

        if title:
            items.append({
                "title": title,
                "description": desc,
                "link": link,
                "pub_date": pub,
            })
    return items


def _matches(item: dict, aliases: list[str]) -> bool:
    """Case-insensitive word-boundary match of any alias against title+description.

    Word-boundary (``\\b``) is required because three-letter aliases like
    "BCA", "BRI", "BNI", "PGN" would substring-match unrelated text otherwise
    — e.g. "ABCA Mining" would falsely match BBCA, "REBNI" would falsely
    match BBNI. Caught by the PR #17 reviewer; regression test in
    tests/test_indonesia_news.py pins the boundary behavior.
    """
    hay = f"{item['title']} {item['description']}"
    return any(
        re.search(r"\b" + re.escape(alias) + r"\b", hay, re.IGNORECASE)
        for alias in aliases
    )


def get_news_indonesia(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    max_articles: int = 20,
) -> str:
    """Fetch Indonesian financial news for an IDX ticker in a date window.

    Output format mirrors `get_news_yfinance` so the News Analyst LLM
    receives a familiar shape regardless of which vendor served the call.

    Args:
        ticker: IDX ticker with or without the `.JK` suffix (e.g. "BBCA.JK").
        start_date / end_date: yyyy-mm-dd inclusive bounds.
        max_articles: cap to keep token usage reasonable.
    """
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        # End-date inclusive through 23:59:59 of that day — RSS pub dates are
        # local-time wall-clock (after tzinfo strip), so an item published at
        # 08:00 on the end_date would otherwise fall outside [00:00, 00:00].
        # Mirrors get_news_yfinance's `end_dt + relativedelta(days=1)`.
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        return f"Error: invalid date range {start_date} → {end_date}"

    aliases = _aliases_for(ticker)
    matched: list[dict] = []
    seen_titles: set[str] = set()

    for source_name, url in _RSS_SOURCES:
        body = _fetch_rss(url)
        if body is None:
            continue
        for item in _parse_rss(body):
            # Date filter (tolerate missing pub_date — include rather than skip)
            if item["pub_date"] is not None:
                pub_naive = item["pub_date"].replace(tzinfo=None)
                if not (start_dt <= pub_naive <= end_dt):
                    continue
            # Relevance filter
            if not _matches(item, aliases):
                continue
            # Dedup by title across sources
            key = item["title"].lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            item["_source"] = source_name
            matched.append(item)
            if len(matched) >= max_articles:
                break
        if len(matched) >= max_articles:
            break

    if not matched:
        return (
            f"No Indonesian news found for {ticker} between "
            f"{start_date} and {end_date}. Sources tried: "
            f"{', '.join(name for name, _ in _RSS_SOURCES)}."
        )

    # Sort newest-first to match the global vendors' implicit ordering.
    matched.sort(
        key=lambda i: i["pub_date"] or datetime.min,
        reverse=True,
    )

    out = [f"## {ticker} News (Indonesia), from {start_date} to {end_date}:\n"]
    for item in matched:
        out.append(f"### {item['title']} (source: {item['_source']})")
        if item["description"]:
            out.append(item["description"])
        if item["link"]:
            out.append(f"Link: {item['link']}")
        out.append("")
    return "\n".join(out)
