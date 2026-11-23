# LexiPress — 高端杂志风 UI / UX 详细设计规范

> **文档用途**：本规范作为 `LexiPress` 静态站点前端（Jinja2 模板 + CSS + Vanilla JS）的完整视觉与交互实现蓝图，可直接交由 AI Coding Agent（如 DeepSeek Harness）按项落地实现。

---

## 1. 设计理念与美学基准

### 1.1 视觉定位：**Editorial Luxury（高端数字外刊美学）**
- **参考标杆**：*The New Yorker*（经典出版物排版）、*Kinfolk*（极简留白与高级感）、*Stripe Press*（精致排版细节与微交互）、*Readwise Reader*（极度顺手的沉浸式精读工作流）。
- **核心气质**：克制、通透、有纸张质感、零视觉噪音、高信息信噪比。打开网站应当像翻开一本印刷精良的现代国际期刊，而不是普通的博客或管理系统。

### 1.2 明确的反模式（禁止事项）
- **禁止**使用刺眼的纯白背景（`#FFFFFF`）配纯黑文字（`#000000`）。
- **禁止**使用廉价的彩虹渐变、厚重黑影（`box-shadow: 0 10px 30px rgba(0,0,0,0.4)`）或过度圆角的卡通风格。
- **禁止**引入重型前端框架（React/Vue/Webpack/Vite）；全部基于 **Jinja2 + 现代原生 CSS（Variables / Grid / Flex）+ 模块化 Vanilla JS** 实现，保证零构建依赖与极速首屏加载。
- **禁止**在任何资源或链接中写死根路径 `/static/...`，所有路径必须通过 `{{ base_url }}`（如 `/LexiPress`）动态拼接。

---

## 2. Design Tokens（设计变量系统）

所有视觉样式必须在 `templates/static/css/tokens.css` 中通过 CSS Custom Properties 定义，并在 `<html>` 上通过 `data-theme="paper" | "sepia" | "ink"` 切换。

### 2.1 三套护眼主题色板

| Token 名称 | `paper`（晨纸白，默认） | `sepia`（羊皮纸） | `ink`（深夜静谧黑） | 用途说明 |
| :--- | :--- | :--- | :--- | :--- |
| `--bg-page` | `#FAF8F5` | `#F4ECD8` | `#121417` | 页面主背景（暖纸/羊皮/炭墨） |
| `--bg-surface` | `#FFFFFF` | `#FAF3E3` | `#191C21` | 卡片、浮窗、侧边栏背景 |
| `--bg-elevated` | `#F3EFE8` | `#EBE0C7` | `#22262E` | 悬浮态、次级按钮、标签底色 |
| `--bg-glass` | `rgba(250, 248, 245, 0.82)` | `rgba(244, 236, 216, 0.85)` | `rgba(18, 20, 23, 0.82)` | 顶栏与悬浮控制条毛玻璃背景 |
| `--text-primary` | `#1C1B19` | `#352A1E` | `#E6E3DC` | 标题与英文正文主文字 |
| `--text-secondary` | `#57534E` | `#6B5B47` | `#A3A098` | 导读、中文译文、辅助说明 |
| `--text-muted` | `#8C867D` | `#91806A` | `#6E6C66` | 日期、词数、次要元数据 |
| `--border-subtle` | `rgba(28, 27, 25, 0.09)` | `rgba(53, 42, 30, 0.12)` | `rgba(230, 227, 220, 0.10)` | 极细杂志分割线与卡片边框 |
| `--border-strong` | `rgba(28, 27, 25, 0.22)` | `rgba(53, 42, 30, 0.26)` | `rgba(230, 227, 220, 0.22)` | 悬停态边框、输入框聚焦态 |
| `--accent` | `#9B2C2C`（典雅刊红） | `#8C3B2B`（赤陶棕红） | `#D97757`（暖陶橙） | 主强调色、进度条、激活状态 |
| `--accent-soft` | `rgba(155, 44, 44, 0.08)` | `rgba(140, 59, 43, 0.10)` | `rgba(217, 119, 87, 0.14)` | 强调色浅底（徽章、选中态） |
| `--vocab-underline` | `rgba(155, 44, 44, 0.45)` | `rgba(140, 59, 43, 0.50)` | `rgba(217, 119, 87, 0.55)` | 文内生词高亮下划线 |
| `--vocab-bg-hover` | `rgba(155, 44, 44, 0.12)` | `rgba(140, 59, 43, 0.14)` | `rgba(217, 119, 87, 0.18)` | 生词悬停/激活背景高亮 |
| `--shadow-sm` | `0 2px 8px rgba(28, 27, 25, 0.04)` | `0 2px 8px rgba(53, 42, 30, 0.06)` | `0 2px 10px rgba(0, 0, 0, 0.28)` | 卡片微投影 |
| `--shadow-lg` | `0 12px 32px rgba(28, 27, 25, 0.10)` | `0 12px 32px rgba(53, 42, 30, 0.14)` | `0 16px 40px rgba(0, 0, 0, 0.45)` | 浮窗、搜索弹窗、抽屉投影 |

### 2.2 字体与杂志排版规范（Typography）
引入 Google Fonts（配合优雅本地字体回退，确保国内网络偶发超时时依然美观）：
- **英文展示标题 & 正文衬线体（`--font-serif`）**：`'Newsreader', 'Source Serif 4', 'Georgia', 'Times New Roman', serif`
- **中文译文与导读体（`--font-zh`）**：`'Noto Serif SC', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif`
- **UI 控件与标签无衬线体（`--font-sans`）**：`'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`
- **期刊号/日期/音标/难度等宽体（`--font-mono`）**：`'JetBrains Mono', ui-monospace, SFMono-Regular, monospace`

**核心排版比例**：
- 首页头条大标题：`clamp(2rem, 3.8vw, 3.25rem)`，行高 `1.15`，字距 `-0.025em`，字重 `500~600`。
- 精读页文章标题：`clamp(1.85rem, 3.2vw, 2.75rem)`，行高 `1.2`，字距 `-0.02em`。
- 英文正文：支持三档字号变量 `--reader-font-size`：
  - `S`: `17px` / `M`（默认）: `19px` / `L`: `21.5px`。
  - 黄金行高 `--reader-line-height`：`1.82`；最大阅读列宽：`68ch`。
- **首字下沉（Drop Cap）**：文章第一段英文首字母（`.article-body .para-en:first-of-type::first-letter`）使用衬线大字（`font-size: 3.6em; float: left; line-height: 0.82; padding-right: 0.14em; padding-top: 0.06em; color: var(--accent);`），营造经典纸媒开篇仪式感。

### 2.3 间距、圆角与动效曲线
- **圆角克制**：小标签 `4px`，按钮与输入框 `8px`，卡片与浮窗 `12px`，胶囊按钮 `9999px`。
- **统一动效曲线**：`--ease-editorial: cubic-bezier(0.22, 1, 0.36, 1)`，过渡时长 `180ms`（微交互）~ `320ms`（抽屉/面板展开）。
- 尊重无障碍设置：在 `@media (prefers-reduced-motion: reduce)` 中关闭位移与缩放动画。

---

## 3. 全局通用组件设计（`base.html`）

### 3.1 极简玻璃拟态顶栏（Sticky Header）
- **高度**：`64px`，`position: sticky; top: 0; z-index: 40;`，背景使用 `var(--bg-glass)` + `backdrop-filter: blur(16px)`，底部 `1px solid var(--border-subtle)`。
- **左区（品牌刊头）**：
  - 衬线体标识 `LexiPress`（点击返回首页），右侧以极细竖线分隔一行等宽小字：`CURATED ENGLISH READING`。
- **右区（精简功能组）**：
  - **快捷搜索触发按钮**：模拟精致输入框样式，显示放大镜图标 + `Search...` + 右侧键盘提示徽章 `⌘K`（移动端收缩为纯图标）。
  - **三态主题切换按钮**：单击依次循环 `Paper → Sepia → Ink`（带太阳/纸张/月亮线性 SVG 图标与 tooltip）。
  - **生词本抽屉按钮**：书签图标 + 实时收藏数量角标（无收藏时隐藏角标）。

### 3.2 全局命令面板搜索（Command Palette Modal）
- **触发方式**：点击顶栏搜索框，或任意页面按下 `Cmd + K` / `Ctrl + K`（按下 `Esc` 关闭）。
- **视觉形态**：居中悬浮弹窗（最大宽 `580px`，顶部距视口 `12vh`），背景遮罩 `rgba(0,0,0,0.35)` + `blur(4px)`。
- **能力**：异步加载 `{{ base_url }}/search-index.json`，实时模糊检索文章标题、来源期刊、主题标签、以及已解析的核心生词；支持键盘 `↑ / ↓` 选择与 `Enter` 跳转。

### 3.3 个人学习工作台（Slide-over Vocab & Progress Drawer）
- **触发方式**：点击顶栏生词本按钮，从视口右侧平滑滑出（宽 `380px`，移动端 `100vw`）。
- **内容分区**：
  1. **学习数据概览条**（3 个精致数据格）：连续打卡天数（Streak）、已读篇数、已收藏生词数（数据来自 `localStorage`）。
  2. **生词本列表**：按收藏时间倒序展示词条（单词 + 音标 + 语境释义 + 来源文章链接 + 发音按钮 + 删除按钮），支持顶部迷你搜索过滤。
  3. **底部导出操作区**：
     - 「导出 Anki CSV」按钮（生成 UTF-8 BOM CSV，列：`Word,Phonetic,Meaning,Context,Source`）。
     - 「导出 Markdown」按钮（生成整洁的 `.md` 复习清单）。

---

## 4. 首页设计：杂志画报风（`index.html`）

整体容器最大宽度 `1200px`，左右留白充裕（桌面端 `32px`，移动端 `20px`）。

### 4.1 刊头刊期栏（Editorial Masthead Strip）
- 顶部细线分割区：左侧显示当前最新一期日期与刊号（如 `ISSUE · NOV 23, 2026`），右侧显示“已精读 X / Y 篇”的极简进度徽章。

### 4.2 Hero 今日头条封面卡（Featured Issue）
展示最新且综合评分最高的一篇文章，采用**不对称双栏杂志头版布局**（桌面端 `1.25fr : 1fr`，移动端上下堆叠）：
- **左栏（文字内容）**：
  - 顶行元数据：强调色刊物来源名（全大写追踪字距，如 `AEON`） + `·` + CEFR 难度胶囊（如 `C1 ADVANCED`） + `·` + `8 min read`。
  - 超大衬线标题（悬停时呈现优雅微下划线动效）。
  - 2~3 行精炼中文/英文导读摘要（`--text-secondary`）。
  - 底部操作行：主按钮「开始精读 →」（实心 `--text-primary` 背景 + 反色文字，极有质感）+ 文章核心关键词标签（最多 3 个）。
- **右栏（封面视觉）**：
  - 若文章有高质量头图：展示 `4:3` 比例封面图，微圆角，悬停轻微放大（`scale(1.02)`）。
  - **无头图时的优雅兜底（关键细节）**：严禁出现难看的占位灰框！改为渲染一张**「印刷排版艺术封面卡」**——暖色渐变纸纹底 + 超大半透明首字母水印 + 期刊来源大字 + 精选金句/首句摘录，让无图文章同样具有 *The New Yorker* 封面级的视觉冲击力。

### 4.3 灵动筛选胶囊栏（Filter Bar）
位于 Hero 下方、网格上方，左侧为筛选组，右侧为状态切换：
- **来源筛选胶囊**：`全部`、`Aeon`、`MIT Tech Review`、`The Guardian` 等（根据实际文章动态生成）。
- **难度筛选胶囊**：`B2`、`C1`、`C2`。
- **阅读状态过滤**：`全部` / `未读` / `已读`。
- 切换时纯前端即时过滤，卡片带有平滑淡入动画；若筛选结果为空，展示极简留白空状态与「重置筛选」按钮。

### 4.4 Bento / 杂志专栏网格（Curated Grid）
- **布局**：桌面端 3 列（`repeat(3, 1fr)`，间距 `24px`），平板 2 列，手机 1 列。
- **单张卡片结构**：
  - 背景 `var(--bg-surface)`，`1px solid var(--border-subtle)`，内边距 `24px`，Flex 纵向撑满使底部对齐。
  - **顶行**：来源期刊名（等宽大写）+ 发布日期 + 已读状态绿/红小圆点或 `✓` 标记（由 `localStorage` 动态注入）。
  - **中部**：衬线体文章标题（最多 3 行截断）+ 导读预览（2 行截断）。
  - **底行**（顶部细虚线分隔）：难度徽章 + 词数/阅读时长 + 生词数（如 `12 vocab`）。
- **微交互**：悬停时卡片轻抬 `translateY(-3px)`，边框过渡为 `var(--border-strong)`，柔和投影浮现，标题微变色。

---

## 5. 精读页设计：沉浸式阅读工坊（`article.html`）

这是用户停留时间最长的核心页面，必须做到**零干扰、高专注、查词与双语切换极致顺手**。

### 5.1 顶部阅读进度条
- 视口最顶部 `height: 2px; position: fixed; top: 0; left: 0; z-index: 60;`，背景色 `var(--accent)`，宽度随页面滚动实时平滑更新。

### 5.2 悬浮极简控制胶囊（Floating Reader Controls）
固定在视口底部居中（或桌面端正文上方吸顶），毛玻璃胶囊造型，集成所有高频阅读开关：
1. **阅读模式分段切换器（Segmented Control）**：
   - `纯英`（隐藏译文与生词下划线，极致原版阅读）
   - `生词`（默认：高亮核心生词与短语，点击弹窗查词）
   - `双语`（展开全篇段落中文译文，逐段对照）
2. **排版微调弹出面板（`Aa` 按钮）**：
   - 字号调节：`S` / `M` / `L`
   - 主题速切：三个圆形色块（晨纸白 / 羊皮纸 / 静谧黑）
3. **禅模式按钮（Zen Mode，仅桌面端）**：一键收起右侧精读助手栏，正文平滑居中至视野黄金位置。

### 5.3 桌面端双栏布局（Desktop >= 1100px）与移动端适配
- **容器**：最大宽度 `1160px`，主阅读栏 `minmax(0, 68ch)` + 右侧精读助手栏 `340px`（`position: sticky; top: 88px; max-height: calc(100vh - 110px); overflow-y: auto;`），中间留白 `48px`。
- **移动端（< 1100px）**：右侧助手栏自动隐藏，转为右下角悬浮按钮「精读笔记」，点击后从底部平滑拉出 **Bottom Sheet 抽屉**。

### 5.4 主阅读区（Reading Column）细节
1. **文章刊头区**：
   - 返回链接 `← Back to Issues`。
   - 来源徽章 + 外部原文链接 `Read Original ↗`（新标签页打开）。
   - 超大衬线标题 + 作者与发布日期 + 统计胶囊条（词数 · 阅读时长 · 难度 · 生词数）。
2. **正文段落交互**：
   - 每个段落包裹在 `.para-block` 中，包含 `.para-en`（英文）与 `.para-zh`（中文译文）。
   - **单段按需翻译**：在「纯英」或「生词」模式下，悬停段落左侧（或移动端轻触段落右上角极简 `译` 图标），可**单独展开/收起当前段落的中文译文**，彻底避免因一两句没看懂而被迫打开全文翻译。
   - **译文排版风格**：比英文小 1~2px，使用 `var(--text-secondary)`，左侧带 `2px solid var(--border-strong)` 细竖线缩进，视觉层级清晰不喧宾夺主。
3. **文内生词高亮（`<mark class="vocab-term">`）**：
   - 在「生词」和「双语」模式下激活：透明底色 + `border-bottom: 1.5px dashed var(--vocab-underline)`，悬停或选中时浮现 `var(--vocab-bg-hover)` 柔和底色。
   - 在「纯英」模式下，通过 CSS 自动剥离下划线与指针样式，还原纯净纸书体验。
4. **文末打卡与连读区**：
   - 精致水平分隔饰线（`✦`）。
   - 「✓ 标记为已读」按钮（点击后变更为已读徽章，写入 `localStorage` 并更新连续打卡天数）。
   - 上一篇 / 下一篇杂志风推荐卡片。

### 5.5 丝滑生词浮窗（Context Vocab Popover）
- 点击文内任意高亮生词时触发，动态计算坐标定位于词汇正上方或正下方（自动防视口边缘溢出）。
- **卡片内容**（宽 `300px`，圆角 `12px`，`var(--bg-surface)` + `var(--shadow-lg)`）：
  - **顶行**：单词/短语（加粗衬线体）+ 词性徽章（如 `n.` / `idiom`）+ 朗读图标按钮（调用浏览器 `window.speechSynthesis` 朗读英/美音）。
  - **音标行**：等宽字体音标（如 `/ɪˈfem.ər.əl/`）。
  - **语境释义**：精准中文释义 + 简短英文用法提示。
  - **底行**：一键切换按钮 `☆ 加入生词本` / `★ 已收藏`（实时同步右上角生词本角标与 `localStorage`）。
- 点击页面空白处或按 `Esc` 键平滑关闭。

### 5.6 右侧精读助手栏（Study Assistant Sidebar）
顶部采用极简下划线 Tab 切换，包含三个视图：
1. **导读（Overview）**：
   - **盲读保护罩（Spoiler Shield）**：导读摘要与核心观点默认覆盖一层半透明毛玻璃与提示「点击揭晓文章导读（建议先读英文）」，点击后丝滑清晰展开。
   - 展示：3 条核心要点（Key Takeaways）、文章背景/主题标签。
2. **核心词表（Vocab）**：
   - 列出本文所有提取的高价值词汇卡片，支持发音与一键收藏。
   - **双向联动**：点击右侧词表中的某个词，主阅读区自动平滑滚动到该词首次出现的位置，并对该词播放一次短暂的脉冲高亮动画（`vocab-pulse`）。
3. **长难句（Sentences）**：
   - 卡片化展示 3~5 个长难句：英文原句 + 语法主干拆解（以轻量标签或缩进区分主句、定语/状语从句）+ 地道中文意译。

### 5.7 悬浮播客音频条（Phase 3 预留接口）
- 仅当文章数据中存在 `audio_url` 时渲染在底部控制栏上方或整合进底栏：
  - 播放/暂停按钮、可拖拽进度条、当前时间/总时长、倍速循环切换（`0.8x` / `1.0x` / `1.25x` / `1.5x`）。

---

## 6. 前端数据契约（供模板与 JS 对接）

### 6.1 Jinja2 核心数据结构约定
单篇文章 JSON（`data/parsed/<id>.json`）字段约定如下，模板渲染时做容错降级（若 Phase 1 尚未接入 LLM，则 `overview` / `vocab` / `sentences` / `zh` 为空时优雅隐藏对应区块，不报错、不露空壳）：

```json
{
  "id": "2026-11-23-aeon-example",
  "title": "The Architecture of Attention",
  "source": "Aeon",
  "author": "Jane Doe",
  "published_at": "2026-11-23",
  "original_url": "https://aeon.co/...",
  "cover_image": "",
  "tags": ["Psychology", "Culture"],
  "difficulty": "C1",
  "word_count": 1850,
  "read_time_min": 9,
  "score": 9.2,
  "audio_url": "",
  "overview": {
    "summary_zh": "一句话或三句话核心导读...",
    "takeaways": ["要点一", "要点二", "要点三"]
  },
  "paragraphs": [
    {
      "index": 0,
      "en": "Original English paragraph text...",
      "zh": "对应的精准中文译文（Phase 1 可为空字符串）"
    }
  ],
  "vocab": [
    {
      "id": "v1",
      "term": "ephemeral",
      "phonetic": "/ɪˈfem.ər.əl/",
      "pos": "adj.",
      "meaning_zh": "短暂的，转瞬即逝的",
      "note": "常用于形容注意力、潮流或记忆",
      "para_index": 0
    }
  ],
  "sentences": [
    {
      "en": "Complex English sentence...",
      "structure": "主干：... | 从句：...",
      "zh": "地道意译..."
    }
  ]
}
```

### 6.2 `localStorage` 持久化键规范
统一使用 `lexipress_` 前缀，避免同域下其他 GitHub Pages 项目冲突：
- `lexipress_theme`：`"paper" | "sepia" | "ink"`
- `lexipress_reader_prefs`：`{ "mode": "vocab", "fontSize": "m", "zen": false }`
- `lexipress_read_history`：`{ "readIds": ["..."], "streakDays": 3, "lastReadDate": "2026-11-23" }`
- `lexipress_vocab_book`：`[ { "term": "...", "phonetic": "...", "meaning_zh": "...", "source": "...", "articleId": "...", "savedAt": "..." } ]`

---

## 7. 快捷键与无障碍体验

- `Cmd/Ctrl + K`：打开全局搜索面板
- `Esc`：依次关闭弹窗 / 生词浮窗 / 生词本抽屉
- 精读页单键快捷键（非输入框聚焦时生效）：
  - `1` / `2` / `3`：快速切换「纯英 / 生词 / 双语」模式
  - `Z`：切换全屏禅模式（Zen Mode）
  - `T`：循环切换护眼主题

---

## 8. 交付验收清单（供实现阶段自检）

- [ ] **视觉质感**：三套主题（Paper / Sepia / Ink）切换无闪烁（首屏 `<head>` 内联极短脚本提前读取 `localStorage` 设置 `data-theme`），对比度符合 WCAG AA 标准。
- [ ] **无图兜底**：无封面图的 Hero 头条自动渲染印刷排版艺术封面，视觉协调惊艳。
- [ ] **子路径兼容**：将站点托管于 `http://localhost:8000/LexiPress/` 与 `https://<user>.github.io/LexiPress/` 时，CSS、JS、`search-index.json` 与所有内链 100% 无 404。
- [ ] **核心交互**：首页筛选与 `Cmd+K` 搜索流畅；精读页模式切换、单段译文展开、生词点击浮窗与发音、词表联动滚动、生词收藏与 Anki CSV 导出均可用。
- [ ] **空数据降级**：当文章暂无译文/生词/长难句（Phase 1 阶段）时，页面依然排版优雅、无报错与空白尴尬区块。
- [ ] **响应式完美**：在 `1440px`（桌面）、`820px`（平板）、`390px`（手机）视口下无横向滚动条、无文字重叠、触控热区合理。
