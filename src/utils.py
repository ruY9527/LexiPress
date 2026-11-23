"""LexiPress 公共工具函数。

包含：URL 归一化与指纹、时间解析、词数统计、难度评估、日志总线与文本清洗辅助。
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ---------------------------------------------------------------------------
# URL 归一化
# ---------------------------------------------------------------------------

TRACKING_PARAM_PREFIXES = ("utm_", "pk_", "mc_", "hsa_", "gclid", "fbclid", "msclkid")
TRACKING_PARAMS = {
    "ref",
    "referrer",
    "source",
    "src",
    "spm",
    "share",
    "sharesource",
    "campaign",
    "cmpid",
    "campid",
    "yclid",
    "igshid",
    "mkt_tok",
    "trk",
    "trk_contact",
    "trk_msg",
    "trk_module",
    "trk_sid",
    "_hsenc",
    "_hsmi",
    "at_medium",
    "at_campaign",
    "smid",
    "partner",
    "guccounter",
    "guce_referrer",
    "guce_referrer_sig",
    "utm",
    "output",
    "comments",
}


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    if k in TRACKING_PARAMS:
        return True
    return any(k.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES)


def normalize_url(url: str) -> str:
    """归一化 URL：去锚点、去追踪参数、统一小写主机名、去末尾斜杠、HTTPS 升级。"""

    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    if not parsed.scheme or not parsed.netloc:
        return url

    scheme = "https" if parsed.scheme in {"http", "https"} else parsed.scheme
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        # 保留 www：部分站点去掉后 301 到别处；仅统一大小写。
        netloc = netloc

    path = parsed.path or "/"
    # 去掉重复斜杠
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    kept_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not _is_tracking_param(k)]
    kept_pairs.sort()
    query = urlencode(kept_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def url_hash(url: str) -> str:
    """规范化 URL 的 sha256 指纹。"""

    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def is_probably_article_url(url: str) -> bool:
    """粗筛：排除明显的非文章链接（视频、仓库、PDF、首页等）。"""

    if not url:
        return False
    low = url.lower()
    blocked_domains = (
        "youtube.com",
        "youtu.be",
        "github.com",
        "twitter.com",
        "x.com",
        "reddit.com/r/",
        "news.ycombinator.com",
        "linkedin.com",
        "instagram.com",
        "tiktok.com",
        "facebook.com",
        "medium.com/@",
        "arxiv.org/abs",
    )
    for dom in blocked_domains:
        if dom in low:
            return False
    if low.endswith((".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".svg")):
        return False
    return True


# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------


def parse_datetime_loose(value: str | None) -> datetime | None:
    """尽力解析各种时间字符串（RFC822 / ISO8601 / 常见日期）。"""

    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return _ensure_tz(dt)
    except (TypeError, ValueError, IndexError):
        pass

    iso_candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return _ensure_tz(dt)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return _ensure_tz(datetime.strptime(raw, fmt))
        except ValueError:
            continue

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return _ensure_tz(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return None
    return None


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_date_iso(value: str | datetime | None) -> str:
    """统一输出 `YYYY-MM-DD`；解析失败则回退今天。"""

    if isinstance(value, datetime):
        return _ensure_tz(value).date().isoformat()
    dt = parse_datetime_loose(value)
    if dt is None:
        return date.today().isoformat()
    return dt.date().isoformat()


def format_date_display(value: str | None) -> str:
    """输出杂志风日期：`NOV 23, 2026`。"""

    dt = parse_datetime_loose(value)
    if dt is None:
        return ""
    return dt.strftime("%b %d, %Y").upper()


def hours_since(value: str | datetime | None) -> float:
    """距今小时数；无法解析时返回一个大数（视为陈旧）。"""

    if isinstance(value, datetime):
        dt = _ensure_tz(value)
    else:
        dt = parse_datetime_loose(value)
    if dt is None:
        return 24 * 365.0
    delta = datetime.now(timezone.utc) - dt
    return max(delta.total_seconds() / 3600.0, 0.0)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def days_between(a: date, b: date) -> int:
    return abs((a - b).days)


# ---------------------------------------------------------------------------
# 文本处理
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'“(])")


def count_words(text: str) -> int:
    """英文词数（按字母序列计数，含连字符词）。"""

    if not text:
        return 0
    return len(_WORD_RE.findall(text))


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = _SENT_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def read_time_minutes(word_count: int, wpm: int = 200) -> int:
    if word_count <= 0:
        return 0
    return max(1, math.ceil(word_count / wpm))


def clean_text(text: str) -> str:
    """归一化空白、去零宽字符、修复常见编码噪音。"""

    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def slugify(text: str, fallback: str = "article") -> str:
    """ASCII slug；非 ASCII 一律折叠为连字符（中文标题回退到 fallback）。"""

    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    ascii_text = re.sub(r"-{2,}", "-", ascii_text)
    if not ascii_text:
        return fallback
    return ascii_text[:60].strip("-") or fallback


# ---------------------------------------------------------------------------
# 难度评估（规则版，供 RuleOnlyParser 与 LLM 结果交叉校验）
# ---------------------------------------------------------------------------

# 高价值学术/外刊高频词（CEFR B2 以上）。用于估算生词密度。
_ADVANCED_WORDS: frozenset[str] = frozenset(
    """
    aberration acquiesce acumen admonish admonition aesthetic affectation affable
    alacrity albeit ambivalent ameliorate anachronism anathema antipathy apocryphal
    apposite arcane arduous ascetic assiduous attenuate audacious austere autonomy
    banal belie benevolent bequeath berate blithe bolster bombastic buoyant burgeon
    cacophony candour capitulate castigate cessation circumspect coalesce cogent
    commensurate compelling complacent conundrum corroborate covert credulous
    culminate cursory deference delineate demagogue demeanour denigrate deride
    desultory diatribe didactic discern disparate disseminate dissonance divergent
    dogmatic eclectic efficacy egregious elucidate elude emanate embellish empirical
    emulate enigma ephemeral equivocal erode esoteric exacerbate exculpate exemplify
    exhort exonerate extrapolate facetious fallacious fastidious fecund fervent
    flourish formidable fortuitous foster fraught furtive galvanize gratuitous
    gregarious guile hapless heresy hinder idiosyncrasy illuminate imbue immutable
    impede imperative imperturbable impetus implicit inchoate incongruous
    indefatigable indigenous inexorable infer innate innocuous inscrutable insidious
    insipid intransigent intrinsic inundate irrevocable itinerant juxtapose laconic
    lament latent laudable lethargy levity lucid lucrative magnanimous malleable
    manifest maverick meander mendacious mercurial meticulous mitigate mollify
    mundane munificent nascent nebulous nefarious negligible nuance obfuscate
    oblique oblivious obstinate obviate offset onerous opaque ostensible ostentatious
    palliate paradox paramount partisan paucity peculiarity penchant perceptive
    perfunctory peripheral pernicious perspicacious pertinent pervasive phenomenon
    pinnacle placate plausible poignant polarize pragmatic precarious predicament
    predilection predominant prefatory prejudice preliminary premise prerogative
    prescient prevalent pristine probity proclivity prodigious proficient profound
    proliferate prolix propensity prosaic protagonist provisional prudent pugnacious
    punctilious quandary quintessential radical rancour ratify rebuff recalcitrant
    reciprocal reconcile recondite redundant refractory refute reiterate relentless
    reluctant remedy reminiscent remote renounce repel repercussion reprimand
    reproach repudiate requisite resilient resolute respite reticent retrograde
    revere rhetorical rigorous robust rudimentary sagacious salient sanction
    scrupulous scrutinize sequester serendipity servile skeptical solicitous
    sophisticated specious sporadic spurious squander staunch steadfast stigma
    stipulate strive subjective substantiate subterfuge subtlety succinct superfluous
    supplant surmise surreptitious susceptible sustain sycophant tacit taciturn
    tangential tantamount tenacious tenuous tepid terse thwart timorous tolerance
    torpor tractable tranquil transcend transient trepidation truncate ubiquitous
    unabashed unassailable unassuming unconventional undermine unequivocal uniform
    universal unwarranted usurious vacillate vagary valid vantage variance vehement
    venerable veracity verbose versatile vex vertiginous viable vigilant vindicate
    vindictive virtuoso vociferous volatile volition voracious wanton wary
    whimsical wield wistful zealous zenith
    """.split()
)

_COMMON_WORDS: frozenset[str] = frozenset(
    """
    the be to of and a in that have i it for not on with he as you do at this but his by from
    they we say her she or an will my one all would there their what so up out if about who get
    which go me when make can like time no just him know take people into year your good some
    could them see other than then now look only come its over think also back after use two how
    our work first well way even new want because any these give day most us is are was were been
    has had did does doing am being having more very much many such own same few both each every
    """.split()
)


def estimate_difficulty(text: str) -> tuple[str, float]:
    """基于高阶词密度的 CEFR 估算。返回 `(level, vocab_rate)`。"""

    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    if not words:
        return "B2", 0.0
    advanced = sum(1 for w in words if w in _ADVANCED_WORDS)
    long_words = sum(1 for w in words if len(w) >= 11)
    rate = advanced / len(words)
    ratio_long = long_words / len(words)

    composite = rate * 0.7 + ratio_long * 0.3
    if composite >= 0.075:
        level = "C2"
    elif composite >= 0.048:
        level = "C1"
    elif composite >= 0.028:
        level = "B2"
    else:
        level = "B1"
    return level, round(rate, 4)


def is_stopword(word: str) -> bool:
    return word.lower() in _COMMON_WORDS


def advanced_candidates(text: str, limit: int = 40) -> list[str]:
    """从文本中挑出高阶词候选（按出现顺序去重）。"""

    seen: list[str] = []
    seen_lower: set[str] = set()
    for match in _WORD_RE.findall(text or ""):
        low = match.lower()
        if len(low) < 5 or low in seen_lower or low in _COMMON_WORDS:
            continue
        if low in _ADVANCED_WORDS or len(low) >= 10:
            seen_lower.add(low)
            seen.append(match.lower())
        if len(seen) >= limit:
            break
    return seen


# ---------------------------------------------------------------------------
# 日志总线（供 SSE 与 CLI 共用）
# ---------------------------------------------------------------------------

_LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}


def level_value(level: str) -> int:
    return _LOG_LEVELS.get((level or "INFO").upper(), 20)


def iter_items(value: Iterable | None) -> list:
    return list(value or [])
