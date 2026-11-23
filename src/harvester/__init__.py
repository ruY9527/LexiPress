"""采集器包初始化。"""

from __future__ import annotations

from .base import LOG_BUS, BaseSourceAdapter, DiscoveryItem, LogBus, log
from .extractor import ExtractResult, extract_article, extract_from_html
from .hackernews import HackerNewsAdapter
from .pipeline import HarvesterPipeline, compute_score, freshness_score, length_fit_score
from .rss import RSSAdapter

__all__ = [
    "LOG_BUS",
    "BaseSourceAdapter",
    "DiscoveryItem",
    "ExtractResult",
    "HackerNewsAdapter",
    "HarvesterPipeline",
    "LogBus",
    "RSSAdapter",
    "compute_score",
    "extract_article",
    "extract_from_html",
    "freshness_score",
    "length_fit_score",
    "log",
]
