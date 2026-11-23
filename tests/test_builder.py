"""静态站构建器测试：产物完整性、base_url 前缀、Clean URL、搜索索引。"""

from __future__ import annotations

import json
import re

import pytest

from src.builder import SiteBuilder
from src.config import load_settings
from src.models import (
    ArticleOverview,
    Difficulty,
    ParagraphPair,
    ParsedArticle,
    SentenceAnalysis,
    VocabItem,
)
from src.storage import Storage
from src.utils import iso_now, url_hash


@pytest.fixture()
def storage(tmp_path):
    return Storage(
        db_path=tmp_path / "test.db",
        index_path=tmp_path / "index.json",
        parsed_dir=tmp_path / "parsed",
    )


def _make_article(idx: int, *, with_vocab: bool = True, with_zh: bool = True) -> ParsedArticle:
    slug = f"article-{idx}"
    return ParsedArticle(
        id=f"2026-11-2{idx}-test-{slug}",
        url_hash=url_hash(f"https://example.com/{slug}"),
        title=f"Test Article Number {idx}",
        source="Test Journal",
        source_id="test",
        author="Author Name",
        published_at=f"2026-11-2{idx}",
        original_url=f"https://example.com/{slug}",
        cover_image="",
        tags=["Testing", "Media"],
        difficulty=Difficulty.C1,
        word_count=900,
        read_time_min=5,
        score=8.0 + idx * 0.1,
        parsed_at=iso_now(),
        parser_mode="llm" if with_vocab else "rule",
        overview=ArticleOverview(
            summary_zh="这是测试用的中文导读摘要。",
            takeaways=["要点一", "要点二"],
            background="背景说明",
            structure="结构说明",
        ),
        paragraphs=[
            ParagraphPair(
                index=0,
                en="Attention was borrowed from the room, and the article argues that art matters.",
                zh="注意力是从房间里借来的，文章主张艺术很重要。" if with_zh else "",
            ),
            ParagraphPair(index=1, en="The modern word carries a different weight.", zh="现代的词带着另一种分量。" if with_zh else ""),
        ],
        vocab=(
            [
                VocabItem(id="v1", term="attention", phonetic="/əˈten.ʃən/", pos="n.", meaning_zh="注意力", para_index=0),
                VocabItem(id="v2", term="art", phonetic="/ɑːt/", pos="n.", meaning_zh="艺术", para_index=0),
            ]
            if with_vocab
            else []
        ),
        sentences=(
            [SentenceAnalysis(en="Attention was borrowed.", structure="主干 + 被动", zh="注意力是被借来的。")]
            if with_vocab
            else []
        ),
    )


@pytest.fixture()
def built(tmp_path, storage):
    for i in (1, 2, 3):
        storage.export_parsed_article(_make_article(i))
    out = tmp_path / "dist"
    builder = SiteBuilder(storage=storage)
    summary = builder.build(out)
    return out, summary


# ---------------------------------------------------------------------------
# 产物完整性
# ---------------------------------------------------------------------------


def test_build_produces_required_files(built):
    out, summary = built
    assert summary.ok
    assert summary.article_count == 3

    assert (out / ".nojekyll").exists()
    assert (out / "index.html").exists()
    assert (out / "404.html").exists()
    assert (out / "search-index.json").exists()
    assert (out / "static" / "css" / "tokens.css").exists()
    assert (out / "static" / "css" / "site.css").exists()
    assert (out / "static" / "js" / "app.js").exists()
    assert (out / "static" / "js" / "reader.js").exists()
    assert (out / "static" / "js" / "search.js").exists()
    assert (out / "static" / "js" / "vocab.js").exists()


def test_build_creates_clean_url_article_pages(built):
    out, _ = built
    for i in (1, 2, 3):
        assert (out / "articles" / f"2026-11-2{i}-test-article-{i}" / "index.html").exists()


def test_nojekyll_is_empty(built):
    out, _ = built
    assert (out / ".nojekyll").read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# base_url
# ---------------------------------------------------------------------------


def test_all_assets_prefixed_with_base_url(built):
    out, summary = built
    base = load_settings().base_url
    assert base == "/LexiPress"

    html = (out / "index.html").read_text(encoding="utf-8")
    for pattern in (
        'href="/LexiPress/static/css/tokens.css"',
        'href="/LexiPress/static/css/site.css"',
        'src="/LexiPress/static/js/app.js"',
    ):
        assert pattern in html


def test_no_hardcoded_root_absolute_links(built):
    out, _ = built
    for page in [out / "index.html", out / "404.html"] + list((out / "articles").glob("*/index.html")):
        html = page.read_text(encoding="utf-8")
        for match in re.finditer(r'(?:href|src)="(/[^"]*)"', html):
            url = match.group(1)
            assert url.startswith("/LexiPress"), f"{page.name} 出现未带前缀的根路径：{url}"


def test_article_links_use_base_url(built):
    out, _ = built
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "/LexiPress/articles/2026-11-21-test-article-1/" in html


# ---------------------------------------------------------------------------
# 搜索索引
# ---------------------------------------------------------------------------


def test_search_index_contains_all_articles(built):
    out, _ = built
    index = json.loads((out / "search-index.json").read_text(encoding="utf-8"))
    assert len(index) == 3
    entry = index[0]
    for key in ("id", "title", "source", "tags", "difficulty", "url", "excerpt", "vocab"):
        assert key in entry
    assert entry["url"].startswith("/LexiPress/articles/")
    # 生词进入索引，供 ⌘K 搜索
    all_vocab = [v for e in index for v in e["vocab"]]
    assert "attention" in all_vocab


# ---------------------------------------------------------------------------
# 渲染细节
# ---------------------------------------------------------------------------


def test_article_page_injects_safe_vocab_marks(built):
    out, _ = built
    html = (out / "articles" / "2026-11-21-test-article-1" / "index.html").read_text(encoding="utf-8")
    assert 'class="vocab-term"' in html
    # art 不应命中 article
    assert ">article<" not in html
    assert html.count('data-term="art"') >= 1


def test_hero_falls_back_to_art_cover_without_image(built):
    out, _ = built
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "art-cover" in html
    assert "art-cover__watermark" in html
    assert "art-cover__quote" in html


def test_hero_uses_headline_and_primary_cta(built):
    out, _ = built
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "开始精读" in html
    assert "hero__title" in html


def test_filter_pills_rendered_for_sources_and_levels(built):
    out, _ = built
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'data-filter="source"' in html
    assert 'data-filter="level"' in html
    assert 'data-filter="state"' in html


def test_reader_page_has_core_interactions(built):
    out, _ = built
    html = (out / "articles" / "2026-11-21-test-article-1" / "index.html").read_text(encoding="utf-8")
    # 进度条 / 控制胶囊 / 三模式 / 生词浮窗 / 双语段落 / 助手段
    assert "reading-progress" in html
    assert "reader-controls" in html
    assert 'data-mode="en"' in html and 'data-mode="vocab"' in html and 'data-mode="dual"' in html
    assert "vocab-popover" in html
    assert "para-zh" in html
    assert "study-aside" in html
    assert "spoiler" in html  # 盲读保护罩
    assert "sheet" in html  # 移动端抽屉


def test_theme_inline_script_prevents_flash(built):
    out, _ = built
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "lexipress_theme" in html
    assert "data-theme" in html
    # 内联脚本必须在样式表之前
    assert html.index("lexipress_theme") < html.index("tokens.css")


def test_404_page_has_return_link(built):
    out, _ = built
    html = (out / "404.html").read_text(encoding="utf-8")
    assert "404" in html
    assert 'href="/LexiPress/"' in html


# ---------------------------------------------------------------------------
# 降级与边界
# ---------------------------------------------------------------------------


def test_build_with_empty_parsed_dir(tmp_path):
    storage = Storage(
        db_path=tmp_path / "t.db",
        index_path=tmp_path / "index.json",
        parsed_dir=tmp_path / "parsed",
    )
    out = tmp_path / "dist"
    summary = SiteBuilder(storage=storage).build(out)
    assert summary.article_count == 0
    assert (out / "index.html").exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "第一期正在排版中" in html


def test_build_tolerates_missing_translation_and_vocab(tmp_path):
    storage = Storage(
        db_path=tmp_path / "t.db",
        index_path=tmp_path / "index.json",
        parsed_dir=tmp_path / "parsed",
    )
    storage.export_parsed_article(_make_article(1, with_vocab=False, with_zh=False))
    out = tmp_path / "dist"
    summary = SiteBuilder(storage=storage).build(out)
    assert summary.ok
    html = (out / "articles" / "2026-11-21-test-article-1" / "index.html").read_text(encoding="utf-8")
    # 不应出现空的尴尬区块文案，但页面必须正常
    assert "Test Article Number 1" in html
    assert "vocab-term" not in html


def test_build_removes_stale_article_dirs(tmp_path):
    storage = Storage(
        db_path=tmp_path / "t.db",
        index_path=tmp_path / "index.json",
        parsed_dir=tmp_path / "parsed",
    )
    storage.export_parsed_article(_make_article(1))
    out = tmp_path / "dist"
    SiteBuilder(storage=storage).build(out)

    stale = out / "articles" / "stale-one"
    stale.mkdir(parents=True)
    (stale / "index.html").write_text("old", encoding="utf-8")

    SiteBuilder(storage=storage).build(out)
    assert not stale.exists()


def test_build_warns_on_orphan_index_entries(tmp_path):
    storage = Storage(
        db_path=tmp_path / "t.db",
        index_path=tmp_path / "index.json",
        parsed_dir=tmp_path / "parsed",
    )
    storage.export_parsed_article(_make_article(1))
    storage.save_index(
        storage.load_index() + [{"id": "ghost-entry", "title": "Ghost", "url_hash": "x", "canonical_url": "https://e.com/g"}]
    )
    summary = SiteBuilder(storage=storage).build(tmp_path / "dist")
    assert any("ghost-entry" in w for w in summary.warnings)


def test_offline_article_is_not_built(tmp_path):
    """index.json 是发布真理源：从 index 移除（下线）后不应再生成页面。"""

    storage = Storage(
        db_path=tmp_path / "t.db",
        index_path=tmp_path / "index.json",
        parsed_dir=tmp_path / "parsed",
    )
    keep = _make_article(1)
    drop = _make_article(2)
    storage.export_parsed_article(keep)
    storage.export_parsed_article(drop)
    out = tmp_path / "dist"
    assert SiteBuilder(storage=storage).build(out).article_count == 2

    # 模拟后台点「下线」：从 index 移除，但保留 parsed 文件
    storage.remove_index_entry(drop.id)
    assert storage.parsed_path_for(drop.id).exists()

    summary = SiteBuilder(storage=storage).build(out)
    assert summary.article_count == 1
    assert not (out / "articles" / drop.id).exists()
    assert (out / "articles" / keep.id).exists()
