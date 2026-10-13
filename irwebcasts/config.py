"""Paths and tunables shared by every pipeline step."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
# The built site goes to docs/, which GitHub Pages publishes.
SITE_DIR = Path(os.environ.get("IRW_SITE_DIR", ROOT / "docs"))

COMPANIES_FILE = DATA_DIR / "companies.json"
WEBCASTS_FILE = DATA_DIR / "webcasts.json"
OVERRIDES_FILE = DATA_DIR / "overrides.csv"
CONFERENCE_ALIASES_FILE = DATA_DIR / "conference_aliases.json"
# Tickers to limit every run to (one per line). Empty = the whole U.S. market.
WATCHLIST_FILE = DATA_DIR / "watchlist.txt"

# A stable name sites can recognise; the link explains what the bot does.
BOT_INFO_URL = os.environ.get("IRW_KEY_DIRECTORY", "https://github.com/scrodden/webcast-tracker").rstrip("/") + "/"
USER_AGENT = os.environ.get(
    "IRW_USER_AGENT",
    f"Mozilla/5.0 (compatible; WebcastTrackerBot/1.0; +{BOT_INFO_URL})",
)

# Data APIs (not web pages), so robots.txt doesn't apply to them.
API_HOSTS = ("api.nasdaq.com", "www.nasdaqtrader.com", "api.search.brave.com",
             "query.wikidata.org", "raw.githubusercontent.com")

# Seconds between requests to the same host.
SITE_DELAY = 1.0
TIMEOUT = 15
# Parallel workers for discover/crawl; each works on a different company site.
WORKERS = 8
