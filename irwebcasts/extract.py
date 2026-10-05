"""Pull webcast links (with a title and date) out of an IR page's HTML.

IR sites come from a handful of vendors (Q4, Notified/GlobeNewswire, S&P,
EQS, ...) plus custom builds, so rather than per-vendor parsers this works on
two generic signals: links to known webcast hosts, and links whose text or URL
says "webcast"/"listen"/"replay". The surrounding list item / table row / card
supplies the event title and date.
"""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .dates import find_date, strip_dates

# Hosts that only serve webcasts/event players, so any link to them counts.
WEBCAST_HOSTS = (
    "edge.media-server.com", "webcasts.com", "events.q4inc.com",
    "onlinexperiences.com", "wsw.com", "kvgo.com", "viavid.com", "choruscall.com",
    "veracast.com", "on24.com", "webinar.net", "openbriefing.com", "investis-live.com",
    "world-television.com", "royalcast.com", "mediasite.com", "netroadshow.com",
    "streamstudio.com", "webcaster4.com", "brrmedia.co.uk", "media-server.com",
    "notified.com", "lsegissuerservices.com", "mzwebcast.com", "webcastlite.mziq.com",
    "conferencingportals.com", "incommconferencing.com",
    "irwebcasting.com", "webcastgroup.com", "gowebcasting.com",
    "cuepoint.com", "event.choruscall.com", "virtualshareholdermeeting.com",
    "meetnow.global", "lumiconnect.com",
)

# Hosts that are dial-in registration pages, not webcasts.
EXCLUDED_HOSTS = ("register.vevent.com", "vevent.com", "register-conf.media-server.com")

_LINK_TEXT_RE = re.compile(
    r"\b(webcast|listen|replay|archived? (?:audio|presentation|event)|live audio|"
    r"watch (?:the )?(?:live|replay|webcast|presentation|event)|audio archive|"
    r"view (?:the )?(?:webcast|replay|event|presentation recording))\b", re.I)
_URL_RE = re.compile(r"webcast|/player|replay", re.I)
_SKIP_URL_RE = re.compile(r"\.(pdf|pptx?|xlsx?|docx?|jpg|png|zip|m3u8)(\?|$)|^mailto:|^tel:|^javascript:|podcast", re.I)
# A link found only by its URL must also live in an investor-ish part of the site.
_IR_PATH_RE = re.compile(r"investor|/ir/|^ir\.|earnings|event|webcast|presentation|conference", re.I)

# Words that describe the link rather than the event.
_GENERIC = re.compile(
    r"^(webcast|live webcast|listen|listen to (?:the )?(?:webcast|replay|call)|replay|"
    r"webcast replay|watch|watch (?:the )?(?:webcast|replay|now)|view|view (?:webcast|replay|event|details)|"
    r"click here|here|audio|presentation|slides|transcript|event details|details|more|"
    r"register|add to calendar|download|pdf|play|archive|archived webcast|upcoming events?|"
    r"past events?|events?|and presentations|events & presentations|events and presentations|"
    r"read more|learn more|skip to (?:main )?content|top of page|back to top|view details\W*|"
    r"related (?:information|links)|earnings release pages?|documents?|materials?|event materials|presentation materials|resources|"
    r"downloads?|supplemental (?:information|materials)|related (?:documents|materials)|media|"
    r"audio webcast|video webcast|webcast & presentation|webcast and presentation|\W*)$",
    re.I)

_CONTAINERS = {"li", "tr", "article", "section", "div", "dd", "td", "p"}

# Links on an IR page that lead to events/presentations listings.
EVENTS_LINK_RE = re.compile(
    r"\b(events?|presentations?|webcasts?|calendar|conferences?)\b", re.I)
EVENT_DETAIL_RE = re.compile(r"event[-_]?details?|/events?/(?:detail|\d)|eventid=|/event/", re.I)


def is_youtube_video(url):
    """A YouTube video or livestream (not a channel link from a social-media footer)."""
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return len(parts.path) > 1
    if host in ("youtube.com", "youtube-nocookie.com"):
        if parts.path == "/watch":
            return "v=" in parts.query
        return parts.path.startswith(("/live/", "/embed/")) and len(parts.path) > 7
    return False


def is_webcast_url(url):
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if any(host == h or host.endswith("." + h) for h in EXCLUDED_HOSTS):
        return False
    if parts.path in ("", "/") and not parts.query:
        return False  # a provider's home page, not an event
    if "/analyst/" in parts.path or "pwd=" in parts.query:
        return False  # Q&A access for sell-side participants
    if is_youtube_video(url):
        return True
    return any(host == h or host.endswith("." + h) for h in WEBCAST_HOSTS)


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _is_generic(text):
    return bool(_GENERIC.match(_clean(text))) or len(_clean(text)) < 6


def _event_blocks(a):
    """Ancestors of a link, innermost first, that could be one event's block."""
    node = a
    for _ in range(8):
        node = node.parent
        if node is None or node.name in ("body", "html", "[document]"):
            return
        if node.name not in _CONTAINERS:
            continue
        text = _clean(node.get_text(" "))
        if len(text) < 12:
            continue
        # Stop before climbing into a list that holds several events.
        if len(text) > 1500 or _count_webcast_links(node) > 3:
            return
        yield node


def _count_webcast_links(node):
    return sum(1 for a in node.find_all("a", href=True) if _looks_like_webcast(a, a["href"]))


def _looks_like_webcast(a, href):
    if _SKIP_URL_RE.search(href):
        return False
    if is_webcast_url(href):
        return True
    parts = urlsplit(href)
    host = parts.netloc.lower()
    if any(host == h or host.endswith("." + h) for h in EXCLUDED_HOSTS):
        return False
    text = _clean(a.get_text(" ")) or a.get("title", "") or a.get("aria-label", "")
    if _LINK_TEXT_RE.search(text):
        return True
    return bool(_URL_RE.search(parts.path) and _IR_PATH_RE.search(host + parts.path))


_TITLE_CLASS = re.compile(r"title|headline|heading|name|subject", re.I)


def _usable(text):
    text = strip_dates(_clean(text))
    if re.search(r"debug info|cvtoken|javascript|cookie|opens? .{0,20}in (?:a )?new window", text, re.I):
        return None
    # Document labels and site sections ("HTML for 2025 Q2", "SEC Filings", "Overview").
    if re.fullmatch(r"(?:html|pdf|xbrl|10-[qk]|8-k|view all|see all|sec filings|investor relations|overview|"
                    r"news center|newsroom|home|press release|news release|earnings release|.*\bleadership)"
                    r"(?:\s+for\b.*|\s*\(.*\))?", text, re.I):
        return None
    if len(text) < 8 or _is_generic(text) or re.fullmatch(r"[\d\s:/.,apmAPMET-]+", text):
        return None
    return text[:200]


def _title_in(node, use_links=False):
    """Event title inside a block: headline-like elements, then plain text,
    then links that aren't webcast/registration links (event-detail links)."""
    for el in node.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"]) + \
            node.find_all(class_=_TITLE_CLASS):
        if (text := _usable(el.get_text(" "))):
            return text
    for string in node.find_all(string=True):
        if string.find_parent("a") is None and string.parent.name not in ("script", "style"):
            if (text := _usable(string)):
                return text
    if not use_links:
        return ""
    for link in node.find_all("a", href=True):
        href = link["href"]
        host = urlsplit(href).netloc.lower()
        if (_SKIP_URL_RE.search(href) or _looks_like_webcast(link, href)
                or any(host.endswith(h) for h in EXCLUDED_HOSTS)):
            continue
        if (text := _usable(link.get_text(" "))):
            return text
    return ""


def _describe(a):
    """(title, date) for a webcast link, from the link itself or its block."""
    anchor = _clean(a.get_text(" ")) or _clean(a.get("title", ""))
    title = _usable(anchor) if not _LINK_TEXT_RE.search(anchor) else None
    date = find_date(anchor)
    blocks = list(_event_blocks(a))
    for node in blocks:
        title = title or _title_in(node)
        date = date or find_date(_clean(node.get_text(" ")))
        if title and date:
            break
    for node in blocks:
        title = title or _title_in(node, use_links=True)
    return title or "", date


def _humanize(words):
    out = []
    for w in words.split():
        if re.fullmatch(r"q\d|fy\d*", w, re.I):
            out.append(w.upper())
        elif w.islower():
            out.append(w.capitalize())
        else:
            out.append(w)
    return " ".join(out)


def slug_title(url):
    """An event name spelled out in the address:
    '…/event-details/2026/2026-Q1-Earnings-Call-2026-nW8k/' → '2026 Q1 Earnings Call'."""
    for segment in reversed([x for x in urlsplit(url).path.split("/") if x]):
        if re.match(r"(?:default|index)\.", segment):
            continue
        m = re.match(r"(.*?(?:earnings[-_]call|conference|investor[-_]day|annual[-_]meeting|summit|symposium|forum))",
                     segment, re.I)
        if m:
            return _humanize(re.sub(r"[-_]+", " ", m.group(1)).strip())
    return ""


def title_from_url(url):
    """Fallback: '…/earnings/fy-2026-q4/press-release-webcast' → 'FY 2026 Q4 Earnings'."""
    path = urlsplit(url).path.lower()
    m = re.search(r"fy[-_ ]?(\d{2,4})[-_ ]?q([1-4])|q([1-4])[-_ ]?(?:fy)?[-_ ]?(\d{2,4})", path)
    if m and "earning" in path:
        year, q = (m[1], m[2]) if m[1] else (m[4], m[3])
        year = year if len(year) == 4 else "20" + year
        return f"{'FY ' if m[1] else ''}{year} Q{q} Earnings Call"
    return ""


def unwrap(url):
    """Undo e-mail security link wrapping (Proofpoint urldefense, Outlook safelinks)."""
    m = re.match(r"https?://urldefense(?:\.proofpoint)?\.com/v3/__(.+?)__;", url)
    if m:
        return re.sub(r"^(https?):/(?!/)", r"\1://", m.group(1))
    if "safelinks.protection.outlook.com" in url:
        from urllib.parse import parse_qs
        return parse_qs(urlsplit(url).query).get("url", [""])[0] or url
    return url


def extract_webcasts(html, base_url):
    """Return [{url, title, date}] for every webcast link on the page."""
    soup = BeautifulSoup(html, "lxml")
    # Site-wide menus, headers and footers are navigation, not event listings.
    for chrome in soup.find_all(["nav", "header", "footer"]):
        chrome.decompose()
    for chrome in soup.find_all(attrs={"role": ["navigation", "banner", "contentinfo"]}):
        chrome.decompose()
    found, seen = {}, set()
    for a in soup.find_all(["a", "iframe"]):
        raw = a.get("href") if a.name == "a" else a.get("src")
        if not raw:
            continue
        if a.name == "iframe" and not is_webcast_url(urljoin(base_url, raw.strip())):
            continue
        href = unwrap(urljoin(base_url, raw.strip()))
        if "#" in href:
            page, _, _ = href.partition("#")
            if page.rstrip("/").lower() == base_url.split("#")[0].rstrip("/").lower():
                continue  # "skip to content" / "top of page" style anchors
            href = page
        key = href.lower().rstrip("/")
        if not href.startswith("http") or key in seen or not _looks_like_webcast(a, href):
            continue
        if href.rstrip("/").lower() == base_url.rstrip("/").lower():
            continue
        title, date = _describe(a)
        if is_youtube_video(href) and not date and not _LINK_TEXT_RE.search(_clean(a.get_text(" "))):
            continue  # a corporate/marketing video rather than a streamed event
        seen.add(key)
        if is_webcast_url(href):
            title = slug_title(href) or title or title_from_url(href)
        else:
            # A page on the company's own site counts only if it is clearly about a
            # specific event: dated, or named in its address.
            url_title = slug_title(href) or title_from_url(href)
            if not date and not url_title:
                continue
            title = url_title or title
        found[href] = {"url": href, "title": title, "date": date}
    return list(found.values())


def find_links(html, base_url, pattern):
    """Links whose text (or path) matches pattern, as absolute URLs."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip()).split("#")[0]
        if not href.startswith("http") or _SKIP_URL_RE.search(href):
            continue
        text = _clean(a.get_text(" "))
        if pattern.search(text) or pattern.search(urlsplit(href).path):
            if href not in out:
                out.append(href)
    return out


def page_heading(html):
    """Best-effort event title for an event-detail page."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["h1", "h2"]):
        text = strip_dates(_clean(tag.get_text(" ")))
        if len(text) >= 8 and not _is_generic(text):
            return text[:200], find_date(_clean(soup.get_text(" "))[:3000])
    return "", None
