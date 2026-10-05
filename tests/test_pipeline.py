import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from irwebcasts import conferences, discover, nasdaq, wikidata  # noqa: E402
from irwebcasts.crawl import crawl_company  # noqa: E402
from irwebcasts.dates import find_date  # noqa: E402
from irwebcasts.discover import pick_domain  # noqa: E402
from irwebcasts.extract import extract_webcasts  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class ExtractTests(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "notified_events.html").read_text()
        self.found = {w["url"]: w for w in extract_webcasts(html, "https://investors.acme.com/news-events/events")}

    def test_finds_webcasts_and_skips_noise(self):
        self.assertEqual(set(self.found), {
            "https://wsw.com/webcast/jpm44/acme/",
            "https://edge.media-server.com/mmc/p/abc123",
            "https://kvgo.com/morgan-stanley/acme-sept-2025",
            "https://www.virtualshareholdermeeting.com/ACME2025",
        })

    def test_titles_and_dates_come_from_the_event_block(self):
        jpm = self.found["https://wsw.com/webcast/jpm44/acme/"]
        self.assertEqual(jpm["title"], "J.P. Morgan 44th Annual Healthcare Conference")
        self.assertEqual(jpm["date"], "2026-01-13")
        q3 = self.found["https://edge.media-server.com/mmc/p/abc123"]
        self.assertEqual(q3["title"], "Q3 2025 Earnings Conference Call")
        self.assertEqual(q3["date"], "2025-11-04")
        ms = self.found["https://kvgo.com/morgan-stanley/acme-sept-2025"]
        self.assertEqual(ms["date"], "2025-09-08")
        self.assertIn("Morgan Stanley", ms["title"])


class Q4LayoutTests(unittest.TestCase):
    def test_section_labels_are_not_titles(self):
        html = (FIXTURES / "q4_events.html").read_text()
        [w] = extract_webcasts(html, "https://investor.atmeta.com/investor-events/default.aspx")
        self.assertEqual(w["title"], "Q3 2026 Earnings Call")
        self.assertEqual(w["date"], "2026-10-28")


class NoiseTests(unittest.TestCase):
    def test_navigation_and_marketing_links_are_not_webcasts(self):
        html = """<html><body>
          <a href="#mainContent">Skip to main content</a>
          <a href="/en-us/microsoft-365/outlook#modalvideo2" aria-label="Watch video">Faster emails, fewer errors</a>
          <div><h3>Earnings Release FY26 Q4</h3>
            <a href="/en-us/investor/earnings/fy-2026-q4/press-release-webcast">VIEW DETAILS ></a></div>
        </body></html>"""
        found = extract_webcasts(html, "https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast")
        self.assertEqual(found, [])  # only a link to the page itself
        found = extract_webcasts(html, "https://www.microsoft.com/en-us/investor/default")
        self.assertEqual([(w["url"], w["title"]) for w in found], [
            ("https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast",
             "FY 2026 Q4 Earnings Call")])


class YouTubeTests(unittest.TestCase):
    def test_streams_count_but_channel_links_do_not(self):
        html = """<html><body>
          <div class="event"><h3>Q3 2026 Earnings Call</h3><p>October 27, 2026</p>
            <a href="https://www.youtube.com/watch?v=abc123XYZ">Watch</a></div>
          <div class="event"><h3>Annual Meeting of Stockholders</h3><p>June 5, 2026</p>
            <iframe src="https://www.youtube.com/embed/def456"></iframe></div>
          <footer><a href="https://www.youtube.com/user/Google">YouTube</a></footer>
        </body></html>"""
        found = {w["url"]: w for w in extract_webcasts(html, "https://abc.xyz/investor/")}
        self.assertEqual(set(found), {"https://www.youtube.com/watch?v=abc123XYZ",
                                      "https://www.youtube.com/embed/def456"})
        self.assertEqual(found["https://www.youtube.com/watch?v=abc123XYZ"]["title"], "Q3 2026 Earnings Call")
        self.assertEqual(found["https://www.youtube.com/embed/def456"]["date"], "2026-06-05")


class UnwrapTests(unittest.TestCase):
    def test_urldefense(self):
        from irwebcasts.extract import unwrap
        wrapped = ("https://urldefense.com/v3/__https:/cc.webcasts.com/gold006/091426a_js/?entity=24_7NURBBQ"
                   "__;!!IfjTnhH9!WcYvsRg4a$")
        self.assertEqual(unwrap(wrapped), "https://cc.webcasts.com/gold006/091426a_js/?entity=24_7NURBBQ")


class DedupeTests(unittest.TestCase):
    def test_same_event_via_several_links_is_listed_once(self):
        from irwebcasts.build import dedupe
        rows = [
            {"id": "1", "company_id": "us-msft", "title": "FY 2026 Q4 Earnings Call", "date": None,
             "url": "https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast"},
            {"id": "2", "company_id": "us-msft", "title": "FY 2026 Q4 Earnings Call", "date": "2026-07-29",
             "url": "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q4"},
            {"id": "3", "company_id": "us-lly", "title": "FY 2026 Q4 Earnings Call", "date": None,
             "url": "https://edge.media-server.com/mmc/p/x"},
        ]
        self.assertEqual(sorted(w["id"] for w in dedupe(rows)), ["2", "3"])


class InstructionTitleTests(unittest.TestCase):
    def test_instructions_are_not_titles(self):
        html = """<div class="event"><h2>Alphabet at the Goldman Sachs Communacopia + Technology Conference</h2>
          <p>September 9, 2026</p>
          <p>To access the live audio webcast of the session, please click
             <a href="https://event.webcasts.com/viewer/event.jsp?ei=1773132">here</a>.</p></div>"""
        [w] = extract_webcasts(html, "https://abc.xyz/investor/events/event-details/2026/x/default.aspx")
        self.assertEqual(w["title"], "Alphabet at the Goldman Sachs Communacopia + Technology Conference")


class AnnouncementTests(unittest.TestCase):
    def test_press_release_names_and_dates_the_event(self):
        from irwebcasts.crawl import _with_announcement
        html = """<html><body><header><a href="/investor">Investors</a></header>
          <h1>Alphabet to Present at the Goldman Sachs 2026 Communacopia + Technology Conference</h1>
          <p>MOUNTAIN VIEW, Calif. - August 19, 2026 - Alphabet Inc. (NASDAQ: GOOG, GOOGL) today announced that
          its CFO will present at the Goldman Sachs 2026 Communacopia + Technology Conference on Tuesday,
          September 8, 2026 at 8:00 a.m. PT.</p>
          <p>To access the live audio webcast of the session, please click
             <a href="https://event.webcasts.com/viewer/event.jsp?ei=1773132">here</a>.</p>
          <h3>About Alphabet Inc.</h3><p>Alphabet is a collection of businesses.</p></body></html>"""
        url = ("https://abc.xyz/investor/news/news-details/2026/Alphabet-to-Present-at-the-Goldman-Sachs-2026-"
               "Communacopia--Technology-Conference-2026-9xibpppaLF/default.aspx")
        [w] = _with_announcement(extract_webcasts(html, url), html, url)
        self.assertEqual(w["title"], "Goldman Sachs 2026 Communacopia + Technology Conference")
        self.assertEqual(w["date"], "2026-09-08")


class SlugTitleTests(unittest.TestCase):
    def test_headline_addresses_become_event_names(self):
        from irwebcasts.extract import slug_title
        base = "https://abc.xyz/investor/news/news-details/2026/"
        self.assertEqual(slug_title(base + "Alphabet-to-Present-at-the-Goldman-Sachs-2026-Communacopia--Technology-"
                                           "Conference-2026-9xibpppaLF/default.aspx"),
                         "Goldman Sachs 2026 Communacopia + Technology Conference")
        self.assertEqual(slug_title(base + "Alphabet-Announces-Date-of-First-Quarter-2026-Financial-Results-"
                                           "Conference-Call-2026-x/default.aspx"),
                         "First Quarter 2026 Earnings Call")


class FakeResponse:
    def __init__(self, url, text):
        self.url, self.text = url, text


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, url, **kwargs):
        self.requested.append(url)
        return FakeResponse(url, self.pages[url]) if url in self.pages else None


class CrawlTests(unittest.TestCase):
    def test_follows_events_and_detail_pages_on_the_ir_site(self):
        events = (FIXTURES / "notified_events.html").read_text().replace(
            "</body>", '<a href="/news-events/event-details/goldman-2025">Goldman Sachs Communacopia</a></body>')
        fetcher = FakeFetcher({
            "https://investors.acme.com": (FIXTURES / "ir_home.html").read_text(),
            "https://investors.acme.com/news-events/events": events,
            "https://investors.acme.com/news-events/event-details/goldman-2025": (FIXTURES / "event_detail.html").read_text(),
        })
        found = {w["url"]: (w, page) for w, page in crawl_company({"ir_url": "https://investors.acme.com"}, fetcher)}
        self.assertIn("https://edge.media-server.com/mmc/p/abc123", found)
        gs, page = found["https://wsw.com/webcast/gsc25/acme/"]
        self.assertEqual(gs["title"], "Goldman Sachs Communacopia + Technology Conference")
        self.assertEqual(gs["date"], "2025-09-09")
        self.assertTrue(page.endswith("goldman-2025"))
        self.assertNotIn("https://www.otherbank.com/events", fetcher.requested)

    def test_hand_entered_events_page_on_another_subdomain(self):
        fetcher = FakeFetcher({
            "https://stock.acme.com": (FIXTURES / "ir_home.html").read_text(),
            "https://corporate.acme.com/news/events": (FIXTURES / "notified_events.html").read_text(),
        })
        company = {"ir_url": "https://stock.acme.com", "events_urls": ["https://corporate.acme.com/news/events"]}
        urls = {w["url"] for w, _ in crawl_company(company, fetcher)}
        self.assertIn("https://edge.media-server.com/mmc/p/abc123", urls)


class NasdaqTests(unittest.TestCase):
    NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
GOOGL|Alphabet Inc. - Class A Common Stock|Q|N|N|100|N|N
GOOG|Alphabet Inc. - Class C Capital Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ACMEW|Acme Corp - Warrant|S|N|N|100|N|N
ZZZT|Test Co - Common Stock|S|Y|N|100|N|N
File Creation Time: 1005202615:00|||||||
"""
    OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.A|Berkshire Hathaway Inc. Class A Common Stock|N|BRK.A|N|1|N|BRK.A
BRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK.B
JPM$C|JPMorgan Chase & Co. Depositary Shares, each representing a 1/400th interest in 6.0% Preferred|N|JPMpC|N|100|N|JPM-C
ET|Energy Transfer LP Common Units|N|ET|N|100|N|ET
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
NYT|New York Times Company (The) Common Stock|N|NYT|N|100|N|NYT
UNH|UnitedHealth Group Incorporated Common Stock|N|UNH|N|100|N|UNH
File Creation Time: 1005202615:00|||||||
"""

    def test_symbol_files(self):
        rows = {r["ticker"]: r for r in nasdaq.parse_symbol_files(self.NASDAQ, self.OTHER)}
        self.assertEqual(set(rows), {"AAPL", "GOOGL", "GOOG", "BRK.A", "BRK.B", "ET", "NYT", "UNH"})
        self.assertEqual(rows["GOOG"]["name"], "Alphabet Inc.")
        self.assertEqual(rows["BRK.B"]["name"], "Berkshire Hathaway Inc.")
        self.assertEqual(rows["ET"]["name"], "Energy Transfer LP")
        self.assertEqual(rows["NYT"]["name"], "New York Times Company (The)")
        self.assertEqual(rows["BRK.A"]["exchange"], "NYSE")

    def test_screener_and_profile(self):
        screener = nasdaq.parse_screener({"data": {"rows": [
            {"symbol": "AAPL", "name": "Apple Inc. Common Stock", "marketCap": "3,500,000,000,000",
             "country": "United States", "industry": "Computer Manufacturing", "sector": "Technology"},
            {"symbol": "BRK/B", "marketCap": "", "sector": "Finance", "industry": "Insurance"}]}})
        self.assertEqual(screener["AAPL"]["sector"], "Information Technology")
        self.assertEqual(screener["AAPL"]["market_cap"], 3.5e12)
        self.assertEqual(screener["BRK.B"]["sector"], "Financials")
        self.assertEqual(pick_domain({"name": "Apple Inc.", "tickers": ["AAPL"],
                                      "website": "https://www.apple.com"}), "apple.com")
        # A subdomain is reduced to the company's domain; an unrelated site is ignored.
        self.assertEqual(pick_domain({"name": "Visa Inc.", "tickers": ["V"],
                                      "website": "https://corporate.visa.com/"}), "visa.com")
        self.assertIsNone(pick_domain({"name": "Johnson & Johnson", "tickers": ["JNJ"],
                                       "website": "http://www.jjmt.com.tw/"}))
        self.assertEqual(discover.guess_domains({"name": "Johnson & Johnson", "tickers": ["JNJ"]})[0], "jnj.com")

    def test_wikidata_websites(self):
        payload = {"results": {"bindings": [
            {"ticker": {"value": "BRK.B"}, "website": {"value": "https://www.berkshirehathaway.com"}},
            {"ticker": {"value": "AAPL"}, "website": {"value": "https://www.apple.com/"}}]}}
        sites = wikidata.parse(payload)
        self.assertEqual(sites[wikidata.normalize_ticker("BRK-B")], "https://www.berkshirehathaway.com")
        self.assertEqual(sites["AAPL"], "https://www.apple.com/")


class SearchTests(unittest.TestCase):
    def test_ddg_results_and_company_match(self):
        html = """<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Finvestor.atmeta.com%2F&rut=x">Meta IR</a></div>
                  <div class="result"><a class="result__a" href="https://finance.yahoo.com/quote/META">Yahoo</a></div>
                  <div class="result"><a class="result__a" href="https://investor.otherco.com/">Other</a></div>"""
        self.assertEqual(discover.parse_ddg(html)[0], "https://investor.atmeta.com/")
        with mock.patch.object(discover, "_search_results", lambda q, f, k: discover.parse_ddg(html)):
            found = discover.search({"name": "Meta Platforms, Inc.", "tickers": ["META"]}, None)
        self.assertEqual(found, ["https://investor.atmeta.com/"])

    def test_guess_domains(self):
        self.assertEqual(discover.guess_domains({"name": "Agilent Technologies, Inc."}),
                         ["agilent.com", "agilenttechnologies.com"])


class ConferenceTests(unittest.TestCase):
    def test_same_conference_written_differently_groups_together(self):
        companies = {"a": {"sector": "Health Care"}, "b": {"sector": "Health Care"},
                     "c": {"sector": "Information Technology"}, "d": {"sector": "Financials"}}
        webcasts = [
            {"id": "1", "company_id": "a", "url": "https://x.com/1", "title": "J.P. Morgan 44th Annual Healthcare Conference", "date": "2026-01-13"},
            {"id": "2", "company_id": "b", "url": "https://x.com/2", "title": "Fireside Chat at the 2026 JPMorgan Healthcare Conference", "date": "2026-01-14"},
            {"id": "3", "company_id": "c", "url": "https://wsw.com/webcast/jpm44/ccc/", "title": "Fireside chat", "date": "2026-01-15"},
            {"id": "4", "company_id": "a", "url": "https://wsw.com/webcast/jpm44/aaa/", "title": "J.P. Morgan Healthcare Conference", "date": "2026-01-13"},
            {"id": "5", "company_id": "d", "url": "https://x.com/5", "title": "Q4 2025 Earnings Conference Call", "date": "2026-02-01"},
            {"id": "6", "company_id": "a", "url": "https://x.com/6", "title": "J.P. Morgan Healthcare Conference", "date": "2025-01-14"},
        ]
        confs = {c["id"]: c for c in conferences.build(webcasts, companies)}
        cid = webcasts[0]["conference_id"]
        self.assertEqual({w["id"] for w in webcasts if w.get("conference_id") == cid}, {"1", "2", "3", "4"})
        self.assertEqual(confs[cid]["company_count"], 3)
        self.assertEqual(confs[cid]["host"], "J.P. Morgan")
        self.assertEqual((confs[cid]["start"], confs[cid]["end"]), ("2026-01-13", "2026-01-15"))
        self.assertNotIn("conference_id", webcasts[4])
        self.assertEqual(webcasts[4]["event_type"], "Earnings")
        self.assertNotEqual(webcasts[5]["conference_id"], cid)  # previous year's edition

    def test_not_a_conference(self):
        for text in ("Q3 2026 Earnings Conference Call",
                     "log on at https://edge.media-server.com/mmc/p/65yp7xh9/ Conference ID 1234",
                     "dial the Conference Operator"):
            self.assertIsNone(conferences.extract_conference_name(text), text)

    def test_classify(self):
        self.assertEqual(conferences.classify("2026 Annual Meeting of Stockholders"), "Shareholder Meeting")
        self.assertEqual(conferences.classify("Investor Day 2026"), "Investor Day")
        self.assertEqual(conferences.classify("Third Quarter 2026 Results"), "Earnings")


class MiscTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(find_date("Tuesday, Sept. 9th, 2026 at 9am"), "2026-09-09")
        self.assertEqual(find_date("13 March 2026"), "2026-03-13")
        self.assertIsNone(find_date("no date here"))


if __name__ == "__main__":
    unittest.main()
