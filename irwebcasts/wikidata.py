"""Company websites from Wikidata (the free database behind Wikipedia).

One query returns the official website of every company Wikidata lists with a
ticker on a U.S. exchange, so we don't need a per-company lookup.
"""
import re

SPARQL_URL = "https://query.wikidata.org/sparql"

QUERY = """
SELECT ?ticker ?exchangeLabel ?website WHERE {
  ?company p:P414 ?listing .
  ?listing ps:P414 ?exchange ; pq:P249 ?ticker .
  ?company wdt:P856 ?website .
  ?exchange rdfs:label ?exchangeLabel .
  FILTER(LANG(?exchangeLabel) = "en")
  # U.S. venues only: Nasdaq Stockholm, Helsinki, etc. share the "Nasdaq" name.
  FILTER(REGEX(?exchangeLabel, "^(nasdaq|nasdaq stock market|new york stock exchange|nyse.*|cboe.*)$", "i"))
}
"""


def normalize_ticker(ticker):
    return re.sub(r"[^A-Z0-9]", "", (ticker or "").upper())


def parse(payload):
    """{normalized ticker: website} from a SPARQL JSON result."""
    out = {}
    for row in ((payload or {}).get("results") or {}).get("bindings", []):
        ticker = normalize_ticker(row.get("ticker", {}).get("value"))
        website = row.get("website", {}).get("value", "")
        if ticker and website.startswith("http") and ticker not in out:
            out[ticker] = website
    return out


def fetch_websites(fetcher):
    payload = fetcher.get_json(SPARQL_URL, params={"query": QUERY, "format": "json"},
                               headers={"Accept": "application/sparql-results+json"}, timeout=90)
    return parse(payload)
