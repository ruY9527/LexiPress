"""LexiPress 单元测试公共夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import RawArticle  # noqa: E402
from src.utils import iso_now, url_hash  # noqa: E402


@pytest.fixture()
def sample_raw() -> RawArticle:
    paragraphs = [
        "For most of human history, attention was not something a person owned outright. "
        "It was borrowed from the room: from the fire that had to be watched, the child who "
        "had to be minded, the horizon that had to be scanned for weather or riders.",
        "The modern word carries a different weight. We speak of paying attention, as though "
        "it were currency, and of spending it wisely, as though a day had a fixed exchange rate. "
        "This metaphor is not innocent.",
        "What the metaphor obscures is the extent to which attention is built rather than held. "
        "A room can be arranged so that conversation is easy and interruption is difficult, or "
        "the reverse. These are the architecture of an attentional commons.",
    ]
    body = "\n\n".join(paragraphs)
    words = len([w for w in body.replace("—", " ").split() if any(c.isalpha() for c in w)])
    return RawArticle(
        id="2026-11-23-test-attention",
        url_hash=url_hash("https://example.com/attention"),
        canonical_url="https://example.com/attention",
        source_id="test-source",
        source_name="Test Journal",
        title="The Architecture of Attention",
        author="Jane Doe",
        published_at="2026-11-23",
        fetched_at=iso_now(),
        paragraphs=paragraphs,
        word_count=words,
        read_time_min=2,
        score=8.5,
    )
