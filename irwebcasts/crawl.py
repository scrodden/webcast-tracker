"""Visit each company's IR site and record the webcasts it links to.

From the IR home page we follow links that look like events / presentations
listings (same site only), then event-detail pages, collecting webcast links on
every page. Companies are processed oldest-crawl-first so a time-boxed
scheduled run gradually covers the whole universe.
"""
import os
import re
import threading
import time
from urllib.parse import urlsplit

from . import config, store
from .extract import EVENT_DETAIL_RE, EVENTS_LINK_RE, extract_webcasts, find_links, page_heading
from .http import Fetcher

MAX_LISTING_PAGES = 6
MAX_DETAIL_PAGES = 25


def _site(url):
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:])


class Renderer:
    """Optional headless-browser fetch for IR pages built with JavaScript."""

    def __init__(self):
        from playwright.sync_api import sync_playwright  # optional dependency
        self._pw = sync_playwright().start()
        # IRW_CHROMIUM points at an already-installed Chromium if Playwright's own isn't there.
        # IRW_BROWSER_PROXY: route the browser through a proxy (e.g. a sandbox egress proxy
        # that re-signs TLS, in which case certificate errors are expected and ignored).
        proxy = os.environ.get("IRW_BROWSER_PROXY")
        self._browser = self._pw.chromium.launch(
            executable_path=os.environ.get("IRW_CHROMIUM") or None,
            proxy={"server": proxy} if proxy else None,
            args=["--ignore-certificate-errors"] if proxy else [])

    def html(self, url):
        page = self._browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass  # pages with background polling never go idle; use what has loaded
            page.wait_for_timeout(1500)
            return page.content()
        except Exception:
            return None
        finally:
            page.close()

    def close(self):
        self._browser.close()
        self._pw.stop()


_RANK = [(re.compile(r"event", re.I), -3), (re.compile(r"webcast", re.I), -3),
         (re.compile(r"presentation", re.I), -2), (re.compile(r"calendar|conference", re.I), -2),
         (re.compile(r"news|press|release|blog|stories", re.I), 2)]


def events_rank(url):
    """Lower = more likely to be the events/webcasts page (sort key, stable)."""
    path = urlsplit(url).path
    segments = [x for x in path.split("/") if x and not re.match(r"(default|index)\.\w+$", x)]
    last = segments[-1] if segments else ""

    def score(text):
        return sum(weight for pattern, weight in _RANK if pattern.search(text))
    # The last path segment says most about the page ("news-events/press-releases").
    return 2 * score(last) + score(path)


def crawl_company(company, fetcher, renderer=None):
    """Return [(webcast, source_page)] found on the company's IR site."""
    root = company["ir_url"]
    site = _site(root)
    pages, results = {}, []

    def fetch(url, render=False):
        if url in pages:
            return pages[url]
        resp = fetcher.get(url, retries=1)
        html = resp.text if resp is not None else None
        # Many IR sites (e.g. Q4's) fill in their event lists with JavaScript, often
        # after showing one or two upcoming events in the page itself, so events
        # pages are always also loaded in the browser and the fuller version kept.
        if render and renderer is not None:
            rendered = renderer.html(url)
            if rendered and (html is None or len(extract_webcasts(rendered, url)) > len(extract_webcasts(html, url))):
                html = rendered
        pages[url] = html
        return html

    home = fetch(root, render=True)
    if home is None:
        return None
    # Events pages entered by hand (data/overrides.csv) come first.
    found = sorted((u for u in find_links(home, root, EVENTS_LINK_RE) if _site(u) == site),
                   key=events_rank)
    listing = list(dict.fromkeys([root] + company.get("events_urls", []) + found))
    detail = []
    for url in listing[:MAX_LISTING_PAGES]:
        html = fetch(url, render=True)
        if not html:
            continue
        results += [(w, url) for w in extract_webcasts(html, url)]
        detail += [u for u in find_links(html, url, EVENT_DETAIL_RE)
                   if _site(u) in (site, _site(url)) and u not in detail and u not in listing]

    for url in detail[:MAX_DETAIL_PAGES]:
        html = fetch(url)
        if not html:
            continue
        heading, when = page_heading(html)
        for w in extract_webcasts(html, url):
            # On a detail page the page heading names the event better than link text.
            if heading:
                w["title"] = heading
            w["date"] = w["date"] or when
            results.append((w, url))
    return results


def run(limit=None, max_minutes=None, render=False, tickers=None, fetcher=None):
    companies = store.load_companies()
    webcasts = store.load_webcasts()
    wanted = {t.upper() for t in tickers} if tickers else None
    todo = [c for c in companies.values() if c.get("ir_url") and c.get("listed", True)
            and (wanted is None or wanted & set(c.get("tickers", [])))]
    todo.sort(key=lambda c: (c.get("last_crawled") or "", -(c.get("market_cap") or 0)))
    if limit:
        todo = todo[:limit]
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    queue = list(reversed(todo))
    lock = threading.Lock()
    counts = {"crawled": 0, "new": 0}

    def worker():
        # Each worker has its own HTTP session and browser.
        own_fetcher = fetcher or Fetcher()
        renderer = None
        if render:
            try:
                renderer = Renderer()
            except Exception as exc:
                print(f"crawl: headless browser unavailable ({exc!r}); continuing without it")
        try:
            while True:
                with lock:
                    if not queue or (deadline and time.monotonic() > deadline):
                        return
                    company = queue.pop()
                try:
                    found = crawl_company(company, own_fetcher, renderer)
                except Exception as exc:  # one odd site must not stop the run
                    print(f"crawl {company['tickers'][0]}: {exc!r}")
                    found = None
                with lock:
                    company["last_crawled"] = store.now_iso()
                    company["crawl_status"] = "unreachable" if found is None else f"ok:{len(found)}"
                    for w, page in found or []:
                        counts["new"] += store.upsert_webcast(webcasts, company["id"], w["url"], w["title"],
                                                              w["date"], "ir-page", page)
                    counts["crawled"] += 1
                    if counts["crawled"] % 50 == 0:
                        store.save_companies(companies)
                        store.save_webcasts(webcasts)
        finally:
            if renderer:
                renderer.close()

    threads = [threading.Thread(target=worker) for _ in range(config.WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    store.save_companies(companies)
    store.save_webcasts(webcasts)
    return counts["crawled"], counts["new"]
