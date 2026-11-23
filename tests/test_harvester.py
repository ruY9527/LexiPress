"""采集器测试：RSS 解析、HN 过滤、正文抽取、付费墙检测、单源失败隔离。"""

from __future__ import annotations

import asyncio

import pytest

from src.harvester.extractor import (
    detect_paywall,
    extract_from_html,
    filter_paragraphs,
    text_to_paragraphs,
)
from src.harvester.hackernews import HackerNewsAdapter
from src.harvester.rss import RSSAdapter
from src.models import SourceConfig, SourceType

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>First Long Read About Attention</title>
      <link>https://example.com/first?utm_source=rss</link>
      <description>Snippet one.</description>
      <pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate>
      <author>Alice Writer</author>
      <content:encoded><![CDATA[<p>Body of first.</p>]]></content:encoded>
    </item>
    <item>
      <title>Second Piece</title>
      <link>https://example.com/second</link>
      <description>Snippet two.</description>
      <pubDate>Sun, 22 Nov 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Duplicate of First</title>
      <link>https://example.com/first/</link>
      <description>Dup.</description>
    </item>
    <item>
      <title>YouTube Video</title>
      <link>https://www.youtube.com/watch?v=abc</link>
      <description>Noise.</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_HTML = """<!DOCTYPE html><html><head>
<meta property="og:image" content="https://example.com/cover.jpg">
<title>Attention Test</title></head>
<body>
<nav>Home | About</nav>
<article>
<h1>The Architecture of Attention</h1>
<p>""" + ("For most of human history attention was borrowed from the room and the fire. " * 12) + """</p>
<p>""" + ("The modern word carries a different weight and we speak of paying attention as currency. " * 12) + """</p>
<p>""" + ("What the metaphor obscures is the extent to which attention is built rather than held today. " * 12) + """</p>
</article>
<footer>All rights reserved</footer>
</body></html>"""

PAYWALL_HTML = """<!DOCTYPE html><html><head><title>Members Only</title></head><body>
<div class="gate"><p>Subscribe to continue reading this article.</p></div>
</body></html>"""


# ---------------------------------------------------------------------------
# RSS
# ---------------------------------------------------------------------------


def test_rss_adapter_parses_and_deduplicates():
    cfg = SourceConfig(id="test", name="Test Feed", type=SourceType.RSS, url="https://example.com/feed")
    adapter = RSSAdapter(cfg)
    items = adapter.parse_feed_bytes(SAMPLE_RSS)

    urls = [i.url for i in items]
    assert "https://example.com/first" in urls
    assert "https://example.com/second" in urls
    # 末尾斜杠变体与 youtube 应被剔除
    assert len(urls) == 2
    assert all("youtube" not in u for u in urls)

    first = next(i for i in items if i.url.endswith("/first"))
    assert "Attention" in first.title
    assert first.published_at == "2026-11-23"
    assert first.author == "Alice Writer"
    assert "Body of first" in first.content_html


def test_rss_adapter_respects_per_source_limit():
    cfg = SourceConfig(id="test", name="Test Feed", type=SourceType.RSS, url="https://example.com/feed")
    adapter = RSSAdapter(cfg)
    adapter.settings.harvester.per_source_limit = 1
    items = adapter.parse_feed_bytes(SAMPLE_RSS)
    assert len(items) == 1


# ---------------------------------------------------------------------------
# Hacker News
# ---------------------------------------------------------------------------


def test_hackernews_adapter_exposes_thresholds():
    cfg = SourceConfig(
        id="hn", name="HN", type=SourceType.HACKERNEWS,
        url="https://hacker-news.firebaseio.com/v0/topstories.json",
        min_score=250, limit=15,
    )
    adapter = HackerNewsAdapter(cfg)
    assert adapter._score_threshold() == 250
    assert adapter._limit() == 15
    assert adapter.source_type is SourceType.HACKERNEWS


def test_hackernews_filters_low_score_and_noise():
    """用假 client 验证 score 阈值与域名白名单逻辑。"""

    class FakeResponse:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status_code = status

        def json(self):
            return self._payload

    class FakeClient:
        async def get(self, url):
            if "topstories" in url:
                return FakeResponse([1, 2, 3, 4])
            mapping = {
                "1": {"id": 1, "type": "story", "url": "https://example.com/good", "title": "Good", "score": 400, "time": 1800000000, "by": "a"},
                "2": {"id": 2, "type": "story", "url": "https://example.com/low", "title": "Low", "score": 50, "time": 1800000000},
                "3": {"id": 3, "type": "story", "url": "https://github.com/x/y", "title": "Repo", "score": 500, "time": 1800000000},
                "4": {"id": 4, "type": "story", "url": "https://example.com/pdf.pdf", "title": "PDF", "score": 500, "time": 1800000000},
            }
            nid = url.split("/")[-1].replace(".json", "")
            return FakeResponse(mapping.get(nid, {}))

    cfg = SourceConfig(
        id="hn", name="HN", type=SourceType.HACKERNEWS,
        url="https://hacker-news.firebaseio.com/v0/topstories.json",
        min_score=180, limit=10,
    )
    adapter = HackerNewsAdapter(cfg, client=FakeClient())
    items = asyncio.run(adapter.discover())

    assert len(items) == 1
    assert items[0].url == "https://example.com/good"
    assert items[0].extra["hn_score"] == 400


# ---------------------------------------------------------------------------
# 正文抽取
# ---------------------------------------------------------------------------


def test_extract_from_html_returns_clean_paragraphs():
    result = extract_from_html(SAMPLE_HTML, "https://example.com/a")
    assert result.status == "fetched"
    assert result.word_count > 200
    assert len(result.paragraphs) >= 2
    joined = " ".join(result.paragraphs)
    assert "All rights reserved" not in joined
    assert "Home | About" not in joined
    assert result.cover_image == "https://example.com/cover.jpg"


def test_extract_from_html_detects_paywall():
    result = extract_from_html(PAYWALL_HTML, "https://example.com/members", http_status=200)
    assert result.status == "paywalled"
    assert "subscribe" in result.error_message.lower() or "HTTP" in result.error_message


def test_extract_from_html_flags_http_403():
    result = extract_from_html("<p>tiny</p>", "https://example.com/x", http_status=403)
    assert result.status == "paywalled"
    assert "403" in result.error_message


def test_extract_from_html_fails_on_too_short_body():
    result = extract_from_html("<html><body><p>Too short.</p></body></html>", "https://example.com/x")
    assert result.status == "failed"
    assert "过短" in result.error_message


def test_extract_falls_back_to_rss_content():
    thin_html = "<html><body><p>Only a stub here.</p></body></html>"
    rich = "<p>" + ("This is a rich RSS body paragraph with enough words to pass the threshold. " * 20) + "</p>"
    result = extract_from_html(thin_html, "https://example.com/x", rss_content_html=rich)
    assert result.status == "fetched"
    assert result.method in {"rss_content", "readability"}
    assert result.word_count > 200


def test_detect_paywall_markers():
    assert detect_paywall("subscribe to continue") != ""
    assert detect_paywall("log in to read", 200) != ""
    assert detect_paywall("normal article body with plenty of words") == ""
    assert detect_paywall("x", 429) != ""


def test_filter_paragraphs_drops_noise_and_duplicates():
    blocks = [
        "Subscribe to our newsletter",
        "Read more:",
        "This is a real paragraph with more than five words in it.",
        "This is a real paragraph with more than five words in it.",
        "Advertisement",
        "Another genuine paragraph that carries substantive content for readers.",
    ]
    out = filter_paragraphs(blocks)
    assert "Subscribe to our newsletter" not in out
    assert "Advertisement" not in out
    assert len(out) == 2


def test_text_to_paragraphs_splits_on_blank_lines():
    text = "First paragraph here.\n\nSecond paragraph here.\n\n\nThird one."
    out = text_to_paragraphs(text)
    assert len(out) == 3
    assert out[0].startswith("First")
