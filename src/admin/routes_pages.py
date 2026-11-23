"""LexiPress Admin 页面渲染路由（Jinja2 SSR）。

注意：Starlette ≥0.29 起 `TemplateResponse` 的签名为
`TemplateResponse(request, name, context)`；此处统一封装为 `_render()`，
同时兼容旧版 `(name, context)` 形式，避免因依赖版本差异导致 500。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import ADMIN_TEMPLATES_DIR, DIST_DIR, load_feeds, load_settings
from ..storage import STATUS_LABELS, Storage
from .tasks import TASKS

router = APIRouter(tags=["pages"])

templates = Jinja2Templates(directory=str(ADMIN_TEMPLATES_DIR))

STATUS_TABS = [
    {"value": "all", "label": "全部"},
    {"value": "fetched", "label": "新抓取"},
    {"value": "shortlisted", "label": "已精选"},
    {"value": "parsed", "label": "已解析"},
    {"value": "published", "label": "已发布"},
    {"value": "error", "label": "异常/付费墙"},
    {"value": "rejected", "label": "已淘汰"},
]


def _render(request: Request, name: str, context: dict[str, Any]) -> HTMLResponse:
    """跨 Starlette 版本的 TemplateResponse 封装。"""

    try:
        return templates.TemplateResponse(request, name, context)
    except TypeError:
        return templates.TemplateResponse(name, context)


def _context(request: Request, page: str, **extra: Any) -> dict[str, Any]:
    settings = load_settings()
    base: dict[str, Any] = {
        "request": request,
        "page": page,
        "site_title": settings.site.title,
        "tasks": TASKS.all_states(),
        "any_running": TASKS.any_running(),
        "running": TASKS.running_names(),
        "dist_ready": (DIST_DIR / "index.html").exists(),
        "status_labels": STATUS_LABELS,
        "status_tabs": STATUS_TABS,
        "base_url": "",
    }
    base.update(extra)
    return base


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    storage = Storage()
    stats = storage.dashboard_stats()
    runs = storage.list_runs(limit=8)
    for run in runs:
        try:
            run["summary"] = json.loads(run.get("summary_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            run["summary"] = {}
    sources = [s.model_dump() for s in storage.list_source_health()]
    return _render(
        request,
        "dashboard.html",
        _context(request, "dashboard", stats=stats, runs=runs, sources=sources),
    )


@router.get("/articles", response_class=HTMLResponse)
async def articles_page(request: Request) -> HTMLResponse:
    storage = Storage()
    sources = [s.model_dump() for s in storage.list_source_health()]
    return _render(request, "articles.html", _context(request, "articles", sources=sources))


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request) -> HTMLResponse:
    storage = Storage()
    storage.sync_sources(load_feeds())
    sources = [s.model_dump() for s in storage.list_source_health()]
    return _render(request, "sources.html", _context(request, "sources", sources=sources))


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    return _render(request, "logs.html", _context(request, "logs"))


@router.get("/publish", response_class=HTMLResponse)
async def publish_page(request: Request) -> HTMLResponse:
    storage = Storage()
    index_entries = storage.load_index()
    parsed_articles = storage.iter_parsed_articles()

    published_ids = {e.get("id") for e in index_entries}
    rows = []
    for article in parsed_articles:
        rows.append(
            {
                "id": article.id,
                "title": article.title,
                "source": article.source,
                "published_at": article.published_at,
                "word_count": article.word_count,
                "difficulty": article.difficulty.value,
                "vocab_count": len(article.vocab),
                "parser_mode": article.parser_mode,
                "online": article.id in published_ids,
            }
        )
    rows.sort(key=lambda r: r["published_at"] or "", reverse=True)
    parsed_ids = {r["id"] for r in rows}
    unstaged = [e for e in index_entries if e.get("id") not in parsed_ids]
    return _render(
        request,
        "publish.html",
        _context(request, "publish", rows=rows, orphan_entries=unstaged, total=len(rows)),
    )
