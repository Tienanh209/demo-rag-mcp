"""Full BFS Crawler for the YZU AI Center site into data/raw/*.json.

Dynamic breadth-first search crawling over ai.yzu.edu.tw:
- Discovers all internal links dynamically starting from site entry points.
- Follows pagination (e.g. /news_list/all?page=2, ?page=3) to collect all news & notices.
- Cleans and normalizes DOM structure, stripping navigation, header, footer, sidebars,
  and breadcrumbs to avoid polluting RAG index chunks.
- Extracts headers, paragraphs, lists, and tables (for course credit & curriculum data).
"""

import argparse
import asyncio
import hashlib
import json
import re
from collections import deque
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.common.config import settings
from src.common.trace import get_logger

log = get_logger("crawl")

BASE = "https://ai.yzu.edu.tw"
ALLOWED_HOST = "ai.yzu.edu.tw"

# The site was rebuilt on Joomla in 2026 and every pre-rebuild URL now 404s.
# The old scheme (/article/*, /news_detail/*, /teacher_list/*) is gone; content
# is served under /index.php/tw/ with SEF routing. The retired corpus is kept in
# data/raw with status="archived"; scripts/resolve_sources.py points each one
# at either a live equivalent (if the BFS crawl found one — see CONTENT_
# CATEGORIES below) or the centre's own current home page, so a citation
# always resolves on ai.yzu.edu.tw itself and never depends on a third party.
LANG_PREFIX = "/index.php/tw"

# Seed points to bootstrap BFS queue.
#
# Both category listings are seeded explicitly rather than relied upon to be
# discovered by BFS from "/":
#   catid=10 (news)  is inlined as teasers on the home page, but nothing links
#                     to the listing itself.
#   catid=9  (TAICA)  is not linked from anywhere the crawler can reach at
#                     all — no nav item, no home-page teaser, no breadcrumb.
#                     It only exists because Joomla still serves the category
#                     ID directly. Found by sweeping /component/content/
#                     category/<id> for 0-40 and checking which return 200
#                     with real content (2=Uncategorised, 8=Blog, both empty).
#                     Losing this seed silently drops all 5 TAICA credit
#                     programs from the corpus with no error anywhere — the
#                     crawl still "succeeds", it just succeeds at fetching
#                     everything except the site's actual subject matter.
CONTENT_CATEGORIES = (9, 10)
INITIAL_SEEDS = [
    f"{BASE}{LANG_PREFIX}/",
    f"{BASE}{LANG_PREFIX}/intro",
    f"{BASE}{LANG_PREFIX}/apply",
    *(f"{BASE}{LANG_PREFIX}/component/content/category/{cat}" for cat in CONTENT_CATEGORIES),
]

# Mirrors robots.txt Disallow, plus the asset roots Joomla serves from the web
# root. Matched against the FIRST PATH SEGMENT ONLY, never as a substring:
# robots.txt disallows "/components/" (plural, at the root), while Joomla's SEF
# router emits "/index.php/tw/component/content/article/..." (singular, not at
# the root). A substring test here would silently exclude every news article —
# the exact pages this crawl exists to fetch.
DENY_ROOT_SEGMENTS = {
    "administrator", "bin", "cache", "cli", "components", "includes",
    "installation", "language", "layouts", "libraries", "logs", "modules",
    "plugins", "tmp", "media", "templates", "images", "api",
}

# Joomla puts routing state in the query string, so a blanket "strip the query"
# would collapse distinct articles onto one URL. Only ALLOWED_PARAMS are
# understood well enough to keep; anything outside both sets below (tmpl=
# component, format=pdf, print=1, task=...) is a duplicate view or an action
# URL and gets skipped rather than guessed at.
ALLOWED_PARAMS = ("catid", "id", "start", "limit", "page")

# Recognised, but dropped rather than kept: DECORATIVE_PARAMS are known to
# carry no addressing information, verified against the live site rather than
# assumed. Itemid is the menu item Joomla uses to highlight the active nav
# entry and build the breadcrumb — /apply, /apply?Itemid=101 and
# /apply?Itemid=999 all return byte-for-byte identical content. Keeping it
# would give one document two citation URLs; the general "skip, don't strip"
# rule above is for params that MIGHT matter, not this one.
DECORATIVE_PARAMS = ("Itemid",)

SITE_NAME = "人工智慧教學與應用發展中心"
# The centre was renamed in the rebuild. Both names have to be stripped: the
# live pages carry the new one, and the archived corpus in data/raw carries the
# old one, so a single-name pattern would leave the site name on half the
# titles.
FORMER_SITE_NAME = "人工智慧跨域創新應用中心"
# The site puts its name in front of the page title ("<site> | 關於中心"), not
# after it. Matching only the suffix left the name on all 47 titles, and since
# ingest prepends the title to every chunk it ended up in all 923 of them —
# which flattens the embedding space and costs the refusal gate its margin.
_NAMES = "|".join(re.escape(n) for n in (SITE_NAME, FORMER_SITE_NAME))
TITLE_NOISE = re.compile(rf"^\s*(?:{_NAMES})\s*[|｜–-]\s*|\s*[|｜–-]\s*(?:{_NAMES})\s*$")
# The new pages title the landing page "首頁", which says nothing. Since ingest
# prepends the title to every chunk, a corpus whose home chunks all start with
# "首頁" wastes the strongest signal each chunk has.
GENERIC_TITLES = {"首頁", "Home", "home"}

TEXT_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "blockquote", "figcaption"]

LONG_BLOCK = 200  # above this, a repeated block is a layout artifact, not prose
NON_WORD = re.compile(r"[\W_]+")

DROP_TAGS = ["script", "style", "nav", "header", "footer", "noscript", "form", "svg", "iframe"]
# sppb-addon-articles is the home page's news-teaser module: it repeats the
# three article pages verbatim, so a "最新消息" query retrieves the home page
# instead of the article and the citation then points at the wrong page.
DROP_CLASSES = re.compile(
    r"(breadcrumb|pc-left-menu|col-left|megamenu|top_text|search"
    r"|sppb-addon-articles|sp-preloader|sp-scroll-up)"
)
IGNORED_EXTS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".css", ".js", ".ico", ".woff", ".woff2", ".ttf",
    ".pdf", ".doc", ".docx", ".zip", ".rar", ".mp4",
)


def normalize_url(raw_url: str, base_url: str = BASE) -> str | None:
    """Normalize and validate a URL for internal crawling."""
    if not raw_url:
        return None
    joined = urljoin(base_url, raw_url).split("#")[0].strip()
    parsed = urlparse(joined)

    # Allow ai.yzu.edu.tw and www.ai.yzu.edu.tw. Lowercase first: an uppercase
    # "WWW." survived the old replace() and got the URL rejected.
    host = parsed.netloc.lower().split(":")[0].removeprefix("www.")
    if host != ALLOWED_HOST:
        return None

    path = parsed.path.rstrip("/")
    if not path:
        path = "/"

    # Ignore broken template slug placeholders or ignored file extensions
    if ":slug" in path or path.lower().endswith(IGNORED_EXTS):
        return None

    # First segment only — see the DENY_ROOT_SEGMENTS comment for why a
    # substring test would lock the crawler out of every news article.
    if path.strip("/").split("/")[0].lower() in DENY_ROOT_SEGMENTS:
        return None

    # The site 301s "/" to the language root; resolving that here rather than
    # over the wire saves a round trip and, more importantly, stops "/" and
    # "/index.php/tw" being saved as two documents with identical content.
    if path == "/":
        path = LANG_PREFIX
    if not path.startswith(LANG_PREFIX):
        return None

    # A param outside both sets is skipped rather than guessed at: dropping an
    # unrecognised param and fetching the shortened URL would save one page's
    # content under a URL that was never verified to serve it, and nothing
    # downstream could detect the mismatch. A skip shows up in the log.
    qs = parse_qs(parsed.query)
    if qs:
        if any(k not in ALLOWED_PARAMS and k not in DECORATIVE_PARAMS for k in qs):
            return None
        kept = {k: v for k, v in qs.items() if k in ALLOWED_PARAMS}
        if not kept:
            return f"{BASE}{path}"
        try:
            # Sorted, so ?catid=10&Itemid=101 and ?Itemid=101&catid=10 (Itemid
            # now dropped either way) canonicalise to one URL. Without this the
            # BFS visited-set misses and the same article is indexed twice —
            # two citation chips for one page.
            pairs = sorted((k, int(v[0])) for k, v in kept.items())
        except (ValueError, IndexError):
            return None
        query = "&".join(f"{k}={v}" for k, v in pairs)
        return f"{BASE}{path}?{query}"

    return f"{BASE}{path}"


# Joomla stamps every page with a publish date, including the standing menu
# pages. Only a news item's date is a *publication* date; keeping the others
# put 算力申請 and 服務團隊 above every real article in get_news, because
# retriever.news() orders on date and those are the most recently edited.
# A TAICA program page carries the same <time itemprop="datePublished"> markup
# as a news article (it is just "when this course table was last edited"), so
# "article" must stay out of this set too.
NEWS_SECTIONS = {"news_detail", "notice"}

# catid=10 is the news category; every other content category (currently just
# catid=9, TAICA) is a standing program page, not a dated announcement. Both
# an article and its listing are served from the identical
# /component/content/{article,category}/... shape, so once Itemid is dropped
# the query's catid is the only thing left in the URL that tells them apart.
_NEWS_CATID = "10"


def section_for(url: str) -> str:
    """Classify a page from its URL.

    Joomla routes content through /component/content/{article,category}/..., so
    the first path segment is "index.php" for every page and carries nothing.
    The names returned here are deliberately the ones the retired site used:
    retriever.news() excludes "*_list" and "home" so that a listing page cannot
    outrank the article it links to, and keeping that vocabulary means the live
    and archived halves of the corpus stay describable by one rule — a TAICA
    program page here gets the same "article" section the retired site's own
    /article/TAICA* pages used.

    The category id lives in two different places depending on the view: an
    article carries it as the ?catid= query param, a category listing carries
    it as the last path segment (.../category/9). Reading from the wrong one
    silently put every listing page in "news_list" regardless of category.
    """
    parsed = urlparse(url)
    rest = parsed.path.removeprefix(LANG_PREFIX)
    rest = rest.strip("/")
    if not rest:
        return "home"
    if rest.startswith("component/content/article"):
        catid = parse_qs(parsed.query).get("catid", [""])[0]
        return "news_detail" if catid == _NEWS_CATID else "article"
    if rest.startswith("component/content/category"):
        catid = rest.rsplit("/", 1)[-1]
        return "news_list" if catid == _NEWS_CATID else "article_list"
    return rest.split("/")[0]


def published_date(soup: BeautifulSoup) -> str:
    """ISO date from the page's own metadata, or '' when it carries none.

    Must run before DROP_TAGS decomposes the header: the Joomla article body
    opens with the headline, so ingest.extract_date (which scans text[:300])
    finds nothing and get_news would return an empty list for the whole live
    corpus. The date only exists in the markup.
    """
    tag = soup.find("time", attrs={"itemprop": "datePublished"})
    raw = (tag.get("datetime") or "") if tag else ""
    if not raw:
        meta = soup.find("meta", attrs={"property": "article:published_time"})
        raw = (meta.get("content") or "") if meta else ""
    return raw[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", raw) else ""


def clean(html: str) -> tuple[str, str, str]:
    """Extract clean title, structured body markdown, and publication date."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    # Strip the site name from either end. Keep the original if that leaves
    # nothing — the home page's title is the site name and nothing else.
    title = TITLE_NOISE.sub("", title).strip() or title
    if title in GENERIC_TITLES:
        title = SITE_NAME
    date = published_date(soup)

    # Drop script, styles, header, footer
    for tag in soup(DROP_TAGS):
        tag.decompose()

    # Drop navigation and sidebar menus
    for el in soup.find_all(class_=DROP_CLASSES):
        el.decompose()

    # Locate main content container
    content = (
        soup.find("div", class_="col-right")
        or soup.find(class_="fck")
        or soup.find("main")
        or soup.find(id="content")
        or soup.body
        or soup
    )

    lines: list[str] = []

    # Tables first, one line per row. The generic pass below emits each cell on
    # its own line, which detaches a course's credit count from the course name.
    # Rows are removed from the tree afterwards so they are not emitted twice.
    for table in content.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if any(cells):
                lines.append("| " + " | ".join(cells) + " |")
        table.decompose()

    # find_all() walks the whole subtree, so a <li> wrapping a <p> used to emit
    # the same text twice — 207 duplicated lines across 9 pages. Skip any element
    # already covered by an emitted ancestor. Tracking node identity rather than
    # text keeps legitimately repeated short strings.
    emitted: set[int] = set()
    seen_long: list[str] = []
    for el in content.find_all(TEXT_TAGS):
        if any(id(parent) in emitted for parent in el.parents):
            continue
        text = el.get_text(" ", strip=True)
        if len(text) < 2:
            continue
        emitted.add(id(el))
        if el.name.startswith("h"):
            try:
                level = int(el.name[1])
            except ValueError:
                level = 2
            lines.append(f"\n{'#' * level} {text}")
        else:
            # Tabbed layouts render the same block under several tabs, and each
            # copy carries its own tab label, so the copies are near-identical
            # rather than equal. Match on an interior window of the normalised
            # text instead: one 47k-char publication list served under two tabs
            # was 57% of the whole corpus and won every search. Short repeats are
            # left alone — those can be real content.
            if len(text) > LONG_BLOCK:
                norm = NON_WORD.sub("", text)
                probe = norm[200:700] or norm[:500]
                if probe and any(probe in seen for seen in seen_long):
                    continue
                seen_long.append(norm)
            lines.append(text)

    body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, body, date


def extract_links(html: str, current_url: str) -> set[str]:
    """Extract all valid internal links from the page."""
    soup = BeautifulSoup(html, "html.parser")
    found = set()
    for a in soup.find_all("a", href=True):
        norm = normalize_url(a["href"], current_url)
        if norm:
            found.add(norm)
    return found


async def crawl(max_pages: int, delay: float, clear: bool = False) -> int:
    """Execute full BFS crawl of YZU AI Center website."""
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    if clear:
        # Only live pages. data/raw now holds two generations of the corpus and
        # the archived half cannot be re-fetched from anywhere — the site that
        # served it is gone. A blanket unlink would be unrecoverable.
        removed = kept = 0
        for f in settings.raw_dir.glob("*.json"):
            try:
                status = json.loads(f.read_text(encoding="utf-8")).get("status", "live")
            except (json.JSONDecodeError, OSError):
                status = "archived"  # unreadable: refuse to delete it
            if status == "live":
                f.unlink()
                removed += 1
            else:
                kept += 1
        log.info("cleared %d live files from %s (%d archived kept)",
                 removed, settings.raw_dir, kept)

    queue: deque[str] = deque()
    visited: set[str] = set()
    queued: set[str] = set()  # membership test; scanning the deque was O(n)

    for s in INITIAL_SEEDS:
        norm = normalize_url(s)
        if norm and norm not in queued:
            queue.append(norm)
            queued.add(norm)

    saved = 0
    fetched = 0
    live_urls_seen: set[str] = set()

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "yzu-rag-mcp/0.2 (full-bfs crawler)"},
    ) as client:
        while queue and fetched < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    log.warning("HTTP %d for %s", resp.status_code, url)
                    continue
            except httpx.HTTPError as exc:
                log.warning("skip %s (%s)", url, exc)
                continue
            finally:
                # Politeness cannot depend on the happy path: the old `continue`
                # jumped over the delay, so the site got hit hardest exactly when
                # it was already failing.
                await asyncio.sleep(delay)

            # Only a successful fetch spends the budget.
            fetched += 1

            # Discover links via BFS queue
            for link in extract_links(resp.text, url):
                if link not in visited and link not in queued:
                    queue.append(link)
                    queued.add(link)

            title, body, date = clean(resp.text)
            # Only save pages that contain real content (exclude empty listing containers)
            if len(body) < 100:
                log.info("thin page (links extracted, not saved): %s (%d chars)", url, len(body))
            else:
                name = hashlib.sha1(url.encode()).hexdigest()[:12]
                section = section_for(url)
                (settings.raw_dir / f"{name}.json").write_text(
                    json.dumps(
                        {
                            # "url" is identity and is never rewritten: retriever
                            # .get_document(), the chunk-id hash and eval_set.json
                            # all key off it. "cite_url" is presentation only —
                            # what the user clicks — so a retired page's citation
                            # can point at the centre's current home page without
                            # changing what document this *is*.
                            "url": url,
                            "cite_url": url,
                            "status": "live",
                            "archived_at": "",
                            "title": title or url,
                            "text": body,
                            "section": section,
                            "date": date if section in NEWS_SECTIONS else "",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                saved += 1
                live_urls_seen.add(url)
                log.info("[%2d] %s (%d chars) -> %s", saved, title[:40] or url, len(body), url)

    # A live page saved under an OLD URL shape becomes a stale duplicate the
    # moment normalize_url() changes and produces a different canonical form
    # for it — as happened when Itemid was dropped: the three news articles
    # were already on disk under ?Itemid=101&catid=10, and this same run
    # refetched them under ?catid=10, leaving two copies of each. Rather than
    # requiring a manual data/raw cleanup after every crawler fix, prune any
    # live doc this crawl did NOT just (re)confirm and whose own URL no longer
    # round-trips through the current normalize_url() — that combination means
    # it was superseded this run, not that it is simply unreachable today.
    pruned = 0
    for f in settings.raw_dir.glob("*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if doc.get("status", "live") != "live" or doc["url"] in live_urls_seen:
            continue
        if normalize_url(doc["url"]) != doc["url"]:
            log.info("pruning stale duplicate (superseded this run): %s", doc["url"])
            f.unlink()
            pruned += 1

    # Report the remaining frontier: a silently truncated crawl and a complete
    # one look identical without it.
    log.info(
        "BFS crawl complete: fetched %d pages, saved %d documents, %d pruned, %d still queued -> %s",
        fetched, saved, pruned, len(queue), settings.raw_dir,
    )
    return saved


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Full BFS Crawler for YZU AI Center")
    p.add_argument("--max-pages", type=int, default=200, help="maximum pages to crawl")
    p.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    p.add_argument("--clear", action="store_true", help="clear data/raw before crawling")
    args = p.parse_args()
    asyncio.run(crawl(args.max_pages, args.delay, args.clear))
