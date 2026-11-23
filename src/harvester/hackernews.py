"""Hacker News 高热长文发现适配器。

调用官方 Firebase API：topstories → item 详情，按 score 阈值过滤，
并排除非文章域名（视频、仓库、PDF、社交平台等）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import load_settings
from ..models import SourceConfig, SourceType
from ..utils import format_date_iso, is_probably_article_url, normalize_url
from .base import BaseSourceAdapter, DiscoveryItem, fetch_with_retry, log, make_client

HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


class HackerNewsAdapter(BaseSourceAdapter):
    """HN Top/Best 故事里的高质量外链长文。"""

    type = SourceType.HACKERNEWS

    def __init__(self, config: SourceConfig, settings=None, client: httpx.AsyncClient | None = None):
        settings = settings or load_settings()
        super().__init__(config, settings, client)
        self._owns_client = client is None

    @property
    def source_type(self) -> SourceType:
        return SourceType.HACKERNEWS

    def _score_threshold(self) -> int:
        return int(getattr(self.config, "min_score", 180) or 180)

    def _limit(self) -> int:
        return int(getattr(self.config, "limit", 20) or 20)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_client(self.settings)
            self._owns_client = True
        return self._client

    async def discover(self) -> list[DiscoveryItem]:
        client = await self._get_client()
        list_url = self.config.url or "https://hacker-news.firebaseio.com/v0/topstories.json"
        resp = await fetch_with_retry(
            client, list_url, retries=self.settings.harvester.max_retries, scope="hn:list"
        )
        if resp is None or resp.status_code >= 400:
            raise RuntimeError(f"HN 榜单请求失败: {getattr(resp, 'status_code', 'no response')}")
        try:
            ids = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"HN 榜单 JSON 解析失败: {exc}") from exc
        if not isinstance(ids, list):
            raise RuntimeError("HN 榜单返回结构异常")

        target = self._limit()
        threshold = self._score_threshold()
        semaphore = asyncio.Semaphore(min(8, self.settings.harvester.max_concurrency * 2))
        # 扫描上限：想拿到 target 条合格文章，最多看 200 条榜单
        scan_ids = [int(i) for i in ids[:200] if isinstance(i, int) or str(i).isdigit()]

        async def fetch_item(item_id: int) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    r = await client.get(HN_ITEM_URL.format(id=item_id))
                    if r.status_code >= 400:
                        return None
                    data = r.json()
                    return data if isinstance(data, dict) else None
                except (httpx.HTTPError, ValueError):
                    return None

        items_found: list[DiscoveryItem] = []
        batch_size = 25
        for start in range(0, len(scan_ids), batch_size):
            if len(items_found) >= target:
                break
            batch = scan_ids[start : start + batch_size]
            results = await asyncio.gather(*(fetch_item(i) for i in batch))
            for data in results:
                if not data:
                    continue
                if data.get("type") != "story":
                    continue
                if data.get("dead") or data.get("deleted"):
                    continue
                url = str(data.get("url") or "").strip()
                if not url:
                    continue
                score = int(data.get("score") or 0)
                if score < threshold:
                    continue
                if not is_probably_article_url(url):
                    continue
                canonical = normalize_url(url)
                if not canonical:
                    continue
                published = ""
                if data.get("time"):
                    import datetime as _dt

                    published = format_date_iso(
                        _dt.datetime.fromtimestamp(int(data["time"]), tz=_dt.timezone.utc).isoformat()
                    )
                items_found.append(
                    DiscoveryItem(
                        url=canonical,
                        title=str(data.get("title") or "").strip(),
                        summary="",
                        author=str(data.get("by") or ""),
                        published_at=published,
                        extra={"hn_score": score, "hn_id": data.get("id"), "hn_comments": data.get("descendants")},
                    )
                )
                if len(items_found) >= target:
                    break

        log(
            "INFO",
            f"HN 发现 {len(items_found)} 篇长文（阈值 score≥{threshold}）",
            scope=f"hn:{self.config.id}",
        )
        return items_found

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
