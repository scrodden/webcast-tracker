"""Command line entry point: python -m irwebcasts <step> [options]

Steps, in pipeline order:
  universe   refresh the list of U.S.-listed companies (+ sector) from Nasdaq
  discover   find IR sites for companies that don't have one yet
  crawl      visit IR sites and collect webcast links
  build      regenerate the static website
  daily      universe + discover + crawl + build, time-boxed
"""
import argparse
import sys

from . import build, crawl, discover, universe


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

    c = sub.add_parser("crawl")
    c.add_argument("--limit", type=int)
    c.add_argument("--minutes", type=float)
    c.add_argument("--render", action="store_true", help="use Playwright for JS-heavy IR sites")
    c.add_argument("--tickers", nargs="*")

    sub.add_parser("build")

    dl = sub.add_parser("daily")
    dl.add_argument("--crawl-minutes", type=float, default=150)
    dl.add_argument("--discover-minutes", type=float, default=150)
    dl.add_argument("--no-render", action="store_true", help="skip the headless browser")

    args = p.parse_args(argv)
    if args.step == "universe":
        n = universe.refresh(args.limit, args.tickers)
        print(f"universe: {n} listed companies")
    elif args.step == "discover":
        n, found = discover.run(args.limit, args.retry_failed, args.minutes)
        print(f"discover: {found}/{n} IR sites found")
    elif args.step == "crawl":
        n, new = crawl.run(args.limit, args.minutes, args.render, args.tickers)
        print(f"crawl: {n} companies crawled, {new} new webcasts")
    elif args.step == "build":
        print("build:", build.build())
    elif args.step == "daily":
        print("universe:", universe.refresh())
        print("discover:", discover.run(max_minutes=args.discover_minutes))
        print("crawl:", crawl.run(max_minutes=args.crawl_minutes, render=not args.no_render))
        print("build:", build.build())
    return 0


if __name__ == "__main__":
    sys.exit(main())
