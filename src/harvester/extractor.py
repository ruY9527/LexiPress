"""正文抽取与清洗（trafilatura 主 + readability-lxml 兜底 + RSS 富文本三级兜底）。

包含付费墙／异常识别与段落噪音过滤，输出无广告、无导航的英文分段正文。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..utils import clean_text, count_words

# 付费墙 / 登录墙特征词
PAYWALL_MARKERS = (
    "subscribe to continue",
    "subscribe to read",
    "subscribe now to continue",
    "to continue reading",
    "log in to read",
    "login to read",
    "sign in to continue",
    "this article is for subscribers",
    "subscribers only",
    "already a subscriber",
    "create a free account to continue",
    "paywall",
    "you have reached your limit",
    "register to continue reading",
)

# 订阅引导 / 广告噪音（短段落命中即丢弃）
NOISE_PATTERNS = (
    r"^subscribe( to)? our (newsletter|podcast)",
    r"^sign up for (our|the) (newsletter|daily|weekly)",
    r"^read more\s*[:：]?$",
    r"^(read|see) (more|also)\s*[:：]",
    r"^follow us on",
    r"^share this (article|story)",
    r"^advertisement$",
    r"^(photo|image|illustration|credit)\s*[:：]",
    r"^get the (latest|best) .* delivered",
    r"^listen to this article",
    r"^this (article|story) (was|is) (originally )?published",
    r"^support our journalism",
    r"^become a (member|subscriber)",
    r"^©\s*\d{4}",
    r"^all rights reserved",
    r"^topics?\s*[:：]",
)
_NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)

_MIN_ARTICLE_WORDS = 250


@dataclass
class ExtractResult:
    """抽取结果。"""

    title: str = ""
    author: str = ""
    published_at: str = ""
    cover_image: str = ""
    paragraphs: list[str] = field(default_factory=list)
    word_count: int = 0
    status: str = "fetched"
    error_message: str = ""
    method: str = ""
    http_status: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "fetched" and self.word_count > 0

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


def html_to_paragraphs(html: str) -> list[str]:
    """HTML → 清洗后的段落列表。"""

    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        return []

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe", "form", "aside", "nav", "footer", "header", "figure"]):
        tag.decompose()

    blocks: list[str] = []
    for node in soup.find_all(["p", "blockquote", "h2", "h3", "li"]):
        text = clean_text(node.get_text(" ", strip=True))
        if text:
            blocks.append(text)

    if not blocks:
        fallback = clean_text(soup.get_text("\n", strip=True))
        blocks = [line for line in fallback.split("\n") if line.strip()]

    return filter_paragraphs(blocks)


def text_to_paragraphs(text: str) -> list[str]:
    """纯文本 → 段落列表（按空行切分，退化为按句子聚合）。"""

    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n\s*\n+", normalized)
    if len(chunks) <= 1:
        chunks = [c for c in normalized.split("\n") if c.strip()]
    blocks = [clean_text(c) for c in chunks]
    return filter_paragraphs([b for b in blocks if b])


def filter_paragraphs(blocks: list[str]) -> list[str]:
    """过滤噪音段、超短段落与重复段落。"""

    result: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        text = clean_text(block)
        if not text:
            continue
        words = count_words(text)
        if words == 0:
            continue
        if words < 25 and _NOISE_RE.search(text):
            continue
        if words < 4 and not text.endswith((".", "!", "?", ":", "”", '"')):
            continue
        key = text.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def detect_paywall(text: str, http_status: int = 200) -> str:
    """返回付费墙/异常原因；空串表示正常。"""

    if http_status in (401, 403, 429):
        return f"HTTP {http_status}"
    low = (text or "").lower()
    if count_words(text) < _MIN_ARTICLE_WORDS:
        for marker in PAYWALL_MARKERS:
            if marker in low:
                return f"检测到订阅/登录墙提示：{marker}"
    return ""


def _extract_with_trafilatura(html: str, url: str) -> dict[str, Any]:
    """主抽取器。返回 dict；失败返回空 dict。"""

    try:
        import trafilatura
        from trafilatura.settings import use_config

        cfg = use_config()
        cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
        raw = trafilatura.bare_extraction(
            html,
            url=url,
            include_images=True,
            include_comments=False,
            favor_precision=True,
            deduplicate=True,
            config=cfg,
        )
    except Exception:  # noqa: BLE001 - 抽取器内部异常不应中断管线
        try:
            import trafilatura

            raw = trafilatura.bare_extraction(html, url=url, include_images=True, favor_precision=True)
        except Exception:  # noqa: BLE001
            return {}

    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    # trafilatura >=1.9 可能返回 Document 对象
    data: dict[str, Any] = {}
    for attr in ("title", "author", "date", "text", "image", "url", "excerpt"):
        try:
            value = getattr(raw, attr, None)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            data[attr] = value
    return data


def _extract_with_readability(html: str) -> dict[str, Any]:
    """兜底抽取器 readability-lxml。"""

    try:
        from readability import Document

        doc = Document(html)
        title = clean_text(doc.short_title() or "")
        content_html = doc.summary(html_partial=True)
        paragraphs = html_to_paragraphs(content_html)
        return {"title": title, "text": "\n\n".join(paragraphs), "paragraphs": paragraphs}
    except Exception:  # noqa: BLE001
        return {}


def _pick_image(html: str) -> str:
    """从 HTML 里找 og:image / twitter:image。"""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for prop in ("og:image", "twitter:image", "twitter:image:src"):
            tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def extract_from_html(
    html: str,
    url: str,
    *,
    http_status: int = 200,
    rss_title: str = "",
    rss_author: str = "",
    rss_published: str = "",
    rss_content_html: str = "",
    min_words: int = 200,
) -> ExtractResult:
    """纯函数式抽取：给定 HTML，返回标准化结果（可单测）。"""

    result = ExtractResult(http_status=http_status)
    text = html or ""

    # 付费墙预检：先看原始页面是否明显是登录墙
    pre_paywall = detect_paywall(text, http_status)
    if pre_paywall and count_words(text) < 200:
        result.status = "paywalled"
        result.error_message = pre_paywall
        result.title = rss_title
        return result

    paragraphs: list[str] = []
    method = ""

    # 1) trafilatura
    if text:
        traf = _extract_with_trafilatura(text, url)
        if traf:
            traf_text = str(traf.get("text") or "")
            paragraphs = text_to_paragraphs(traf_text)
            result.title = clean_text(str(traf.get("title") or "")) or rss_title
            result.author = clean_text(str(traf.get("author") or "")) or rss_author
            result.published_at = str(traf.get("date") or "") or rss_published
            result.cover_image = str(traf.get("image") or "")
            if paragraphs:
                method = "trafilatura"

    wc = count_words(" ".join(paragraphs))

    # 2) readability 兜底
    if wc < min_words and text:
        read = _extract_with_readability(text)
        read_paragraphs = read.get("paragraphs") or []
        read_words = count_words(" ".join(read_paragraphs))
        if read_words > wc:
            paragraphs = read_paragraphs
            wc = read_words
            method = "readability"
            result.title = result.title or clean_text(str(read.get("title") or "")) or rss_title

    # 3) RSS content:encoded 兜底
    if wc < min_words and rss_content_html:
        rss_paragraphs = html_to_paragraphs(rss_content_html)
        rss_words = count_words(" ".join(rss_paragraphs))
        if rss_words > wc:
            paragraphs = rss_paragraphs
            wc = rss_words
            method = "rss_content"

    if not result.cover_image and text:
        result.cover_image = _pick_image(text)
    if not result.title:
        result.title = rss_title
    if not result.author:
        result.author = rss_author
    if not result.published_at:
        result.published_at = rss_published

    result.paragraphs = paragraphs
    result.word_count = wc
    result.method = method

    paywall_reason = detect_paywall(" ".join(paragraphs), http_status)
    if paywall_reason:
        result.status = "paywalled"
        result.error_message = paywall_reason
        return result

    if wc < min_words:
        result.status = "failed"
        result.error_message = f"正文过短（{wc} 词），抽取器：{method or 'none'}"
        return result

    result.status = "fetched"
    return result


async def extract_article(
    url: str,
    *,
    client: httpx.AsyncClient,
    rss_title: str = "",
    rss_author: str = "",
    rss_published: str = "",
    rss_content_html: str = "",
    min_words: int = 200,
) -> ExtractResult:
    """网络抽取入口：带重试的 GET + 纯函数抽取。"""

    from .base import fetch_with_retry

    resp = await fetch_with_retry(client, url, retries=2, scope="extract")
    if resp is None:
        return ExtractResult(status="failed", error_message="网络请求失败（超时/连接错误）", title=rss_title)

    # 非 HTML（PDF 等）直接判失败
    ctype = resp.headers.get("content-type", "").lower()
    if ctype and ("html" not in ctype and "xml" not in ctype and "text" not in ctype):
        return ExtractResult(
            status="failed",
            error_message=f"非 HTML 内容：{ctype}",
            title=rss_title,
            http_status=resp.status_code,
        )

    return extract_from_html(
        resp.text,
        url,
        http_status=resp.status_code,
        rss_title=rss_title,
        rss_author=rss_author,
        rss_published=rss_published,
        rss_content_html=rss_content_html,
        min_words=min_words,
    )
