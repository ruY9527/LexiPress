"""FastAPI 应用入口：挂载管理后台 + `/LexiPress` 静态预览路由。

关键点（对应 `plan/04` 第 1.6 节）：
- `dist/` 不存在时，`/LexiPress/` 返回友好引导页，且应用启动不崩溃。
- `dist/` 存在时用 `StaticFiles(html=True)` 直挂，模拟 GitHub Pages 子路径行为。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import DIST_DIR, ROOT_DIR, ensure_dirs, load_settings
from ..harvester.base import LOG_BUS

PREVIEW_PREFIX = "/LexiPress"
ADMIN_STATIC_DIR = ROOT_DIR / "templates" / "admin" / "static"

GUIDE_HTML = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="paper">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LexiPress · 尚未构建</title>
<style>
  :root {
    --bg: #FAF8F5; --surface: #FFFFFF; --ink: #1C1B19; --muted: #8C867D;
    --accent: #9B2C2C; --border: rgba(28,27,25,0.10);
    --serif: 'Newsreader', Georgia, 'Times New Roman', serif;
    --sans: 'Inter', -apple-system, 'Segoe UI', 'PingFang SC', sans-serif;
    --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 32px;
    background: var(--bg); color: var(--ink); font-family: var(--sans); line-height: 1.7;
  }
  .card {
    width: min(620px, 100%); padding: 48px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 12px;
    box-shadow: 0 12px 32px rgba(28,27,25,0.06);
  }
  .eyebrow {
    font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.2em;
    text-transform: uppercase; color: var(--muted); margin-bottom: 14px;
  }
  h1 { margin: 0 0 12px; font-family: var(--serif); font-size: 2rem; font-weight: 600; letter-spacing: -0.02em; }
  p { margin: 0 0 20px; color: #57534E; }
  code {
    padding: 2px 7px; background: #F3EFE8; border-radius: 4px;
    font-family: var(--mono); font-size: 0.84em; color: var(--accent);
  }
  pre {
    margin: 0 0 24px; padding: 16px 18px; background: #1C1B19; color: #E4E2DD;
    border-radius: 8px; font-family: var(--mono); font-size: 0.8rem;
    overflow-x: auto; line-height: 1.8;
  }
  pre span { color: #D97757; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; }
  a.btn {
    display: inline-flex; align-items: center; gap: 8px; padding: 11px 20px;
    border-radius: 8px; font-size: 0.85rem; text-decoration: none; transition: all 180ms;
  }
  a.primary { background: var(--ink); color: var(--bg); }
  a.primary:hover { opacity: 0.88; }
  a.ghost { border: 1px solid rgba(28,27,25,0.22); color: var(--ink); }
  a.ghost:hover { background: #F3EFE8; }
  hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
  .hint { font-size: 0.82rem; color: var(--muted); }
</style>
</head>
<body>
  <div class="card">
    <div class="eyebrow">LexiPress · Reading Studio</div>
    <h1>静态站还没有构建</h1>
    <p>
      预览目录 <code>dist/</code> 不存在或为空。先执行一次构建，即可在
      <code>/LexiPress/</code> 下看到与 GitHub Pages 完全一致的杂志风站点。
    </p>
    <pre><span>$</span> python main.py --build-only
<span>$</span> python main.py --admin   <span># 再启动后台</span></pre>
    <div class="row">
      <a class="btn primary" href="/">返回后台仪表盘</a>
      <a class="btn ghost" href="/publish">前往构建与发布中心</a>
    </div>
    <hr>
    <p class="hint">
      提示：也可以直接调用 <code>POST /api/site/build</code> 触发构建；
      构建完成后刷新本页就能看到阅读站。
    </p>
  </div>
</body>
</html>
"""


def _has_built_site() -> bool:
    return (DIST_DIR / "index.html").exists()


class PreviewStatic(StaticFiles):
    """`/LexiPress` 静态挂载：dist/ 缺失时回退到引导页，而不是 404 或崩溃。"""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        if not _has_built_site():
            return HTMLResponse(GUIDE_HTML, status_code=200)
        try:
            response = await super().get_response(path, scope)
        except Exception:  # noqa: BLE001 - 兜底到引导页/404
            return HTMLResponse(GUIDE_HTML, status_code=200)
        if response.status_code == 404:
            not_found = DIST_DIR / "404.html"
            if not_found.exists():
                return HTMLResponse(not_found.read_text(encoding="utf-8"), status_code=404)
        return response


def create_app() -> FastAPI:
    ensure_dirs()
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        LOG_BUS.emit(
            "INFO",
            f"LexiPress Admin 已启动 · 解析模式：{'LLM' if settings.llm.usable else '规则降级'}",
            scope="admin",
        )
        if not settings.llm.usable:
            LOG_BUS.emit(
                "WARN",
                "未检测到 LLM_API_KEY，精读解析将自动使用 RuleOnlyParser（站点仍可正常构建发布）",
                scope="admin",
            )
        if not _has_built_site():
            LOG_BUS.emit("WARN", "dist/ 尚未构建，/LexiPress/ 将显示构建引导页", scope="admin")
        yield

    app = FastAPI(
        title="LexiPress Admin",
        description="外刊精读工坊 · 本地可视化管理后台",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    from .routes_api import router as api_router
    from .routes_pages import router as pages_router

    app.include_router(api_router)
    app.include_router(pages_router)

    # 后台静态资源
    ADMIN_STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/admin-static", StaticFiles(directory=str(ADMIN_STATIC_DIR)), name="admin-static")

    # 前台阅读站预览（子路径一致性验证）
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(PREVIEW_PREFIX, PreviewStatic(directory=str(DIST_DIR), html=True), name="site-preview")

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "data": {
                "preview_prefix": PREVIEW_PREFIX,
                "dist_ready": _has_built_site(),
                "llm_enabled": settings.llm.usable,
                "base_url": settings.base_url,
            },
            "message": "",
        }

    return app


app = create_app()


def run(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    """启动 uvicorn（供 main.py --admin 调用）。"""

    import uvicorn

    settings = load_settings()
    bind_host = host or os.getenv("ADMIN_HOST") or settings.admin.host
    bind_port = int(port or os.getenv("ADMIN_PORT") or settings.admin.port)
    print(f"\n  LexiPress Admin → http://{bind_host}:{bind_port}")
    print(f"  阅读站预览      → http://{bind_host}:{bind_port}/LexiPress/\n")
    uvicorn.run(
        "src.admin.app:app" if reload else app,
        host=bind_host,
        port=bind_port,
        reload=reload,
        log_level="info",
    )
