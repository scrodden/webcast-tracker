"""JSON-backed storage for companies and webcasts.

Plain JSON keeps the data diffable when it is committed by the scheduled job.
Companies are keyed by a country-prefixed id ("us-aapl") that stays put when a
ticker changes; other countries can use their own prefix later.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone

from . import config


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def load_companies():
    """Return {company_id: company_dict}."""
    return _load(config.COMPANIES_FILE, {})


def save_companies(companies):
    _save(config.COMPANIES_FILE, companies)


def load_webcasts():
    """Return {webcast_id: webcast_dict}."""
    return _load(config.WEBCASTS_FILE, {})


def save_webcasts(webcasts):
    _save(config.WEBCASTS_FILE, webcasts)


def webcast_id(company_id, url):
    return hashlib.sha1(f"{company_id}|{url}".encode()).hexdigest()[:12]


def upsert_webcast(webcasts, company_id, url, title, date, source, source_url, kind="webcast"):
    """Insert or refresh one webcast; returns True when it is new.

    kind="event" marks an announced event whose link is the company's own webcast
    page rather than the player itself (keyed by date and title as well, since
    several events share that page).
    """
    wid = webcast_id(company_id, url if kind == "webcast" else f"{url}|{date}|{title}")
    seen = now_iso()
    existing = webcasts.get(wid)
    if existing:
        existing["last_seen"] = seen
        # Later passes may read the page better (e.g. after a parser fix).
        if title:
            existing["title"] = title
        if date:
            existing["date"] = date
        return False
    webcasts[wid] = {
        "id": wid,
        "company_id": company_id,
        "url": url,
        "title": title or "",
        "date": date,
        "source": source,
        "source_url": source_url,
        "kind": kind,
        "first_seen": seen,
        "last_seen": seen,
    }
    return True


def prune_stale(webcasts, company_id, found_urls):
    """After a successful crawl, forget links to the company's own pages that the
    crawler no longer accepts (left over from older, looser rules). Links to webcast
    players are kept as history even once they drop off the IR site."""
    from .extract import is_webcast_url
    for wid, w in list(webcasts.items()):
        if (w["company_id"] == company_id and w["source"] == "ir-page" and w.get("kind") != "event"
                and w["url"] not in found_urls and not is_webcast_url(w["url"])):
            del webcasts[wid]


def load_overrides():
    """Manual corrections keyed by ticker: ir_url, website, sector."""
    if not config.OVERRIDES_FILE.exists():
        return {}
    with open(config.OVERRIDES_FILE, encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {r["ticker"].strip().upper(): {k: v.strip() for k, v in r.items() if v and v.strip()}
                for r in rows if r.get("ticker")}


def load_watchlist():
    """Tickers from data/watchlist.txt, or None to cover every company."""
    if not config.WATCHLIST_FILE.exists():
        return None
    tickers = [line.split("#")[0].strip().upper() for line in config.WATCHLIST_FILE.read_text().splitlines()]
    return [t for t in tickers if t] or None


def companies_by_ticker(companies):
    return {t: c for c in companies.values() for t in c.get("tickers", [])}
