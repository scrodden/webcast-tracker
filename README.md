# Webcast Tracker

A website that collects links to the webcasts posted on the investor-relations (IR)
pages of every company listed on a U.S. exchange: earnings calls, broker and industry
conferences, investor days and shareholder meetings.

Site: https://scrodden.github.io/webcast-tracker/

* **Webcasts** (`index.html`): every webcast, newest first. Filter by sector, event type,
  exchange and date (upcoming, past 30/90/365 days, by year), or search by company,
  ticker or conference. Filters are saved in the URL, so a view like
  `index.html?sector=Health+Care&type=Conference` can be bookmarked and shared.
* **Conferences** (`conferences.html` → `conference.html?id=…`): presentations from the
  same conference are grouped onto one landing page with its dates, host bank and
  presenting companies. The page can be filtered by sector.
* **Companies** (`companies.html` → `company.html?id=…` or `company.html?t=TICKER`): one
  landing page per company with its IR site link, sector, industry and all of its webcasts.

## How the data is collected

| Step | What it does | Source |
|---|---|---|
| `universe` | Every stock on Nasdaq, NYSE, NYSE American and Cboe. Funds, warrants, preferreds and test issues are left out, and share classes of one company (GOOGL/GOOG) are grouped. Each company gets its sector, industry and market cap. | Nasdaq symbol directory (nasdaqtrader.com), Nasdaq stock screener |
| `discover` | Finds each company's IR site, biggest companies first. It gets the company's website from its Nasdaq profile, then checks the usual IR addresses (`investors.<site>`, `<site>/investors`, …) and the homepage's "Investors" link. If those fail and a search key is set, it searches "*company* investor relations". A page is accepted only if it reads like an IR site. | Nasdaq company profile, company websites, Brave Search (optional) |
| `crawl` | Opens the IR site, follows events/presentations links on the same site, then event-detail pages. Collects links to known webcast hosts (Q4, Notified, webcasts.com, Chorus Call, wsw.com, Kaleido, …) and links labelled webcast/listen/replay. Each link gets a title and date from its surrounding event block. | IR sites |
| `build` | Classifies event types, groups conference webcasts into conferences and writes the site to `docs/`. | — |

**Conference grouping** (`irwebcasts/conferences.py`): the conference name is pulled out of
each title and normalized. That means aligning bank aliases (J.P. Morgan / JPMorgan / JPM,
BofA / Bank of America, Cowen / TD Cowen, …), dropping ordinals and "Annual", and keying on
the year. So "J.P. Morgan 44th Annual Healthcare Conference" and "Fireside chat at the 2026
JPMorgan Healthcare Conference" land on the same page. Webcasts on conference platforms
that share an event code (e.g. `wsw.com/webcast/jpm44/...`) are merged even when a title
leaves the conference name out. If two names should be one conference, add the pair to
`data/conference_aliases.json`.

## Automatic daily updates

`.github/workflows/daily.yml` runs every day. It refreshes the company list, finds IR sites,
crawls for about 3½ hours and commits the rebuilt site. The first full pass over all
companies takes a few weeks, after which each company is re-checked in rotation.

Optional: add a [Brave Search API](https://brave.com/search/api/) key as the repository secret
`BRAVE_API_KEY` (Settings → Secrets and variables → Actions). The crawler will then search for
the IR sites it can't find on its own.

## Running it yourself

```bash
pip install -r requirements.txt
python -m irwebcasts universe --limit 200    # just the 200 largest companies
python -m irwebcasts discover --minutes 30
python -m irwebcasts crawl --minutes 60      # oldest-crawled first, so repeated runs rotate
python -m irwebcasts build                   # → docs/
python -m http.server -d docs                # preview at http://localhost:8000
python -m unittest discover -s tests
```

`crawl --tickers AAPL MSFT` crawls specific companies. `crawl --render` uses a headless browser
for IR pages built in JavaScript (needs `pip install playwright && playwright install chromium`).

## Fixing data by hand

`data/overrides.csv` holds per-ticker corrections for the IR URL, website, sector and events page(s). Use it for companies
the discovery step can't find or that Nasdaq puts in the wrong sector.

## Data files

* `data/companies.json`: `{id: {id, country, tickers[], name, exchange, sector, industry, market_cap, website, ir_url, ir_source, last_crawled, crawl_status, listed}}`
* `data/webcasts.json`: `{id: {id, company_id, url, title, date, source, source_url, first_seen, last_seen}}`

Company ids look like `us-aapl`. Every company also carries a `country`, ready for other markets.

## Adding non-U.S. exchanges later

Only the `universe` step is U.S.-specific. Add a loader per market that emits companies with
their own id prefix (e.g. `gb-…`), `country`, `exchange`, a sector and, if available, a website.
`discover`, `crawl` and `build` work unchanged. Most international webcast providers
(Investis, Royalcast, Openbriefing, EQS, LSEG) are already in the webcast-host list. Then add a
country filter to the pages.

## Known limits

* **JS-only IR sites.** Some sites render their event lists in the browser. `--render` handles
  them more slowly.
* **Crawl speed.** Requests run one at a time, with one request per second per site. Crawling
  several sites in parallel would speed up the first full pass.
* **Search engines.** Company and conference pages render in the browser from JSON. Pre-render
  them in `build` if they should be indexed by Google.
