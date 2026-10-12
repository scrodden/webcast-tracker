"""Index membership lists used to choose which companies to track.

S&P 500 members come from Wikipedia's "List of S&P 500 companies" (updated when
the index changes), with a public CSV copy as a fallback. Both include each
member's official GICS sector, which is used instead of Nasdaq's own scheme.
"""
import csv
import io

from bs4 import BeautifulSoup

SP500_WIKIPEDIA = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"


def parse_wikipedia(html):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="constituents")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) >= 4 and cells[0]:
            rows.append({"ticker": cells[0].upper(), "name": cells[1], "sector": cells[2], "industry": cells[3]})
    return rows


def parse_csv(text):
    return [{"ticker": r["Symbol"].strip().upper(), "name": r["Security"], "sector": r["GICS Sector"],
             "industry": r["GICS Sub-Industry"]}
            for r in csv.DictReader(io.StringIO(text)) if r.get("Symbol")]


def sp500(fetcher):
    """[{ticker, name, sector, industry}] for current S&P 500 members."""
    resp = fetcher.get(SP500_WIKIPEDIA, retries=1)
    rows = parse_wikipedia(resp.text) if resp is not None else []
    if len(rows) < 450:  # page layout changed or unavailable
        resp = fetcher.get(SP500_CSV, retries=1)
        rows = parse_csv(resp.text) if resp is not None else rows
    return rows


INDEXES = {"@sp500": sp500}
