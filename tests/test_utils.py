"""URL 归一化、去重指纹、打分与词数工具测试。"""

from __future__ import annotations

from src.harvester.pipeline import compute_score, freshness_score, length_fit_score
from src.utils import (
    count_words,
    format_date_display,
    format_date_iso,
    is_probably_article_url,
    normalize_url,
    read_time_minutes,
    url_hash,
)


def test_normalize_url_strips_tracking_and_anchor():
    raw = "https://Example.com/Story/?utm_source=x&utm_medium=y&fbclid=abc&id=7#section"
    assert normalize_url(raw) == "https://example.com/Story?id=7"


def test_normalize_url_removes_trailing_slash_and_double_slashes():
    assert normalize_url("https://example.com/a//b/") == "https://example.com/a/b"
    # 根路径保留单个 "/"，否则 URL 不合法
    assert normalize_url("http://example.com") == "https://example.com/"
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_normalize_url_upgrades_scheme_relative():
    assert normalize_url("//example.com/x") == "https://example.com/x"


def test_url_hash_is_stable_across_tracking_variants():
    a = url_hash("https://example.com/post?utm_source=twitter")
    b = url_hash("https://example.com/post/")
    assert a == b
    assert len(a) == 64


def test_url_hash_differs_for_different_paths():
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")


def test_is_probably_article_url_blocks_noise():
    assert not is_probably_article_url("https://www.youtube.com/watch?v=1")
    assert not is_probably_article_url("https://github.com/foo/bar")
    assert not is_probably_article_url("https://example.com/file.pdf")
    assert is_probably_article_url("https://aeon.co/essays/some-title")


def test_count_words_and_read_time():
    text = "The quick brown fox jumps over the lazy dog."
    assert count_words(text) == 9
    assert read_time_minutes(0) == 0
    assert read_time_minutes(200) == 1
    assert read_time_minutes(201) == 2


def test_date_formatting_helpers():
    assert format_date_iso("Mon, 23 Nov 2026 10:00:00 GMT") == "2026-11-23"
    assert format_date_iso("2026-11-23T10:00:00Z") == "2026-11-23"
    assert format_date_display("2026-11-23") == "NOV 23, 2026"


def test_freshness_score_tiers():
    assert freshness_score("2099-01-01") == 1.0  # 未来时间视为最新
    assert freshness_score("2000-01-01") == 0.0  # 极旧
    assert freshness_score("not-a-date") == 0.5  # 无法解析给中性分


def test_length_fit_score_peaks_in_ideal_range():
    assert length_fit_score(1200) == 1.0
    assert length_fit_score(800) == 1.0
    assert length_fit_score(2800) == 1.0
    assert length_fit_score(300) < 0.3
    assert length_fit_score(6000) < 0.3
    assert length_fit_score(0) == 0.0


def test_compute_score_bounds_and_ordering():
    high = compute_score(1.0, "2099-01-01", 1500)
    low = compute_score(0.2, "2000-01-01", 200)
    assert 0.0 <= low <= high <= 10.0
    assert high > low
