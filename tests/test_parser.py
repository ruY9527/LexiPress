"""解析器测试：规则降级、LLM 两阶段结构、JSON 容错、索引回填、失败降级。"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.models import RawArticle
from src.parser import (
    RuleOnlyParser,
    StudyParser,
    safe_json_loads,
    strip_json_fence,
)
from src.utils import iso_now, url_hash


def _raw(paragraphs: list[str] | None = None) -> RawArticle:
    paras = paragraphs or [
        "Attention was borrowed from the room: the fire, the child, the horizon that had to be scanned.",
        "The modern word carries a different weight. We speak of paying attention as though it were currency.",
        "What the metaphor obscures is the extent to which attention is built rather than held, "
        "and an attentional commons can be enclosed, depleted, or restored.",
    ]
    body = "\n\n".join(paras)
    return RawArticle(
        id="2026-11-23-test-attention",
        url_hash=url_hash("https://example.com/attention"),
        canonical_url="https://example.com/attention",
        source_id="test",
        source_name="Test Journal",
        title="The Architecture of Attention",
        author="Jane Doe",
        published_at="2026-11-23",
        fetched_at=iso_now(),
        paragraphs=paras,
        word_count=sum(len(p.split()) for p in paras),
        read_time_min=2,
        score=8.0,
    )


# ---------------------------------------------------------------------------
# JSON 容错
# ---------------------------------------------------------------------------


def test_strip_json_fence_handles_code_block():
    raw = '```json\n{"a": 1}\n```'
    assert json.loads(strip_json_fence(raw)) == {"a": 1}


def test_strip_json_fence_handles_plain_object():
    assert json.loads(strip_json_fence('{"a": 2}')) == {"a": 2}


def test_strip_json_fence_handles_surrounding_prose():
    raw = 'Here you go:\n{"a": 3, "b": [1,2]}\nHope this helps.'
    assert json.loads(strip_json_fence(raw)) == {"a": 3, "b": [1, 2]}


def test_strip_json_fence_handles_nested_braces_in_strings():
    raw = '{"text": "a } brace", "n": 1}'
    assert json.loads(strip_json_fence(raw)) == {"text": "a } brace", "n": 1}


def test_safe_json_loads_raises_on_garbage():
    with pytest.raises(ValueError):
        safe_json_loads("not json at all")


def test_safe_json_loads_raises_on_empty():
    with pytest.raises(ValueError):
        safe_json_loads("")


# ---------------------------------------------------------------------------
# RuleOnlyParser
# ---------------------------------------------------------------------------


def test_rule_parser_produces_valid_article():
    raw = _raw()
    parsed = RuleOnlyParser().parse(raw)

    assert parsed.id == raw.id
    assert parsed.parser_mode == "rule"
    assert len(parsed.paragraphs) == len(raw.paragraphs)
    assert all(p.zh == "" for p in parsed.paragraphs)
    assert parsed.difficulty.value in {"B1", "B2", "C1", "C2"}
    assert parsed.word_count > 0
    assert parsed.read_time_min >= 1
    assert parsed.overview.summary_zh
    assert isinstance(parsed.vocab, list)
    assert isinstance(parsed.sentences, list)


def test_rule_parser_vocab_has_para_index_within_range():
    raw = _raw()
    parsed = RuleOnlyParser().parse(raw, vocab_limit=8)
    for item in parsed.vocab:
        assert 0 <= item.para_index < len(raw.paragraphs)
        assert item.term.strip()


def test_rule_parser_is_deterministic():
    raw = _raw()
    a = RuleOnlyParser().parse(raw)
    b = RuleOnlyParser().parse(raw)
    assert [v.term for v in a.vocab] == [v.term for v in b.vocab]
    assert a.difficulty == b.difficulty


def test_rule_parser_handles_empty_paragraphs():
    raw = _raw(["", ""])
    parsed = RuleOnlyParser().parse(raw)
    assert parsed.paragraphs[0].en == ""
    assert parsed.overview.summary_zh  # 有兜底文案


# ---------------------------------------------------------------------------
# StudyParser 降级
# ---------------------------------------------------------------------------


def test_study_parser_degrades_without_api_key(monkeypatch):
    parser = StudyParser()
    # 强制无 key
    parser.settings.llm.api_key = ""
    assert parser.llm_available is False

    parsed = asyncio.run(parser.parse_article(_raw()))
    assert parsed.parser_mode == "rule"
    assert parsed.paragraphs


def test_study_parser_force_rule_only():
    parser = StudyParser()
    parsed = asyncio.run(parser.parse_article(_raw(), force_rule_only=True))
    assert parsed.parser_mode == "rule"


def test_study_parser_degrades_on_llm_exception():
    parser = StudyParser()
    parser.settings.llm.api_key = "fake-key"
    parser.settings.llm.enabled = True
    assert parser.llm_available is True

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated upstream failure")

    parser._chat_json = boom  # type: ignore[assignment]
    parsed = asyncio.run(parser.parse_article(_raw()))
    assert parsed.parser_mode == "rule"
    assert getattr(parsed, "llm_error", "")


def test_study_parser_llm_happy_path_translation_alignment():
    """两阶段 LLM 路径：验证按 index 回填，绝不串段。"""

    parser = StudyParser()
    parser.settings.llm.api_key = "fake-key"
    parser.settings.llm.enabled = True

    calls: list[str] = []

    async def fake_chat(system: str, user: str, **kwargs):
        calls.append(system[:20])
        if "翻译" in system or "translation" in system.lower():
            # 故意倒序返回，验证按 index 回填而非依赖数组顺序
            payload = json.loads(user.split("输入段落：")[-1])
            return {
                "translations": [
                    {"index": item["index"], "zh": f"第{item['index'] + 1}段译文"} for item in reversed(payload)
                ]
            }
        return {
            "overview": {
                "summary_zh": "核心导读",
                "takeaways": ["要点一", "要点二"],
                "background": "背景",
                "structure": "结构",
            },
            "vocab": [
                {
                    "term": "attention",
                    "phonetic": "/əˈten.ʃən/",
                    "pos": "n.",
                    "meaning_zh": "注意力",
                    "note": "常用搭配 pay attention to",
                    "para_index": 0,
                },
                {
                    "term": "attentional commons",
                    "phonetic": "",
                    "pos": "phrase",
                    "meaning_zh": "注意力公地",
                    "note": "",
                    "para_index": 2,
                },
            ],
            "sentences": [
                {
                    "en": "What the metaphor obscures is the extent to which attention is built rather than held in place.",
                    "structure": "主语从句 + 定语从句",
                    "zh": "这个比喻所遮蔽的，是注意力在多大程度上是被建造出来的。",
                }
            ],
        }

    parser._chat_json = fake_chat  # type: ignore[assignment]
    raw = _raw()
    parsed = asyncio.run(parser.parse_article(raw))

    assert parsed.parser_mode == "llm"
    # 三个段落都应有译文，且按 index 精确对齐（与返回顺序无关）
    assert len(parsed.paragraphs) == 3
    assert [p.zh for p in parsed.paragraphs] == ["第1段译文", "第2段译文", "第3段译文"]
    assert parsed.overview.summary_zh == "核心导读"
    assert len(parsed.vocab) == 2
    assert parsed.sentences[0].zh


def test_study_parser_drops_vocab_not_present_in_body():
    parser = StudyParser()
    parser.settings.llm.api_key = "fake-key"
    parser.settings.llm.enabled = True

    async def fake_chat(system: str, user: str, **kwargs):
        if "翻译" in system:
            start = json.loads(user.split("输入段落：")[-1])[0]["index"]
            return {"translations": [{"index": start, "zh": "译文"}]}
        return {
            "overview": {"summary_zh": "s", "takeaways": []},
            "vocab": [
                {"term": "attention", "meaning_zh": "注意力", "para_index": 0},
                {"term": "zzzznotpresent", "meaning_zh": "不存在", "para_index": 0},
            ],
            "sentences": [{"en": "Attention was borrowed.", "structure": "主干", "zh": "注意力是借来的。"}],
        }

    parser._chat_json = fake_chat  # type: ignore[assignment]
    parsed = asyncio.run(parser.parse_article(_raw()))
    terms = [v.term for v in parsed.vocab]
    assert "attention" in terms
    assert "zzzznotpresent" not in terms


def test_study_parser_fixes_para_index_when_wrong():
    parser = StudyParser()
    parser.settings.llm.api_key = "fake-key"
    parser.settings.llm.enabled = True

    async def fake_chat(system: str, user: str, **kwargs):
        if "翻译" in system:
            start = json.loads(user.split("输入段落：")[-1])[0]["index"]
            return {"translations": [{"index": start, "zh": "译文"}]}
        return {
            "overview": {"summary_zh": "s", "takeaways": []},
            "vocab": [{"term": "currency", "meaning_zh": "货币", "para_index": 0}],  # 实际在第 2 段
            "sentences": [{"en": "Attention was borrowed.", "structure": "s", "zh": "z"}],
        }

    parser._chat_json = fake_chat  # type: ignore[assignment]
    parsed = asyncio.run(parser.parse_article(_raw()))
    assert parsed.vocab[0].para_index == 1


def test_truncate_body_keeps_head_and_tail():
    body = "\n\n".join([f"Paragraph {i} " + "word " * 200 for i in range(10)])
    truncated = StudyParser._truncate_body(body, max_words=500)
    assert "…[truncated]" in truncated
    assert "Paragraph 0" in truncated
    assert len(truncated.split()) < len(body.split())


def test_truncate_body_noop_when_short():
    body = "short body"
    assert StudyParser._truncate_body(body, max_words=500) == body
