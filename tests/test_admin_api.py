"""后台 API 与页面路由集成测试（FastAPI TestClient）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.admin.app import create_app
from src.admin.tasks import TaskConflict, TaskManager


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/articles", "/sources", "/logs", "/publish"])
def test_admin_pages_return_200(client, path):
    res = client.get(path)
    assert res.status_code == 200
    html = res.text
    assert "<!DOCTYPE html>" in html
    assert "LexiPress" in html


def test_admin_pages_have_nav_and_assets(client):
    html = client.get("/").text
    assert "/admin-static/admin.css" in html
    assert "/admin-static/admin.js" in html
    for href in ("/articles", "/sources", "/logs", "/publish"):
        assert f'href="{href}"' in html


def test_preview_route_is_mounted(client):
    res = client.get("/LexiPress/")
    assert res.status_code == 200
    # dist 存在时是真实首页，否则是构建引导页
    assert "LexiPress" in res.text


def test_preview_guide_when_dist_missing(client, monkeypatch):
    import src.admin.app as app_module

    monkeypatch.setattr(app_module, "_has_built_site", lambda: False)
    res = client.get("/LexiPress/")
    assert res.status_code == 200
    assert "静态站还没有构建" in res.text or "python main.py --build-only" in res.text


# ---------------------------------------------------------------------------
# 基础 API
# ---------------------------------------------------------------------------


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["data"]["preview_prefix"] == "/LexiPress"


@pytest.mark.parametrize(
    "path",
    [
        "/api/dashboard",
        "/api/sources",
        "/api/articles",
        "/api/crawl/runs",
        "/api/tasks",
        "/api/site/status",
        "/api/git/status",
        "/api/logs",
    ],
)
def test_api_envelope_shape(client, path):
    res = client.get(path)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"ok", "data", "message"}
    assert body["ok"] is True


def test_dashboard_payload(client):
    data = client.get("/api/dashboard").json()["data"]
    for key in ("stats", "runs", "sources", "tasks", "dist_ready"):
        assert key in data
    for kpi in ("today_new", "shortlisted", "published", "sources_total", "sources_healthy"):
        assert kpi in data["stats"]


def test_articles_endpoint_supports_filters(client):
    res = client.get("/api/articles", params={"status": "all", "sort": "score", "page": 1, "page_size": 5})
    body = res.json()
    assert body["ok"]
    data = body["data"]
    for key in ("items", "total", "page", "page_size", "pages"):
        assert key in data
    assert isinstance(data["items"], list)


def test_articles_endpoint_unknown_article_404(client):
    res = client.get("/api/articles/definitely-not-exist")
    assert res.status_code == 404


def test_manual_url_validates_scheme(client):
    res = client.post("/api/articles/manual", json={"url": "ftp://bad"})
    assert res.status_code == 422


def test_manual_url_requires_url(client):
    res = client.post("/api/articles/manual", json={})
    assert res.status_code == 422


def test_status_update_rejects_invalid_status(client):
    res = client.patch("/api/articles/some-id/status", json={"status": "not-a-status"})
    assert res.status_code == 422


def test_status_update_404_for_missing_article(client):
    res = client.patch("/api/articles/nope/status", json={"status": "shortlisted"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 源管理
# ---------------------------------------------------------------------------


def test_sources_list_shape(client):
    data = client.get("/api/sources").json()["data"]
    assert "sources" in data
    assert isinstance(data["sources"], list)
    if data["sources"]:
        src = data["sources"][0]
        for key in ("id", "name", "type", "weight", "enabled"):
            assert key in src


def test_source_create_requires_valid_payload(client):
    res = client.post("/api/sources", json={"id": "", "name": ""})
    assert res.status_code == 422


def test_source_create_and_delete_roundtrip(client):
    payload = {
        "id": "pytest-temp-source",
        "name": "Pytest Temp",
        "type": "rss",
        "url": "https://example.com/feed.xml",
        "category": "Testing",
        "weight": 0.5,
    }
    created = client.post("/api/sources", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["data"]["id"] == "pytest-temp-source"

    # 重复创建 → 409
    dup = client.post("/api/sources", json=payload)
    assert dup.status_code == 409

    patched = client.patch("/api/sources/pytest-temp-source", json={"enabled": False, "weight": 0.7})
    assert patched.status_code == 200
    assert patched.json()["data"]["enabled"] is False
    assert abs(patched.json()["data"]["weight"] - 0.7) < 1e-6

    removed = client.delete("/api/sources/pytest-temp-source")
    assert removed.status_code == 200

    missing = client.delete("/api/sources/pytest-temp-source")
    assert missing.status_code == 404


def test_source_patch_404(client):
    res = client.patch("/api/sources/nonexistent", json={"enabled": True})
    assert res.status_code == 404


def test_source_test_404(client):
    res = client.post("/api/sources/nonexistent/test")
    assert res.status_code == 404


def test_feeds_yaml_is_written_after_source_change(client):
    from src.config import FEEDS_FILE

    payload = {
        "id": "pytest-yaml-check",
        "name": "YAML Check",
        "type": "rss",
        "url": "https://example.com/y.xml",
        "weight": 0.6,
    }
    client.post("/api/sources", json=payload)
    text = FEEDS_FILE.read_text(encoding="utf-8")
    assert "pytest-yaml-check" in text
    client.delete("/api/sources/pytest-yaml-check")
    assert "pytest-yaml-check" not in FEEDS_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 并发锁（409）
# ---------------------------------------------------------------------------


def test_crawl_run_conflicts_when_reserved(client):
    from src.admin.tasks import TASKS

    TASKS.reserve("crawl", "测试占位")
    try:
        res = client.post("/api/crawl/run", json={"trigger_type": "manual"})
        assert res.status_code == 409
        assert "运行中" in res.json()["detail"]
    finally:
        TASKS.release("crawl")


def test_build_conflicts_when_reserved(client):
    from src.admin.tasks import TASKS

    TASKS.reserve("build", "测试占位")
    try:
        res = client.post("/api/site/build", json={})
        assert res.status_code == 409
    finally:
        TASKS.release("build")


def test_parse_conflicts_when_reserved(client):
    from src.admin.tasks import TASKS

    TASKS.reserve("parse", "测试占位")
    try:
        # 先用一个存在的文章 id 才能进入到并发检查；不存在则先 404
        listing = client.get("/api/articles", params={"page_size": 1}).json()["data"]["items"]
        if listing:
            res = client.post(f"/api/articles/{listing[0]['id']}/parse", json={})
            assert res.status_code == 409
    finally:
        TASKS.release("parse")


# ---------------------------------------------------------------------------
# TaskManager 单元行为
# ---------------------------------------------------------------------------


def test_task_manager_reserve_is_exclusive():
    tm = TaskManager()

    async def scenario():
        tm.reserve("crawl", "A")
        assert tm.is_running("crawl")
        with pytest.raises(TaskConflict):
            tm.reserve("crawl", "B")
        tm.release("crawl")
        assert not tm.is_running("crawl")

    asyncio.run(scenario())


def test_task_manager_spawn_reserves_synchronously():
    """spawn 必须同步占位，否则并发请求会双双通过。"""

    tm = TaskManager()
    ran = {"value": False}

    async def scenario():
        async def work():
            ran["value"] = True
            await asyncio.sleep(0.01)
            return {"done": True}

        task = tm.spawn("build", work, task_label="build")
        # 占位在 spawn 返回时即生效
        assert tm.is_running("build")
        with pytest.raises(TaskConflict):
            tm.reserve("build")
        await task
        await asyncio.sleep(0.02)
        assert not tm.is_running("build")
        assert ran["value"] is True

    asyncio.run(scenario())


def test_task_manager_records_error_state():
    tm = TaskManager()

    async def scenario():
        async def boom():
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError):
            await tm.run("parse", boom, task_label="parse")
        state = tm.state("parse")
        assert state["status"] == "error"
        assert "kaboom" in state["message"]
        assert not tm.is_running("parse")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


def test_logs_endpoint_returns_items(client):
    data = client.get("/api/logs").json()["data"]
    assert "items" in data
    assert isinstance(data["items"], list)


def test_logs_stream_emits_history_event(client):
    with client.stream("GET", "/api/logs/stream") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        chunk = next(response.iter_text())
        assert "event: history" in chunk or "history" in chunk


def test_log_clear(client):
    res = client.post("/api/logs/clear")
    assert res.status_code == 200
    assert res.json()["ok"] is True


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------


def test_site_build_endpoint(client):
    res = client.post("/api/site/build", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "article_count" in body["data"]


def test_site_status_reports_artifacts(client):
    client.post("/api/site/build", json={})
    data = client.get("/api/site/status").json()["data"]
    assert data["dist_exists"] is True
    if data.get("index_exists"):
        assert data["has_nojekyll"] is True
        assert data["has_404"] is True
        assert data["has_search_index"] is True


def test_crawl_runs_pagination(client):
    data = client.get("/api/crawl/runs", params={"page": 1, "page_size": 5}).json()["data"]
    assert "items" in data
    assert data["page"] == 1
