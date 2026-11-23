"""生词高亮注入与安全词边界算法测试。"""

from __future__ import annotations

from src.builder import build_vocab_pattern, inject_vocab_highlights
from src.models import VocabItem


def _vocab(*terms: str) -> list[VocabItem]:
    return [VocabItem(id=f"v{i + 1}", term=t) for i, t in enumerate(terms)]


def test_highlight_respects_word_boundaries():
    html = inject_vocab_highlights(
        "She looked at the start of the article: art matters.",
        _vocab("art"),
    )
    # 只应命中独立的 art，不命中 start / article
    assert html.count('<mark class="vocab-term"') == 1
    assert ">art</mark>" in html
    assert "start" in html and ">start<" not in html
    assert "article" in html and ">article<" not in html


def test_highlight_prefers_longer_phrases_first():
    html = inject_vocab_highlights(
        "We take for granted the take of the scene.",
        _vocab("take", "take for granted"),
    )
    # 短语作为一个整体被标记，不会被拆成两段嵌套 mark
    assert html.count("<mark") == html.count("</mark>")
    assert "take for granted</mark>" in html
    assert "<mark" in html and html.count('<mark class="vocab-term"') == 2


def test_highlight_escapes_html_input():
    html = inject_vocab_highlights("<script>alert(1)</script> art", _vocab("art"))
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert ">art</mark>" in html


def test_highlight_is_case_insensitive_and_preserves_original_case():
    html = inject_vocab_highlights("Attention and ATTENTION both count.", _vocab("attention"))
    assert html.count("<mark") == 2
    assert ">Attention</mark>" in html
    assert ">ATTENTION</mark>" in html


def test_highlight_no_vocab_returns_escaped_text():
    assert inject_vocab_highlights("A & B", []) == "A &amp; B"


def test_highlight_handles_multiword_and_hyphen_terms():
    html = inject_vocab_highlights(
        "This is a well-known attentional commons, as it were.",
        _vocab("attentional commons"),
    )
    assert html.count("<mark") == 1
    assert "attentional commons</mark>" in html


def test_no_nested_marks_possible():
    vocab = _vocab("attention", "attentional commons", "commons")
    html = inject_vocab_highlights("the attentional commons of attention", vocab)
    # 单遍替换：不允许出现 mark 嵌套
    assert "<mark" in html
    assert html.count("<mark") == html.count("</mark>")
    assert "<mark" not in html.replace('<mark class="vocab-term"', "", html.count('<mark class="vocab-term"'))


def test_build_vocab_pattern_empty():
    pattern, mapping = build_vocab_pattern([])
    assert pattern is None
    assert mapping == {}


def test_build_vocab_pattern_dedupes_case_variants():
    pattern, mapping = build_vocab_pattern(_vocab("Attention", "attention"))
    assert pattern is not None
    assert len(mapping) == 1


def test_highlight_renders_data_attributes():
    html = inject_vocab_highlights("an ephemeral thing", _vocab("ephemeral"))
    assert 'data-vocab-id="v1"' in html
    assert 'data-term="ephemeral"' in html
    assert 'tabindex="0"' in html
    assert 'role="button"' in html
