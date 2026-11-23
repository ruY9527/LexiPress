"""双层存储测试：SQLite WAL、双重去重、原子落盘、双向同步。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.models import (
    ArticleOverview,
    Difficulty,
    ParagraphPair,
    ParsedArticle,
    RawArticle,
    SourceConfig,
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


def _raw(url: str = "https://example.com/a", title: str = "A Title") -> RawArticle:
    return RawArticle(
        url_hash=url_hash(url),
        canonical_url=url,
        source_id="test",
        source_name="Test Journal",
        title=title,
        published_at="2026-11-23",
        fetched_at=iso_now(),
        paragraphs=["A paragraph with several words in it for counting purposes."],
        word_count=11,
        read_time_min=1,
        score=7.5,
    )


def _parsed(article_id: str = "2026-11-23-test-a") -> ParsedArticle:
    return ParsedArticle(
        id=article_id,
        url_hash=url_hash("https://example.com/a"),
        title="A Title",
        source="Test Journal",
        source_id="test",
        published_at="2026-11-23",
        original_url="https://example.com/a",
        difficulty=Difficulty.C1,
        word_count=11,
        read_time_min=1,
        score=7.5,
        parsed_at=iso_now(),
        parser_mode="rule",
        overview=ArticleOverview(summary_zh="摘要"),
        paragraphs=[ParagraphPair(index=0, en="Hello world.", zh="你好世界。")],
        vocab=[VocabItem(id="v1", term="hello", meaning_zh="你好")],
    )


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------


def test_init_db_enables_wal_and_tables(storage):
    with storage.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert mode.lower() == "wal"
    assert {"sources", "crawl_runs", "articles"} <= tables
    assert busy == 5000


# ---------------------------------------------------------------------------
# 文章 CRUD
# ---------------------------------------------------------------------------


def test_upsert_article_inserts_then_updates(storage):
    raw = _raw()
    aid = storage.upsert_article(raw)
    assert aid
    row = storage.get_article(aid)
    assert row["title"] == "A Title"

    raw.title = "Updated Title"
    aid2 = storage.upsert_article(raw)
    assert aid2 == aid  # 同一 url_hash 复用同一 id
    assert storage.get_article(aid)["title"] == "Updated Title"

    listing = storage.list_articles(page=1, page_size=10)
    assert listing["total"] == 1


def test_upsert_article_assigns_unique_ids_for_different_urls(storage):
    a = storage.upsert_article(_raw("https://example.com/a", "Same Title"))
    b = storage.upsert_article(_raw("https://example.com/b", "Same Title"))
    assert a != b
    assert storage.list_articles()["total"] == 2


def test_list_articles_filters_by_status_and_query(storage):
    storage.upsert_article(_raw("https://example.com/a", "Attention Piece"))
    storage.upsert_article(_raw("https://example.com/b", "Power Grid"))
    storage.update_status(storage.get_article_by_hash(url_hash("https://example.com/b"))["id"], "shortlisted")

    fetched = storage.list_articles(status="fetched")
    assert fetched["total"] == 1
    assert "Attention" in fetched["items"][0]["title"]

    short = storage.list_articles(status="shortlisted")
    assert short["total"] == 1

    found = storage.list_articles(q="power")
    assert found["total"] == 1


def test_count_by_status_and_dashboard(storage):
    storage.upsert_article(_raw("https://example.com/a"))
    stats = storage.dashboard_stats()
    assert stats["total"] == 1
    assert stats["fetched"] == 1


# ---------------------------------------------------------------------------
# 去重双检
# ---------------------------------------------------------------------------


def test_known_hashes_merges_index_and_db(storage):
    raw = _raw("https://example.com/db-only")
    storage.upsert_article(raw)

    # 只在 index.json 里的条目
    storage.save_index(
        [
            {
                "id": "idx-1",
                "url_hash": url_hash("https://example.com/index-only"),
                "canonical_url": "https://example.com/index-only",
                "title": "Index Only",
            }
        ]
    )
    hashes = storage.get_known_url_hashes()
    assert url_hash("https://example.com/db-only") in hashes
    assert url_hash("https://example.com/index-only") in hashes


def test_known_hashes_derives_hash_from_canonical_url(storage):
    storage.save_index([{"id": "x", "canonical_url": "https://example.com/derived", "title": "T"}])
    assert url_hash("https://example.com/derived") in storage.get_known_url_hashes()


def test_no_duplicate_on_repeated_upsert_of_same_canonical(storage):
    """模拟连续两次全源采集：同一 URL 只留一条记录。"""

    for _ in range(3):
        storage.upsert_article(_raw("https://example.com/same?utm_source=x"))
    assert storage.list_articles()["total"] == 1


# ---------------------------------------------------------------------------
# 发布资产
# ---------------------------------------------------------------------------


def test_export_parsed_article_writes_files(storage):
    parsed = _parsed()
    path = storage.export_parsed_article(parsed)

    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == parsed.id
    assert data["vocab"][0]["term"] == "hello"

    index = storage.load_index()
    assert len(index) == 1
    assert index[0]["id"] == parsed.id
    assert index[0]["vocab_count"] == 1


def test_export_parsed_article_is_atomic_no_tmp_left(storage):
    storage.export_parsed_article(_parsed())
    leftovers = list(storage.parsed_dir.glob("*.tmp")) + list(storage.parsed_dir.parent.glob("*.tmp"))
    assert leftovers == []


def test_upsert_index_entry_replaces_existing(storage):
    storage.export_parsed_article(_parsed("id-1"))
    parsed = _parsed("id-1")
    parsed.title = "New Title"
    storage.export_parsed_article(parsed)
    index = storage.load_index()
    assert len(index) == 1
    assert index[0]["title"] == "New Title"


def test_remove_index_entry(storage):
    storage.export_parsed_article(_parsed("id-1"))
    storage.remove_index_entry("id-1")
    assert storage.load_index() == []


def test_iter_parsed_articles_skips_broken_files(storage):
    storage.export_parsed_article(_parsed("good"))
    (storage.parsed_dir / "broken.json").write_text("{not valid json", encoding="utf-8")
    items = storage.iter_parsed_articles()
    assert len(items) == 1
    assert items[0].id == "good"


# ---------------------------------------------------------------------------
# 双向同步
# ---------------------------------------------------------------------------


def test_sync_git_assets_to_db_backfills_cloud_articles(storage):
    """模拟 Actions 回写后本地 pull：index + parsed → 本地 DB。"""

    parsed = _parsed("cloud-article")
    storage.export_parsed_article(parsed)

    # 清空 DB 模拟"本地从未见过云端文章"
    with storage.connect() as conn:
        conn.execute("DELETE FROM articles")

    stats = storage.sync_git_assets_to_db()
    assert stats["inserted"] == 1

    row = storage.get_article("cloud-article")
    assert row is not None
    assert row["status"] == "published"
    assert row["title"] == "A Title"


def test_sync_git_assets_to_db_is_idempotent(storage):
    storage.export_parsed_article(_parsed("cloud-article"))
    storage.sync_git_assets_to_db()
    stats = storage.sync_git_assets_to_db()
    assert stats["inserted"] == 0
    assert stats["updated"] == 1
    assert storage.list_articles()["total"] == 1


def test_sync_git_assets_repairs_missing_index_entries_only_when_asked(storage):
    """有 parsed 文件但 index.json 丢条目：默认视为「已下线」，不自动恢复上线。"""

    storage.export_parsed_article(_parsed("orphan"))
    storage.save_index([])  # 人为清空 index（等价于后台点了「下线」）

    stats = storage.sync_git_assets_to_db()
    assert stats["skipped"] == 1
    assert stats["backfilled"] == 0
    assert storage.load_index() == []
    # 但资产仍应进入本地候选池，状态 parsed，可随时重新上线
    row = storage.get_article("orphan")
    assert row is not None
    assert row["status"] == "parsed"


def test_sync_git_assets_backfill_when_explicitly_requested(storage):
    storage.export_parsed_article(_parsed("orphan"))
    storage.save_index([])

    stats = storage.sync_git_assets_to_db(backfill_index=True)
    assert stats["backfilled"] == 1
    assert {e["id"] for e in storage.load_index()} == {"orphan"}


def test_sync_db_to_index_adds_missing(storage):
    storage.export_parsed_article(_parsed("a1"))
    storage.save_index([])
    result = storage.sync_db_to_index()
    assert result["added"] == 1
    assert len(storage.load_index()) == 1


# ---------------------------------------------------------------------------
# 源
# ---------------------------------------------------------------------------


def test_sync_sources_adds_and_removes(storage):
    s1 = SourceConfig(id="s1", name="S1", url="https://e.com/1")
    s2 = SourceConfig(id="s2", name="S2", url="https://e.com/2")
    storage.sync_sources([s1, s2])
    assert len(storage.list_source_health()) == 2

    storage.sync_sources([s1])
    health = storage.list_source_health()
    assert len(health) == 1
    assert health[0].id == "s1"


def test_record_source_result_tracks_failures(storage):
    s1 = SourceConfig(id="s1", name="S1", url="https://e.com/1")
    storage.upsert_source(s1)
    storage.record_source_result("s1", ok=True, latency_ms=100)
    health = storage.list_source_health()[0]
    assert health.consecutive_failures == 0
    assert health.last_status == "ok"

    storage.record_source_result("s1", ok=False)
    storage.record_source_result("s1", ok=False)
    storage.record_source_result("s1", ok=False)
    health = storage.list_source_health()[0]
    assert health.consecutive_failures == 3
    assert health.status_color == "error"


# ---------------------------------------------------------------------------
# 采集任务
# ---------------------------------------------------------------------------


def test_crawl_run_lifecycle(storage):
    from src.models import CrawlRunResult

    run_id = storage.start_run("manual")
    result = CrawlRunResult(trigger_type="manual", discovered_count=10, fetched_count=4)
    storage.finish_run(run_id, result)

    runs = storage.list_runs()
    assert runs[0]["id"] == run_id
    assert runs[0]["fetched_count"] == 4
    assert storage.count_runs() == 1
