"""采集器基础设施：日志总线、抽象基类、HTTP 客户端工厂。"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Deque, Protocol

import httpx

from ..models import RawArticle, SourceConfig, SourceType
from ..utils import iso_now

# ---------------------------------------------------------------------------
# 日志总线（SSE / CLI / 文件 三路共用）
# ---------------------------------------------------------------------------

LogCallback = Callable[[dict[str, Any]], Any]


@dataclass
class LogEntry:
    ts: str
    level: str
    message: str
    scope: str = "pipeline"
    progress: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "level": self.level,
            "message": self.message,
            "scope": self.scope,
            "progress": self.progress,
        }


class LogBus:
    """进程内广播总线：保存最近 N 条日志，并支持多个订阅者（SSE）。"""

    def __init__(self, capacity: int = 500) -> None:
        self._buffer: Deque[LogEntry] = deque(maxlen=capacity)
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = asyncio.Lock()

    def emit(self, level: str, message: str, scope: str = "pipeline", progress: float | None = None) -> dict[str, Any]:
        entry = LogEntry(
            ts=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            level=(level or "INFO").upper(),
            message=message,
            scope=scope,
            progress=progress,
        )
        payload = entry.as_dict()
        self._buffer.append(entry)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        self._write_file(payload)
        return payload

    def _write_file(self, payload: dict[str, Any]) -> None:
        try:
            from ..config import LOG_DIR

            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with (LOG_DIR / "lexipress.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{payload['ts']} [{payload['level']}] [{payload['scope']}] {payload['message']}\n")
        except OSError:
            pass

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def recent(self, limit: int = 200, level: str | None = None) -> list[dict[str, Any]]:
        items = list(self._buffer)
        if level and level.upper() != "ALL":
            threshold = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}.get(level.upper(), 0)
            scale = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
            items = [i for i in items if scale.get(i.level, 20) >= threshold]
        return [i.as_dict() for i in items[-limit:]]

    def clear(self) -> None:
        self._buffer.clear()


LOG_BUS = LogBus()


def log(level: str, message: str, scope: str = "pipeline", progress: float | None = None) -> None:
    LOG_BUS.emit(level, message, scope=scope, progress=progress)


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------


def make_client(settings, *, timeout: int | None = None) -> httpx.AsyncClient:
    """构建统一 HTTP 客户端。

    显式 `trust_env=False`：不读取宿主机的 HTTP(S)_PROXY / ALL_PROXY 环境变量。
    原因：开发机上常有大小写重复或带方括号的代理变量（如 `http://[::1]`），
    httpx 会在构造阶段直接抛 `InvalidURL`，把采集任务整体打断。
    采集目标是公开外刊站点，直连即可；需要代理时通过配置显式传入。
    """

    harv = settings.harvester
    kwargs: dict[str, Any] = {
        "headers": harv.headers(),
        "timeout": httpx.Timeout(timeout or harv.request_timeout_sec),
        "follow_redirects": True,
        "trust_env": False,
        "limits": httpx.Limits(max_connections=harv.max_concurrency * 2, max_keepalive_connections=10),
    }
    proxy = (getattr(harv, "proxy", "") or "").strip()
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    retries: int = 2,
    backoff: float = 0.8,
    scope: str = "http",
) -> httpx.Response | None:
    """带指数退避的 GET；网络异常返回 None，不抛出。"""

    last_error = ""
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(backoff * (2**attempt))
                continue
            return resp
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                await asyncio.sleep(backoff * (2**attempt))
                continue
    log("WARN", f"请求失败 {url} → {last_error or 'unknown'}", scope=scope)
    return None


# ---------------------------------------------------------------------------
# 适配器基类
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryItem:
    """Step 1 的输出：待抽取的链接与源侧元数据。"""

    url: str
    title: str = ""
    summary: str = ""
    author: str = ""
    published_at: str = ""
    cover_image: str = ""
    content_html: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class BaseSourceAdapter(ABC):
    """所有采集源的统一抽象基类。"""

    type: SourceType = SourceType.RSS

    def __init__(self, config: SourceConfig, settings, client: httpx.AsyncClient | None = None):
        self.config = config
        self.settings = settings
        self._client = client

    @property
    @abstractmethod
    def source_type(self) -> SourceType: ...

    @abstractmethod
    async def discover(self) -> list[DiscoveryItem]:
        """Step 1：发现候选链接（不抓正文）。"""

    async def close(self) -> None:
        return None


def build_article(
    item: DiscoveryItem,
    config: SourceConfig,
    *,
    paragraphs: list[str],
    word_count: int,
    read_time_min: int,
    score: float,
    status: str = "fetched",
    error_message: str = "",
    canonical_url: str = "",
) -> RawArticle:
    from ..utils import url_hash as compute_hash

    canonical = canonical_url or item.url
    return RawArticle(
        url_hash=compute_hash(canonical),
        canonical_url=canonical,
        source_id=config.id,
        source_name=config.name,
        title=item.title,
        author=item.author,
        published_at=item.published_at,
        fetched_at=iso_now(),
        cover_image=item.cover_image,
        paragraphs=paragraphs,
        word_count=word_count,
        read_time_min=read_time_min,
        score=score,
        status=status,  # type: ignore[arg-type]
        error_message=error_message,
        summary_hint=item.summary,
    )


class RateLimiter:
    """简易令牌间隔限流：保证同一源两次请求至少间隔 `min_interval` 秒。"""

    def __init__(self, min_interval: float = 0.0):
        self.min_interval = max(0.0, min_interval)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
