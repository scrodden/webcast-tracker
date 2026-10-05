"""Find each company's investor-relations site.

Order of evidence:
  1. data/overrides.csv (manual)
  2. Common IR locations on the company's website (investors.<d>, <d>/investors, ...),
     with the website from Wikidata or, failing that, guessed from the name
  3. An "Investors" link on the company homepage
  4. A web search for "<company> investor relations" (DuckDuckGo, or Brave Search
     when BRAVE_API_KEY is set)
A candidate is accepted only if the page actually reads like an IR site.
"""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from . import config, store
from .http import Fetcher

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
DDG_URL = "https://html.duckduckgo.com/html/"
SEARCH_DELAY = 4.0  # seconds between searches, shared by all workers
_search_lock = threading.Lock()
_last_search = [0.0]

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


def registrable(host):
    """'corporate.visa.com' → 'visa.com'; 'www.bbc.co.uk' → 'bbc.co.uk'."""
    parts = host.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "net", "org") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _matches_company(host, company):
    tokens = _name_tokens(company.get("name"))
    tickers = [t.lower() for t in company.get("tickers", [])]
    label = registrable(host).split(".")[0]
    return any(t in label for t in tokens) or label in tickers


def pick_domain(company):
    """The company's own domain, from its website (override or Wikidata).

    A Wikidata website that doesn't resemble the company's name or ticker is
    ignored (e.g. a foreign subsidiary's site), unless it's a manual override.
    """
    if not company.get("website"):
        return None
    host = re.sub(r"^https?://", "", company["website"].strip()).split("/")[0]
    if not host:
        return None
    if company.get("website_source") != "override" and not _matches_company(host, company):
        return None
    return registrable(host)


def guess_domains(company):
    """Likely domains from the name: 'Agilent Technologies' → agilent.com, agilenttechnologies.com."""
    tokens = _name_tokens(company.get("name"))
    out = [f"{t.lower()}.com" for t in company.get("tickers", [])[:1] if len(t) >= 3 and t.isalpha()]
    if tokens and len(tokens[0]) >= 4:
        out.append(f"{tokens[0]}.com")
    if len(tokens) > 1:
        out.append(f"{''.join(tokens[:2])}.com")
    return list(dict.fromkeys(out))


def looks_like_ir(html):
    text = BeautifulSoup(html, "lxml").get_text(" ").lower()
    return sum(1 for w in _IR_WORDS if w in text) >= 4 and "investor" in text


def candidates(domain):
    """Usual IR addresses on a company domain."""
    return [p.format(d=domain) for p in (
        "https://investors.{d}", "https://investor.{d}", "https://ir.{d}",
        "https://stock.{d}", "https://www.{d}/investors", "https://www.{d}/investor-relations",
        "https://{d}/investors", "https://corporate.{d}/investors")]


def _search_results(query, fetcher, api_key):
    with _search_lock:
        wait = _last_search[0] + SEARCH_DELAY - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_search[0] = time.monotonic()
        if api_key:
            data = fetcher.get_json(BRAVE_URL, params={"q": query, "count": 10}, retries=1,
                                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"})
            return [r.get("url", "") for r in ((data or {}).get("web") or {}).get("results", [])]
        resp = fetcher.get(DDG_URL, params={"q": query}, retries=1)
    results = parse_ddg(resp.text) if resp is not None else []
    if not results:
        status = "no response" if resp is None else f"HTTP {resp.status_code}, {len(resp.text)} bytes"
        print(f"search: no results for {query!r} ({status})")
    return results


def parse_ddg(html):
    """Result URLs from DuckDuckGo's HTML results page."""
    urls = []
    for a in BeautifulSoup(html, "lxml").select("a.result__a"):
        href = a.get("href", "")
        if "uddg=" in href:
            href = parse_qs(urlsplit(href).query).get("uddg", [""])[0]
        if href.startswith("http"):
            urls.append(href)
    return urls


def search(company, fetcher, api_key=None):
    """IR site candidates from a web search for '<name> investor relations'."""
    results = _search_results(f"{company['name']} investor relations", fetcher, api_key)
    tokens = _name_tokens(company.get("name"))
    tickers = [t.lower() for t in company.get("tickers", [])]

    def matches_company(url):
        host = urlsplit(url).netloc.lower()
        return sum(2 for t in tokens if t in host) + sum(2 for t in tickers if t in host.split("."))

    def score(url):
        return matches_company(url) + (3 if _IR_URL.search(urlsplit(url).netloc + urlsplit(url).path) else 0)

    # Only the company's own site: its name or ticker must appear in the host.
    urls = [u for u in results if u.startswith("http") and matches_company(u)
            and not any(urlsplit(u).netloc.lower().endswith(h) for h in _NOT_IR_HOSTS)]
    return sorted(urls, key=score, reverse=True)[:4]


def _try_domain(domain, fetcher):
    for url in candidates(domain):
        resp = fetcher.get(url, retries=0)
        if resp is not None and looks_like_ir(resp.text):
            return resp.url, "probe"
    resp = fetcher.get(f"https://www.{domain}", retries=0)
    if resp is not None:
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            if _INVESTOR_LINK.search(a.get_text(" ")):
                page = fetcher.get(urljoin(resp.url, a["href"]), retries=0)
                if page is not None and looks_like_ir(page.text):
                    return page.url, "homepage-link"
    return None, None


def discover_one(company, fetcher, search_key=None):
    domain = pick_domain(company)
    if domain:
        url, how = _try_domain(domain, fetcher)
        if url:
            return url, how
    for url in search(company, fetcher, search_key):
        resp = fetcher.get(url, retries=0)
        if resp is not None and looks_like_ir(resp.text):
            return resp.url, "search"
    for guess in guess_domains(company):
        if guess != domain:
            url, how = _try_domain(guess, fetcher)
            if url:
                return url, "name-guess"
    return None, None


def run(limit=None, retry_failed=False, max_minutes=None, tickers=None, fetcher=None):
    search_key = os.environ.get("BRAVE_API_KEY") or None
    companies = store.load_companies()
    wanted = {t.upper() for t in tickers} if tickers else None
    todo = [c for c in companies.values()
            if c.get("listed", True) and not c.get("ir_url")
            and (wanted is None or wanted & set(c.get("tickers", [])))
            and (retry_failed or wanted or not c.get("ir_checked"))]
    todo.sort(key=lambda c: -(c.get("market_cap") or 0))  # biggest companies first
    if limit:
        todo = todo[:limit]
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    local = threading.local()
    counts = {"checked": 0, "found": 0}
    lock = threading.Lock()

    def work(company):
        if deadline and time.monotonic() > deadline:
            return
        if not hasattr(local, "fetcher"):
            local.fetcher = fetcher or Fetcher()
        try:
            url, how = discover_one(company, local.fetcher, search_key)
        except Exception as exc:  # one odd site must not stop the run
            print(f"discover {company['tickers'][0]}: {exc!r}")
            url, how = None, None
        with lock:
            company["ir_checked"] = store.now_iso()
            counts["checked"] += 1
            if url:
                company["ir_url"], company["ir_source"] = url, how
                counts["found"] += 1
            if counts["checked"] % 50 == 0:
                store.save_companies(companies)

    with ThreadPoolExecutor(config.WORKERS) as pool:
        list(pool.map(work, todo))
    store.save_companies(companies)
    return counts["checked"], counts["found"]
