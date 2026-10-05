"""Command line entry point: python -m irwebcasts <step> [options]

Steps, in pipeline order:
  universe   refresh the list of U.S.-listed companies (+ sector) from Nasdaq
  discover   find IR sites for companies that don't have one yet
  crawl      visit IR sites and collect webcast links
  build      regenerate the static website
  daily      universe + discover + crawl + build, time-boxed
  report     per-company results (website, IR site, webcasts)

data/watchlist.txt limits `daily` to the tickers listed in it.
"""
import argparse
import sys

from collections import Counter

from . import build, crawl, discover, store, universe


def debug(urls):
    """Print what the plain download and the headless browser each see."""
    import re
    from bs4 import BeautifulSoup
    from .crawl import Renderer
    from .extract import EVENTS_LINK_RE, extract_webcasts, find_links
    from .http import Fetcher

    def describe(label, url, html, status):
        if html is None:
            print(f"  {label}: nothing ({status})")
            return
        soup = BeautifulSoup(html, "lxml")
        text = re.sub(r"\s+", " ", soup.get_text(" "))
        hosts = Counter(re.sub(r"^https?://([^/]+).*", r"\1", a["href"]) for a in soup.find_all("a", href=True)
                        if a["href"].startswith("http"))
        print(f"  {label}: {status}, {len(html)} bytes, title={soup.title.get_text(strip=True) if soup.title else None!r}")
        print(f"    links: {len(soup.find_all('a'))}, iframes: {[f.get('src') for f in soup.find_all('iframe')][:5]}")
        print(f"    top link hosts: {hosts.most_common(8)}")
        print(f"    events-like links: {find_links(html, url, EVENTS_LINK_RE)[:8]}")
        for w in extract_webcasts(html, url)[:10]:
            print(f"    webcast: {w['date']} {w['title']!r} {w['url']}")
        print(f"    text: {text[:1200]!r}")

    fetcher = Fetcher(respect_robots=False)
    renderer = Renderer()
    try:
        for url in urls:
            print(f"== {url}")
            resp = fetcher.get(url, retries=0)
            describe("plain", url, resp.text if resp is not None else None,
                     f"HTTP {resp.status_code}" if resp is not None else "failed/blocked")
            page = renderer._browser.new_page()
            try:
                r = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                describe("browser", url, page.content(), f"HTTP {r.status if r else '?'}")
            except Exception as exc:
                print(f"  browser: error {exc!r}")
            finally:
                page.close()
    finally:
        renderer.close()


def report(tickers=None):
    """Per-company results, for checking a run from its log."""
    companies = store.load_companies()
    webcasts = list(store.load_webcasts().values())
    wanted = {t.upper() for t in tickers} if tickers else None
    rows = [c for c in companies.values() if c.get("listed", True)
            and (wanted is None or wanted & set(c.get("tickers", [])))]
    per_company = Counter(w["company_id"] for w in webcasts)
    print(f"report: {len(rows)} companies, {sum(1 for c in rows if c.get('website'))} with website, "
          f"{sum(1 for c in rows if c.get('ir_url'))} with IR site, "
          f"{sum(per_company[c['id']] for c in rows)} webcasts")
    if len(rows) > 50:
        return
    for c in sorted(rows, key=lambda c: c["tickers"][0]):
        print(f"  {c['tickers'][0]:6} {c.get('sector', '?'):24} website={c.get('website')} "
              f"ir={c.get('ir_url')} ({c.get('ir_source')}) crawl={c.get('crawl_status')} "
              f"webcasts={per_company[c['id']]}")
        for w in sorted((w for w in webcasts if w["company_id"] == c["id"]),
                        key=lambda w: w.get("date") or "", reverse=True)[:8]:
            print(f"      {w.get('date') or '----------'}  {w.get('title')!r:60.60}  {w['url']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="irwebcasts", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="step", required=True)

    u = sub.add_parser("universe")
    u.add_argument("--limit", type=int, help="only the N largest companies")
    u.add_argument("--tickers", nargs="*")

    d = sub.add_parser("discover")
    d.add_argument("--limit", type=int)
    d.add_argument("--retry-failed", action="store_true")
    d.add_argument("--minutes", type=float)
    d.add_argument("--tickers", nargs="*")

    c = sub.add_parser("crawl")
    c.add_argument("--limit", type=int)
    c.add_argument("--minutes", type=float)
    c.add_argument("--render", action="store_true", help="use Playwright for JS-heavy IR sites")
    c.add_argument("--tickers", nargs="*")

    sub.add_parser("build")
    sub.add_parser("report")
    dbg = sub.add_parser("debug", help="show what the crawler sees on given pages")
    dbg.add_argument("urls", nargs="+")

    dl = sub.add_parser("daily")
    dl.add_argument("--crawl-minutes", type=float, default=150)
    dl.add_argument("--discover-minutes", type=float, default=150)
    dl.add_argument("--no-render", action="store_true", help="skip the headless browser")

    args = p.parse_args(argv)
    if args.step == "universe":
        n = universe.refresh(args.limit, args.tickers)
        print(f"universe: {n} listed companies")
    elif args.step == "discover":
        n, found = discover.run(args.limit, args.retry_failed, args.minutes, args.tickers)
        print(f"discover: {found}/{n} IR sites found")
    elif args.step == "crawl":
        n, new = crawl.run(args.limit, args.minutes, args.render, args.tickers)
        print(f"crawl: {n} companies crawled, {new} new webcasts")
    elif args.step == "build":
        print("build:", build.build())
    elif args.step == "debug":
        debug(args.urls)
    elif args.step == "report":
        report(store.load_watchlist())
    elif args.step == "daily":
        tickers = store.load_watchlist()
        if tickers:
            print(f"watchlist: limiting this run to {len(tickers)} tickers")
        print("universe:", universe.refresh(tickers=tickers))
        print("discover:", discover.run(max_minutes=args.discover_minutes, tickers=tickers))
        print("crawl:", crawl.run(max_minutes=args.crawl_minutes, render=not args.no_render, tickers=tickers))
        print("build:", build.build())
        report(tickers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
