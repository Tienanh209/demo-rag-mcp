"""Chunking, tokenisation and fusion are where retrieval quality is won or lost."""

from src.server.ingest import chunk_document, split_sections, window
from src.server.store import tokenize


def test_sections_split_on_headings():
    text = "intro\n\n## 學程\nbody one\n\n## 設備\nbody two"
    assert [h for h, _ in split_sections(text)] == ["", "學程", "設備"]


def test_window_overlaps_and_bounds_length():
    body = "。".join(f"句子{i}" for i in range(200))
    pieces = window(body, size=200, overlap=40)
    assert len(pieces) > 1
    assert all(len(p) <= 280 for p in pieces)


def test_chunk_carries_title_heading_and_url():
    doc = {
        "title": "課程資訊",
        "url": "https://ai.yzu.edu.tw/article/courses",
        "text": "## TAICA\n" + "內容" * 400,
        "section": "article",
    }
    chunks = chunk_document(doc)
    assert chunks
    assert all(c["url"] == doc["url"] for c in chunks)
    assert chunks[0]["text"].startswith("課程資訊 > TAICA")
    assert len({c["id"] for c in chunks}) == len(chunks)


def test_chunk_defaults_a_document_with_no_archive_metadata_to_live():
    """data/raw predates status/cite_url; an old file must not produce a chunk
    with an empty citation URL, which renders as a link to nowhere."""
    doc = {
        "title": "課程資訊",
        "url": "https://ai.yzu.edu.tw/article/courses",
        "text": "內容" * 400,
        "section": "article",
    }
    chunk = chunk_document(doc)[0]
    assert chunk["status"] == "live"
    assert chunk["cite_url"] == doc["url"]


def test_chunk_carries_the_archived_documents_real_site_citation():
    """An archived document's cite_url is a page on the real site — its own,
    when a live equivalent was found (see scripts/resolve_sources.py), or the
    centre's current home page when there is no live equivalent. Never a
    third-party URL."""
    doc = {
        "title": "課程資訊",
        "url": "https://ai.yzu.edu.tw/article/courses",
        "cite_url": "https://ai.yzu.edu.tw/index.php/tw",
        "status": "archived",
        "text": "內容" * 400,
        "section": "article",
        "date": "2026-02-17",
    }
    chunk = chunk_document(doc)[0]
    # url is identity and must survive untouched — get_document, the chunk id
    # hash and eval_set.json all key off it.
    assert chunk["url"] == doc["url"]
    assert chunk["cite_url"] == doc["cite_url"]
    assert chunk["status"] == "archived"
    assert chunk["date"] == "2026-02-17"


def test_crawler_supplied_date_beats_the_body_regex():
    """The rebuilt site carries its date only in markup, so the crawler reads it
    there; the regex stays for the archived corpus, which leads with its date."""
    doc = {
        "title": "最新消息",
        "url": "https://ai.yzu.edu.tw/index.php/tw/component/content/article/news-1",
        "text": "2024-01-01 舊的日期出現在內文" + "內容" * 100,
        "section": "news_detail",
        "date": "2025-10-02",
    }
    assert chunk_document(doc)[0]["date"] == "2025-10-02"


def test_chinese_tokenisation_is_not_empty():
    tokens = tokenize("人工智慧視覺技術學分學程 AI vision")
    assert len(tokens) > 3
    assert "ai" in tokens


def test_english_words_map_to_chinese_search_terms():
    """The safety net for a failed LLM rewrite: an English question must still
    reach Chinese passages."""
    from src.client.agents.retrieval_agent import chinese_terms

    assert "學分學程" in chinese_terms("What credit programs does TAICA offer?")
    assert "師資" in chinese_terms("Which teachers are at the centre?")
    assert "最新消息" in chinese_terms("What's the latest news from the centre?")
    assert chinese_terms("TAICA 有哪些學分學程？") == ""


def test_format_passages_marks_archived_material():
    """The model cannot otherwise tell a retired program from a current one."""
    from src.client.agents.retrieval_agent import RetrievalAgent

    rendered = RetrievalAgent.format_passages([
        {"title": "TAICA", "url": "u1", "cite_url": "snap1", "text": "t",
         "score": 0.9, "status": "archived"},
        {"title": "算力申請", "url": "u2", "cite_url": "u2", "text": "t",
         "score": 0.9, "status": "live"},
    ])
    assert "[1] (score 0.9, archived) TAICA" in rendered
    assert "(score 0.9) 算力申請" in rendered


def test_format_passages_shows_the_citable_url_not_the_dead_one():
    """Models echo these URLs into prose. The identity URL of an archived page
    is a 404, so the prompt must not be the thing that hands one over — it
    shows cite_url, which always resolves on the real site."""
    from src.client.agents.retrieval_agent import RetrievalAgent

    rendered = RetrievalAgent.format_passages([
        {"title": "TAICA", "url": "https://ai.yzu.edu.tw/article/TAICA",
         "cite_url": "https://ai.yzu.edu.tw/index.php/tw",
         "text": "t", "score": 1.0, "status": "archived"},
    ])
    assert "URL: https://ai.yzu.edu.tw/index.php/tw" in rendered
    assert "URL: https://ai.yzu.edu.tw/article/TAICA\n" not in rendered


def test_format_passages_omits_the_url_when_there_is_nowhere_to_link():
    """Defensive: nothing in the pipeline produces an empty cite_url today —
    scripts/resolve_sources.py gives every archived document a real citation —
    but format_passages must still degrade safely rather than hand the model
    an "URL:" line with nothing after it."""
    from src.client.agents.retrieval_agent import RetrievalAgent

    rendered = RetrievalAgent.format_passages([
        {"title": "退役頁面", "url": "https://ai.yzu.edu.tw/article/100", "cite_url": "",
         "text": "t", "score": 1.0, "status": "archived"},
    ])
    assert "URL:" not in rendered
    assert "archived) 退役頁面" in rendered
