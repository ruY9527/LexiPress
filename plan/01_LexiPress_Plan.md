# LexiPress（外刊精读工坊）项目规划

> **完整规划文档集（Spec Pack，建议按序号顺序阅读执行）**：
> 1. [01_LexiPress_Plan.md](./01_LexiPress_Plan.md) — 总体架构、目录规划、GitHub Workflow 与分阶段路线图
> 2. [02_UI_UX_Design_Spec.md](./02_UI_UX_Design_Spec.md) — 高端杂志风前台 UI / UX 视觉、交互与数据契约规范
> 3. [03_Harvester_And_Admin_Spec.md](./03_Harvester_And_Admin_Spec.md) — 多源外刊采集器、双层存储与 FastAPI 本地可视化后台规范
> 4. [04_Technical_Architecture_And_Closure_Spec.md](./04_Technical_Architecture_And_Closure_Spec.md) — 全链路闭环审计、代码级关键算法、配置/CLI 契约与 Workflow 防坑蓝图

## 1. 项目概述

- **项目名称**：`LexiPress`
- **定位**：本地 Python 驱动 + GitHub Actions 全自动化的外刊精选、英语精读解析与高端杂志风静态阅读站。
- **核心目标**：自动从高质量英文外刊源中筛选最新、最值得读的文章，完成清洗与英语精读解析，渲染出**优雅、惊艳且极度顺手**的在线精读界面，并通过 **GitHub Workflow（GitHub Actions）** 自动构建与发布至带仓库路径的 GitHub Pages（`https://<username>.github.io/LexiPress/`）。

---

## 2. 系统架构与模块设计

整体采用“本地可调试 + GitHub Actions 全自动运行”的双栖流水线架构，分为五大核心模块：

```text
[1. SourceHarvester 采集器]
        ↓ (原始链接 + 元数据 + 清洗正文)
[2. ValueRanker 精选器]
        ↓ (Top N 最值得读的文章)
[3. StudyParser 精读解析器]
        ↓ (结构化 JSON 学习数据 + 缓存)
[4. SiteBuilder 站点生成器]
        ↓ (高端杂志风静态 HTML / CSS / JS / 可选音频)
[5. GitHub Workflow 自动发布流]
        ↓ (actions/deploy-pages)
https://<username>.github.io/LexiPress/
```

### 2.1 `SourceHarvester`（多源外刊采集器）与本地可视化后台

> 详细的插件化采集管线、SQLite/JSON 双层存储、FastAPI 本地可视化管理后台与 REST/SSE 接口规范已单独沉淀至 [03_Harvester_And_Admin_Spec.md](./03_Harvester_And_Admin_Spec.md)，实现数据采集与后台管理时请以该文档为准。

- **采集方式**：优先通过 RSS / Atom / 公开 API 获取最新文章列表，兼顾稳定性与可维护性。
- **候选外刊源（首批示例）**：
  - 深度人文/思想：*Aeon*、*The Guardian Long Read*、*BBC Future*
  - 科技与商业：*MIT Technology Review*、*Hacker News（高赞长文）*、*The Verge*
  - 科普与综合：*Quanta Magazine*、*The Conversation*（CC 协议友好）
- **正文抽取**：使用 `trafilatura`（`readability-lxml` 兜底）剥离广告与导航，保留标题、作者、发布时间、头图（若有）与干净段落。
- **去重存储**：使用轻量数据索引（`data/index.json` 或 SQLite `data/articles.db`）按 URL Hash 去重，支持在 GitHub 仓库中持久化同步，避免重复抓取与重复解析。

### 2.2 `ValueRanker`（“最值得读”精选器）
- **规则初筛**：
  - 词数区间过滤（例如 `600 ~ 3500` 词，过滤过短快讯与过长论文）。
  - 时效性窗口（最近 48~72 小时内发布）+ 媒体源基础权重。
- **AI 价值打分（可选）**：
  - 按 **信息密度、语言地道度、主题多样性** 综合打分（1~10 分），每日精选 Top 1~3 篇进入深度解析。

### 2.3 `StudyParser`（英语学习解析器）
- **基础阅读指标**：总词数、预计阅读时间、基于高频词表的难度等级（如 CEFR B2 / C1 / C2）与生词率。
- **深度精读内容生成**（通过 LLM API，结果按文章 ID 持久化缓存到 `data/parsed/`）：
  - **文章导读**：核心摘要、背景与结构脉络（默认折叠，支持盲读后展开）。
  - **核心词汇与地道短语**：提取 10~15 个高价值表达，含音标、当前语境释义、原句高亮定位。
  - **长难句拆解**：挑选 3~5 个典型复杂句，提供语法主干结构拆分与地道意译。
  - **段落双语对照**：逐段生成中文译文，默认隐藏，按需点击或全局切换显示。
- **听力伴读（进阶）**：使用 `edge-tts` 生成英文朗读音频（MP3）随静态产物一并发布。

### 2.4 `SiteBuilder`（静态站点生成器）
- 使用 Python `Jinja2` 模板引擎渲染静态 HTML，配合精心设计的现代 CSS 变量系统与模块化 Vanilla JS，做到**零繁重前端构建链、极速加载、离线友好**。
- 统一通过 `base_url`（如 `/LexiPress`）注入所有静态资源与跳转路径，彻底解决 GitHub Pages 子路径 404 问题。

---

## 3. UI / UX 视觉与交互设计（核心亮点）

> 详细像素级与交互级规范已单独沉淀至 [02_UI_UX_Design_Spec.md](./02_UI_UX_Design_Spec.md)，实现前端模板与样式时请严格以该文档为准。

设计目标：**高端数字外刊杂志美学（Editorial Luxury）**——参考 *The New Yorker*、*Kinfolk*、*Stripe Press* 与 *Readwise Reader* 的排版克制感与沉浸体验，让打开网页本身成为一种享受。

### 3.1 视觉美学与配色系统
- **三套精调护眼主题（丝滑过渡 + 本地持久化）**：
  - **晨纸白（Warm Paper，默认）**：暖白纸张底色 `#FAF8F5` + 深墨黑字色 `#1C1B19` + 刊物典雅红/深翠绿点缀，告别刺眼纯白。
  - **羊皮纸（Sepia）**：温润米黄 `#F3EAD8` + 棕墨色 `#3B2F23`，适合长时间沉浸精读。
  - **静谧夜（Deep Ink）**：低蓝光炭黑 `#121417` + 柔灰白 `#E4E2DD`，夜间阅读不累眼。
- **杂志级排版（Typography）**：
  - 英文正文与大标题：优雅衬线体（`Newsreader` / `Playfair Display` + 系统衬线回退），文章首段支持精致的**首字下沉（Drop Cap）**。
  - 中文译文与导读：温润可读的无衬线/宋体搭配，与英文视觉区分清晰。
  - UI 标签与元数据：精致等宽/几何无衬线体（`Inter` / `JetBrains Mono`），展现刊号、日期、难度徽章与词数。
  - 黄金阅读参数：严格控制正文行宽 `66ch ~ 72ch`，行高 `1.8`，段落间距舒展呼吸。

### 3.2 首页设计（杂志画报风）
- **极简玻璃拟态顶栏（Glassmorphism Header）**：品牌标识 `LexiPress` + 快捷搜索框（支持 `Ctrl/Cmd + K` 唤起全局模糊搜索）+ 主题切换 + 生词本入口（带收藏角标）。
- **Hero 今日头条封面区（Featured Issue）**：
  - 每日评分最高的文章以“杂志封面头版”形态展示：大幅留白、来源期刊徽章、难度星级/CEFR 标签、3 句话导读预览、预计阅读时长、醒目的「开始精读」主按钮。
- **Bento Grid 精选刊物网格**：
  - 其余文章采用精致卡片布局，带柔和边框、细腻悬浮阴影与微位移过渡动画。
  - 顶部提供一行**灵动筛选胶囊条**：按「外刊来源 / 难度等级 / 主题标签 / 未读状态」即时无刷新过滤。

### 3.3 沉浸式精读页（Reading Studio）
- **顶部极细阅读进度条**：随滚动实时指示阅读百分比。
- **悬浮极简控制胶囊（Floating Control Bar）**：
  - 一键切换阅读模式：**纯英沉浸** / **生词高亮** / **双语对照**。
  - 快捷调节：字体大小（S / M / L）、行距、三套护眼主题切换。
- **桌面端优雅双栏 + 移动端底部抽屉**：
  - 主区域：专注正文精读，点击任意段落可单独展开/收起该段译文（避免全篇中文干扰英文思维）。
  - 右侧精读助手栏（可一键收起进入全屏禅模式）：分 Tab 展示「导读概览 / 核心词汇表 / 长难句语法拆解」。
- **丝滑生词浮窗（Context Popover）**：
  - 在生词高亮模式下，文内高价值词汇带有细腻的彩色虚线下划线；点击后原地弹出精致浮窗卡片，展示音标、**点击即读（Web Speech API 发音）**、当前语境释义，以及一键「★ 加入生词本」。
- **底部悬浮音频条（Phase 3）**：类播客迷你播放器，支持 0.8x / 1.0x / 1.25x 倍速与进度拖拽。
- **个人学习工作台（侧滑抽屉，纯前端 LocalStorage）**：
  - 自动记录已读文章、连续打卡天数、累计精读词数。
  - 随时查看/删除收藏的生词，支持**一键导出 Anki CSV / Markdown 笔记**。

---

## 4. GitHub 托管与 GitHub Workflow（Actions）全自动方案

整个发布流完全走 GitHub 原生标准工作流，既支持**本地一键触发**，也支持 **GitHub 云端全自动定时更新**。

### 4.1 仓库与 GitHub Pages 配置
- 仓库名：`LexiPress`（最终访问地址：`https://<username>.github.io/LexiPress/`）。
- GitHub Pages 发布源选择：**GitHub Actions**（无需手动维护脏乱的 `gh-pages` 静态分支，部署记录清晰可回溯）。

### 4.2 双 Workflow 设计（`.github/workflows/`）

1. **`daily-publish.yml`（全自动每日更新与发布）**
   - **触发条件**：
     - `schedule`：每日定时触发（例如北京时间每天早上 07:00，对应 `cron: '0 23 * * *'`）。
     - `workflow_dispatch`：支持在 GitHub 网页端点击 **Run workflow** 随时手动触发。
   - **执行步骤**：
     1. 检出仓库代码（`actions/checkout@v4`）。
     2. 配置 Python 环境并缓存依赖（`actions/setup-python@v5`）。
     3. 运行 `python main.py --pipeline full`（从 GitHub Secrets 读取 `LLM_API_KEY` 完成采集、筛选、精读解析与静态构建）。
     4. 将新增的解析缓存与索引（`data/parsed/`、`data/index.json`）自动 commit 回主分支（`[skip ci]` 避免死循环），确保历史文章沉淀且不重复消耗 API。
     5. 调用官方部署动作 `actions/configure-pages@v5` → `actions/upload-pages-artifact@v3`（上传 `dist/`）→ `actions/deploy-pages@v4`，完成上线。

2. **`deploy-site.yml`（本地更新/改 UI 样式即时发布）**
   - **触发条件**：
     - `push` 到 `main` 分支，且改动涉及 `templates/**`、`src/builder.py`、`data/parsed/**` 或 `config/**`。
   - **执行步骤**：
     - 跳过抓取与 LLM 调用，直接运行 `python main.py --build-only` 重新渲染 `dist/` 并秒级发布到 GitHub Pages。
     - **优势**：当你在本地调整 UI 样式或手动新增一篇本地解析的文章后，只需 `git push`，约 30 秒内线上站点即自动刷新。

---

## 5. 推荐目录结构

```text
LexiPress/
├── .github/
│   └── workflows/
│       ├── daily-publish.yml   # 每日定时采集 + 解析 + 数据回写 + 发布 Pages
│       └── deploy-site.yml     # 代码/模板/数据 push 后自动重新构建并发布 Pages
├── plan/
│   ├── 01_LexiPress_Plan.md                        # 总体项目规划
│   ├── 02_UI_UX_Design_Spec.md                     # 高端杂志风 UI/UX 规范
│   ├── 03_Harvester_And_Admin_Spec.md              # 多源采集器与可视化后台规范
│   └── 04_Technical_Architecture_And_Closure_Spec.md # 全链路闭环与代码级规范
├── config/
│   ├── feeds.yaml              # 外刊 RSS 源、分类与权重配置
│   └── settings.yaml           # base_url(/LexiPress)、筛选阈值、LLM 与站点配置
├── src/
│   ├── __init__.py
│   ├── storage.py              # 文章索引与去重管理（JSON/SQLite）
│   ├── harvester.py            # RSS 抓取与正文清洗
│   ├── ranker.py               # 规则过滤与价值打分
│   ├── parser.py               # 难度统计与 LLM 精读解析
│   └── builder.py              # Jinja2 静态页面与前端资源生成
├── data/
│   ├── index.json              # 已抓取/已发布文章元数据与去重索引
│   └── parsed/                 # 按日期/ID 缓存的精读解析 JSON
├── templates/
│   ├── base.html               # 全局布局（顶栏、搜索弹窗、生词本抽屉）
│   ├── index.html              # 杂志画报风首页（Hero + Bento Grid + 筛选）
│   ├── article.html            # 沉浸式精读页（双栏 + 悬浮栏 + 生词浮窗）
│   └── static/
│       ├── css/                # 主题变量、排版美学与响应式样式
│       └── js/                 # 交互控制、搜索、生词本、Anki 导出
├── dist/                       # 静态构建产物（.gitignore 忽略，由 Workflow 部署）
├── requirements.txt            # Python 依赖清单
└── main.py                     # 统一 CLI 入口（--full / --build-only / --local-preview）
```

---

## 6. 技术栈选型

| 层级 | 推荐方案 | 说明 |
| :--- | :--- | :--- |
| 运行环境 | Python 3.11+ | 本地开发与 GitHub Actions 统一环境 |
| RSS 与正文提取 | `feedparser` + `trafilatura` + `httpx` | 抓取稳定，正文去噪能力强 |
| 数据持久化 | `data/index.json` + `data/parsed/*.json` | Git 友好，方便在 Actions 中回写与版本追踪 |
| AI 精读解析 | OpenAI 兼容 SDK（支持 DeepSeek / Gemini / OpenAI） | 统一接口，Key 托管于 GitHub Secrets |
| 静态页与 UI | `Jinja2` + 现代原生 CSS（变量/Grid/毛玻璃）+ Vanilla JS | 零构建负担，极致排版与丝滑交互 |
| 语音朗读（进阶） | Web Speech API（即时）+ `edge-tts`（离线 MP3） | 兼顾零成本查词发音与整篇伴读 |
| CI/CD 与托管 | GitHub Actions + GitHub Pages（`actions/deploy-pages`） | 全自动定时更新 + Push 即时预览 |

---

## 7. 分阶段实施路线（Roadmap）

### Phase 1：骨架、惊艳 UI 与 GitHub Workflow 闭环（MVP）
- [ ] 初始化 `LexiPress` 项目骨架、配置文件（`feeds.yaml`、`settings.yaml`）与 `requirements.txt`。
- [ ] 实现 `SourceHarvester` + `ValueRanker`（规则版），成功从 3~5 个优质外刊源拉取并清洗出干净文章。
- [ ] 打造高颜值杂志风前端模板（三套护眼主题、Hero 头版 + Bento 网格、沉浸式精读页、阅读进度条、响应式适配）。
- [ ] 实现 `SiteBuilder` 与本地预览命令，确保 `/LexiPress/` 子路径下所有资源与路由完美运行。
- [ ] 编写 `.github/workflows/deploy-site.yml` 与 `daily-publish.yml`，跑通推送即部署到 `https://<username>.github.io/LexiPress/`。

### Phase 2：英语精读解析与核心学习交互
- [ ] 实现 `StudyParser`：接入大模型 API，生成文章导读、语境生词（含音标/释义）、长难句语法拆解与段落译文，并落盘缓存。
- [ ] 前端完善精读交互：纯英/生词高亮/双语模式一键切换、文内生词点击浮窗与发音、单击段落展开译文。
- [ ] 上线个人学习工作台：全局 `Ctrl+K` 搜索、已读打卡统计、LocalStorage 生词本与一键导出 Anki CSV。

### Phase 3：全自动进化与听读体验
- [ ] 在 `ValueRanker` 中引入 LLM 质量评分，进一步提升每日入选文章含金量。
- [ ] 集成 `edge-tts` 生成整篇英文伴读音频，并在精读页加入悬浮播客风格播放器。
- [ ] 在 GitHub 仓库配置 Secrets 与每日定时调度，实现无人值守的每日外刊精读站。

---

## 8. 关键注意事项与风控

1. **版权与合规**：优先选择开放协议/友好媒体（如 *The Conversation*、*Aeon* 等），每篇文章显著标注原刊来源与原文链接；若后续需要导入受限付费外刊自用，可额外启用静态页面加密（`StatiCrypt`）。
2. **GitHub Pages 子路径规范**：部署地址为 `https://<user>.github.io/LexiPress/`，模板中所有 CSS、JS、图片、文章链接一律通过 `{{ base_url }}` 动态拼接，并在本地预览时模拟相同前缀做校验。
3. **Actions 幂等与成本控制**：将解析结果 JSON 提交回仓库作为持久化缓存，避免每次 Workflow 运行重复调用大模型；同时限制每日最大解析篇数（默认 2~3 篇）。

---

## 9. 待确认事项（进入开发前）

- [ ] **外刊内容偏好**：科技商业 / 深度人文 / 新闻时政 / 综合混合？
- [ ] **大模型 API 选择**：Phase 2 计划接入哪家接口（如 DeepSeek、Gemini、OpenAI 兼容接口）？
- [ ] **GitHub 仓库准备**：是否已创建（或准备创建）名为 `LexiPress` 的 GitHub 仓库用于挂载 GitHub Pages？
