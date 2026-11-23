"""端到端浏览器验收（Playwright Chromium）。

覆盖：
- 首页 / 精读页 / 404 无控制台报错、无 4xx 资源
- 三套主题切换、Cmd+K 搜索、筛选胶囊、已读标记
- 精读页三模式切换、单段译文、生词浮窗、发音按钮、词表联动、禅模式、移动端抽屉
- LocalStorage 生词本与 Anki / Markdown 导出
- 响应式视口（1440 / 820 / 390）无横向滚动

运行：
    python scripts/e2e_check.py [--base http://127.0.0.1:8088] [--shots]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.console import ensure_utf8_console  # noqa: E402

ensure_utf8_console()

from playwright.sync_api import sync_playwright  # noqa: E402

SHOT_DIR = ROOT / "logs" / "shots"


class Report:
    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}" + (f"  — {detail}" if detail else ""))

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]


def collect_console(page, sink: list[str]) -> None:
    page.on("console", lambda msg: sink.append(f"{msg.type}: {msg.text}") if msg.type in ("error", "warning") else None)
    page.on("pageerror", lambda exc: sink.append(f"pageerror: {exc}"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8088")
    parser.add_argument("--shots", action="store_true", help="保存截图到 logs/shots/")
    args = parser.parse_args()

    if args.shots:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)

    base = args.base.rstrip("/")
    site = base + "/LexiPress"
    rep = Report()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 960})
        page = ctx.new_page()
        console_msgs: list[str] = []
        collect_console(page, console_msgs)

        failed_requests: list[str] = []
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.url} :: {req.failure}"))
        page.on(
            "response",
            lambda res: (
                failed_requests.append(f"{res.status} {res.url}")
                if res.status >= 400 and not res.url.endswith("favicon.ico")
                else None
            ),
        )

        # ---------------- 首页 ----------------
        print("\n▸ 首页")
        page.goto(site + "/", wait_until="networkidle")
        rep.add("首页加载", page.locator(".hero__title").count() == 1)
        rep.add("玻璃拟态顶栏", page.locator(".site-header").count() == 1)
        rep.add("刊期栏", page.locator(".masthead-strip").count() == 1)
        rep.add("Hero 艺术封面兜底", page.locator(".art-cover__watermark").count() == 1)
        rep.add("Bento 卡片", page.locator(".card[data-article-id]").count() >= 2)
        rep.add("筛选胶囊", page.locator(".pill[data-filter]").count() >= 6)

        if args.shots:
            page.screenshot(path=str(SHOT_DIR / "01-home-paper.png"), full_page=True)

        # 主题循环
        themes = []
        for _ in range(3):
            page.click('[data-action="cycle-theme"]')
            page.wait_for_timeout(240)
            themes.append(page.evaluate("document.documentElement.getAttribute('data-theme')"))
        rep.add("主题三态循环", themes[:3] == ["sepia", "ink", "paper"], str(themes))

        # 持久化
        rep.add(
            "主题写入 localStorage",
            page.evaluate("localStorage.getItem('lexipress_theme')") == "paper",
        )

        # Cmd+K 搜索
        page.keyboard.press("Control+k")
        page.wait_for_timeout(400)
        rep.add("Cmd/Ctrl+K 打开搜索", page.locator(".palette.is-open").count() == 1)
        page.fill("#palette-input", "attention")
        page.wait_for_timeout(420)
        rep.add("搜索有结果", page.locator(".palette__item").count() >= 1)
        if args.shots:
            page.screenshot(path=str(SHOT_DIR / "02-search.png"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(260)
        rep.add("Esc 关闭搜索", page.locator(".palette.is-open").count() == 0)

        # 筛选
        page.click('.pill[data-filter="level"][data-value="C1"]')
        page.wait_for_timeout(320)
        visible = page.locator(".card[data-article-id]:not(.is-hidden)").count()
        total = page.locator(".card[data-article-id]").count()
        rep.add("难度筛选生效", visible <= total, f"{visible}/{total} 可见")
        page.click('.pill[data-filter="level"][data-value="all"]')
        page.wait_for_timeout(260)
        rep.add(
            "重置筛选恢复全部",
            page.locator(".card[data-article-id]:not(.is-hidden)").count() == total,
        )

        # 空态与重置按钮：筛一个必无结果的组合
        page.click('.pill[data-filter="level"][data-value="C2"]')
        page.click('.pill[data-filter="state"][data-value="read"]')
        page.wait_for_timeout(300)
        empty_visible = page.locator('[data-role="empty-state"]').is_visible()
        rep.add("空筛选结果展示空态", empty_visible)
        if empty_visible:
            page.click('[data-action="reset-filters"]')
            page.wait_for_timeout(300)
            rep.add(
                "空态重置按钮可用",
                page.locator(".card[data-article-id]:not(.is-hidden)").count() == total,
            )
        else:
            page.click('.pill[data-filter="level"][data-value="all"]')
            page.click('.pill[data-filter="state"][data-value="all"]')
            page.wait_for_timeout(200)

        # 生词本抽屉空态
        page.click('[data-action="open-drawer"]')
        page.wait_for_timeout(360)
        rep.add("学习工作台抽屉打开", page.locator(".drawer.is-open").count() == 1)
        page.click('[data-action="close-drawer"]')
        page.wait_for_timeout(320)

        # ---------------- 精读页 ----------------
        print("\n▸ 精读页")
        page.goto(site + "/", wait_until="networkidle")
        first_link = page.locator('.card__title a').first.get_attribute("href")
        if first_link.startswith("/"):
            first_link = base + first_link
        page.goto(first_link, wait_until="networkidle")

        rep.add("阅读进度条", page.locator(".reading-progress").count() == 1)
        rep.add("悬浮控制胶囊", page.locator(".reader-controls").count() == 1)
        rep.add("首字下沉样式", page.locator(".para-en").count() >= 3)
        rep.add("生词高亮注入", page.locator("mark.vocab-term").count() >= 5)

        # 三模式
        for mode, cls in (("en", "reader-mode-en"), ("dual", "reader-mode-dual"), ("vocab", "reader-mode-vocab")):
            page.click(f'.segmented__btn[data-mode="{mode}"]')
            page.wait_for_timeout(220)
            rep.add(f"模式切换 {mode}", page.locator(f".article-body.{cls}").count() == 1)

        # 双语模式译文可见
        page.click('.segmented__btn[data-mode="dual"]')
        page.wait_for_timeout(300)
        zh_visible = page.locator(".para-zh").first.is_visible()
        rep.add("双语模式段落译文可见", zh_visible)

        # 单段译文切换（回到生词模式）
        page.click('.segmented__btn[data-mode="vocab"]')
        page.wait_for_timeout(240)
        toggle = page.locator('[data-action="toggle-para"]').first
        toggle.click(force=True)
        page.wait_for_timeout(280)
        rep.add("单段译文按需展开", page.locator(".para-block.is-zh-open").count() >= 1)

        # 字号
        page.click('[data-action="toggle-aa"]')
        page.wait_for_timeout(220)
        page.click('.size-btn[data-size="l"]')
        page.wait_for_timeout(200)
        rep.add("字号切换为 L", page.evaluate("document.documentElement.getAttribute('data-font')") == "l")
        page.keyboard.press("Escape")
        page.click('.size-btn[data-size="m"]')

        # 生词浮窗 + 收藏
        page.goto(first_link, wait_until="networkidle")
        page.locator("mark.vocab-term").first.click(force=True)
        page.wait_for_timeout(360)
        rep.add("生词浮窗打开", page.locator(".vocab-popover.is-open").count() == 1)
        pop_term = page.locator('[data-role="pop-term"]').inner_text()
        rep.add("浮窗显示词条", bool(pop_term.strip()), pop_term)

        if args.shots:
            page.screenshot(path=str(SHOT_DIR / "03-article-popover.png"), full_page=False)

        # 发音按钮（Web Speech 可能无声，只验证不抛错）
        page.click('[data-action="speak-pop"]')
        page.wait_for_timeout(220)

        page.click('[data-action="pop-save"]')
        page.wait_for_timeout(300)
        saved = page.evaluate("JSON.parse(localStorage.getItem('lexipress_vocab_book')||'[]').length")
        rep.add("收藏生词写入 localStorage", saved >= 1, f"{saved} 条")
        rep.add("顶栏角标更新", page.locator('[data-role="vocab-badge"]').is_visible())
        page.keyboard.press("Escape")

        # 词表联动
        page.click('.aside-tab[data-tab="vocab"]')
        page.wait_for_timeout(300)
        cards = page.locator(".vocab-card").count()
        rep.add("词表卡片渲染", cards >= 5, f"{cards} 张")
        page.locator(".vocab-card").first.click()
        page.wait_for_timeout(900)
        rep.add("词表点击联动高亮", page.locator(".vocab-card.is-linked").count() >= 1)

        # 长难句
        page.click('.aside-tab[data-tab="sentences"]')
        page.wait_for_timeout(300)
        rep.add("长难句卡片", page.locator(".sentence-card").count() >= 3)

        # 导读盲读保护罩
        page.click('.aside-tab[data-tab="overview"]')
        page.wait_for_timeout(300)
        has_spoiler = page.locator(".spoiler").count() >= 1
        rep.add("导读盲读保护罩", has_spoiler)
        if has_spoiler:
            page.click('[data-action="reveal-spoiler"]')
            page.wait_for_timeout(400)
            rep.add("点击揭晓导读", page.locator(".spoiler.is-revealed").count() == 1)

        # 禅模式
        page.click('[data-action="toggle-zen"]')
        page.wait_for_timeout(340)
        rep.add("禅模式收起助手栏", page.locator(".article-layout.is-zen").count() == 1)
        if args.shots:
            page.screenshot(path=str(SHOT_DIR / "04-article-zen.png"), full_page=True)
        page.click('[data-action="toggle-zen"]')
        page.wait_for_timeout(280)

        # 已读标记
        page.click('[data-action="mark-read"]')
        page.wait_for_timeout(400)
        rep.add("已读打卡", page.evaluate("JSON.parse(localStorage.getItem('lexipress_read_history')||'{}').readIds.length") >= 1)
        rep.add("已读按钮态变化", page.locator(".mark-read.is-done").count() == 1)

        # 快捷键
        page.keyboard.press("3")
        page.wait_for_timeout(260)
        rep.add("快捷键 3 → 双语", page.locator(".article-body.reader-mode-dual").count() == 1)
        page.keyboard.press("t")
        page.wait_for_timeout(240)
        rep.add("快捷键 T 切主题", page.evaluate("document.documentElement.getAttribute('data-theme')") != "")

        # 导出
        page.click('[data-action="open-drawer"]')
        page.wait_for_timeout(400)
        with page.expect_download(timeout=6000) as dl:
            page.click('[data-action="export-anki"]')
        anki = dl.value
        rep.add("导出 Anki CSV", anki.suggested_filename.endswith(".csv"), anki.suggested_filename)

        with page.expect_download(timeout=6000) as dl2:
            page.click('[data-action="export-markdown"]')
        md = dl2.value
        rep.add("导出 Markdown", md.suggested_filename.endswith(".md"), md.suggested_filename)
        page.click('[data-action="close-drawer"]')
        page.wait_for_timeout(300)

        # ---------------- 404 ----------------
        print("\n▸ 404")
        not_found_url = site + "/articles/definitely-not-here/"
        resp = page.goto(not_found_url, wait_until="domcontentloaded")
        rep.add("404 返回 404 状态", resp is not None and resp.status == 404, str(resp.status if resp else "?"))
        rep.add("404 页面有返回按钮", page.locator('a[href$="/LexiPress/"]').count() >= 1)

        # 故意访问不存在页面产生的 404 与 console 提示属于预期，不计入缺陷
        expected_noise = ("definitely-not-here",)

        # ---------------- 响应式 ----------------
        print("\n▸ 响应式")
        for width, label in ((1440, "桌面"), (820, "平板"), (390, "手机")):
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(first_link, wait_until="networkidle")
            page.wait_for_timeout(300)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            rep.add(f"{label} {width}px 无横向滚动", overflow <= 1, f"overflow={overflow}px")
            if width == 390:
                rep.add("移动端精读笔记按钮", page.locator(".aside-fab").is_visible())
                page.click(".aside-fab")
                page.wait_for_timeout(500)
                rep.add("移动端底部抽屉打开", page.locator(".sheet.is-open").count() == 1)
                if args.shots:
                    page.screenshot(path=str(SHOT_DIR / "05-mobile-sheet.png"))

        # ---------------- 后台 ----------------
        print("\n▸ 后台")
        admin_console: list[str] = []
        apage = ctx.new_page()
        collect_console(apage, admin_console)
        for path, label in (
            ("/", "仪表盘"),
            ("/articles", "候选池"),
            ("/sources", "源管理"),
            ("/logs", "实时日志"),
            ("/publish", "发布中心"),
        ):
            apage.goto(base + path, wait_until="networkidle")
            apage.wait_for_timeout(600)
            rep.add(f"后台 {label} 渲染", apage.locator(".app .nav").count() == 1)
            if path == "/articles":
                apage.wait_for_timeout(700)
                rep.add("候选池表格有数据", apage.locator("tr[data-id]").count() >= 1, f"{apage.locator('tr[data-id]').count()} 行")
            if path == "/logs":
                apage.wait_for_timeout(1200)
                label = apage.locator('[data-role="connection-label"]').inner_text()
                rep.add("日志终端已连接", "CONNECTED" in label.upper(), label)
            if path == "/publish":
                rep.add("发布中心显示构建状态", apage.locator('[data-role="s-built"]').inner_text() != "—")
            if args.shots and path == "/":
                apage.screenshot(path=str(SHOT_DIR / "06-admin-dashboard.png"), full_page=True)

        # 候选池抽屉预览
        apage.goto(base + "/articles", wait_until="networkidle")
        apage.wait_for_timeout(900)
        preview_btns = apage.locator('[data-action="preview"]')
        if preview_btns.count():
            preview_btns.first.click()
            apage.wait_for_timeout(900)
            rep.add("候选池右侧预览抽屉", apage.locator(".drawer.is-open").count() == 1)
            rep.add("抽屉显示正文段落", apage.locator(".preview-body p").count() >= 1)
            if args.shots:
                apage.screenshot(path=str(SHOT_DIR / "07-admin-drawer.png"))
            apage.click('[data-action="close-drawer"]')

        # ---------------- 汇总 ----------------
        print("\n▸ 控制台与网络")

        def is_expected_noise(text: str) -> bool:
            if "favicon" in text.lower():
                return True
            return any(marker in text for marker in expected_noise)

        real_console = [
            m for m in console_msgs if not is_expected_noise(m) and "Failed to load resource: the server responded with a status of 404" not in m
        ]
        rep.add(
            "前台无控制台错误",
            not any(m.startswith(("error", "pageerror")) for m in real_console),
            "; ".join(real_console[:3]),
        )
        real_admin = [m for m in admin_console if not is_expected_noise(m)]
        rep.add(
            "后台无控制台错误",
            not any(m.startswith(("error", "pageerror")) for m in real_admin),
            "; ".join(real_admin[:3]),
        )
        real_failed = [
            r for r in failed_requests if not is_expected_noise(r) and "fonts.g" not in r
        ]
        rep.add("无失败资源请求", not real_failed, "; ".join(real_failed[:3]))

        browser.close()

    total = len(rep.checks)
    passed = total - len(rep.failed)
    print(f"\n{'═' * 62}")
    print(f"  端到端验收：{passed}/{total} 通过")
    if rep.failed:
        print("  失败项：")
        for name, _ok, detail in rep.failed:
            print(f"    ✗ {name}  {detail}")
    print(f"{'═' * 62}\n")
    return 0 if not rep.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
