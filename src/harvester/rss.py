"""RSS / Atom 采集适配器：httpx 拉取 + feedparser 解析。"""

from __future__ import annotations

import asyncio
from typing import Any

import feedparser
import httpx

from ..config import load_settings
from ..models import SourceConfig, SourceType
from ..utils import clean_text, format_date_iso, is_probably_article_url, normalize_url
from .base import BaseSourceAdapter, DiscoveryItem, RateLimiter, fetch_with_retry, log, make_client


class RSSAdapter(BaseSourceAdapter):
    """标准 RSS 2.0 / Atom 源适配器。"""

    type = SourceType.RSS

    def __init__(self, config: SourceConfig, settings=None, client: httpx.AsyncClient | None = None):
        settings = settings or load_settings()
        super().__init__(config, settings, client)
        self._owns_client = client is None
        self._limiter = RateLimiter(min_interval=0.4)

    @property
    def source_type(self) -> SourceType:
        return SourceType.RSS

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_client(self.settings)
            self._owns_client = True
        return self._client

    async def fetch_raw(self) -> tuple[bytes, float]:
        """拉取 feed 原始字节，返回 `(content, latency_ms)`。"""

        import time

        client = await self._get_client()
        await self._limiter.acquire()
        started = time.monotonic()
        resp = await fetch_with_retry(
            client,
            self.config.url,
            retries=self.settings.harvester.max_retries,
            scope=f"rss:{self.config.id}",
        )
        latency = (time.monotonic() - started) * 1000.0
        if resp is None:
            raise RuntimeError("RSS 请求失败（超时或网络错误）")
        if resp.status_code in (401, 403, 429):
            raise RuntimeError(f"RSS 被拒绝 HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise RuntimeError(f"RSS 返回 HTTP {resp.status_code}")
        return resp.content, latency

    async def discover(self) -> list[DiscoveryItem]:
        content, _latency = await self.fetch_raw()
        return self.parse_feed_bytes(content)

    def parse_feed_bytes(self, content: bytes) -> list[DiscoveryItem]:
        """纯函数式解析：便于单元测试注入本地 XML。"""

        parsed = feedparser.parse(content)
        entries = getattr(parsed, "entries", []) or []
        limit = self.settings.harvester.per_source_limit
        items: list[DiscoveryItem] = []
        seen: set[str] = set()

        feed_title = clean_text(getattr(parsed.feed, "title", "") if not isinstance(parsed.feed, str) else "")

        for entry in entries[: max(limit * 3, limit)]:
            link = ""
            for key in ("link",):
                candidate = entry.get(key) if hasattr(entry, "get") else getattr(entry, key, "")
                if candidate:
                    link = str(candidate)
                    break
            if not link:
                links = getattr(entry, "links", []) or []
                for lk in links:
                    if isinstance(lk, dict) and lk.get("href"):
                        link = lk["href"]
                        break
            if not link:
                continue

            canonical = normalize_url(link)
            if not canonical or canonical in seen:
                continue
            if not is_probably_article_url(canonical):
                continue
            seen.add(canonical)

            title = clean_text(str(getattr(entry, "title", "") or ""))
            summary = ""
            for key in ("summary", "description"):
                raw_summary = getattr(entry, key, "") or ""
                if raw_summary:
                    summary = clean_text(_strip_html(str(raw_summary)))
                    break

            author = ""
            authors = getattr(entry, "authors", []) or []
            if authors and isinstance(authors, list):
                names = [str(a.get("name", "")).strip() for a in authors if isinstance(a, dict)]
                author = ", ".join([n for n in names if n])
            if not author:
                author = clean_text(str(getattr(entry, "author", "") or ""))

            published_raw = ""
            for key in ("published", "updated", "created"):
                value = getattr(entry, key, "") or ""
                if value:
                    published_raw = str(value)
                    break

            cover = ""
            media = getattr(entry, "media_content", None) or []
            for m in media:
                if isinstance(m, dict) and m.get("url"):
                    cover = str(m["url"])
                    break
            if not cover:
                enclosures = getattr(entry, "enclosures", None) or []
                for enc in enclosures:
                    if isinstance(enc, dict) and str(enc.get("type", "")).startswith("image"):
                        cover = str(enc.get("href") or enc.get("url") or "")
                        break

            content_html = ""
            content_field = getattr(entry, "content", None)
            if isinstance(content_field, list) and content_field:
                first = content_field[0]
                if isinstance(first, dict):
                    content_html = str(first.get("value", "") or "")

            items.append(
                DiscoveryItem(
                    url=canonical,
                    title=title,
                    summary=summary,
                    author=author,
                    published_at=format_date_iso(published_raw) if published_raw else "",
                    cover_image=cover,
                    content_html=content_html,
                    extra={"feed_title": feed_title},
                )
            )
            if len(items) >= limit:
                break

        return items

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "RSSAdapter":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()


def _strip_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    except Exception:  # noqa: BLE001
        import re

        return re.sub(r"<[^>]+>", " ", html)


async def discover_source(config: SourceConfig, settings=None) -> tuple[list[DiscoveryItem], float]:
    """便捷函数：抓取单个 RSS 源，返回条目与耗时。"""

    import time

    settings = settings or load_settings()
    adapter = RSSAdapter(config, settings)
    started = time.monotonic()
    try:
        items = await adapter.discover()
        return items, (time.monotonic() - started) * 1000.0
    finally:
        await adapter.close()
