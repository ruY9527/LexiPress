"""高端杂志风静态站生成器（SiteBuilder）。

对应 `plan/02` 全部视觉/交互规范与 `plan/04` 第 1.4 / 1.6 节：
- 编译期安全生词高亮注入（html.escape → 词边界单遍替换）。
- 所有资源与内链 100% 通过 `{{ base_url }}` 拼接。
- 产物包含 `.nojekyll` / `404.html` / `search-index.json` / Clean URL 文章页 / static 资源。
"""

from __future__ import annotations

import html
import json
import re
import shutil
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import (
    DIST_DIR,
    STATIC_SRC_DIR,
    SITE_TEMPLATES_DIR,
    atomic_write_json,
    atomic_write_text,
    ensure_dirs,
    load_feeds,
    load_settings,
)
from .models import ArticleOverview, BuildSummary, ParsedArticle, VocabItem
from .storage import Storage
from .utils import count_words, format_date_display, truncate

# ---------------------------------------------------------------------------
# 生词高亮注入（编译期）
# ---------------------------------------------------------------------------


def build_vocab_pattern(vocab: Iterable[VocabItem | dict[str, Any]]) -> tuple[re.Pattern[str] | None, dict[str, dict[str, Any]]]:
    """构造单遍联合正则 + term→vocab 映射。

    - 按 term 长度从长到短排序（先短语后单词）。
    - 词边界使用 `(?<![A-Za-z])` / `(?![A-Za-z])`，避免 `art` 命中 `start`。
    """

    mapping: dict[str, dict[str, Any]] = {}
    terms: list[str] = []
    for idx, item in enumerate(vocab):
        if isinstance(item, dict):
            term = str(item.get("term") or "").strip()
            vid = str(item.get("id") or f"v{idx + 1}")
            payload = dict(item)
            payload["id"] = vid
        else:
            term = item.term.strip()
            vid = item.id or f"v{idx + 1}"
            payload = item.model_dump(mode="json")
            payload["id"] = vid
        if not term:
            continue
        key = term.lower()
        if key in mapping:
            continue
        mapping[key] = payload
        terms.append(term)

    if not terms:
        return None, {}

    terms.sort(key=len, reverse=True)
    joined = "|".join(re.escape(t) for t in terms)
    pattern = re.compile(r"(?<![A-Za-z])(" + joined + r")(?![A-Za-z])", re.IGNORECASE)
    return pattern, mapping


def inject_vocab_highlights(text: str, vocab: Iterable[VocabItem | dict[str, Any]]) -> str:
    """把英文段落转为安全 HTML，并为生词插入 `<mark class="vocab-term">`。

    关键：先 `html.escape`（保证输入是纯文本、绝不破坏既有标签），
    再单遍 `re.sub`（不会二次扫描已插入的标签），从根本上杜绝嵌套与属性污染。
    """

    if not text:
        return ""
    escaped = html.escape(text, quote=False)
    pattern, mapping = build_vocab_pattern(vocab)
    if pattern is None:
        return escaped

    def _replace(match: re.Match[str]) -> str:
        matched = match.group(0)
        item = mapping.get(matched.lower())
        if not item:
            return matched
        vid = html.escape(str(item.get("id") or ""), quote=True)
        term_attr = html.escape(str(item.get("term") or matched), quote=True)
        return (
            f'<mark class="vocab-term" data-vocab-id="{vid}" '
            f'data-term="{term_attr}" tabindex="0" role="button">{matched}</mark>'
        )

    return pattern.sub(_replace, escaped)


# ---------------------------------------------------------------------------
# 构建器
# ---------------------------------------------------------------------------


class SiteBuilder:
    """读取 `data/index.json` + `data/parsed/*.json`，渲染完整 `dist/`。"""

    def __init__(self, storage: Storage | None = None, settings=None):
        self.settings = settings or load_settings()
        self.storage = storage or Storage()
        ensure_dirs()
        self.env = Environment(
            loader=FileSystemLoader(str(SITE_TEMPLATES_DIR)),
            autoescape=select_autoescape(enabled_extensions=("html", "xml"), default_for_string=False),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.globals["base_url"] = self.settings.base_url
        self.env.globals["site"] = self.settings.site
        self.env.filters["date_display"] = format_date_display

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def build(self, output_dir: Path | str | None = None) -> BuildSummary:
        started = time.monotonic()
        out = Path(output_dir) if output_dir else DIST_DIR
        warnings: list[str] = []

        articles = self._collect_articles(warnings)
        out.mkdir(parents=True, exist_ok=True)
        (out / "articles").mkdir(exist_ok=True)
        (out / "static").mkdir(exist_ok=True)

        # 清理历史文章目录，避免已下线文章残留
        self._clean_article_dirs(out, {a["id"] for a in articles})

        featured, rest = self._split_featured(articles)
        page_count = 0

        # 首页
        html_text = self.env.get_template("index.html").render(
            featured=featured,
            articles=rest,
            all_articles=articles,
            sources=self._source_facets(articles),
            difficulties=self._difficulty_facets(articles),
            issue_label=self._issue_label(articles),
            total_count=len(articles),
            page="home",
            build_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        atomic_write_text(out / "index.html", html_text)
        page_count += 1

        # About 页（Clean URL: /about/）
        about_dir = out / "about"
        about_dir.mkdir(exist_ok=True)
        atomic_write_text(
            about_dir / "index.html",
            self.env.get_template("about.html").render(
                page="about",
                nav_articles=articles[:8],
                build_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )
        page_count += 1

        # 文章页
        for idx, article in enumerate(articles):
            prev_article = articles[idx - 1] if idx > 0 else None
            next_article = articles[idx + 1] if idx + 1 < len(articles) else None
            article_dir = out / "articles" / article["id"]
            article_dir.mkdir(parents=True, exist_ok=True)
            page_html = self.env.get_template("article.html").render(
                article=article,
                paragraphs=article["paragraphs_html"],
                vocab=article["vocab"],
                sentences=article["sentences"],
                overview=article["overview"],
                prev_article=prev_article,
                next_article=next_article,
                page="article",
                nav_articles=articles[:8],
                build_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            )
            atomic_write_text(article_dir / "index.html", page_html)
            page_count += 1

        # 404
        atomic_write_text(
            out / "404.html",
            self.env.get_template("404.html").render(
                page="404",
                nav_articles=articles[:8],
                build_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )
        page_count += 1

        # .nojekyll（GitHub Pages 必须）
        atomic_write_text(out / ".nojekyll", "")

        # search-index.json
        atomic_write_json(out / "search-index.json", self._search_index(articles))

        # 静态资源
        self._copy_static(out)

        duration = round(time.monotonic() - started, 2)
        return BuildSummary(
            ok=True,
            output_dir=str(out),
            article_count=len(articles),
            page_count=page_count,
            duration_sec=duration,
            base_url=self.settings.base_url,
            generated_at=datetime.now().replace(microsecond=0).isoformat(),
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 数据装配
    # ------------------------------------------------------------------

    def _collect_articles(self, warnings: list[str]) -> list[dict[str, Any]]:
        """以 `data/index.json` 为发布真理源装配页面数据。

        - 只有出现在 index.json 且存在 `data/parsed/<id>.json` 的文章才会上线，
          这样后台的「上线 / 下线」开关才真正生效（parsed 文件可保留为候选资产）。
        - index 中登记但缺 parsed 文件的条目：告警并跳过，不建立空壳页。
        """

        index_entries = self.storage.load_index()
        articles: list[dict[str, Any]] = []
        seen: set[str] = set()

        for entry in index_entries:
            aid = str(entry.get("id") or "").strip()
            if not aid or aid in seen:
                continue
            raw = self.storage.load_parsed(aid)
            if not raw:
                warnings.append(f"index.json 中的 {aid} 缺少 data/parsed/{aid}.json，已跳过")
                continue
            try:
                parsed = ParsedArticle(**raw)
            except Exception as exc:  # noqa: BLE001 - 单个坏资产不应中断整站构建
                warnings.append(f"{aid} 解析资产校验失败（{exc}），已跳过")
                continue
            seen.add(aid)
            articles.append(self._to_view(parsed, entry, warnings))

        articles.sort(
            key=lambda a: (a["published_at"] or "", a["score"] or 0.0),
            reverse=True,
        )
        return articles

    def _to_view(self, parsed: ParsedArticle, entry: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        vocab_payload = [v.model_dump(mode="json") for v in parsed.vocab]
        paragraphs_html = [
            {
                "index": p.index,
                "html": inject_vocab_highlights(p.en, vocab_payload),
                "zh": p.zh,
                "plain": p.en,
            }
            for p in parsed.paragraphs
        ]

        paragraphs_en_words = count_words("\n\n".join(p.en for p in parsed.paragraphs))
        word_count = parsed.word_count or int(entry.get("word_count") or 0) or paragraphs_en_words

        excerpt = ""
        if parsed.overview.summary_zh.strip():
            excerpt = parsed.overview.summary_zh.strip()
        elif parsed.paragraphs:
            excerpt = truncate(parsed.paragraphs[0].en, 180)
        if not excerpt:
            excerpt = truncate(parsed.title, 120)

        cover = parsed.cover_image or str(entry.get("cover_image") or "")
        published = parsed.published_at or str(entry.get("published_at") or "")

        return {
            "id": parsed.id,
            "title": parsed.title,
            "source": parsed.source or str(entry.get("source") or ""),
            "source_id": parsed.source_id or str(entry.get("source_id") or ""),
            "author": parsed.author,
            "published_at": published,
            "published_display": format_date_display(published),
            "tags": parsed.tags or list(entry.get("tags") or []),
            "difficulty": parsed.difficulty.value if hasattr(parsed.difficulty, "value") else str(parsed.difficulty),
            "word_count": word_count,
            "read_time_min": parsed.read_time_min or max(1, round(word_count / 200)),
            "score": round(float(parsed.score or entry.get("score") or 0.0), 2),
            "cover_image": cover,
            "original_url": parsed.original_url or str(entry.get("canonical_url") or ""),
            "audio_url": parsed.audio_url,
            "parser_mode": parsed.parser_mode,
            "vocab": vocab_payload,
            "vocab_count": len(parsed.vocab),
            "sentences": [s.model_dump(mode="json") for s in parsed.sentences],
            "overview": parsed.overview.model_dump(mode="json"),
            "paragraphs_html": paragraphs_html,
            "paragraph_count": len(parsed.paragraphs),
            "excerpt": excerpt,
            "has_translation": parsed.has_translation,
            "has_vocab": parsed.has_vocab,
            "url": f"{self.settings.base_url}/articles/{parsed.id}/",
            "first_letter": (parsed.title[:1] or "L").upper(),
            "kicker": (parsed.paragraphs[0].en.strip()[:150] + "…") if parsed.paragraphs and len(parsed.paragraphs[0].en) > 150 else (parsed.paragraphs[0].en.strip() if parsed.paragraphs else ""),
        }

    def _split_featured(self, articles: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Hero 头条：最新日期中评分最高者。"""

        if not articles:
            return None, []
        latest_date = max((a["published_at"] or "") for a in articles)
        same_day = [a for a in articles if (a["published_at"] or "") == latest_date]
        featured = max(same_day, key=lambda a: a["score"])
        rest = [a for a in articles if a["id"] != featured["id"]]
        return featured, rest

    def _source_facets(self, articles: list[dict[str, Any]]) -> list[dict[str, str]]:
        seen: dict[str, str] = {}
        for a in articles:
            sid = a["source_id"] or a["source"] or "unknown"
            if sid not in seen:
                seen[sid] = a["source"] or sid
        return [{"id": sid, "name": name} for sid, name in seen.items()]

    def _difficulty_facets(self, articles: list[dict[str, Any]]) -> list[str]:
        order = {"B1": 0, "B2": 1, "C1": 2, "C2": 3}
        levels = {a["difficulty"] for a in articles if a["difficulty"]}
        return sorted(levels, key=lambda x: order.get(x, 9))

    def _issue_label(self, articles: list[dict[str, Any]]) -> str:
        if articles:
            latest = max(a["published_at"] or "" for a in articles)
            display = format_date_display(latest)
            if display:
                return f"ISSUE · {display}"
        return f"ISSUE · {format_date_display(date.today().isoformat())}"

    def _clean_article_dirs(self, out: Path, keep: set[str]) -> None:
        root = out / "articles"
        if not root.exists():
            return
        for child in root.iterdir():
            if child.is_dir() and child.name not in keep:
                shutil.rmtree(child, ignore_errors=True)

    def _search_index(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        index: list[dict[str, Any]] = []
        for a in articles:
            index.append(
                {
                    "id": a["id"],
                    "title": a["title"],
                    "source": a["source"],
                    "tags": a["tags"],
                    "difficulty": a["difficulty"],
                    "published_at": a["published_at"],
                    "url": a["url"],
                    "excerpt": truncate(a["excerpt"], 160),
                    "vocab": [v.get("term", "") for v in a["vocab"]][:40],
                }
            )
        return index

    def _copy_static(self, out: Path) -> None:
        target = out / "static"
        if not STATIC_SRC_DIR.exists():
            return
        for src in STATIC_SRC_DIR.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(STATIC_SRC_DIR)
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
