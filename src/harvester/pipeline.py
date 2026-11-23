"""采集流水线：并发发现 → 双重去重 → 正文抽取 → 初筛打分 → 入库。

关键约定（对应 `plan/03` 第 2.2 节与 `plan/04` 第 1.1 节）：
- 去重集合 = `data/index.json` 的 url_hash ∪ SQLite `articles.url_hash`（Actions 无 DB 时同样幂等）。
- 单源失败隔离：任一源超时／403／XML 异常不影响其它源。
- 所有步骤通过 `log()` 广播到 SSE 日志流。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import httpx

from ..config import ensure_dirs, load_feeds, load_settings
from ..models import (
    ArticleStatus,
    CrawlRunResult,
    RawArticle,
    SourceConfig,
    SourceTestResult,
    SourceType,
    TriggerType,
)
from ..storage import Storage
from ..utils import (
    count_words,
    format_date_iso,
    is_probably_article_url,
    iso_now,
    normalize_url,
    read_time_minutes,
    url_hash as compute_url_hash,
)
from .base import LOG_BUS, DiscoveryItem, log, make_client
from .extractor import ExtractResult, extract_article
from .hackernews import HackerNewsAdapter
from .rss import RSSAdapter


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------


def freshness_score(published_at: str, now: datetime | None = None) -> float:
    """24h 内 1.0；48h 内 0.8；72h 内 0.6；更早线性衰减到 0（120h 后）。"""

    from ..utils import parse_datetime_loose

    dt = parse_datetime_loose(published_at)
    if dt is None:
        return 0.5
    now = now or datetime.now(timezone.utc)
    hours = max((now - dt).total_seconds() / 3600.0, 0.0)
    if hours <= 24:
        return 1.0
    if hours <= 48:
        return 0.8
    if hours <= 72:
        return 0.6
    if hours >= 168:
        return 0.0
    # 72h → 168h 线性衰减 0.6 → 0.0
    return round(0.6 * (1 - (hours - 72) / (168 - 72)), 3)


def length_fit_score(word_count: int, ideal: tuple[int, int] = (800, 2800)) -> float:
    """篇幅适配度：理想区间满分；过短/过长递减。"""

    lo, hi = ideal
    wc = max(0, int(word_count))
    if wc <= 0:
        return 0.0
    if lo <= wc <= hi:
        return 1.0
    if wc < 500:
        return 0.15
    if wc < lo:
        # 500 → lo 线性 0.55 → 1.0
        span = max(lo - 500, 1)
        return round(0.55 + 0.45 * (wc - 500) / span, 3)
    if wc <= 4500:
        # hi → 4500 线性 1.0 → 0.42
        span = max(4500 - hi, 1)
        return round(1.0 - 0.58 * (wc - hi) / span, 3)
    return 0.2


def compute_score(
    source_weight: float,
    published_at: str,
    word_count: int,
    *,
    weights: tuple[float, float, float] = (4.0, 3.0, 3.0),
    ideal: tuple[int, int] = (800, 2800),
) -> float:
    """综合初筛分：`clip(w_src*source + w_fresh*freshness + w_len*length, 0, 10)`。"""

    w_src, w_fresh, w_len = weights
    raw = (
        float(source_weight) * w_src
        + freshness_score(published_at) * w_fresh
        + length_fit_score(word_count, ideal) * w_len
    )
    return round(max(0.0, min(10.0, raw)), 2)


# ---------------------------------------------------------------------------
# 适配器工厂
# ---------------------------------------------------------------------------


def build_adapter(config: SourceConfig, settings, client: httpx.AsyncClient):
    if config.type is SourceType.HACKERNEWS:
        return HackerNewsAdapter(config, settings, client=client)
    return RSSAdapter(config, settings, client=client)


# ---------------------------------------------------------------------------
# 流水线
# ---------------------------------------------------------------------------


@dataclass
class PipelineOptions:
    trigger_type: TriggerType = TriggerType.MANUAL
    source_ids: list[str] = field(default_factory=list)
    dry_run: bool = False
    limit_per_source: int | None = None
    include_disabled: bool = False


class HarvesterPipeline:
    """多源外刊采集调度器。"""

    def __init__(self, storage: Storage | None = None, settings=None):
        ensure_dirs()
        self.settings = settings or load_settings()
        self.storage = storage or Storage()
        self._semaphore = asyncio.Semaphore(max(1, self.settings.harvester.max_concurrency))

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def run_all(
        self,
        trigger_type: str = "manual",
        log_cb: Callable[[dict[str, Any]], Any] | None = None,
        source_ids: Iterable[str] | None = None,
    ) -> CrawlRunResult:
        """全源（或指定源）采集。"""

        started = time.monotonic()
        sources = self._load_sources(include_disabled=False)
        wanted = {s for s in (source_ids or [])}
        if wanted:
            sources = [s for s in sources if s.id in wanted]

        result = CrawlRunResult(
            trigger_type=TriggerType(trigger_type),
            started_at=iso_now(),
            status="running",
        )
        run_id = self.storage.start_run(trigger_type)
        result.run_id = run_id
        log("INFO", f"采集任务 #{run_id} 启动，共 {len(sources)} 个源", scope="pipeline")

        if not sources:
            result.status = "ok"
            result.finished_at = iso_now()
            result.duration_sec = round(time.monotonic() - started, 2)
            result.summary = {"note": "没有启用的采集源"}
            self.storage.finish_run(run_id, result)
            log("WARN", "没有启用的采集源，任务结束", scope="pipeline")
            return result

        known_hashes = self.storage.get_known_url_hashes()
        log("INFO", f"已知 url_hash {len(known_hashes)} 条（index.json ∪ SQLite）", scope="pipeline")

        per_source: dict[str, dict[str, Any]] = {}
        all_articles: list[RawArticle] = []
        total_sources = len(sources)
        done = 0

        async with make_client(self.settings) as client:
            for src in sources:
                done += 1
                progress = round(done / total_sources * 100, 1)
                log(
                    "INFO",
                    f"[{done}/{total_sources}] 采集源：{src.name}（{src.type.value}）",
                    scope="pipeline",
                    progress=progress,
                )
                src_started = time.monotonic()
                try:
                    async with self._semaphore:
                        adapter = build_adapter(src, self.settings, client)
                        discovery_started = time.monotonic()
                        items = await adapter.discover()
                        latency_ms = (time.monotonic() - discovery_started) * 1000.0
                    self.storage.record_source_result(src.id, ok=True, latency_ms=latency_ms)
                    log(
                        "INFO",
                        f"  ↳ {src.name} 发现 {len(items)} 条候选（{latency_ms:.0f}ms）",
                        scope="pipeline",
                        progress=progress,
                    )
                except Exception as exc:  # noqa: BLE001 - 单源失败隔离
                    self.storage.record_source_result(src.id, ok=False)
                    per_source[src.id] = {"status": "error", "error": str(exc), "discovered": 0, "fetched": 0}
                    log("ERROR", f"  ↳ {src.name} 采集失败：{exc}", scope="pipeline", progress=progress)
                    result.failed_count += 1
                    continue

                result.discovered_count += len(items)
                fetched_here = 0
                skipped_here = 0
                failed_here = 0

                for item in items:
                    canonical = normalize_url(item.url)
                    if not canonical or not is_probably_article_url(canonical):
                        skipped_here += 1
                        continue
                    h = compute_url_hash(canonical)
                    if h in known_hashes:
                        skipped_here += 1
                        continue
                    known_hashes.add(h)  # 本轮内二次去重

                    try:
                        extracted = await self._extract_one(client, item, src)
                    except Exception as exc:  # noqa: BLE001
                        extracted = ExtractResult(status="failed", error_message=str(exc), title=item.title)

                    article = self._to_article(item, src, extracted)
                    all_articles.append(article)
                    self.storage.upsert_article(article, ArticleStatus(extracted.status))

                    if extracted.status == "fetched":
                        fetched_here += 1
                        log(
                            "INFO",
                            f"     ✓ {extracted.word_count} 词 · {article.score:.2f} 分 · {article.title[:64]}",
                            scope="pipeline",
                        )
                    elif extracted.status == "paywalled":
                        result.paywalled_count += 1
                        failed_here += 1
                        log("WARN", f"     ⊘ 付费墙：{item.title[:60]}", scope="pipeline")
                    else:
                        failed_here += 1
                        log(
                            "WARN",
                            f"     ✗ 抽取失败：{item.title[:60]}（{extracted.error_message or '未知'}）",
                            scope="pipeline",
                        )

                result.fetched_count += fetched_here
                result.skipped_count += skipped_here
                result.failed_count += failed_here
                per_source[src.id] = {
                    "status": "ok",
                    "discovered": len(items),
                    "fetched": fetched_here,
                    "skipped": skipped_here,
                    "failed": failed_here,
                    "latency_ms": round((time.monotonic() - src_started) * 1000.0, 1),
                }

        result.articles = all_articles
        result.status = "ok"
        result.finished_at = iso_now()
        result.duration_sec = round(time.monotonic() - started, 2)
        result.summary = {"sources": per_source}
        self.storage.finish_run(run_id, result)
        log(
            "INFO",
            f"采集完成：新增 {result.fetched_count} 篇 · 跳过 {result.skipped_count} · 失败 {result.failed_count} "
            f"· 付费墙 {result.paywalled_count}（{result.duration_sec}s）",
            scope="pipeline",
            progress=100,
        )
        if log_cb:
            try:
                log_cb({"event": "run_finished", "run_id": run_id, "fetched": result.fetched_count})
            except Exception:  # noqa: BLE001
                pass
        return result

    async def run_single_source(self, source_id: str, dry_run: bool = False, limit: int = 3) -> SourceTestResult:
        """单源试抓（默认只抽取前 3 篇，不污染正式库）。"""

        sources = {s.id: s for s in self._load_sources(include_disabled=True)}
        src = sources.get(source_id)
        if src is None:
            return SourceTestResult(
                source_id=source_id, source_name=source_id, ok=False, message="未找到该采集源"
            )

        started = time.monotonic()
        log("INFO", f"单源测试：{src.name}", scope="source-test")
        try:
            async with make_client(self.settings) as client:
                adapter = build_adapter(src, self.settings, client)
                items = await adapter.discover()
        except Exception as exc:  # noqa: BLE001
            return SourceTestResult(
                source_id=src.id,
                source_name=src.name,
                ok=False,
                message=f"发现阶段失败：{exc}",
                latency_ms=round((time.monotonic() - started) * 1000.0, 1),
            )

        report = SourceTestResult(
            source_id=src.id,
            source_name=src.name,
            ok=True,
            feed_parsed=len(items) >= 0,
            discovered_count=len(items),
            message=f"发现 {len(items)} 条候选",
        )
        if not items:
            report.ok = False
            report.message = "RSS 解析成功但未发现可用条目"
            report.latency_ms = round((time.monotonic() - started) * 1000.0, 1)
            return report

        sample_limit = max(1, min(limit, 3)) if not dry_run else max(1, min(limit, 3))
        async with make_client(self.settings) as client:
            for item in items[:sample_limit]:
                try:
                    extracted = await self._extract_one(client, item, src)
                except Exception as exc:  # noqa: BLE001
                    report.samples.append({"title": item.title, "ok": False, "error": str(exc)})
                    continue
                article = self._to_article(item, src, extracted)
                report.samples.append(
                    {
                        "title": article.title or item.title,
                        "url": article.canonical_url,
                        "status": extracted.status,
                        "word_count": extracted.word_count,
                        "paragraphs": len(extracted.paragraphs),
                        "method": extracted.method,
                        "score": article.score,
                        "error": extracted.error_message,
                    }
                )
                if extracted.status == "fetched":
                    report.extracted_count += 1
                    if not report.first_title:
                        report.first_title = article.title
                        report.first_word_count = extracted.word_count
                        report.first_paragraphs = len(extracted.paragraphs)

        report.ok = report.extracted_count > 0
        if not report.ok:
            report.message = f"发现 {len(items)} 条，但前 {sample_limit} 篇均未抽取成功"
        else:
            report.message = f"发现 {len(items)} 条，试抽 {sample_limit} 篇成功 {report.extracted_count} 篇"
        report.latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        log("INFO", f"单源测试完成：{report.message}", scope="source-test")
        return report

    async def fetch_manual_url(self, url: str) -> RawArticle:
        """人工粘贴 URL：走同一套抽取与打分管线。"""

        canonical = normalize_url(url)
        if not canonical:
            raise ValueError("URL 无效")
        pseudo_src = SourceConfig(
            id="manual",
            name="Manual Import",
            type=SourceType.MANUAL_URL,
            url=canonical,
            category="Manual",
            weight=0.9,
            enabled=True,
        )
        item = DiscoveryItem(url=canonical, title="", published_at=format_date_iso(iso_now()))
        async with make_client(self.settings) as client:
            extracted = await self._extract_one(client, item, pseudo_src)
        article = self._to_article(item, pseudo_src, extracted)
        if not article.title:
            article.title = canonical.rstrip("/").split("/")[-1] or "Untitled"
        self.storage.upsert_article(article, ArticleStatus(extracted.status))
        log("INFO", f"手动导入 {canonical} → {extracted.status}（{extracted.word_count} 词）", scope="manual")
        return article

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _load_sources(self, include_disabled: bool = False) -> list[SourceConfig]:
        sources = load_feeds()
        if not include_disabled:
            sources = [s for s in sources if s.enabled]
        return sources

    async def _extract_one(self, client: httpx.AsyncClient, item: DiscoveryItem, src: SourceConfig) -> ExtractResult:
        harv = self.settings.harvester
        return await extract_article(
            item.url,
            client=client,
            rss_title=item.title,
            rss_author=item.author,
            rss_published=item.published_at,
            rss_content_html=item.content_html,
            min_words=200,
        )

    def _to_article(self, item: DiscoveryItem, src: SourceConfig, extracted: ExtractResult) -> RawArticle:
        harv = self.settings.harvester
        paragraphs = extracted.paragraphs
        word_count = extracted.word_count or count_words(" ".join(paragraphs))
        published = format_date_iso(extracted.published_at or item.published_at or iso_now())
        canonical = normalize_url(item.url)
        score = compute_score(
            src.weight,
            published,
            word_count,
            weights=(
                harv.score_weight_source,
                harv.score_weight_freshness,
                harv.score_weight_length,
            ),
            ideal=harv.ideal_word_range,
        )
        if extracted.status != "fetched":
            score = round(max(0.0, score - 3.0), 2)

        return RawArticle(
            url_hash=compute_url_hash(canonical),
            canonical_url=canonical,
            source_id=src.id,
            source_name=src.name,
            title=extracted.title or item.title or canonical,
            author=extracted.author or item.author,
            published_at=published,
            fetched_at=iso_now(),
            cover_image=extracted.cover_image or item.cover_image,
            paragraphs=paragraphs,
            word_count=word_count,
            read_time_min=read_time_minutes(word_count),
            score=score,
            status=ArticleStatus(extracted.status),
            error_message=extracted.error_message,
            summary_hint=item.summary,
        )

    # ------------------------------------------------------------------
    # 精选
    # ------------------------------------------------------------------

    def select_top_candidates(self, limit: int | None = None) -> list[dict[str, Any]]:
        """从候选池挑选 Top N（按分数、去重来源过多、满足词数窗口）。"""

        limit = limit or self.settings.harvester.daily_publish_limit
        harv = self.settings.harvester
        listing = self.storage.list_articles(status="fetched", sort="score", page=1, page_size=200)
        candidates: list[dict[str, Any]] = []
        used_sources: dict[str, int] = {}
        for row in listing["items"]:
            wc = int(row.get("word_count") or 0)
            if wc < harv.min_word_count or wc > harv.max_word_count:
                continue
            sid = str(row.get("source_id") or "")
            if used_sources.get(sid, 0) >= 2:
                continue
            candidates.append(row)
            used_sources[sid] = used_sources.get(sid, 0) + 1
            if len(candidates) >= limit:
                break
        return candidates
