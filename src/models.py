"""LexiPress 核心数据模型（Pydantic v2）。

本模块是采集器、解析器、存储层、静态站生成器与后台之间的唯一契约。
字段命名严格对齐 `plan/02_UI_UX_Design_Spec.md` 第 6.1 节的 JSON Schema。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    """采集源类型。"""

    RSS = "rss"
    HACKERNEWS = "hackernews"
    MANUAL_URL = "manual_url"


class ArticleStatus(str, Enum):
    """文章全生命周期状态机。"""

    DISCOVERED = "discovered"
    FETCHED = "fetched"
    SHORTLISTED = "shortlisted"
    PARSED = "parsed"
    PUBLISHED = "published"
    REJECTED = "rejected"
    PAYWALLED = "paywalled"
    FAILED = "failed"


class Difficulty(str, Enum):
    """CEFR 阅读难度分级。"""

    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


class TriggerType(str, Enum):
    """采集任务触发方式。"""

    MANUAL = "manual"
    SCHEDULE = "schedule"
    SINGLE_SOURCE = "single_source"
    MANUAL_URL = "manual_url"


# ---------------------------------------------------------------------------
# 采集源
# ---------------------------------------------------------------------------


class SourceConfig(BaseModel):
    """`config/feeds.yaml` 中的单条源配置。"""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: SourceType = SourceType.RSS
    url: str = ""
    category: str = "General"
    weight: float = Field(default=0.85, ge=0.0, le=1.0)
    enabled: bool = True
    # Hacker News 专属
    min_score: int = Field(default=180, ge=0)
    limit: int = Field(default=20, ge=1, le=200)

    @field_validator("id")
    @classmethod
    def _slugify_id(cls, v: str) -> str:
        cleaned = v.strip().lower().replace(" ", "-")
        if not cleaned:
            raise ValueError("source id 不能为空")
        return cleaned


class SourceHealth(BaseModel):
    """外刊源健康度运行指标（数据库镜像 + 实时统计）。"""

    id: str
    name: str
    type: str = SourceType.RSS.value
    url: str = ""
    category: str = "General"
    weight: float = 0.85
    enabled: bool = True
    min_score: int = 180
    limit: int = 20
    last_fetch_at: str | None = None
    last_status: str = "unknown"
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0
    article_count: int = 0

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, v: Any) -> str:
        """DB 里可能存的是 `SourceType.RSS` 枚举或 `rss` 字符串，统一成纯字符串。"""

        if isinstance(v, SourceType):
            return v.value
        text = str(v or SourceType.RSS.value)
        # 兼容 "SourceType.RSS" 这类历史脏值
        if "." in text:
            text = text.rsplit(".", 1)[-1]
        return text.strip().lower() or SourceType.RSS.value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def type_label(self) -> str:
        return {"rss": "RSS", "hackernews": "HN", "manual_url": "MANUAL"}.get(self.type, self.type.upper())

    @property
    def status_color(self) -> str:
        if self.last_status in {"ok", "unknown"} and self.consecutive_failures == 0:
            return "ok"
        if self.consecutive_failures >= 3 or self.last_status == "error":
            return "error"
        return "warn"


class SourceTestResult(BaseModel):
    """单源试抓诊断报告。"""

    source_id: str
    source_name: str
    ok: bool
    feed_parsed: bool = False
    discovered_count: int = 0
    extracted_count: int = 0
    first_title: str = ""
    first_word_count: int = 0
    first_paragraphs: int = 0
    latency_ms: float = 0.0
    message: str = ""
    samples: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 采集态文章
# ---------------------------------------------------------------------------


class RawArticle(BaseModel):
    """采集器输出的标准清洗文章（清洗后、未解析）。"""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    url_hash: str
    canonical_url: str
    source_id: str
    source_name: str
    title: str
    author: str = ""
    published_at: str = ""
    fetched_at: str = ""
    cover_image: str = ""
    paragraphs: list[str] = Field(default_factory=list)
    word_count: int = 0
    read_time_min: int = 0
    score: float = Field(default=0.0, ge=0.0, le=10.0)
    status: ArticleStatus = ArticleStatus.FETCHED
    error_message: str = ""
    summary_hint: str = ""
    tags: list[str] = Field(default_factory=list)

    @property
    def body_text(self) -> str:
        return "\n\n".join(self.paragraphs)


# ---------------------------------------------------------------------------
# 精读解析产物
# ---------------------------------------------------------------------------


class ParagraphPair(BaseModel):
    """段落双语对。"""

    index: int = Field(ge=0)
    en: str = ""
    zh: str = ""


class VocabItem(BaseModel):
    """核心词汇 / 地道短语。"""

    id: str = ""
    term: str = Field(min_length=1)
    phonetic: str = ""
    pos: str = ""
    meaning_zh: str = ""
    note: str = ""
    para_index: int = Field(default=0, ge=0)

    @field_validator("term")
    @classmethod
    def _strip_term(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("term 不能为空")
        return v


class SentenceAnalysis(BaseModel):
    """长难句拆解。"""

    en: str = Field(min_length=1)
    structure: str = ""
    zh: str = ""


class ArticleOverview(BaseModel):
    """文章导读。"""

    summary_zh: str = ""
    takeaways: list[str] = Field(default_factory=list)
    background: str = ""
    structure: str = ""


class ReadingMetrics(BaseModel):
    """基础阅读指标。"""

    word_count: int = 0
    read_time_min: int = 0
    difficulty: Difficulty = Difficulty.B2
    vocab_rate: float = 0.0
    sentence_count: int = 0
    avg_sentence_len: float = 0.0


class ParsedArticle(BaseModel):
    """写入 `data/parsed/<id>.json` 的完整精读资产。"""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    url_hash: str = ""
    title: str
    source: str = ""
    source_id: str = ""
    author: str = ""
    published_at: str = ""
    original_url: str = ""
    cover_image: str = ""
    tags: list[str] = Field(default_factory=list)
    difficulty: Difficulty = Difficulty.B2
    word_count: int = 0
    read_time_min: int = 0
    score: float = 0.0
    audio_url: str = ""
    parsed_at: str = ""
    parser_mode: Literal["llm", "rule"] = "rule"
    overview: ArticleOverview = Field(default_factory=ArticleOverview)
    paragraphs: list[ParagraphPair] = Field(default_factory=list)
    vocab: list[VocabItem] = Field(default_factory=list)
    sentences: list[SentenceAnalysis] = Field(default_factory=list)

    # ---- 便捷视图 ----
    @property
    def english_first_sentence(self) -> str:
        for p in self.paragraphs:
            text = p.en.strip()
            if not text:
                continue
            for sent in text.replace("?", ".").replace("!", ".").split("."):
                if sent.strip():
                    return sent.strip()
        return ""

    @property
    def has_vocab(self) -> bool:
        return bool(self.vocab)

    @property
    def has_translation(self) -> bool:
        return any(p.zh.strip() for p in self.paragraphs)

    @property
    def has_zh_vocab(self) -> bool:
        return any(v.meaning_zh.strip() for v in self.vocab)


class ArticleIndexEntry(BaseModel):
    """`data/index.json` 中的单篇摘要元数据（发布真理源）。"""

    model_config = ConfigDict(extra="allow")

    id: str
    url_hash: str = ""
    canonical_url: str = ""
    title: str
    source: str = ""
    source_id: str = ""
    published_at: str = ""
    updated_at: str = ""
    score: float = 0.0
    difficulty: Difficulty = Difficulty.B2
    word_count: int = 0
    read_time_min: int = 0
    tags: list[str] = Field(default_factory=list)
    cover_image: str = ""
    vocab_count: int = 0
    parser_mode: str = "rule"


# ---------------------------------------------------------------------------
# 运行结果
# ---------------------------------------------------------------------------


class CrawlRunResult(BaseModel):
    """一次采集任务的执行结果。"""

    run_id: int | None = None
    trigger_type: TriggerType = TriggerType.MANUAL
    started_at: str = ""
    finished_at: str = ""
    status: str = "ok"
    discovered_count: int = 0
    fetched_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    paywalled_count: int = 0
    duration_sec: float = 0.0
    summary: dict[str, Any] = Field(default_factory=dict)
    articles: list[RawArticle] = Field(default_factory=list)


class ParseRunResult(BaseModel):
    """一次解析任务的执行结果。"""

    ok: bool = True
    parsed: list[str] = Field(default_factory=list)
    failed: list[dict[str, str]] = Field(default_factory=list)
    mode: str = "rule"


class BuildSummary(BaseModel):
    """静态站构建结果。"""

    ok: bool = True
    output_dir: str = ""
    article_count: int = 0
    page_count: int = 0
    duration_sec: float = 0.0
    base_url: str = ""
    generated_at: str = ""
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 杂项工具模型（后台 API 复用）
# ---------------------------------------------------------------------------


class ApiResponse(BaseModel):
    """后台统一 JSON 返回结构。"""

    ok: bool = True
    data: Any = None
    message: str = ""


def utc_now_iso() -> str:
    """统一时间戳：秒级 ISO8601。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    return date.today().isoformat()
