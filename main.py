#!/usr/bin/env python
"""LexiPress 统一命令行入口。

用法：
    python main.py --admin                 # 启动本地可视化后台 + /LexiPress 预览
    python main.py --pipeline full         # 全自动：去重同步 → 采集 → 精选 → 解析 → 构建
    python main.py --crawl-only            # 仅采集入库（进入候选池）
    python main.py --build-only            # 仅基于 data/parsed/ 重建 dist/

可选参数：
    --limit N             覆盖每日解析篇数
    --force-rule-only     强制使用 RuleOnlyParser（不调 LLM）
    --port/--host         后台绑定地址（等价于 ADMIN_PORT / ADMIN_HOST）
    --source ID           只采集指定源（可重复）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.console import ensure_utf8_console  # noqa: E402

ensure_utf8_console()

# 注意：这里只导入「构建静态站」所需的最小依赖（builder/config/storage）。
# 采集器(harvester)、解析器(parser)、admin 后台等后端模块全部改为函数内惰性导入，
# 这样 `python main.py --build-only`（GitHub Actions 部署路径）无需安装
# trafilatura / feedparser / openai / fastapi 等后端重依赖。

from src.builder import SiteBuilder  # noqa: E402
from src.config import DIST_DIR, ensure_dirs, load_settings  # noqa: E402
from src.storage import Storage  # noqa: E402


def _banner(text: str) -> None:
    print()
    print("═" * 62)
    print(f"  {text}")
    print("═" * 62)


def _console_logger(entry: dict) -> None:
    ts = str(entry.get("ts", ""))[11:19]
    level = str(entry.get("level", "INFO")).ljust(5)
    print(f"  {ts} [{level}] {entry.get('message', '')}")


def _log(level: str, message: str, scope: str = "pipeline") -> None:
    """轻量日志封装：仅构建路径使用，避免导入 harvester 的 LogBus。"""

    try:
        from src.harvester.base import log as _bus_log

        _bus_log(level, message, scope=scope)
    except Exception:  # noqa: BLE001
        _console_logger({"ts": "", "level": level, "message": message})


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------


def _sync(storage: Storage, *, backfill_index: bool = False) -> None:
    """同步：index.json + parsed → 本地 DB（单向）。

    `index.json` 是发布真理源。默认不会把「有 parsed 文件但不在 index」的文章
    重新上线，否则后台的「下线」操作会被下次启动悄悄撤销。
    需要恢复这类离线资产时，显式加 `--backfill-index`。
    """

    stats = storage.sync_git_assets_to_db(backfill_index=backfill_index)
    _log(
        "INFO",
        f"同步完成：index {stats['index_entries']} 条 · parsed {stats['parsed_files']} 份 · "
        f"新增入库 {stats['inserted']} · 更新 {stats['updated']} · 离线保留 {stats['skipped']}",
        scope="sync",
    )
    if backfill_index and stats.get("backfilled"):
        _log("INFO", f"已把 {stats['backfilled']} 篇离线资产恢复进 index.json", scope="sync")


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------


def cmd_admin(args: argparse.Namespace) -> int:
    from src.admin.app import run as run_admin

    storage = Storage()
    _sync(storage, backfill_index=args.backfill_index)

    settings = load_settings()
    print()
    print(f"  解析模式：{'LLM（' + settings.llm.model + '）' if settings.llm.usable else '规则降级（未配置 LLM_API_KEY）'}")
    print(f"  阅读站预览：http://{settings.admin.host}:{settings.admin.port}/LexiPress/")
    run_admin(host=args.host, port=args.port, reload=args.reload)
    return 0


async def cmd_crawl(args: argparse.Namespace) -> int:
    from src.harvester.pipeline import HarvesterPipeline  # 惰性导入，避免构建路径加载后端依赖

    _banner("LexiPress · 采集入库")
    ensure_dirs()
    storage = Storage()
    _sync(storage, backfill_index=args.backfill_index)

    settings = load_settings()
    pipeline = HarvesterPipeline(storage=storage, settings=settings)
    result = await pipeline.run_all(
        trigger_type=args.trigger or "manual",
        log_cb=_console_logger,
        source_ids=args.source or None,
    )

    print()
    print(f"  发现 {result.discovered_count} 条 → 新增 {result.fetched_count} 篇")
    print(f"  跳过 {result.skipped_count} · 失败 {result.failed_count} · 付费墙 {result.paywalled_count}")
    print(f"  耗时 {result.duration_sec}s · run_id={result.run_id}")

    counts = storage.count_by_status()
    print(f"  当前候选池：{counts}")
    print()
    print("  下一步：python main.py --admin （在后台精选并解析）")
    return 0


async def cmd_full(args: argparse.Namespace) -> int:
    from src.harvester.pipeline import HarvesterPipeline  # 惰性导入
    from src.parser import ParseService, StudyParser  # 惰性导入

    _banner("LexiPress · 全自动流水线")
    ensure_dirs()

    settings = load_settings()
    storage = Storage()
    _sync(storage, backfill_index=args.backfill_index)

    # 1) 采集
    print("\n▸ [1/4] 采集全源")
    pipeline = HarvesterPipeline(storage=storage, settings=settings)
    result = await pipeline.run_all(trigger_type="schedule", log_cb=_console_logger)
    print(
        f"  发现 {result.discovered_count} · 新增 {result.fetched_count} · "
        f"跳过 {result.skipped_count} · 失败 {result.failed_count}"
    )

    # 2) 精选
    print("\n▸ [2/4] 按推荐分精选")
    limit = args.limit or settings.harvester.daily_publish_limit
    candidates = pipeline.select_top_candidates(limit=limit)
    if not candidates:
        print("  没有符合条件的候选（可能都已处理或篇幅不符），跳过解析。")
    else:
        for c in candidates:
            print(f"  ★ {c['score']:.2f} · {c['word_count']}词 · {c['title'][:64]}")

    # 3) 解析
    print("\n▸ [3/4] 精读解析")
    parser = StudyParser(settings)
    if not parser.llm_available:
        print("  未检测到 LLM_API_KEY → 自动降级 RuleOnlyParser")
    else:
        print(f"  LLM：{settings.llm.model} @ {settings.llm.base_url}")

    service = ParseService(storage=storage, parser=parser, settings=settings)
    parsed_count = 0
    for c in candidates:
        print(f"  ⚙ 解析 {c['id']} …", end=" ", flush=True)
        outcome = await service.parse_by_id(c["id"], force_rule_only=args.force_rule_only, publish=True)
        if outcome.get("ok"):
            parsed_count += 1
            print(
                f"OK（{outcome['mode']} · 生词 {outcome['vocab']} · 长难句 {outcome['sentences']} · "
                f"译文 {outcome['translated']} 段）"
            )
        else:
            print(f"失败：{outcome.get('message')}")

    if parser.stats.calls:
        print(
            f"  LLM 调用 {parser.stats.calls} 次 · 失败 {parser.stats.failures} 次 · "
            f"tokens {parser.stats.prompt_tokens}+{parser.stats.completion_tokens}"
        )

    # 4) 构建
    print("\n▸ [4/4] 构建静态站")
    builder = SiteBuilder(storage=storage, settings=settings)
    summary = builder.build(DIST_DIR)
    print(
        f"  完成：{summary.article_count} 篇文章 / {summary.page_count} 个页面 · "
        f"{summary.duration_sec}s → {summary.output_dir}"
    )
    if summary.warnings:
        for w in summary.warnings:
            print(f"  ⚠ {w}")

    total_published = len(storage.load_index())
    print()
    print(f"  本次解析 {parsed_count} 篇 · 站点累计 {total_published} 篇")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    _banner("LexiPress · 静态站构建")
    ensure_dirs()

    settings = load_settings()
    storage = Storage()
    _sync(storage, backfill_index=args.backfill_index)

    builder = SiteBuilder(storage=storage, settings=settings)
    output = Path(args.output) if args.output else DIST_DIR
    summary = builder.build(output)

    print(f"  base_url   : {summary.base_url or '(root)'}")
    print(f"  输出目录   : {summary.output_dir}")
    print(f"  文章页     : {summary.article_count}")
    print(f"  总页面数   : {summary.page_count}")
    print(f"  耗时       : {summary.duration_sec}s")
    for w in summary.warnings:
        print(f"  ⚠ {w}")

    checks = {
        ".nojekyll": (output / ".nojekyll").exists(),
        "index.html": (output / "index.html").exists(),
        "404.html": (output / "404.html").exists(),
        "search-index.json": (output / "search-index.json").exists(),
        "static/css/tokens.css": (output / "static" / "css" / "tokens.css").exists(),
        "static/js/app.js": (output / "static" / "js" / "app.js").exists(),
    }
    print()
    print("  产物自检：")
    all_ok = True
    for name, ok in checks.items():
        print(f"    {'✓' if ok else '✗'} {name}")
        all_ok = all_ok and ok

    if not all_ok:
        print("\n  ✗ 产物不完整")
        return 1

    print()
    print("  ✓ 构建成功。本地预览：python main.py --admin → http://127.0.0.1:8088/LexiPress/")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="LexiPress",
        description="外刊精读工坊 · 采集 / 解析 / 构建 / 本地后台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--admin", action="store_true", help="启动本地可视化后台（含 /LexiPress 预览）")
    mode.add_argument(
        "--pipeline",
        choices=["full"],
        help="全自动流水线：采集 → 精选 → 解析 → 构建（GitHub Actions 使用 full）",
    )
    mode.add_argument("--crawl-only", action="store_true", help="仅执行采集入库")
    mode.add_argument("--build-only", action="store_true", help="仅重建 dist/")

    parser.add_argument("--limit", type=int, default=None, help="覆盖每日解析篇数")
    parser.add_argument("--force-rule-only", action="store_true", help="强制规则解析（不调 LLM）")
    parser.add_argument("--source", action="append", default=[], help="只采集指定源 id（可重复）")
    parser.add_argument("--trigger", choices=["manual", "schedule", "single_source"], default="manual")
    parser.add_argument("--output", default=None, help="构建输出目录（默认 dist/）")
    parser.add_argument(
        "--backfill-index",
        action="store_true",
        help="把 data/parsed/ 中未登记在 index.json 的离线资产重新上线（默认视为已下线）",
    )
    parser.add_argument("--host", default=None, help="后台绑定 host")
    parser.add_argument("--port", type=int, default=None, help="后台绑定端口")
    parser.add_argument("--reload", action="store_true", help="后台热重载（开发用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    _log("INFO", f"LexiPress CLI 启动：{vars(args)}", scope="cli")

    try:
        if args.admin:
            return cmd_admin(args)
        if args.pipeline == "full":
            return asyncio.run(cmd_full(args))
        if args.crawl_only:
            return asyncio.run(cmd_crawl(args))
        if args.build_only:
            return cmd_build(args)
    except KeyboardInterrupt:
        print("\n  已中断。")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\n  ✗ 执行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            from src.harvester.base import LOG_BUS

            if LOG_BUS.recent(limit=5):
                print("  最近日志：", file=sys.stderr)
                for entry in LOG_BUS.recent(limit=5):
                    print(f"    [{entry['level']}] {entry['message']}", file=sys.stderr)
        except Exception:  # noqa: BLE001 - 后端依赖未安装时静默跳过
            pass
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
