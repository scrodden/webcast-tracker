"""Build the company universe from Nasdaq's public symbol directory.

Share classes of one company (GOOGL/GOOG, BRK.A/BRK.B) are grouped by company
name. Sector, industry and market cap come from Nasdaq's stock screener; if
that call fails the universe still updates and sectors fill in next time.
"""
import re

from . import nasdaq, store
from .http import Fetcher


def company_id(ticker):
    return "us-" + re.sub(r"[^a-z0-9]+", "-", ticker.lower()).strip("-")


def _group_key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def refresh(limit=None, tickers=None, fetcher=None):
    fetcher = fetcher or Fetcher()
    listed = fetcher.get(nasdaq.NASDAQ_LISTED_URL)
    other = fetcher.get(nasdaq.OTHER_LISTED_URL)
    if listed is None or other is None:
        raise SystemExit("Could not download Nasdaq's symbol directory")
    securities = nasdaq.parse_symbol_files(listed.text, other.text)
    screener = nasdaq.parse_screener(fetcher.get_json(nasdaq.SCREENER_URL, headers=nasdaq.API_HEADERS))
    if not screener:
        print("warning: Nasdaq screener unavailable; sectors not updated this run")

    groups = {}
    for sec in securities:
        groups.setdefault((_group_key(sec["name"]), sec["exchange"]), []).append(sec)

    wanted = {t.upper() for t in tickers} if tickers else None
    companies = store.load_companies()
    by_ticker = store.companies_by_ticker(companies)
    overrides = store.load_overrides()
    current = []
    for members in groups.values():
        symbols = [m["ticker"] for m in members]
        if wanted and not wanted & set(symbols):
            continue
        # Primary line: the largest by market cap, else the shortest symbol.
        symbols.sort(key=lambda t: (-(screener.get(t, {}).get("market_cap") or 0), len(t), t))
        primary = symbols[0]
        existing = next((by_ticker[t] for t in symbols if t in by_ticker), None)
        company = existing or {"id": company_id(primary), "country": "US"}
        info = screener.get(primary, {})
        company.update({
            "tickers": symbols,
            "name": members[0]["name"],
            "exchange": members[0]["exchange"],
            "listed": True,
            "market_cap": info.get("market_cap") or company.get("market_cap") or 0,
        })
        if info:
            company["sector"] = info["sector"]
            company["industry"] = info["industry"]
        company.setdefault("sector", "Other")
        for t in symbols:
            if t in overrides:
                _apply_override(company, overrides[t])
        current.append(company)

    current.sort(key=lambda c: -c["market_cap"])
    if limit:
        current = current[:limit]
    keep = {c["id"] for c in current}
    if not wanted and not limit:
        for c in companies.values():
            if c["id"] not in keep:
                c["listed"] = False  # delisted: keep history, hide from the directory
    for c in current:
        companies[c["id"]] = c
    store.save_companies(companies)
    return len(current)


def _apply_override(company, override):
    if override.get("sector"):
        company["sector"] = override["sector"]
    if override.get("website"):
        company["website"] = override["website"]
    if override.get("ir_url"):
        company["ir_url"] = override["ir_url"]
        company["ir_source"] = "override"
