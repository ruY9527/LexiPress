"""英语精读解析器：StudyParser（LLM 两阶段）+ RuleOnlyParser（无 Key 优雅降级）。

对应 `plan/04` 第 1.2 / 1.3 节的闭环要求：
- 阶段 A：分批、带显式 `index` 的逐段翻译，按 index 精确回填，杜绝错位。
- 阶段 B：全篇导读 / 生词 / 长难句提炼（超长文智能截断首尾）。
- 返回文本做 ```json 围栏剥离 + Pydantic v2 校验，失败指数退避重试。
- `LLM_API_KEY` 缺失或全部重试失败 → 自动降级 `RuleOnlyParser`，仍产出合法标准 JSON。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .config import load_settings
from .models import (
    ArticleOverview,
    Difficulty,
    ParagraphPair,
    ParsedArticle,
    RawArticle,
    SentenceAnalysis,
    VocabItem,
    utc_now_iso,
)
from .utils import (
    advanced_candidates,
    clean_text,
    count_words,
    estimate_difficulty,
    iso_now,
    read_time_minutes,
    split_sentences,
    truncate,
)

# ---------------------------------------------------------------------------
# JSON 容错提取
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def strip_json_fence(text: str) -> str:
    """剥离 ```json ... ``` 围栏与前后噪音，返回最可能的 JSON 片段。"""

    if not text:
        return ""
    raw = text.strip()
    match = _FENCE_RE.search(raw)
    if match:
        raw = match.group(1).strip()
    if raw and raw[0] in "{[":
        # 找到配对的结束括号
        opener = raw[0]
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_str = False
        escape = False
        for idx, ch in enumerate(raw):
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return raw[: idx + 1]
        return raw
    # 首字符不是括号：截取第一个 { 到最后一个 }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        return raw[start : end + 1]
    return raw


def safe_json_loads(text: str) -> Any:
    cleaned = strip_json_fence(text)
    if not cleaned:
        raise ValueError("空响应")
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

TRANSLATE_SYSTEM = (
    "你是资深英中翻译，专精高质量外刊（经济学人、Aeon、MIT Tech Review）长文的精准翻译。"
    "要求：译文地道、克制、无损信息，保留原文语气与逻辑连接，不使用口语化网络用语；"
    "不添加解释、不合并段落、不省略内容。严格按输入 index 一一对应输出。"
)

TRANSLATE_USER_TEMPLATE = """请把下面 {count} 个段落逐一翻译成简体中文。

要求：
1. 必须返回 JSON 对象，形如 {{"translations": [{{"index": 0, "zh": "译文"}}, ...]}}。
2. index 必须与输入完全一致，禁止新增、合并或遗漏任何 index。
3. 每个 zh 字段只放该段译文本身，不要包含 index、原文或任何说明文字。

输入段落：
{payload}"""

STUDY_SYSTEM = (
    "你是顶级英语精读教练，服务对象是希望通过外刊精读提升到 C1/C2 的中文母语学习者。"
    "你的分析必须精准、克制、可验证：音标用 IPA，词性与释义贴合当前语境，长难句拆解要指出真实语法成分。"
    "只输出严格合法的 JSON。"
)

STUDY_USER_TEMPLATE = """请对下面这篇英文外刊文章做精读提炼，并严格按给定 JSON Schema 输出。

文章标题：{title}
来源：{source}
难度参考：{difficulty}
全文（可能已被截断，末尾标注 …[truncated]）：

\"\"\"
{body}
\"\"\"

输出 JSON Schema（字段名必须完全一致，禁止额外包裹层）：
{{
  "overview": {{
    "summary_zh": "3 句话以内的中文核心导读",
    "takeaways": ["要点一", "要点二", "要点三"],
    "background": "作者背景与写作语境，1-2 句中文",
    "structure": "文章结构脉络，如：现象切入 → 机制解释 → 反例 → 结论，1-2 句中文"
  }},
  "vocab": [
    {{
      "term": "原文中真实出现的词或短语（原形或原文形态均可，必须能在正文中按词边界找到）",
      "phonetic": "/IPA/",
      "pos": "n. / v. / adj. / adv. / phrase / idiom",
      "meaning_zh": "贴合当前语境的中文释义",
      "note": "简短用法或搭配提示（可为空字符串）",
      "para_index": 0
    }}
  ],
  "sentences": [
    {{
      "en": "原文中的完整长难句（必须逐字摘自正文）",
      "structure": "主干：... | 修饰：... | 从句：...",
      "zh": "地道中文意译"
    }}
  ]
}}

硬性要求：
1. vocab 恰好 {vocab_min}~{vocab_max} 条，优先高价值、地道、对 C1 学习者有增量的表达；term 不得是 the/a/of 这类功能词。
2. sentences 恰好 {sent_min}~{sent_max} 条，必须是真的复杂句（含从句、插入语、倒装或长修饰）。
3. para_index 为该词/句首次出现的段落序号（从 0 开始），不确定填 0。
4. 全部中文用简体中文；不要输出 Markdown、不要输出解释。
"""


# ---------------------------------------------------------------------------
# 结果容器
# ---------------------------------------------------------------------------


@dataclass
class LLMCallStats:
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


# ---------------------------------------------------------------------------
# RuleOnlyParser
# ---------------------------------------------------------------------------


class RuleOnlyParser:
    """无 LLM 时的规则降级解析器：产出合法、可发布的 ParsedArticle。"""

    def __init__(self, settings=None):
        self.settings = settings or load_settings()

    def parse(self, raw: RawArticle, *, vocab_limit: int = 12, sentence_limit: int = 4) -> ParsedArticle:
        paragraphs = [ParagraphPair(index=i, en=p, zh="") for i, p in enumerate(raw.paragraphs)]
        body = raw.body_text
        word_count = raw.word_count or count_words(body)
        level, vocab_rate = estimate_difficulty(body)
        difficulty = Difficulty(level)

        vocab = self._build_vocab(raw.paragraphs, vocab_limit)
        sentences = self._build_sentences(raw.paragraphs, sentence_limit)
        overview = self._build_overview(raw, word_count, difficulty)

        return ParsedArticle(
            id=raw.id,
            url_hash=raw.url_hash,
            title=raw.title,
            source=raw.source_name,
            source_id=raw.source_id,
            author=raw.author,
            published_at=raw.published_at,
            original_url=raw.canonical_url,
            cover_image=raw.cover_image,
            tags=list(raw.tags) or self._derive_tags(raw),
            difficulty=difficulty,
            word_count=word_count,
            read_time_min=raw.read_time_min or read_time_minutes(word_count),
            score=raw.score,
            audio_url="",
            parsed_at=iso_now(),
            parser_mode="rule",
            overview=overview,
            paragraphs=paragraphs,
            vocab=vocab,
            sentences=sentences,
        )

    # ---- 内部 ----

    def _build_vocab(self, paragraphs: list[str], limit: int) -> list[VocabItem]:
        items: list[VocabItem] = []
        used: set[str] = set()
        for idx, para in enumerate(paragraphs):
            if len(items) >= limit:
                break
            for term in advanced_candidates(para, limit=6):
                if term in used or len(items) >= limit:
                    continue
                used.add(term)
                items.append(
                    VocabItem(
                        id=f"v{len(items) + 1}",
                        term=term,
                        phonetic="",
                        pos=_guess_pos(term),
                        meaning_zh="",
                        note="",
                        para_index=idx,
                    )
                )
        return items

    def _build_sentences(self, paragraphs: list[str], limit: int) -> list[SentenceAnalysis]:
        picked: list[SentenceAnalysis] = []
        for para in paragraphs:
            for sent in split_sentences(para):
                words = count_words(sent)
                if words < 24 or words > 70:
                    continue
                picked.append(
                    SentenceAnalysis(
                        en=clean_text(sent),
                        structure=f"共 {words} 词 · {len(sent.split(','))} 个逗号分句（规则模式未做语法拆解）",
                        zh="",
                    )
                )
                if len(picked) >= limit:
                    return picked
        return picked

    def _build_overview(self, raw: RawArticle, word_count: int, difficulty: Difficulty) -> ArticleOverview:
        first = raw.paragraphs[0] if raw.paragraphs else ""
        summary = truncate(clean_text(raw.summary_hint or first), 220)
        if not summary:
            summary = f"{raw.source_name} 文章，共 {word_count} 词，难度约 {difficulty.value}。"
        takeaways: list[str] = []
        if raw.paragraphs:
            takeaways.append(truncate(raw.paragraphs[0], 120))
            if len(raw.paragraphs) > 1:
                takeaways.append(truncate(raw.paragraphs[len(raw.paragraphs) // 2], 120))
            if len(raw.paragraphs) > 2:
                takeaways.append(truncate(raw.paragraphs[-1], 120))
        return ArticleOverview(
            summary_zh=summary,
            takeaways=[t for t in takeaways if t][:3],
            background=f"来自 {raw.source_name}，发布于 {raw.published_at}。",
            structure=f"全文 {len(raw.paragraphs)} 段：开篇引入 → 主体论证 → 收束结论（规则模式自动推断）。",
        )

    def _derive_tags(self, raw: RawArticle) -> list[str]:
        if raw.tags:
            return raw.tags
        return []


# ---------------------------------------------------------------------------
# StudyParser
# ---------------------------------------------------------------------------


class StudyParser:
    """LLM 精读解析器，带自动降级。"""

    def __init__(self, settings=None, client: Any | None = None):
        self.settings = settings or load_settings()
        self.rule_parser = RuleOnlyParser(self.settings)
        self.stats = LLMCallStats()
        self._client = client
        self._client_ready = client is not None

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    @property
    def llm_available(self) -> bool:
        return self.settings.llm.usable

    async def parse_article(self, raw: RawArticle, force_rule_only: bool = False) -> ParsedArticle:
        """解析单篇；任何异常都回落到规则模式，绝不抛给调用方。"""

        if force_rule_only or not self.llm_available:
            return self.rule_parser.parse(raw)

        try:
            return await self._parse_with_llm(raw)
        except Exception as exc:  # noqa: BLE001 - 降级兜底
            self.stats.failures += 1
            fallback = self.rule_parser.parse(raw)
            fallback.parser_mode = "rule"
            # 把失败原因带出去，便于后台可见
            setattr(fallback, "llm_error", str(exc))
            return fallback

    # ------------------------------------------------------------------
    # LLM 实现
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client_ready and self._client is not None:
            return self._client
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=self.settings.llm.api_key,
            base_url=self.settings.llm.base_url,
            timeout=120.0,
            max_retries=0,
        )
        self._client_ready = True
        return self._client

    async def _chat_json(self, system: str, user: str, *, max_retries: int | None = None) -> Any:
        """调用 OpenAI 兼容接口并返回解析后的 JSON，带重试。"""

        retries = self.settings.llm.max_retries if max_retries is None else max_retries
        client = self._get_client()
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                self.stats.calls += 1
                resp = await client.chat.completions.create(
                    model=self.settings.llm.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=self.settings.llm.temperature,
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content or ""
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    self.stats.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                    self.stats.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
                return safe_json_loads(content)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < retries:
                    import asyncio

                    await asyncio.sleep(1.2 * (2**attempt))
                    continue
        raise RuntimeError(f"LLM 调用失败：{last_error}")

    async def _translate_paragraphs(self, paragraphs: Iterable[str]) -> list[str]:
        """阶段 A：分批逐段翻译，按 index 回填。"""

        texts = [p for p in paragraphs]
        result = ["" for _ in texts]
        batch_size = max(1, self.settings.llm.translate_batch_size)

        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            payload = json.dumps(
                [{"index": start + offset, "en": text} for offset, text in enumerate(batch)],
                ensure_ascii=False,
            )
            user = TRANSLATE_USER_TEMPLATE.format(count=len(batch), payload=payload)
            try:
                data = await self._chat_json(TRANSLATE_SYSTEM, user)
                translations = data.get("translations") if isinstance(data, dict) else None
                if not isinstance(translations, list):
                    continue
                for item in translations:
                    if not isinstance(item, dict):
                        continue
                    try:
                        idx = int(item.get("index"))
                    except (TypeError, ValueError):
                        continue
                    zh = str(item.get("zh") or "").strip()
                    if 0 <= idx < len(result) and zh:
                        result[idx] = zh
            except Exception:  # noqa: BLE001 - 单批失败保留空译文，不影响其它批
                continue

        return result

    async def _extract_study(self, raw: RawArticle, difficulty: Difficulty) -> tuple[ArticleOverview, list[VocabItem], list[SentenceAnalysis]]:
        """阶段 B：全篇导读 / 生词 / 长难句。"""

        llm = self.settings.llm
        body = self._truncate_body(raw.body_text, llm.max_input_words)
        user = STUDY_USER_TEMPLATE.format(
            title=raw.title,
            source=raw.source_name,
            difficulty=difficulty.value,
            body=body,
            vocab_min=llm.vocab_min,
            vocab_max=llm.vocab_max,
            sent_min=llm.sentence_min,
            sent_max=llm.sentence_max,
        )
        data = await self._chat_json(STUDY_SYSTEM, user)
        if not isinstance(data, dict):
            raise ValueError("阶段 B 返回结构不是 JSON 对象")

        overview_raw = data.get("overview") or {}
        overview = ArticleOverview(
            summary_zh=str(overview_raw.get("summary_zh") or "").strip(),
            takeaways=[str(t).strip() for t in (overview_raw.get("takeaways") or []) if str(t).strip()][:5],
            background=str(overview_raw.get("background") or "").strip(),
            structure=str(overview_raw.get("structure") or "").strip(),
        )

        vocab: list[VocabItem] = []
        seen_terms: set[str] = set()
        for entry in data.get("vocab") or []:
            if not isinstance(entry, dict):
                continue
            term = str(entry.get("term") or "").strip()
            if not term or term.lower() in seen_terms:
                continue
            seen_terms.add(term.lower())
            try:
                para_index = int(entry.get("para_index") or 0)
            except (TypeError, ValueError):
                para_index = 0
            vocab.append(
                VocabItem(
                    id=f"v{len(vocab) + 1}",
                    term=term,
                    phonetic=str(entry.get("phonetic") or "").strip(),
                    pos=str(entry.get("pos") or "").strip(),
                    meaning_zh=str(entry.get("meaning_zh") or "").strip(),
                    note=str(entry.get("note") or "").strip(),
                    para_index=max(0, para_index),
                )
            )

        sentences: list[SentenceAnalysis] = []
        for entry in data.get("sentences") or []:
            if not isinstance(entry, dict):
                continue
            en = clean_text(str(entry.get("en") or ""))
            if not en:
                continue
            sentences.append(
                SentenceAnalysis(
                    en=en,
                    structure=str(entry.get("structure") or "").strip(),
                    zh=str(entry.get("zh") or "").strip(),
                )
            )

        if not vocab and not sentences:
            raise ValueError("阶段 B 未返回任何生词与长难句")

        return overview, vocab, sentences

    async def _parse_with_llm(self, raw: RawArticle) -> ParsedArticle:
        body = raw.body_text
        word_count = raw.word_count or count_words(body)
        level, _rate = estimate_difficulty(body)
        difficulty = Difficulty(level)

        translations = await self._translate_paragraphs(raw.paragraphs)
        overview, vocab, sentences = await self._extract_study(raw, difficulty)

        # 校正 para_index：确保 term 真的在该段出现
        vocab = self._fix_para_index(vocab, raw.paragraphs)
        # 过滤掉正文里找不到的 term（避免高亮算法空转）
        vocab = [v for v in vocab if _term_exists(v.term, body)] or vocab

        paragraphs = [
            ParagraphPair(index=i, en=text, zh=translations[i] if i < len(translations) else "")
            for i, text in enumerate(raw.paragraphs)
        ]

        return ParsedArticle(
            id=raw.id,
            url_hash=raw.url_hash,
            title=raw.title,
            source=raw.source_name,
            source_id=raw.source_id,
            author=raw.author,
            published_at=raw.published_at,
            original_url=raw.canonical_url,
            cover_image=raw.cover_image,
            tags=list(raw.tags),
            difficulty=difficulty,
            word_count=word_count,
            read_time_min=raw.read_time_min or read_time_minutes(word_count),
            score=raw.score,
            audio_url="",
            parsed_at=iso_now(),
            parser_mode="llm",
            overview=overview,
            paragraphs=paragraphs,
            vocab=vocab,
            sentences=sentences,
        )

    @staticmethod
    def _truncate_body(body: str, max_words: int) -> str:
        """超长文智能截断：保留前 60% 与后 40% 的段落。"""

        words = count_words(body)
        if words <= max_words:
            return body
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        if len(paragraphs) <= 2:
            return truncate(body, max_words * 6)
        head_target = int(len(paragraphs) * 0.6)
        head = paragraphs[:head_target]
        tail = paragraphs[-max(1, int(len(paragraphs) * 0.25)) :]
        return "\n\n".join(head) + "\n\n…[truncated]\n\n" + "\n\n".join(tail)

    @staticmethod
    def _fix_para_index(vocab: list[VocabItem], paragraphs: list[str]) -> list[VocabItem]:
        for item in vocab:
            term = item.term.strip()
            if not term:
                continue
            pattern = re.compile(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", re.IGNORECASE)
            if 0 <= item.para_index < len(paragraphs) and pattern.search(paragraphs[item.para_index]):
                continue
            for idx, para in enumerate(paragraphs):
                if pattern.search(para):
                    item.para_index = idx
                    break
        return vocab


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

_SUFFIX_POS = (
    ("tion", "n."),
    ("sion", "n."),
    ("ment", "n."),
    ("ness", "n."),
    ("ity", "n."),
    ("ance", "n."),
    ("ence", "n."),
    ("ism", "n."),
    ("ist", "n."),
    ("ous", "adj."),
    ("ful", "adj."),
    ("less", "adj."),
    ("able", "adj."),
    ("ible", "adj."),
    ("ive", "adj."),
    ("ical", "adj."),
    ("al", "adj."),
    ("ic", "adj."),
    ("ize", "v."),
    ("ise", "v."),
    ("ify", "v."),
    ("ate", "v."),
    ("ly", "adv."),
)


def _guess_pos(term: str) -> str:
    low = term.lower()
    if " " in low:
        return "phrase"
    for suffix, pos in _SUFFIX_POS:
        if low.endswith(suffix) and len(low) > len(suffix) + 3:
            return pos
    return ""


def _term_exists(term: str, body: str) -> bool:
    if not term or not body:
        return False
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(term.strip()) + r"(?![A-Za-z])", re.IGNORECASE)
    return bool(pattern.search(body))


# ---------------------------------------------------------------------------
# 批量解析服务（供后台 / CLI 复用）
# ---------------------------------------------------------------------------


class ParseService:
    """把候选文章 → ParsedArticle → 落盘 + 更新状态 的编排层。"""

    def __init__(self, storage, parser: StudyParser | None = None, settings=None):
        self.storage = storage
        self.settings = settings or load_settings()
        self.parser = parser or StudyParser(self.settings)

    async def parse_by_id(self, article_id: str, force_rule_only: bool = False, publish: bool = False) -> dict[str, Any]:
        row = self.storage.get_article(article_id)
        if not row:
            return {"ok": False, "message": f"文章 {article_id} 不存在"}
        raw = RawArticle(
            id=row["id"],
            url_hash=row["url_hash"],
            canonical_url=row["canonical_url"],
            source_id=row.get("source_id") or "",
            source_name=row.get("source_name") or "",
            title=row["title"],
            author=row.get("author") or "",
            published_at=row.get("published_at") or "",
            fetched_at=row.get("fetched_at") or "",
            cover_image=row.get("cover_image") or "",
            paragraphs=row.get("paragraphs") or [],
            word_count=int(row.get("word_count") or 0),
            read_time_min=int(row.get("read_time_min") or 0),
            score=float(row.get("score") or 0.0),
            tags=row.get("tags") or [],
        )
        if not raw.paragraphs:
            return {"ok": False, "message": "该文章没有正文段落，无法解析"}

        parsed = await self.parser.parse_article(raw, force_rule_only=force_rule_only)
        path = self.storage.export_parsed_article(parsed)
        self.storage.set_parsed_path(
            article_id,
            str(path),
            status="published" if publish else "parsed",
        )
        return {
            "ok": True,
            "id": parsed.id,
            "mode": parsed.parser_mode,
            "path": str(path),
            "vocab": len(parsed.vocab),
            "sentences": len(parsed.sentences),
            "translated": sum(1 for p in parsed.paragraphs if p.zh),
        }

    async def parse_many(self, article_ids: list[str], force_rule_only: bool = False, publish: bool = False) -> dict[str, Any]:
        parsed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for aid in article_ids:
            result = await self.parse_by_id(aid, force_rule_only=force_rule_only, publish=publish)
            if result.get("ok"):
                parsed.append(result)
            else:
                failed.append({"id": aid, "message": result.get("message", "")})
        return {"ok": not failed, "parsed": parsed, "failed": failed}
