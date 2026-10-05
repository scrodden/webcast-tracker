"""Webcasts announced in press releases on GlobeNewswire.

Companies announce earnings calls and conference appearances in press releases
("will present at the Goldman Sachs Communacopia + Technology Conference ...
listen to the live webcast at investor.nvidia.com"). This reaches companies whose
IR sites turn away automated visitors. When a release gives the player's address
the entry links to it; otherwise it links to the company page the release names.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import json
from datetime import date

from . import config, store
from .conferences import _CONF_RE, extract_conference_name
from .dates import find_date_near
from .extract import is_webcast_url

# GlobeNewswire's robots.txt rules out its search pages, but its sitemaps list every
# release; the address spells out the headline, which is enough to pick candidates.
SITEMAP_URL = "https://sitemaps.globenewswire.com/news/en/{period}.xml"
BASE = "https://www.globenewswire.com"
SEEN_FILE = config.DATA_DIR / "newswire_seen.json"

# Headline words of releases that announce an event with a webcast.
_EVENT_SLUG = re.compile(r"webcast|conference|present|participat|fireside|investor-day|analyst-day|"
                         r"conference-call|earnings|financial-results|results|upcoming-event|annual-meeting|"
                         r"stockholder|shareholder", re.I)

_EARNINGS_RE = re.compile(
    r"\b((?:first|second|third|fourth)[- ]quarter(?:\s+(?:of\s+)?(?:fiscal\s+(?:year\s+)?)?20\d\d)?|"
    r"q[1-4]\s+(?:fiscal\s+)?(?:fy\s*)?20\d\d|(?:fiscal\s+)?(?:full[- ]year|year[- ]end)\s+20\d\d)", re.I)
_URL_IN_TEXT = re.compile(r"(?:https?://|www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s,;)]*)?", re.I)


def sitemap_urls(xml):
    return [urljoin(BASE, u) for u in re.findall(r"<loc>([^<]+)</loc>", xml)]


def _slug(url):
    return url.rsplit("/", 1)[-1].lower()


_STOP = {"inc", "corp", "corporation", "co", "company", "holdings", "group", "ltd", "plc",
         "the", "and", "of", "incorporated", "limited", "sa", "nv", "ag", "lp", "llc"}


def name_slug(name):
    """'Eli Lilly and Company' → 'eli-lilly'; how GlobeNewswire headlines start."""
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if w not in _STOP]
    return "-".join(words[:2]) if words else ""


def candidates(urls, companies):
    """(release URL, company) pairs whose headline starts with a company's name and
    mentions an event."""
    by_first = {}
    for c in companies:
        slug = name_slug(c.get("name"))
        if slug:
            by_first.setdefault(slug.split("-")[0], []).append((slug, c))
    out = []
    for url in urls:
        slug = _slug(url)
        if not _EVENT_SLUG.search(slug):
            continue
        for prefix, c in by_first.get(slug.split("-")[0], []):
            if slug.startswith(prefix + "-") or slug.startswith(prefix.split("-")[0] + "-"):
                out.append((url, c))
    return out


def mentions_ticker(text, company):
    tickers = "|".join(re.escape(t) for t in company.get("tickers", []))
    return bool(tickers) and bool(re.search(rf"(?:nyse|nasdaq|cboe)[^:)]{{0,25}}:\s*(?:{tickers})\b", text, re.I))


def _webcast_page(text, links, company):
    """Where the release sends listeners: a player URL, else the company page it names."""
    players = [u for u in links if is_webcast_url(u)]
    if players:
        return players[0], "webcast"
    idx = text.lower().find("webcast")
    window = text[idx: idx + 400] if idx >= 0 else ""
    for m in _URL_IN_TEXT.finditer(window):
        candidate = m.group(0).rstrip(".")
        if "." in candidate and "@" not in window[max(0, m.start() - 1): m.start() + 1]:
            if not candidate.startswith("http"):
                candidate = "https://" + candidate
            return candidate, "event"
    return company.get("ir_url"), "event"


def parse_release(html, company):
    """[{title, date, url, kind}] for the events a release announces."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("#main-body-container") or soup.select_one(".main-body-container") or soup.body
    if body is None:
        return []
    text = re.sub(r"\s+", " ", body.get_text(" "))
    if "webcast" not in text.lower() or not mentions_ticker(text, company):
        return []
    released = None
    t = soup.find("time")
    if t and t.get("datetime"):
        released = t["datetime"][:10]
    headline = soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""
    links = [urljoin(BASE, a["href"]) for a in body.find_all("a", href=True)]
    url, kind = _webcast_page(text, links, company)
    if not url:
        return []

    events = []
    # Conference appearances: each named conference, dated by the text right after it.
    for m in _CONF_RE.finditer(text):
        name = extract_conference_name(m.group(0))
        if not name or any(e["title"] == name for e in events):
            continue
        when = find_date_near(text[m.end(): m.end() + 120], released) if released else None
        events.append({"title": name, "date": when, "url": url, "kind": kind})
    if events:
        return events
    # Earnings calls.
    if re.search(r"conference call|earnings call|financial results|results", headline + " " + text[:600], re.I):
        quarter = _EARNINGS_RE.search(headline) or _EARNINGS_RE.search(text[:1500])
        title = f"{quarter.group(1).strip().title()} Earnings Call" if quarter else "Earnings Call"
        idx = text.lower().find("conference call")
        when = find_date_near(text[idx: idx + 300] if idx >= 0 else text[:800], released) if released else None
        return [{"title": title, "date": when, "url": url, "kind": kind}]
    return []


def _periods(months):
    today = date.today()
    out = ["latest"]
    y, m = today.year, today.month
    for _ in range(months):
        out.append(f"{y}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def run(companies, webcasts, fetcher, months=1):
    """Read GlobeNewswire's sitemaps for the last `months` months and add the events
    announced by our companies. Returns (releases read, new entries)."""
    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()
    urls = []
    for period in _periods(months):
        resp = fetcher.get(SITEMAP_URL.format(period=period), retries=1)
        if resp is not None:
            urls += sitemap_urls(resp.text)
    pairs = [(u, c) for u, c in candidates(dict.fromkeys(urls), companies) if u not in seen]
    read = new = 0
    for url, company in pairs:
        page = fetcher.get(url, retries=1)
        if page is None:
            continue
        read += 1
        seen.add(url)
        for e in parse_release(page.text, company):
            new += store.upsert_webcast(webcasts, company["id"], e["url"], e["title"], e["date"],
                                        "press-release", url, kind=e["kind"])
    SEEN_FILE.write_text(json.dumps(sorted(seen)[-50000:]))
    return read, new
