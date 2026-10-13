"""Turn the collected data into the static website.

The site is a handful of HTML pages plus compact JSON files they read, so the
output stays small no matter how many companies we track (no per-company HTML).
"""
import json
import re
import shutil
from datetime import datetime, timezone

from . import config, conferences, sectors, store


_QUARTERS = {"first": "1", "second": "2", "third": "3", "fourth": "4", "1st": "1", "2nd": "2", "3rd": "3", "4th": "4"}


def _event_key(w):
    """Same company + same event. Earnings calls written differently ('First Quarter
    2026 Earnings Call', '2026 Q1 Earnings Call', 'Q1 2026 Earnings Call') share a key."""
    title = (w.get("title") or "").lower()
    if "earnings" in title or "results" in title:
        fy = "fy" if re.search(r"\bfy|fiscal", title) else ""
        q = re.search(r"\bq([1-4])\b", title) or re.search(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter", title)
        y = re.search(r"\b(20\d\d)\b", title)
        if q and y:
            quarter = _QUARTERS.get(q.group(1), q.group(1))
            return (w["company_id"], f"earnings-{fy}{y.group(1)}-q{quarter}")
    return (w["company_id"], re.sub(r"[^a-z0-9]", "", title))


def dedupe(webcasts):
    """One entry per company and event: when several links name the same event
    (e.g. an events page and a press-release page for one earnings call), keep the
    direct webcast player first, then a dated entry, then the earliest found."""
    from .extract import is_webcast_url
    best = {}
    for w in webcasts:
        key = _event_key(w)
        if not key[1]:
            best[w["id"]] = w
            continue
        rank = (not is_webcast_url(w["url"]), w.get("date") is None, w.get("first_seen") or "")
        if key not in best or rank < best[key][0]:
            best[key] = (rank, w)
    return [v[1] if isinstance(v, tuple) else v for v in best.values()]


MAX_AGE_DAYS = 2 * 365


def clean(webcasts, companies):
    """Apply today's rules to everything collected so far: fix or drop titles that
    are page furniture, drop press-release pages and opaque links, and old events."""
    from datetime import date, timedelta
    from urllib.parse import urlsplit
    from .extract import EXCLUDED_HOSTS, _usable, is_webcast_url, slug_title, title_from_url
    cutoff = (date.today() - timedelta(days=MAX_AGE_DAYS)).isoformat()
    out = []
    for w in webcasts:
        host = urlsplit(w["url"]).netloc.lower()
        if any(host == h or host.endswith("." + h) for h in EXCLUDED_HOSTS):
            continue
        if w.get("date") and w["date"] < cutoff:
            continue
        if (not is_webcast_url(w["url"]) and w.get("kind") != "event"
                and re.search(r"/news|press-release(?!-webcast)|news-release|/press/|financial-release|-announces-", urlsplit(w["url"]).path, re.I)):
            continue
        title = w.get("title") or ""
        if not title or not _usable(title):
            title = slug_title(w["url"]) or title_from_url(w["url"]) or ""
        if not title:
            # A player link with no usable name on its page: say what it is at least.
            if not is_webcast_url(w["url"]):
                continue
            title = "Webcast"
        out.append({**w, "title": title})
    return out


def build(out_dir=None):
    out = out_dir or config.SITE_DIR
    companies = store.load_companies()
    webcasts = list(store.load_webcasts().values())
    webcasts = dedupe(clean([w for w in webcasts if w["company_id"] in companies], companies))
    confs = conferences.build(webcasts, companies)

    counts = {}
    for w in webcasts:
        counts[w["company_id"]] = counts.get(w["company_id"], 0) + 1

    company_rows = []
    for c in companies.values():
        if not c.get("listed", True) and not counts.get(c["id"]):
            continue
        company_rows.append({
            "id": c["id"], "n": c.get("name") or c["id"], "t": c.get("tickers", []),
            "x": c.get("exchange"), "co": c.get("country", "US"), "s": c.get("sector", sectors.OTHER),
            "i": c.get("industry"), "ir": c.get("ir_url"), "w": counts.get(c["id"], 0),
            "irb": bool(c.get("ir_blocked")), "ix": c.get("indexes", []),
        })
    company_rows.sort(key=lambda r: r["n"].lower())

    webcast_rows = [{
        "id": w["id"], "c": w["company_id"], "ti": w.get("title") or "Webcast", "u": w["url"],
        "d": w.get("date"), "ty": w.get("event_type", "Other"), "cf": w.get("conference_id"),
        "src": w.get("source_url"), "fs": w.get("first_seen", "")[:10],
        "k": w.get("kind", "webcast"),
    } for w in webcasts]
    # Newest first; undated links go last rather than masquerading as recent.
    webcast_rows.sort(key=lambda r: (r["d"] is not None, r["d"] or "", r["fs"]), reverse=True)

    conf_rows = sorted(confs, key=lambda c: (c.get("start") or c.get("year") or ""), reverse=True)

    meta = {
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sectors": sectors.SECTORS + [sectors.OTHER],
        "companies": len(company_rows),
        "companies_with_ir": sum(1 for r in company_rows if r["ir"]),
        "webcasts": len(webcast_rows),
        "conferences": len(conf_rows),
    }

    out.mkdir(parents=True, exist_ok=True)
    for f in config.WEB_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    data_dir = out / "data"
    data_dir.mkdir(exist_ok=True)
    for name, payload in (("companies", company_rows), ("webcasts", webcast_rows),
                          ("conferences", conf_rows), ("meta", meta)):
        with open(data_dir / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    return meta
