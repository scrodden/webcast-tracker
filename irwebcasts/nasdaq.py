"""Company universe, sectors and websites from Nasdaq's free public data.

* Symbol directory (nasdaqtrader.com): the official daily list of every security
  on Nasdaq, NYSE, NYSE American and Cboe, published for download.
* Stock screener (api.nasdaq.com, or a public daily copy of it): sector, industry
  and market cap for each stock.
"""
import csv
import io
import re

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
# api.nasdaq.com often refuses cloud servers, so read a public daily copy of the
# same screener data first (github.com/rreichel3/US-Stock-Symbols).
SCREENER_MIRRORS = [
    f"https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/{x}/{x}_full_tickers.json"
    for x in ("nasdaq", "nyse", "amex")
]

# api.nasdaq.com only answers requests that look like they come from nasdaq.com.
API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

OTHER_EXCHANGES = {"N": "NYSE", "A": "NYSE American", "Z": "Cboe"}  # P (Arca) and V (IEX) are ETF-heavy

# Nasdaq's sector names → the GICS-style names the site uses.
SECTOR_MAP = {
    "technology": "Information Technology",
    "finance": "Financials",
    "health care": "Health Care",
    "consumer discretionary": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "industrials": "Industrials",
    "energy": "Energy",
    "utilities": "Utilities",
    "real estate": "Real Estate",
    "basic materials": "Materials",
    "telecommunications": "Communication Services",
}

# Securities that aren't a company's main equity line.
_NOT_EQUITY = re.compile(
    r"\b(warrants?|rights?|(?<!common )units?|preferred|preference|notes?|debentures?|bonds?|"
    r"depositary shares,? each|fixed[- ]to[- ]floating|perpetual|subordinated|% )", re.I)
# Words describing the share class, stripped to get the company name.
_SECURITY_WORDS = re.compile(
    r"\s*[-–,]?\s*\b(class [a-z]\b.*|series [a-z]\b.*|common stock.*|common shares.*|ordinary shares.*|"
    r"american depositary (shares|receipts).*|ads\b.*|capital stock.*|shares of beneficial interest.*|"
    r"common units.*|subordinate voting shares.*)$", re.I)


def map_sector(name):
    return SECTOR_MAP.get((name or "").strip().lower(), "Other")


def company_name(security_name):
    """'Alphabet Inc. - Class A Common Stock' → 'Alphabet Inc.'"""
    name = security_name.split(" - ")[0]
    name = _SECURITY_WORDS.sub("", name).strip(" ,-")
    return name or security_name


def parse_symbol_files(nasdaq_txt, other_txt):
    """Return [{ticker, name, security, exchange}] for operating-company equities."""
    rows = []
    for row in csv.DictReader(io.StringIO(nasdaq_txt), delimiter="|"):
        if not row.get("Symbol") or row["Symbol"].startswith("File Creation"):
            continue
        if row.get("ETF") == "Y" or row.get("Test Issue") == "Y":
            continue
        rows.append({"ticker": row["Symbol"], "security": row["Security Name"], "exchange": "Nasdaq"})
    for row in csv.DictReader(io.StringIO(other_txt), delimiter="|"):
        symbol = row.get("ACT Symbol") or ""
        if not symbol or symbol.startswith("File Creation") or "$" in symbol:
            continue
        if row.get("ETF") == "Y" or row.get("Test Issue") == "Y":
            continue
        exchange = OTHER_EXCHANGES.get(row.get("Exchange"))
        if exchange:
            rows.append({"ticker": symbol, "security": row["Security Name"], "exchange": exchange})
    out = []
    for r in rows:
        if _NOT_EQUITY.search(r["security"]):
            continue
        r["name"] = company_name(r["security"])
        out.append(r)
    return out


def parse_screener(payload):
    """{ticker: {sector, industry, market_cap, country}} from the screener JSON."""
    rows = (((payload or {}).get("data") or {}).get("rows")) or []
    out = {}
    for r in rows:
        symbol = (r.get("symbol") or "").strip().replace("/", ".").replace("^", "$")
        if not symbol:
            continue
        try:
            cap = float(str(r.get("marketCap") or "0").replace(",", "") or 0)
        except ValueError:
            cap = 0.0
        out[symbol] = {"sector": map_sector(r.get("sector")), "industry": r.get("industry") or None,
                       "market_cap": cap, "country": r.get("country") or None}
    return out


def fetch_screener(fetcher):
    rows = []
    for url in SCREENER_MIRRORS:
        data = fetcher.get_json(url, retries=1)
        if isinstance(data, list):
            rows += data
    if rows:
        return parse_screener({"data": {"rows": rows}})
    return parse_screener(fetcher.get_json(SCREENER_URL, headers=API_HEADERS, retries=0, timeout=20))
