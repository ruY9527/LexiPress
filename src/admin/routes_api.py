"""LexiPress Admin REST API 与 SSE 日志流。

统一返回结构：`{ "ok": true, "data": ..., "message": "" }`（对应 plan/03 第 5 节）。
并发冲突统一映射为 `409 Conflict`。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..builder import SiteBuilder
from ..config import DIST_DIR, ROOT_DIR, load_feeds, load_settings, save_feeds
from ..harvester.base import LOG_BUS, log
from ..harvester.pipeline import HarvesterPipeline
from ..models import ArticleStatus, SourceConfig, SourceType
from ..parser import ParseService
from ..storage import STATUS_LABELS, Storage
from .tasks import TASKS, TaskConflict

router = APIRouter(prefix="/api", tags=["api"])


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def ok(data: Any = None, message: str = "") -> dict[str, Any]:
    return {"ok": True, "data": data, "message": message}


def fail(message: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "message": message}


def get_storage() -> Storage:
    return Storage()


# ---------------------------------------------------------------------------
# 仪表盘
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def dashboard() -> dict[str, Any]:
    storage = get_storage()
    stats = storage.dashboard_stats()
    runs = storage.list_runs(limit=8)
    health = [s.model_dump() for s in storage.list_source_health()]
    return ok(
        {
            "stats": stats,
            "runs": runs,
            "sources": health,
            "tasks": TASKS.all_states(),
            "dist_ready": (DIST_DIR / "index.html").exists(),
            "status_labels": STATUS_LABELS,
        }
    )


# ---------------------------------------------------------------------------
# 采集源
# ---------------------------------------------------------------------------


@router.get("/sources")
async def list_sources() -> dict[str, Any]:
    storage = get_storage()
    storage.sync_sources(load_feeds())
    health = [s.model_dump() for s in storage.list_source_health()]
    return ok({"sources": health, "types": [t.value for t in SourceType]})


@router.post("/sources")
async def create_source(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    sources = load_feeds()
    try:
        src = SourceConfig(**payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"源配置无效：{exc}") from exc

    if any(s.id == src.id for s in sources):
        raise HTTPException(status_code=409, detail=f"源 id `{src.id}` 已存在")

    sources.append(src)
    save_feeds(sources)
    get_storage().upsert_source(src)
    log("INFO", f"新增采集源：{src.name}（{src.type.value}）", scope="admin")
    return ok(src.model_dump(), f"已新增 {src.name}")


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    sources = load_feeds()
    idx = next((i for i, s in enumerate(sources) if s.id == source_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"未找到源 {source_id}")

    current = sources[idx].model_dump()
    allowed = {"name", "type", "url", "category", "weight", "enabled", "min_score", "limit"}
    merged = {**current, **{k: v for k, v in payload.items() if k in allowed}}
    merged["id"] = source_id
    try:
        updated = SourceConfig(**merged)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"源配置无效：{exc}") from exc

    sources[idx] = updated
    save_feeds(sources)
    get_storage().upsert_source(updated)
    log("INFO", f"更新采集源：{updated.name}（enabled={updated.enabled}）", scope="admin")
    return ok(updated.model_dump(), f"已更新 {updated.name}")


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str) -> dict[str, Any]:
    sources = load_feeds()
    remaining = [s for s in sources if s.id != source_id]
    if len(remaining) == len(sources):
        raise HTTPException(status_code=404, detail=f"未找到源 {source_id}")
    save_feeds(remaining)
    storage = get_storage()
    storage.sync_sources(remaining)
    log("WARN", f"删除采集源：{source_id}", scope="admin")
    return ok({"removed": source_id}, "已删除")


@router.post("/sources/{source_id}/test")
async def test_source(source_id: str, dry_run: bool = Query(default=True)) -> dict[str, Any]:
    settings = load_settings()
    sources = {s.id: s for s in load_feeds()}
    if source_id not in sources:
        raise HTTPException(status_code=404, detail=f"未找到源 {source_id}")
    pipeline = HarvesterPipeline(settings=settings)
    report = await pipeline.run_single_source(source_id, dry_run=dry_run)
    return ok(report.model_dump(), report.message)


# ---------------------------------------------------------------------------
# 采集任务
# ---------------------------------------------------------------------------


@router.post("/crawl/run")
async def crawl_run(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """异步触发采集。重复触发返回 409。"""

    if TASKS.is_running("crawl"):
        raise HTTPException(
            status_code=409,
            detail="采集任务正在运行中，请查看实时日志流（/logs）观察进度",
        )

    source_ids = payload.get("source_ids") or []
    trigger = str(payload.get("trigger_type") or "manual")
    settings = load_settings()
    storage = get_storage()

    def factory():
        pipeline = HarvesterPipeline(storage=storage, settings=settings)
        return pipeline.run_all(trigger_type=trigger, source_ids=source_ids)

    TASKS.spawn("crawl", factory, task_label="全源采集")
    return ok({"status": "started", "sources": source_ids or "all"}, "采集任务已启动")


@router.get("/crawl/runs")
async def crawl_runs(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    storage = get_storage()
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    runs = storage.list_runs(limit=page_size, offset=(page - 1) * page_size)
    total = storage.count_runs()
    for run in runs:
        try:
            run["summary"] = json.loads(run.get("summary_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            run["summary"] = {}
    return ok({"items": runs, "total": total, "page": page, "page_size": page_size})


@router.get("/tasks")
async def task_states() -> dict[str, Any]:
    return ok(TASKS.all_states())


# ---------------------------------------------------------------------------
# 文章
# ---------------------------------------------------------------------------


@router.get("/articles")
async def list_articles(
    status: str = Query(default="all"),
    source_id: str = Query(default="all"),
    q: str = Query(default=""),
    sort: str = Query(default="score"),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
) -> dict[str, Any]:
    storage = get_storage()
    result = storage.list_articles(
        status=status,
        source_id=source_id,
        q=q,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    result["status_labels"] = STATUS_LABELS
    return ok(result)


@router.get("/articles/{article_id}")
async def get_article(article_id: str) -> dict[str, Any]:
    storage = get_storage()
    row = storage.get_article(article_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"未找到文章 {article_id}")
    parsed = storage.load_parsed(article_id)
    row["has_parsed"] = parsed is not None
    if parsed:
        row["parsed_summary"] = {
            "parser_mode": parsed.get("parser_mode"),
            "vocab": len(parsed.get("vocab") or []),
            "sentences": len(parsed.get("sentences") or []),
            "translated": sum(1 for p in (parsed.get("paragraphs") or []) if p.get("zh")),
            "paragraphs": len(parsed.get("paragraphs") or []),
        }
    return ok(row)


@router.post("/articles/manual")
async def manual_url(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="缺少 url")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="URL 必须以 http:// 或 https:// 开头")

    settings = load_settings()
    pipeline = HarvesterPipeline(settings=settings)
    try:
        article = await pipeline.fetch_manual_url(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"抓取失败：{exc}") from exc
    if article.status.value != "fetched":
        return {
            "ok": False,
            "data": article.model_dump(mode="json"),
            "message": article.error_message or "抓取未成功",
        }
    return ok(article.model_dump(mode="json"), f"已入库：{article.title[:40]}")


@router.patch("/articles/{article_id}/status")
async def update_article_status(article_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    status = str(payload.get("status") or "").strip()
    valid = {s.value for s in ArticleStatus}
    if status not in valid:
        raise HTTPException(status_code=422, detail=f"状态 `{status}` 无效，可选：{sorted(valid)}")

    storage = get_storage()
    if not storage.get_article(article_id):
        raise HTTPException(status_code=404, detail=f"未找到文章 {article_id}")
    storage.update_status(article_id, status)
    log("INFO", f"文章状态更新：{article_id} → {status}", scope="admin")
    return ok({"id": article_id, "status": status}, "状态已更新")


@router.post("/articles/{article_id}/refetch")
async def refetch_article(article_id: str) -> dict[str, Any]:
    storage = get_storage()
    row = storage.get_article(article_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"未找到文章 {article_id}")

    settings = load_settings()
    pipeline = HarvesterPipeline(storage=storage, settings=settings)
    try:
        article = await pipeline.fetch_manual_url(row["canonical_url"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"重取失败：{exc}") from exc

    # 保持原 id，避免出现重复记录
    storage.update_status(article_id, article.status.value, article.error_message)
    return ok(
        {
            "id": article_id,
            "status": article.status.value,
            "word_count": article.word_count,
            "error": article.error_message,
        },
        "已重新抓取",
    )


@router.post("/articles/{article_id}/parse")
async def parse_article(article_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    force_rule = bool(payload.get("force_rule_only", False))
    publish = bool(payload.get("publish", False))

    storage = get_storage()
    if not storage.get_article(article_id):
        raise HTTPException(status_code=404, detail=f"未找到文章 {article_id}")

    if TASKS.is_running("parse"):
        raise HTTPException(status_code=409, detail="已有解析任务在运行，请稍候")

    settings = load_settings()

    async def factory():
        service = ParseService(storage=storage, settings=settings)
        return await service.parse_by_id(article_id, force_rule_only=force_rule, publish=publish)

    try:
        result = await TASKS.run("parse", factory, task_label=f"解析 {article_id}")
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not result.get("ok"):
        return fail(result.get("message") or "解析失败")
    return ok(result, f"解析完成（{result.get('mode')} 模式）")


@router.post("/articles/parse-batch")
async def parse_batch(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ids = [str(i) for i in (payload.get("ids") or []) if str(i).strip()]
    if not ids:
        raise HTTPException(status_code=422, detail="ids 不能为空")
    if TASKS.is_running("parse"):
        raise HTTPException(status_code=409, detail="已有解析任务在运行，请稍候")

    force_rule = bool(payload.get("force_rule_only", False))
    publish = bool(payload.get("publish", True))
    storage = get_storage()
    settings = load_settings()

    async def factory():
        service = ParseService(storage=storage, settings=settings)
        return await service.parse_many(ids, force_rule_only=force_rule, publish=publish)

    try:
        result = await TASKS.run("parse", factory, task_label=f"批量解析 {len(ids)} 篇")
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok(result, f"已处理 {len(result.get('parsed', []))} 篇")


@router.post("/articles/{article_id}/publish")
async def publish_article(article_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """把已解析 JSON 标记为 published（或下线）。"""

    storage = get_storage()
    row = storage.get_article(article_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"未找到文章 {article_id}")

    online = bool(payload.get("online", True))
    if online:
        parsed = storage.load_parsed(article_id)
        if not parsed:
            raise HTTPException(status_code=409, detail="该文章尚未解析，无法发布")
        storage.set_parsed_path(article_id, str(storage.parsed_path_for(article_id)), status="published")
        # 确保 index.json 有此条目
        from ..models import ParsedArticle

        try:
            storage.export_parsed_article(ParsedArticle(**parsed))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"索引更新失败：{exc}") from exc
        return ok({"id": article_id, "status": "published"}, "已上线")
    storage.update_status(article_id, "parsed")
    storage.remove_index_entry(article_id)
    return ok({"id": article_id, "status": "parsed"}, "已下线")


@router.delete("/articles/{article_id}")
async def delete_article(article_id: str) -> dict[str, Any]:
    storage = get_storage()
    if not storage.get_article(article_id):
        raise HTTPException(status_code=404, detail=f"未找到文章 {article_id}")
    storage.delete_parsed(article_id)
    storage.delete_article(article_id)
    log("WARN", f"删除文章：{article_id}", scope="admin")
    return ok({"removed": article_id}, "已删除")


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------


@router.post("/site/build")
async def build_site(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if TASKS.is_running("build"):
        raise HTTPException(status_code=409, detail="构建任务正在运行中")

    settings = load_settings()
    storage = get_storage()

    async def factory():
        builder = SiteBuilder(storage=storage, settings=settings)
        return await asyncio.to_thread(builder.build, Path(str(payload.get("output_dir") or DIST_DIR)))

    try:
        summary = await TASKS.run("build", factory, task_label="静态站构建")
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    dist_ok = (DIST_DIR / "index.html").exists()
    return ok(
        {**summary.model_dump(), "dist_ready": dist_ok, "preview_url": "/LexiPress/"},
        f"构建完成：{summary.article_count} 篇 / {summary.page_count} 页（{summary.duration_sec}s）",
    )


@router.get("/site/status")
async def site_status() -> dict[str, Any]:
    index_file = DIST_DIR / "index.html"
    info: dict[str, Any] = {
        "dist_exists": DIST_DIR.exists(),
        "index_exists": index_file.exists(),
        "preview_url": "/LexiPress/",
    }
    if index_file.exists():
        stat = index_file.stat()
        info["built_at"] = _fmt_ts(stat.st_mtime)
        info["size_kb"] = round(stat.st_size / 1024, 1)
        articles_root = DIST_DIR / "articles"
        info["article_pages"] = len([p for p in articles_root.glob("*/index.html")]) if articles_root.exists() else 0
        info["has_404"] = (DIST_DIR / "404.html").exists()
        info["has_nojekyll"] = (DIST_DIR / ".nojekyll").exists()
        info["has_search_index"] = (DIST_DIR / "search-index.json").exists()
    return ok(info)


def _fmt_ts(ts: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Git 状态
# ---------------------------------------------------------------------------


@router.get("/git/status")
async def git_status() -> dict[str, Any]:
    def _run(args: list[str]) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                args,
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            return proc.returncode == 0, (proc.stdout or proc.stderr or "").strip()
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            return False, str(exc)

    is_repo, _ = _run(["git", "rev-parse", "--is-inside-work-tree"])
    if not is_repo:
        return ok(
            {
                "is_repo": False,
                "branch": "",
                "changed": [],
                "summary": "当前目录不是 Git 仓库，跳过同步检查",
            }
        )

    _, status_out = _run(["git", "status", "--short"])
    _, branch_out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    changed = [line for line in status_out.splitlines() if line.strip()]
    tracked = [line for line in changed if any(p in line for p in ("data/", "config/", "templates/", "src/"))]
    return ok(
        {
            "is_repo": True,
            "branch": branch_out,
            "changed": changed,
            "relevant": tracked,
            "has_changes": bool(changed),
            "commit_hint": "git add data/ config/ templates/ src/ && git commit -m 'chore(content): curated issues' && git push",
        }
    )


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


@router.get("/logs")
async def recent_logs(limit: int = 200, level: str = "ALL") -> dict[str, Any]:
    return ok({"items": LOG_BUS.recent(limit=min(limit, 500), level=level)})


@router.post("/logs/clear")
async def clear_logs() -> dict[str, Any]:
    LOG_BUS.clear()
    return ok(None, "日志已清空")


@router.get("/logs/stream")
async def log_stream(request: Request, level: str = "ALL") -> StreamingResponse:
    """SSE 实时日志流。"""

    async def event_generator():
        queue = await LOG_BUS.subscribe()
        try:
            # 首帧：握手 + 历史回放
            history = LOG_BUS.recent(limit=80, level=level)
            payload = json.dumps({"type": "history", "items": history, "tasks": TASKS.all_states()}, ensure_ascii=False)
            yield f"event: history\ndata: {payload}\n\n"

            last_beat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=1.5)
                except asyncio.TimeoutError:
                    now = time.monotonic()
                    if now - last_beat >= 12:
                        last_beat = now
                        yield ": keep-alive\n\n"
                    continue

                if level.upper() != "ALL":
                    scale = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
                    if scale.get(str(entry.get("level", "")).upper(), 20) < scale.get(level.upper(), 0):
                        continue

                yield f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
        finally:
            await LOG_BUS.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
