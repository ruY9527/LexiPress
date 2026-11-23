"""LexiPress 双层存储层。

设计要点（对应 `plan/04` 第 1.1 / 1.5 节）：
1. **本地管理库** `data/lexipress.db`（SQLite，WAL + busy_timeout=5000），不提交 Git。
2. **发布真理源** `data/index.json` + `data/parsed/*.json`，提交 Git，是 GitHub Actions 的唯一依据。
3. `sync_git_assets_to_db()` 在本地启动时把云端新增文章 UPSERT 回本地库，形成双向闭环。
4. 所有 JSON 落盘均为「写 .tmp → os.replace」原子替换。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .config import (
    DB_FILE,
    INDEX_FILE,
    PARSED_DIR,
    atomic_write_json,
    ensure_dirs,
    load_settings,
)
from .models import (
    ArticleIndexEntry,
    ArticleStatus,
    CrawlRunResult,
    ParsedArticle,
    RawArticle,
    SourceConfig,
    SourceHealth,
)
from .utils import iso_now, slugify, url_hash

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'rss',
    url TEXT DEFAULT '',
    category TEXT DEFAULT 'General',
    weight REAL DEFAULT 0.85,
    enabled INTEGER DEFAULT 1,
    min_score INTEGER DEFAULT 180,
    "limit" INTEGER DEFAULT 20,
    last_fetch_at TEXT,
    last_status TEXT DEFAULT 'unknown',
    consecutive_failures INTEGER DEFAULT 0,
    avg_latency_ms REAL DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger_type TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'running',
    discovered_count INTEGER DEFAULT 0,
    fetched_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    paywalled_count INTEGER DEFAULT 0,
    summary_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    url_hash TEXT NOT NULL UNIQUE,
    canonical_url TEXT NOT NULL,
    source_id TEXT DEFAULT '',
    source_name TEXT DEFAULT '',
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    published_at TEXT DEFAULT '',
    fetched_at TEXT DEFAULT '',
    cover_image TEXT DEFAULT '',
    word_count INTEGER DEFAULT 0,
    read_time_min INTEGER DEFAULT 0,
    score REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'fetched',
    error_message TEXT DEFAULT '',
    raw_paragraphs_json TEXT DEFAULT '[]',
    tags_json TEXT DEFAULT '[]',
    parsed_json_path TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(score DESC);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class Storage:
    """SQLite + JSON 双层存储管理器。"""

    def __init__(self, db_path: Path | None = None, index_path: Path | None = None, parsed_dir: Path | None = None):
        ensure_dirs()
        settings = load_settings()
        self.site = settings.site
        self.db_path = Path(db_path) if db_path else DB_FILE
        self.index_path = Path(index_path) if index_path else INDEX_FILE
        self.parsed_dir = Path(parsed_dir) if parsed_dir else PARSED_DIR
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()

    # ------------------------------------------------------------------
    # 连接与建表
    # ------------------------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = _connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # 源（sources）
    # ------------------------------------------------------------------

    def upsert_source(self, src: SourceConfig) -> None:
        now = iso_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sources (id, name, type, url, category, weight, enabled, min_score, "limit", updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    type=excluded.type,
                    url=excluded.url,
                    category=excluded.category,
                    weight=excluded.weight,
                    enabled=excluded.enabled,
                    min_score=excluded.min_score,
                    "limit"=excluded."limit",
                    updated_at=excluded.updated_at
                """,
                (
                    src.id,
                    src.name,
                    src.type.value,
                    src.url,
                    src.category,
                    float(src.weight),
                    1 if src.enabled else 0,
                    int(src.min_score),
                    int(src.limit),
                    now,
                ),
            )

    def sync_sources(self, sources: Sequence[SourceConfig]) -> None:
        """让 DB 的 sources 表与 feeds.yaml 保持一致（不删除运行指标）。"""

        keep = {s.id for s in sources}
        for src in sources:
            self.upsert_source(src)
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM sources").fetchall()
            for row in rows:
                if row["id"] not in keep:
                    conn.execute("DELETE FROM sources WHERE id = ?", (row["id"],))

    def record_source_result(
        self,
        source_id: str,
        *,
        ok: bool,
        latency_ms: float = 0.0,
        message: str = "",
    ) -> None:
        now = iso_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT consecutive_failures, avg_latency_ms FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            failures = int(row["consecutive_failures"]) if row else 0
            avg = float(row["avg_latency_ms"]) if row else 0.0
            new_failures = 0 if ok else failures + 1
            new_avg = round((avg * 0.7 + float(latency_ms) * 0.3), 1) if latency_ms else avg
            conn.execute(
                """
                UPDATE sources
                   SET last_fetch_at = ?, last_status = ?, consecutive_failures = ?, avg_latency_ms = ?
                 WHERE id = ?
                """,
                (now, "ok" if ok else "error", new_failures, new_avg, source_id),
            )
        if message:
            _ = message  # 错误详情由 crawl_runs.summary_json 承载

    def list_source_health(self) -> list[SourceHealth]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*, (SELECT COUNT(*) FROM articles a WHERE a.source_id = s.id) AS article_count
                  FROM sources s ORDER BY s.weight DESC, s.name ASC
                """
            ).fetchall()
        out: list[SourceHealth] = []
        for row in rows:
            out.append(
                SourceHealth(
                    id=row["id"],
                    name=row["name"],
                    type=row["type"],
                    url=row["url"] or "",
                    category=row["category"] or "General",
                    weight=float(row["weight"] or 0.0),
                    enabled=bool(row["enabled"]),
                    min_score=int(row["min_score"] or 180),
                    limit=int(row["limit"] or 20),
                    last_fetch_at=row["last_fetch_at"],
                    last_status=row["last_status"] or "unknown",
                    consecutive_failures=int(row["consecutive_failures"] or 0),
                    avg_latency_ms=float(row["avg_latency_ms"] or 0.0),
                    article_count=int(row["article_count"] or 0),
                )
            )
        return out

    # ------------------------------------------------------------------
    # 采集任务（crawl_runs）
    # ------------------------------------------------------------------

    def start_run(self, trigger_type: str) -> int:
        """新建一次采集任务；同时把历史上残留的 running 记录收尾。

        进程被强杀时 `crawl_runs` 会留下 status='running' 的孤儿行，
        启动新任务时统一标记为 interrupted，避免仪表盘长期显示「进行中」。
        """

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_runs
                   SET status = 'interrupted',
                       finished_at = COALESCE(finished_at, ?)
                 WHERE status = 'running'
                """,
                (iso_now(),),
            )
            cur = conn.execute(
                "INSERT INTO crawl_runs (started_at, trigger_type, status) VALUES (?, ?, 'running')",
                (iso_now(), trigger_type),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, result: CrawlRunResult) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_runs
                   SET finished_at = ?, status = ?, discovered_count = ?, fetched_count = ?,
                       failed_count = ?, skipped_count = ?, paywalled_count = ?, summary_json = ?
                 WHERE id = ?
                """,
                (
                    result.finished_at or iso_now(),
                    result.status,
                    result.discovered_count,
                    result.fetched_count,
                    result.failed_count,
                    result.skipped_count,
                    result.paywalled_count,
                    json.dumps(result.summary, ensure_ascii=False),
                    run_id,
                ),
            )

    def list_runs(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_runs(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM crawl_runs").fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------
    # 文章（articles）
    # ------------------------------------------------------------------

    def url_hash_exists(self, h: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM articles WHERE url_hash = ? LIMIT 1", (h,)).fetchone()
        return row is not None

    def get_known_url_hashes(self) -> set[str]:
        """去重双检：`index.json` ∪ SQLite。"""

        hashes: set[str] = set()
        for entry in self.load_index():
            h = entry.get("url_hash") or (url_hash(entry.get("canonical_url", "")) if entry.get("canonical_url") else "")
            if h:
                hashes.add(h)
        with self.connect() as conn:
            for row in conn.execute("SELECT url_hash FROM articles").fetchall():
                hashes.add(row["url_hash"])
        return hashes

    def make_article_id(self, published_at: str, source_name: str, title: str) -> str:
        day = (published_at or date.today().isoformat())[:10]
        src = slugify(source_name, fallback="source")
        slug = slugify(title, fallback="article")
        base = f"{day}-{src}-{slug}"[:90].strip("-")
        candidate = base
        n = 2
        with self.connect() as conn:
            while conn.execute("SELECT 1 FROM articles WHERE id = ? LIMIT 1", (candidate,)).fetchone():
                candidate = f"{base}-{n}"
                n += 1
        return candidate

    def upsert_article(self, article: RawArticle, status: ArticleStatus | None = None) -> str:
        """插入或更新候选文章，返回文章 id。"""

        now = iso_now()
        status_value = (status or article.status).value
        article_id = article.id or self.make_article_id(
            article.published_at, article.source_name, article.title
        )
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM articles WHERE url_hash = ?", (article.url_hash,)
            ).fetchone()
            if existing:
                article_id = existing["id"]
                conn.execute(
                    """
                    UPDATE articles
                       SET title = ?, author = ?, published_at = ?, fetched_at = ?, cover_image = ?,
                           word_count = ?, read_time_min = ?, score = ?, status = ?, error_message = ?,
                           raw_paragraphs_json = ?, tags_json = ?, source_id = ?, source_name = ?,
                           canonical_url = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (
                        article.title,
                        article.author,
                        article.published_at,
                        article.fetched_at or now,
                        article.cover_image,
                        article.word_count,
                        article.read_time_min,
                        float(article.score),
                        status_value,
                        article.error_message,
                        json.dumps(article.paragraphs, ensure_ascii=False),
                        json.dumps(article.tags, ensure_ascii=False),
                        article.source_id,
                        article.source_name,
                        article.canonical_url,
                        now,
                        article_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO articles (
                        id, url_hash, canonical_url, source_id, source_name, title, author,
                        published_at, fetched_at, cover_image, word_count, read_time_min, score,
                        status, error_message, raw_paragraphs_json, tags_json, parsed_json_path,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                    """,
                    (
                        article_id,
                        article.url_hash,
                        article.canonical_url,
                        article.source_id,
                        article.source_name,
                        article.title,
                        article.author,
                        article.published_at,
                        article.fetched_at or now,
                        article.cover_image,
                        article.word_count,
                        article.read_time_min,
                        float(article.score),
                        status_value,
                        article.error_message,
                        json.dumps(article.paragraphs, ensure_ascii=False),
                        json.dumps(article.tags, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
        article.id = article_id
        return article_id

    def _row_to_article(self, row: sqlite3.Row, with_paragraphs: bool = True) -> dict[str, Any]:
        data = dict(row)
        paragraphs = json.loads(data.pop("raw_paragraphs_json", "[]") or "[]")
        tags = json.loads(data.pop("tags_json", "[]") or "[]")
        data["tags"] = tags
        data["paragraphs"] = paragraphs if with_paragraphs else []
        data["paragraph_count"] = len(paragraphs)
        data["preview"] = (paragraphs[0][:220] if paragraphs else "")
        data["status_label"] = _STATUS_LABELS.get(data.get("status", ""), data.get("status", ""))
        return data

    def get_article(self, article_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return self._row_to_article(row) if row else None

    def get_article_by_hash(self, h: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE url_hash = ?", (h,)).fetchone()
        return self._row_to_article(row) if row else None

    def list_articles(
        self,
        *,
        status: str | None = None,
        source_id: str | None = None,
        q: str | None = None,
        sort: str = "score",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []
        if status and status != "all":
            if status == "error":
                where.append("status IN ('failed','paywalled')")
            else:
                where.append("status = ?")
                params.append(status)
        if source_id and source_id != "all":
            where.append("source_id = ?")
            params.append(source_id)
        if q:
            where.append("(LOWER(title) LIKE ? OR LOWER(source_name) LIKE ?)")
            like = f"%{q.lower()}%"
            params.extend([like, like])

        clause = ("WHERE " + " AND ".join(where)) if where else ""
        order = {
            "score": "score DESC, published_at DESC",
            "published": "published_at DESC, score DESC",
            "words": "word_count DESC",
            "recent": "fetched_at DESC",
            "title": "title ASC",
        }.get(sort, "score DESC, published_at DESC")

        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        offset = (page - 1) * page_size

        with self.connect() as conn:
            total_row = conn.execute(f"SELECT COUNT(*) AS c FROM articles {clause}", params).fetchone()
            rows = conn.execute(
                f"SELECT * FROM articles {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()

        items = [self._row_to_article(r, with_paragraphs=False) for r in rows]
        total = int(total_row["c"]) if total_row else 0
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    def update_status(self, article_id: str, status: str, error_message: str = "") -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE articles SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (status, error_message, iso_now(), article_id),
            )
            return cur.rowcount > 0

    def set_parsed_path(self, article_id: str, path: str, status: str = "parsed") -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE articles SET parsed_json_path = ?, status = ?, updated_at = ? WHERE id = ?",
                (path, status, iso_now(), article_id),
            )

    def delete_article(self, article_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
            return cur.rowcount > 0

    def count_by_status(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS c FROM articles GROUP BY status").fetchall()
        return {row["status"]: int(row["c"]) for row in rows}

    def today_new_count(self) -> int:
        prefix = date.today().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM articles WHERE substr(fetched_at,1,10) = ?", (prefix,)
            ).fetchone()
        return int(row["c"]) if row else 0

    def dashboard_stats(self) -> dict[str, Any]:
        status_counts = self.count_by_status()
        health = self.list_source_health()
        healthy = sum(1 for s in health if s.status_color == "ok")
        return {
            "today_new": self.today_new_count(),
            "shortlisted": status_counts.get("shortlisted", 0),
            "parsed": status_counts.get("parsed", 0),
            "published": status_counts.get("published", 0),
            "fetched": status_counts.get("fetched", 0),
            "rejected": status_counts.get("rejected", 0),
            "failed": status_counts.get("failed", 0) + status_counts.get("paywalled", 0),
            "total": sum(status_counts.values()),
            "sources_total": len(health),
            "sources_healthy": healthy,
            "status_counts": status_counts,
        }

    # ------------------------------------------------------------------
    # 发布资产：index.json + parsed/<id>.json
    # ------------------------------------------------------------------

    def load_index(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(data, dict):
            items = data.get("articles") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        return [i for i in items if isinstance(i, dict)]

    def save_index(self, entries: Iterable[dict[str, Any]]) -> None:
        items = sorted(
            entries,
            key=lambda e: (str(e.get("published_at") or ""), float(e.get("score") or 0)),
            reverse=True,
        )
        payload = {
            "generated_at": iso_now(),
            "count": len(items),
            "articles": items,
        }
        atomic_write_json(self.index_path, payload)

    def upsert_index_entry(self, entry: ArticleIndexEntry) -> None:
        entries = self.load_index()
        payload = entry.model_dump(mode="json")
        replaced = False
        for idx, existing in enumerate(entries):
            if existing.get("id") == entry.id:
                entries[idx] = payload
                replaced = True
                break
        if not replaced:
            entries.append(payload)
        self.save_index(entries)

    def remove_index_entry(self, article_id: str) -> None:
        entries = [e for e in self.load_index() if e.get("id") != article_id]
        self.save_index(entries)

    def parsed_path_for(self, article_id: str) -> Path:
        return self.parsed_dir / f"{article_id}.json"

    def export_parsed_article(self, article: ParsedArticle) -> Path:
        """原子写入 `data/parsed/<id>.json` 并更新 `data/index.json`。"""

        payload = article.model_dump(mode="json")
        path = self.parsed_path_for(article.id)
        atomic_write_json(path, payload)

        entry = ArticleIndexEntry(
            id=article.id,
            url_hash=article.url_hash,
            canonical_url=article.original_url,
            title=article.title,
            source=article.source,
            source_id=article.source_id,
            published_at=article.published_at,
            updated_at=iso_now(),
            score=article.score,
            difficulty=article.difficulty,
            word_count=article.word_count,
            read_time_min=article.read_time_min,
            tags=article.tags,
            cover_image=article.cover_image,
            vocab_count=len(article.vocab),
            parser_mode=article.parser_mode,
        )
        self.upsert_index_entry(entry)
        return path

    def load_parsed(self, article_id: str) -> dict[str, Any] | None:
        path = self.parsed_path_for(article_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def iter_parsed_articles(self) -> list[ParsedArticle]:
        """读取所有合法的 `data/parsed/*.json`（坏文件跳过并记录）。"""

        out: list[ParsedArticle] = []
        for path in sorted(self.parsed_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                out.append(ParsedArticle(**data))
            except Exception:  # noqa: BLE001 - 单个坏缓存不应阻断构建
                continue
        return out

    def delete_parsed(self, article_id: str) -> None:
        path = self.parsed_path_for(article_id)
        if path.exists():
            path.unlink()
        self.remove_index_entry(article_id)

    # ------------------------------------------------------------------
    # 双向同步
    # ------------------------------------------------------------------

    def sync_git_assets_to_db(self, *, backfill_index: bool = False) -> dict[str, int]:
        """把 `index.json` + `parsed/*.json` 回填到本地 SQLite（云端 → 本地）。

        方向是单向的：index.json 是发布真理源，DB 只是本地候选池。
        默认 **不** 把「有 parsed 文件但不在 index 中」的文章补进 index，
        否则后台的「下线」操作会在下次启动时被自动撤销。
        需要恢复这些离线资产时，显式调用 `backfill_index=True`（或 `sync_db_to_index()`）。

        幂等：已存在的 url_hash 仅做状态与路径更新，不会重复插入。
        """

        stats = {"index_entries": 0, "parsed_files": 0, "inserted": 0, "updated": 0, "skipped": 0, "backfilled": 0}
        index_entries = self.load_index()
        stats["index_entries"] = len(index_entries)

        parsed_map: dict[str, dict[str, Any]] = {}
        for path in sorted(self.parsed_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(data, dict) and data.get("id"):
                parsed_map[data["id"]] = data
        stats["parsed_files"] = len(parsed_map)

        seen_ids: set[str] = set()
        for entry in index_entries:
            aid = str(entry.get("id") or "")
            if not aid:
                continue
            seen_ids.add(aid)
            parsed = parsed_map.get(aid, {})
            paragraphs = [p.get("en", "") for p in parsed.get("paragraphs", []) if isinstance(p, dict)]
            word_count = int(entry.get("word_count") or parsed.get("word_count") or 0)
            if not word_count and paragraphs:
                from .utils import count_words

                word_count = count_words(" ".join(paragraphs))
            canonical = str(entry.get("canonical_url") or parsed.get("original_url") or "")
            h = str(entry.get("url_hash") or (url_hash(canonical) if canonical else ""))
            if not h:
                h = url_hash(f"lexipress://{aid}")
            parsed_rel = str(self.parsed_path_for(aid).relative_to(self.parsed_dir.parent.parent)) if self.parsed_path_for(aid).exists() else ""

            now = iso_now()
            with self.connect() as conn:
                existing = conn.execute("SELECT id, status FROM articles WHERE url_hash = ?", (h,)).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE articles SET id = ?, title = ?, source_name = ?, published_at = ?,
                               word_count = ?, read_time_min = ?, score = ?, status = ?,
                               parsed_json_path = ?, canonical_url = ?, cover_image = ?, tags_json = ?,
                               updated_at = ?
                         WHERE url_hash = ?
                        """,
                        (
                            aid,
                            str(entry.get("title") or parsed.get("title") or aid),
                            str(entry.get("source") or parsed.get("source") or ""),
                            str(entry.get("published_at") or parsed.get("published_at") or ""),
                            word_count,
                            int(entry.get("read_time_min") or parsed.get("read_time_min") or 0),
                            float(entry.get("score") or parsed.get("score") or 0.0),
                            ArticleStatus.PUBLISHED.value,
                            parsed_rel,
                            canonical,
                            str(entry.get("cover_image") or parsed.get("cover_image") or ""),
                            json.dumps(entry.get("tags") or parsed.get("tags") or [], ensure_ascii=False),
                            now,
                            h,
                        ),
                    )
                    stats["updated"] += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO articles (
                            id, url_hash, canonical_url, source_id, source_name, title, author,
                            published_at, fetched_at, cover_image, word_count, read_time_min, score,
                            status, error_message, raw_paragraphs_json, tags_json, parsed_json_path,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
                        """,
                        (
                            aid,
                            h,
                            canonical,
                            str(entry.get("source_id") or parsed.get("source_id") or ""),
                            str(entry.get("source") or parsed.get("source") or ""),
                            str(entry.get("title") or parsed.get("title") or aid),
                            str(parsed.get("author") or ""),
                            str(entry.get("published_at") or parsed.get("published_at") or ""),
                            now,
                            str(entry.get("cover_image") or parsed.get("cover_image") or ""),
                            word_count,
                            int(entry.get("read_time_min") or parsed.get("read_time_min") or 0),
                            float(entry.get("score") or parsed.get("score") or 0.0),
                            ArticleStatus.PUBLISHED.value,
                            json.dumps(paragraphs, ensure_ascii=False),
                            json.dumps(entry.get("tags") or parsed.get("tags") or [], ensure_ascii=False),
                            parsed_rel,
                            now,
                            now,
                        ),
                    )
                    stats["inserted"] += 1

        # 有 parsed 文件但 index 里缺失的：默认视为「已下线」，不自动恢复上线。
        missing = [aid for aid in parsed_map if aid not in seen_ids]
        stats["skipped"] = len(missing)
        if backfill_index:
            for aid in missing:
                try:
                    parsed_obj = ParsedArticle(**parsed_map[aid])
                except Exception:  # noqa: BLE001
                    continue
                self.export_parsed_article(parsed_obj)
                stats["backfilled"] += 1

        # 同时把这些资产记录进本地 DB（状态 parsed，可随时在后台一键上线）
        for aid in missing:
            if self.get_article(aid):
                with self.connect() as conn:
                    conn.execute(
                        "UPDATE articles SET status = ?, parsed_json_path = ?, updated_at = ? WHERE id = ?",
                        (
                            ArticleStatus.PARSED.value,
                            str(self.parsed_path_for(aid)),
                            iso_now(),
                            aid,
                        ),
                    )
                continue
            parsed = parsed_map[aid]
            paragraphs = [p.get("en", "") for p in parsed.get("paragraphs", []) if isinstance(p, dict)]
            canonical = str(parsed.get("original_url") or "")
            h = url_hash(canonical) if canonical else url_hash(f"lexipress://{aid}")
            now = iso_now()
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO articles (
                        id, url_hash, canonical_url, source_id, source_name, title, author,
                        published_at, fetched_at, cover_image, word_count, read_time_min, score,
                        status, error_message, raw_paragraphs_json, tags_json, parsed_json_path,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
                    """,
                    (
                        aid,
                        h,
                        canonical,
                        str(parsed.get("source_id") or ""),
                        str(parsed.get("source") or ""),
                        str(parsed.get("title") or aid),
                        str(parsed.get("author") or ""),
                        str(parsed.get("published_at") or ""),
                        now,
                        str(parsed.get("cover_image") or ""),
                        int(parsed.get("word_count") or 0),
                        int(parsed.get("read_time_min") or 0),
                        float(parsed.get("score") or 0.0),
                        ArticleStatus.PARSED.value,
                        json.dumps(paragraphs, ensure_ascii=False),
                        json.dumps(parsed.get("tags") or [], ensure_ascii=False),
                        str(self.parsed_path_for(aid)),
                        now,
                        now,
                    ),
                )

        return stats

    def sync_db_to_index(self) -> dict[str, int]:
        """把 DB 中已发布但 index 缺失的记录补写回 `index.json`（本地 → 云端）。"""

        added = 0
        known = {e.get("id") for e in self.load_index()}
        parsed_articles = self.iter_parsed_articles()
        for article in parsed_articles:
            if article.id not in known:
                self.export_parsed_article(article)
                added += 1
        return {"added": added}


_STATUS_LABELS = {
    "discovered": "已发现",
    "fetched": "新抓取",
    "shortlisted": "已精选",
    "parsed": "已解析",
    "published": "已发布",
    "rejected": "已淘汰",
    "paywalled": "付费墙",
    "failed": "抓取失败",
}

STATUS_LABELS = _STATUS_LABELS


def now_utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()
