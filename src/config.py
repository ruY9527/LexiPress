"""LexiPress 全局配置加载。

职责：
1. 定位项目根目录，读取 `config/settings.yaml` 与 `config/feeds.yaml`。
2. 读取 `.env`（python-dotenv），并把 `LLM_API_KEY` 等环境变量优先级置于 YAML 之上。
3. 提供路径常量与统一的可变配置对象，供采集器 / 解析器 / 构建器 / 后台共享。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .models import SourceConfig, SourceType

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
PARSED_DIR = DATA_DIR / "parsed"
TEMPLATES_DIR = ROOT_DIR / "templates"
SITE_TEMPLATES_DIR = TEMPLATES_DIR / "site"
ADMIN_TEMPLATES_DIR = TEMPLATES_DIR / "admin"
STATIC_SRC_DIR = TEMPLATES_DIR / "site" / "static"
DIST_DIR = ROOT_DIR / "dist"
LOG_DIR = ROOT_DIR / "logs"

SETTINGS_FILE = CONFIG_DIR / "settings.yaml"
FEEDS_FILE = CONFIG_DIR / "feeds.yaml"
INDEX_FILE = DATA_DIR / "index.json"
DB_FILE = DATA_DIR / "lexipress.db"


def ensure_dirs() -> None:
    """确保运行所需目录存在。"""

    for d in (DATA_DIR, PARSED_DIR, DIST_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 配置对象
# ---------------------------------------------------------------------------


@dataclass
class SiteConfig:
    title: str = "LexiPress"
    subtitle: str = "Curated English Reading Studio"
    description: str = ""
    base_url: str = "/LexiPress"
    articles_per_page: int = 24
    default_theme: str = "paper"
    author: str = "LexiPress Studio"

    @property
    def normalized_base_url(self) -> str:
        """`/LexiPress` 形态：无末尾斜杠；空串代表根路径。"""

        b = (self.base_url or "").strip()
        if not b:
            return ""
        if not b.startswith("/"):
            b = "/" + b
        return b.rstrip("/")


@dataclass
class HarvesterConfig:
    max_concurrency: int = 5
    request_timeout_sec: int = 15
    max_retries: int = 2
    freshness_hours: int = 72
    min_word_count: int = 500
    max_word_count: int = 4500
    ideal_word_range: tuple[int, int] = (800, 2800)
    daily_publish_limit: int = 3
    per_source_limit: int = 12
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    accept_language: str = "en-US,en;q=0.9"
    proxy: str = ""
    score_weight_source: float = 4.0
    score_weight_freshness: float = 3.0
    score_weight_length: float = 3.0

    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Language": self.accept_language,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }


@dataclass
class LLMConfig:
    enabled: bool = True
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = 0.3
    translate_batch_size: int = 10
    max_retries: int = 2
    max_input_words: int = 3500
    vocab_min: int = 10
    vocab_max: int = 15
    sentence_min: int = 3
    sentence_max: int = 5
    api_key: str = ""

    @property
    def usable(self) -> bool:
        """是否真的可以走 LLM：开关打开且确实有 key。"""

        return bool(self.enabled and self.api_key.strip())


@dataclass
class AdminConfig:
    host: str = "127.0.0.1"
    port: int = 8088


@dataclass
class Settings:
    site: SiteConfig = field(default_factory=SiteConfig)
    harvester: HarvesterConfig = field(default_factory=HarvesterConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)

    @property
    def base_url(self) -> str:
        return self.site.normalized_base_url


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def load_settings(reload: bool = False) -> Settings:
    """加载全局配置（进程内缓存，`reload=True` 强制重读）。"""

    if reload:
        load_settings.cache_clear()

    load_dotenv(ROOT_DIR / ".env", override=False)

    raw = _read_yaml(SETTINGS_FILE)
    site_raw = raw.get("site") or {}
    harv_raw = raw.get("harvester") or {}
    llm_raw = raw.get("llm") or {}
    admin_raw = raw.get("admin") or {}

    site = SiteConfig(
        title=str(site_raw.get("title", "LexiPress")),
        subtitle=str(site_raw.get("subtitle", "Curated English Reading Studio")),
        description=str(site_raw.get("description", "")),
        base_url=str(site_raw.get("base_url", "/LexiPress") or ""),
        articles_per_page=_as_int(site_raw.get("articles_per_page"), 24),
        default_theme=str(site_raw.get("default_theme", "paper")),
        author=str(site_raw.get("author", "LexiPress Studio")),
    )

    ideal = harv_raw.get("ideal_word_range") or [800, 2800]
    try:
        ideal_range = (int(ideal[0]), int(ideal[1]))
    except (TypeError, ValueError, IndexError):
        ideal_range = (800, 2800)

    weights = harv_raw.get("score_weights") or {}
    harvester = HarvesterConfig(
        max_concurrency=_as_int(harv_raw.get("max_concurrency"), 5),
        request_timeout_sec=_as_int(harv_raw.get("request_timeout_sec"), 15),
        max_retries=_as_int(harv_raw.get("max_retries"), 2),
        freshness_hours=_as_int(harv_raw.get("freshness_hours"), 72),
        min_word_count=_as_int(harv_raw.get("min_word_count"), 500),
        max_word_count=_as_int(harv_raw.get("max_word_count"), 4500),
        ideal_word_range=ideal_range,
        daily_publish_limit=_as_int(harv_raw.get("daily_publish_limit"), 3),
        per_source_limit=_as_int(harv_raw.get("per_source_limit"), 12),
        user_agent=str(harv_raw.get("user_agent", HarvesterConfig.user_agent)),
        accept_language=str(harv_raw.get("accept_language", "en-US,en;q=0.9")),
        proxy=str(harv_raw.get("proxy", "") or ""),
        score_weight_source=_as_float(weights.get("source_weight"), 4.0),
        score_weight_freshness=_as_float(weights.get("freshness"), 3.0),
        score_weight_length=_as_float(weights.get("length_fit"), 3.0),
    )

    vocab_target = llm_raw.get("vocab_target") or [10, 15]
    sent_target = llm_raw.get("sentence_target") or [3, 5]
    try:
        vmin, vmax = int(vocab_target[0]), int(vocab_target[1])
    except (TypeError, ValueError, IndexError):
        vmin, vmax = 10, 15
    try:
        smin, smax = int(sent_target[0]), int(sent_target[1])
    except (TypeError, ValueError, IndexError):
        smin, smax = 3, 5

    llm = LLMConfig(
        enabled=bool(llm_raw.get("enabled", True)),
        base_url=os.getenv("LLM_BASE_URL") or str(llm_raw.get("base_url", "https://api.deepseek.com/v1")),
        model=os.getenv("LLM_MODEL") or str(llm_raw.get("model", "deepseek-chat")),
        temperature=_as_float(llm_raw.get("temperature"), 0.3),
        translate_batch_size=_as_int(llm_raw.get("translate_batch_size"), 10),
        max_retries=_as_int(llm_raw.get("max_retries"), 2),
        max_input_words=_as_int(llm_raw.get("max_input_words"), 3500),
        vocab_min=vmin,
        vocab_max=vmax,
        sentence_min=smin,
        sentence_max=smax,
        api_key=(os.getenv("LLM_API_KEY") or "").strip(),
    )

    admin = AdminConfig(
        host=os.getenv("ADMIN_HOST") or str(admin_raw.get("host", "127.0.0.1")),
        port=_as_int(os.getenv("ADMIN_PORT"), _as_int(admin_raw.get("port"), 8088)),
    )

    return Settings(site=site, harvester=harvester, llm=llm, admin=admin)


# ---------------------------------------------------------------------------
# feeds.yaml 读写
# ---------------------------------------------------------------------------


def load_feeds() -> list[SourceConfig]:
    """读取 `config/feeds.yaml` 中的源列表。"""

    raw = _read_yaml(FEEDS_FILE)
    items = raw.get("sources") or []
    sources: list[SourceConfig] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            src = SourceConfig(**item)
        except Exception:  # noqa: BLE001 - 单条坏配置不应阻断整体加载
            continue
        if src.id in seen:
            continue
        seen.add(src.id)
        sources.append(src)
    return sources


def _source_to_yaml_dict(src: SourceConfig) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": src.id,
        "name": src.name,
        "type": src.type.value,
        "url": src.url,
        "category": src.category,
        "weight": round(float(src.weight), 4),
        "enabled": bool(src.enabled),
    }
    if src.type is SourceType.HACKERNEWS:
        data["min_score"] = src.min_score
        data["limit"] = src.limit
    return data


def save_feeds(sources: list[SourceConfig]) -> None:
    """原子写回 `config/feeds.yaml`（保留文件头注释）。"""

    header = (
        "# LexiPress 外刊源配置\n"
        "# type: rss | hackernews\n"
        "# 每个源均由 src/harvester 下的同名适配器接管；此文件与本地 SQLite sources 表双向同步。\n"
        "# 本文件由 LexiPress Admin 自动维护，手工编辑同样生效。\n\n"
    )
    payload = {"sources": [_source_to_yaml_dict(s) for s in sources]}
    text = header + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    tmp = FEEDS_FILE.with_suffix(".yaml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, FEEDS_FILE)


def atomic_write_text(path: Path, text: str) -> None:
    """原子落盘：先写 `.tmp` 再 `os.replace()`。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    """原子写入 JSON。"""

    import json

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_write_text(path, text + "\n")
