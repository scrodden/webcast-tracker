"""The eleven GICS-style sectors the site filters on.

Nasdaq's sector names are mapped onto these in nasdaq.SECTOR_MAP; fix individual
companies with the `sector` column in data/overrides.csv.
"""

SECTORS = [
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
]
OTHER = "Other"


def slug(sector):
    return sector.lower().replace(" ", "-")
