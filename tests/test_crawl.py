"""URL handling for the rebuilt site.

The source site moved to Joomla and every old URL now 404s. These tests pin the
two rules that were easy to get wrong: the deny list must not lock the crawler
out of the news articles, and two spellings of the same article must canonicalise
to one URL or it gets indexed twice.
"""

import pytest

from scripts.crawl_yzu import BASE, normalize_url, section_for


@pytest.mark.parametrize("raw,expected", [
    ("/index.php/tw/", f"{BASE}/index.php/tw"),
    ("/index.php/tw/apply", f"{BASE}/index.php/tw/apply"),
    ("/index.php/tw/intro", f"{BASE}/index.php/tw/intro"),
    # The site 301s "/" to the language root; resolving it locally stops the
    # same page being saved twice under two URLs.
    ("/", f"{BASE}/index.php/tw"),
])
def test_live_pages_are_accepted(raw, expected):
    assert normalize_url(raw) == expected


def test_article_query_keeps_catid_and_drops_the_decorative_itemid():
    """catid is the real category assignment and section_for() depends on it to
    tell a TAICA program apart from a news article. Itemid is the active-menu
    highlight, identical on every page under /index.php/tw/ regardless of
    content — verified against the live site (?Itemid=101 vs ?Itemid=999 on the
    same article return byte-identical bodies). Two spellings of the same
    catid, and a spelling with Itemid thrown in, must all canonicalise to one
    URL or the article gets indexed (and cited) twice."""
    bare = normalize_url("/index.php/tw/component/content/article/news-20251002?catid=10")
    with_itemid_first = normalize_url(
        "/index.php/tw/component/content/article/news-20251002?Itemid=101&catid=10"
    )
    with_itemid_second = normalize_url(
        "/index.php/tw/component/content/article/news-20251002?catid=10&Itemid=101"
    )
    assert bare == with_itemid_first == with_itemid_second
    assert bare.endswith("?catid=10")
    assert "Itemid" not in bare


@pytest.mark.parametrize("raw", [
    "/administrator/index.php",     # robots.txt
    "/components/x.css",            # robots.txt — plural, at the web root
    "/modules/system/framework.js",
    "/images/logo.png",
    "/index.php/tw/apply?tmpl=component",   # duplicate view
    "/index.php/tw/apply?format=pdf",       # duplicate view
    "/index.php/tw/apply?page=notanumber",
    "https://www.yzu.edu.tw/index.php/tw/",  # different host
    "/article/TAICA",               # retired scheme: no longer fetchable
])
def test_rejected(raw):
    assert normalize_url(raw) is None


def test_component_is_denied_at_the_root_but_not_inside_a_page_path():
    """robots.txt disallows /components/ at the web root, while Joomla's SEF
    router emits /index.php/tw/component/content/... A substring test would
    exclude every news article — the pages the crawl exists to fetch."""
    assert normalize_url("/components/com_content/x.php") is None
    assert normalize_url("/index.php/tw/component/content/article/news-1?catid=10") is not None


@pytest.mark.parametrize("url,expected", [
    (f"{BASE}/index.php/tw", "home"),
    (f"{BASE}/index.php/tw/apply", "apply"),
    (f"{BASE}/index.php/tw/intro", "intro"),
    (f"{BASE}/index.php/tw/component/content/article/news-1?catid=10", "news_detail"),
    (f"{BASE}/index.php/tw/component/content/category/10", "news_list"),
    # catid=9 is the TAICA category: same URL shape as news (both are
    # component/content/article/<slug>), distinguished only by catid. Named
    # "article" — not "taica_detail" or similar — to match the vocabulary the
    # archived corpus already uses for these same five programs.
    (f"{BASE}/index.php/tw/component/content/article/class-1?catid=9", "article"),
    (f"{BASE}/index.php/tw/component/content/category/9", "article_list"),
    # The archived corpus keeps working under the same rule.
    (f"{BASE}/article/TAICA", "article"),
    (f"{BASE}/news_list/all", "news_list"),
])
def test_section_for(url, expected):
    assert section_for(url) == expected


def test_news_sections_match_what_get_news_filters_on():
    """retriever.news() excludes '*_list' and 'home' so a listing page cannot
    outrank the article it links to. These names are chosen to satisfy it."""
    assert section_for(f"{BASE}/index.php/tw/component/content/category/10").endswith("_list")
    assert section_for(f"{BASE}/index.php/tw/component/content/category/9").endswith("_list")
    assert section_for(f"{BASE}/index.php/tw") == "home"
    assert not section_for(
        f"{BASE}/index.php/tw/component/content/article/news-1?catid=10"
    ).endswith("_list")


def test_only_news_sections_are_dated():
    """Joomla stamps a publish date on the standing menu pages too. Keeping it
    put 算力申請 and 服務團隊 above every real article in get_news, because
    retriever.news() orders on date and they are the most recently edited. A
    TAICA program page carries the identical <time itemprop="datePublished">
    markup — it is a "last edited" stamp, not news — so catid=9 must stay out
    of NEWS_SECTIONS exactly like the standing menu pages."""
    from scripts.crawl_yzu import NEWS_SECTIONS

    assert section_for(f"{BASE}/index.php/tw/component/content/article/news-1?catid=10") in NEWS_SECTIONS
    assert section_for(f"{BASE}/index.php/tw/component/content/article/class-1?catid=9") not in NEWS_SECTIONS
    assert section_for(f"{BASE}/index.php/tw/apply") not in NEWS_SECTIONS
    assert section_for(f"{BASE}/index.php/tw/intro") not in NEWS_SECTIONS
    assert section_for(f"{BASE}/index.php/tw") not in NEWS_SECTIONS


def test_taica_category_is_seeded_explicitly():
    """catid=9 is reachable only by knowing its ID — no nav item, no home-page
    teaser, no link anywhere the crawler could discover it from. It was found
    by sweeping category IDs 0-40 against the live site. Losing this seed
    drops all 5 TAICA credit programs from the corpus with the crawl still
    reporting success, which is exactly the failure mode worth pinning."""
    from scripts.crawl_yzu import CONTENT_CATEGORIES, INITIAL_SEEDS

    assert 9 in CONTENT_CATEGORIES
    assert any("category/9" in seed for seed in INITIAL_SEEDS)
