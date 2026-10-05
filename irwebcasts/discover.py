"""Find each company's investor-relations site.

Order of evidence:
  1. data/overrides.csv (manual)
  2. Common IR locations on the company's website (investors.<d>, <d>/investors, ...),
     with the website taken from the company's Nasdaq profile
  3. An "Investors" link on the company homepage
  4. A web search for "<company> investor relations", when BRAVE_API_KEY is set
A candidate is accepted only if the page actually reads like an IR site.
"""
import os
import re
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from . import nasdaq, store
from .http import Fetcher

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

_IR_WORDS = ("investor", "sec filings", "stock", "events", "presentations", "webcast",
             "annual report", "quarterly results", "governance", "shareholder", "dividend",
             "earnings", "financial information", "press releases")
_INVESTOR_LINK = re.compile(r"^\s*investors?(?: relations)?\s*$|investor relations", re.I)
_IR_URL = re.compile(r"(^|\.)(investors?|ir)\.|/(investors?|investor-relations|ir)(/|$)", re.I)
# Sites that are about companies but aren't the company's own IR site.
_NOT_IR_HOSTS = ("nasdaq.com", "nyse.com", "sec.gov", "yahoo.com", "bloomberg.com", "reuters.com",
                 "marketwatch.com", "wikipedia.org", "linkedin.com", "seekingalpha.com", "zacks.com",
                 "morningstar.com", "cnbc.com", "wsj.com", "fool.com", "macrotrends.net", "stockanalysis.com",
                 "globenewswire.com", "prnewswire.com", "businesswire.com", "investing.com", "google.com")
_NAME_STOP = {"inc", "corp", "corporation", "co", "company", "holdings", "group", "ltd", "plc",
              "the", "and", "of", "trust", "sa", "nv", "ag", "lp", "llc", "international", "bancorp"}


def _name_tokens(name):
    return [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in _NAME_STOP and len(t) > 1]


def pick_domain(company):
    """The company's own domain, from its website (override or Nasdaq profile)."""
    if not company.get("website"):
        return None
    return re.sub(r"^https?://(www\.)?", "", company["website"].strip()).split("/")[0].lower() or None


def looks_like_ir(html):
    text = BeautifulSoup(html, "lxml").get_text(" ").lower()
    return sum(1 for w in _IR_WORDS if w in text) >= 4 and "investor" in text


def candidates(company):
    domain = pick_domain(company)
    seen, out = set(), []

    def add(url):
        if url and url not in seen:
            seen.add(url)
            out.append(url)

    if domain:
        for pattern in ("https://investors.{d}", "https://investor.{d}", "https://ir.{d}",
                        "https://www.{d}/investors", "https://www.{d}/investor-relations",
                        "https://{d}/investors"):
            add(pattern.format(d=domain))
    return domain, out


def search(company, fetcher, api_key):
    """IR site candidates from a web search for '<name> investor relations'."""
    data = fetcher.get_json(SEARCH_URL, params={"q": f"{company['name']} investor relations", "count": 10},
                            headers={"X-Subscription-Token": api_key, "Accept": "application/json"})
    results = [r.get("url", "") for r in ((data or {}).get("web") or {}).get("results", [])]
    tokens = _name_tokens(company.get("name"))
    tickers = [t.lower() for t in company.get("tickers", [])]

    def score(url):
        host = urlsplit(url).netloc.lower()
        return (sum(2 for t in tokens if t in host) + sum(2 for t in tickers if t in host.split("."))
                + (3 if _IR_URL.search(host + urlsplit(url).path) else 0))

    urls = [u for u in results if u.startswith("http")
            and not any(urlsplit(u).netloc.lower().endswith(h) for h in _NOT_IR_HOSTS)]
    return sorted(urls, key=score, reverse=True)[:4]


def discover_one(company, fetcher, search_key=None):
    if not company.get("website") and not company.get("profile_checked"):
        profile = fetcher.get_json(nasdaq.PROFILE_URL.format(symbol=company["tickers"][0]),
                                   headers=nasdaq.API_HEADERS)
        company["profile_checked"] = store.now_iso()
        website = nasdaq.parse_profile(profile)
        if website:
            company["website"] = website
    domain, urls = candidates(company)
    for url in urls:
        resp = fetcher.get(url)
        if resp is not None and looks_like_ir(resp.text):
            return resp.url, "probe"
    if domain:
        resp = fetcher.get(f"https://www.{domain}")
        if resp is not None:
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                if _INVESTOR_LINK.search(a.get_text(" ")):
                    page = fetcher.get(urljoin(resp.url, a["href"]))
                    if page is not None and looks_like_ir(page.text):
                        return page.url, "homepage-link"
    if search_key:
        for url in search(company, fetcher, search_key):
            resp = fetcher.get(url)
            if resp is not None and looks_like_ir(resp.text):
                return resp.url, "search"
    return None, None


def run(limit=None, retry_failed=False, max_minutes=None, fetcher=None):
    fetcher = fetcher or Fetcher()
    search_key = os.environ.get("BRAVE_API_KEY") or None
    companies = store.load_companies()
    todo = [c for c in companies.values()
            if c.get("listed", True) and not c.get("ir_url")
            and (retry_failed or not c.get("ir_checked"))]
    todo.sort(key=lambda c: -(c.get("market_cap") or 0))  # biggest companies first
    if limit:
        todo = todo[:limit]
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    found = 0
    for i, company in enumerate(todo, 1):
        if deadline and time.monotonic() > deadline:
            todo = todo[:i - 1]
            break
        url, how = discover_one(company, fetcher, search_key)
        company["ir_checked"] = store.now_iso()
        if url:
            company["ir_url"], company["ir_source"] = url, how
            found += 1
        if i % 25 == 0:
            store.save_companies(companies)
    store.save_companies(companies)
    return len(todo), found
