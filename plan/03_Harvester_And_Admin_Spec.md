# LexiPress — 多源外刊采集器与本地可视化后台设计规范

> **文档用途**：本规范详细定义 `LexiPress` 的**数据采集引擎（`SourceHarvester`）**、**数据存储与状态流转**以及**本地可视化管理后台（`LexiPress Admin`）**的架构、接口与界面交互，可直接交由 AI Coding Agent（如 DeepSeek Harness）按模块实现。

---

## 1. 设计目标

1. **稳定、干净、可扩展的多源采集**：通过插件化适配器统一接入 RSS/Atom、社区热榜（如 Hacker News）及人工粘贴 URL，输出无广告、无导航噪音的分段英文正文。
2. **质量可控与成本可控**：引入“候选池 → 精选 → 解析 → 发布”状态机，用户可在可视化后台直观检查清洗后的正文质量，再决定哪些文章触发 LLM 精读解析与发布。
3. **本地可视化操控体验**：提供轻量、优雅的本地 Web 管理后台（`http://127.0.0.1:8088`），支持一键触发采集、实时日志流查看、外刊源调试、正文抽屉预览与发布状态管理，告别纯命令行盲操。

---

## 2. 多源外刊采集器（`SourceHarvester`）详细设计

### 2.1 插件化采集源架构
所有采集源均继承统一抽象基类 `BaseSourceAdapter`，通过 `config/feeds.yaml` 声明式配置：

- **类型一：`rss`（主力引擎）**
  - 使用 `httpx` 拉取 XML + `feedparser` 解析，支持标准 RSS 2.0 / Atom。
  - 首批推荐高质量外刊源：
    - 深度人文/思想：*Aeon*、*The Guardian Long Read*、*BBC Future*
    - 科技与商业：*MIT Technology Review*、*The Verge*、*Ars Technica*
    - 科普与综合：*Quanta Magazine*、*The Conversation*（CC 协议友好）
- **类型二：`hackernews`（高热长文发现器）**
  - 调用 Hacker News 官方 API 拉取 Top / Best Stories，按阈值过滤（如 `score >= 150`），并自动排除非文章域名（`youtube.com`、`github.com`、`twitter.com`、`x.com`、PDF 直链等）。
- **类型三：`manual_url`（人工投喂器）**
  - 用户在后台直接粘贴任意英文文章 URL，立即走同一套正文抽取与入库管线。

### 2.2 四步采集清洗流水线

```text
[Step 1: 列表发现] → [Step 2: URL归一化与去重] → [Step 3: 正文精准抽取] → [Step 4: 指标计算与初筛打分]
```

#### Step 1：异步并发发现（Discovery）
- 使用 `httpx.AsyncClient` 并发抓取已启用的源，通过 `asyncio.Semaphore(5)` 控制最大并发数，避免被目标站限流。
- 统一配置合理请求头（标准桌面浏览器 `User-Agent`、`Accept-Language: en-US,en;q=0.9`）、单请求超时 `15s`、网络瞬断自动指数退避重试 `2` 次。

#### Step 2：URL 归一化与去重（Normalization & Deduplication）
- 清洗 URL 中的追踪参数（`utm_*`、`ref`、`fbclid`、`gclid`、`source` 等）与锚点 `#...`，统一去除末尾多余斜杠。
- 计算 `url_hash = sha256(canonical_url)`，查询本地 SQLite `articles` 表，已存在则跳过，避免重复抓正文。

#### Step 3：正文精准抽取与反爬检测（Extraction）
- **主抽取器**：使用 `trafilatura.bare_extraction()`（开启 `include_images=True, favor_precision=True, deduplicate=True`）提取标题、作者、发布日期、主图 URL 与纯净正文。
- **二级兜底策略**：若主抽取结果词数 `< 200` 且 RSS 原条目自带 `content:encoded` 全文，则回退清洗 RSS 富文本；否则尝试 `readability-lxml` + `BeautifulSoup4` 提取 `<p>` 段落。
- **段落清洗规则**：
  - 按双换行或 `<p>` 切分为段落列表 `paragraphs: list[str]`。
  - 过滤广告/订阅引导噪音段（如匹配 `"Subscribe to our newsletter"`, `"Sign up for"`, `"Read more:"` 且词数 `< 25` 的尾部段落）。
- **付费墙与异常识别**：
  - HTTP 状态码为 `401 / 403 / 429` 或正文词数 `< 250` 且包含 `"subscribe to continue"` / `"paywall"` / `"log in to read"` 时，自动标记状态为 `paywalled`，记录原因，不混入正常候选池。

#### Step 4：阅读指标计算与推荐初筛打分（Pre-Scoring）
对每篇 `fetched` 文章自动计算基础指标与初始推荐分 `score`（0~10 分）：
- **词数统计（`word_count`）**与**预计阅读时间（`read_time_min = ceil(word_count / 200)`）**。
- **篇幅适配度**：`800 ~ 2800` 词最适合外刊精读（满分）；过短（`< 500` 词）或过长（`> 4500` 词）扣分。
- **综合初筛分公式（可配置）**：
  $$\text{score} = \text{clip}\big(\text{source\_weight} \times 4.0 + \text{freshness\_score} \times 3.0 + \text{length\_fit\_score} \times 3.0,\ 0,\ 10\big)$$
  - `freshness_score`：24 小时内 `1.0`，48 小时内 `0.8`，72 小时内 `0.6`，更早线性衰减。

---

## 3. 文章全生命周期状态机与双层存储

### 3.1 状态机流转

```text
                  ┌──► paywalled / failed（可一键重试抓取）
                  │
discovered ──► fetched（候选池）──► shortlisted（精选待解析）──► parsed（已精读解析）──► published（已上线）
                  │
                  └──► rejected（规则或人工淘汰）
```

### 3.2 双层数据存储设计（兼顾本地管理与 GitHub Actions）
1. **本地管理库：`data/lexipress.db`（SQLite，列入 `.gitignore`）**
   - 存放全部候选文章、失败日志、采集任务历史与订阅源运行指标，支持高速多维筛选与排序。
2. **线上发布资产：`data/index.json` + `data/parsed/<article_id>.json`（提交至 Git 仓库）**
   - 仅当文章进入 `parsed` / `published` 状态时，同步导出标准 JSON 到 `data/parsed/` 并更新 `data/index.json`。
   - 这样既保持 Git 仓库轻量整洁，又能让 GitHub Workflow 直接读取并秒级构建静态站。

### 3.3 SQLite 核心表结构

| 表名 | 核心字段 | 说明 |
| :--- | :--- | :--- |
| `sources` | `id`, `name`, `type`, `url`, `category`, `weight`, `enabled`, `last_fetch_at`, `last_status`, `consecutive_failures`, `avg_latency_ms` | 订阅源配置镜像与实时健康监控指标（与 `config/feeds.yaml` 双向同步） |
| `crawl_runs` | `id`, `started_at`, `finished_at`, `trigger_type` (`manual`/`schedule`/`single_source`), `status`, `discovered_count`, `fetched_count`, `failed_count`, `summary_json` | 每次采集任务的执行审计记录 |
| `articles` | `id`, `url_hash` (UNIQUE), `canonical_url`, `source_id`, `source_name`, `title`, `author`, `published_at`, `fetched_at`, `cover_image`, `word_count`, `read_time_min`, `score`, `status`, `error_message`, `raw_paragraphs_json`, `parsed_json_path` | 候选池与全生命周期文章记录 |

---

## 4. 本地可视化后端管理界面（`LexiPress Admin`）设计

### 4.1 运行方式与技术架构
- **启动方式**：命令行执行 `python main.py --admin`（默认监听 `http://127.0.0.1:8088`，仅本机可访问）。
- **技术栈**：
  - 后端：**FastAPI** + `uvicorn`（异步友好，与 `httpx` 采集器天然契合）。
  - 前端：**Jinja2 + 原生 CSS（沿用前台 `LexiPress` 的温润纸感/暗夜极简美学）+ 模块化 Vanilla JS**（零独立前端构建步骤）。
  - 实时通信：**SSE（Server-Sent Events）** 推送采集/解析/构建的实时进度与日志流。

### 4.2 界面导航结构
采用经典的「左侧极简固定导航栏（宽 `220px`）+ 右侧宽屏工作区」布局，顶部附带全局状态胶囊（显示当前是否正在采集、本地预览站点快捷入口）：

1. **总览仪表盘（`/`）**
2. **文章候选池（`/articles`）**
3. **外刊源管理（`/sources`）**
4. **采集任务与实时日志（`/logs`）**
5. **构建与发布中心（`/publish`）**

### 4.3 五大核心页面详细设计

#### 页面 1：总览仪表盘（Dashboard）
- **顶部 KPI 指标卡（4 列）**：
  1. 今日新入库文章数（`fetched`）
  2. 当前精选待解析数（`shortlisted`）
  3. 已发布文章总数（`published`）
  4. 订阅源健康度（如 `7 / 8 正常`，异常源标红提示）
- **快捷操作条**：
  - 「🚀 立即运行全源采集」主按钮（点击后直接打开底部/侧边实时进度浮条，也可跳至日志页）。
  - 「🔗 手动粘贴 URL 抓取」快捷输入框 + 抓取按钮。
  - 「👁️ 构建并打开本地阅读站预览」按钮。
- **下半区双栏**：
  - 左栏：**最近采集任务记录表**（触发方式、时间、耗时、新增/跳过/失败数，支持展开查看单次运行详情）。
  - 右栏：**外刊源健康雷达**（每个源的绿/黄/红状态点、上次成功时间、平均耗时、连续失败次数）。

#### 页面 2：文章候选池与人工精选台（Articles Workbench）
最核心的日常操作界面：
- **多维筛选栏**：
  - 状态页签：`全部` | `新抓取 (fetched)` | `已精选 (shortlisted)` | `已解析 (parsed)` | `已发布 (published)` | `异常/付费墙` | `已淘汰`
  - 下拉过滤：按外刊来源、排序方式（按推荐分降序 / 发布时间降序 / 词数）、关键词搜索框。
- **文章数据表**：
  - 列项：复选框（支持批量操作） | 文章标题（含原文外链图标） | 来源徽章 | 发布时间 | 词数 & 阅读时长 | 推荐分（色阶徽章） | 状态标签 | 操作区。
  - 单行快捷操作：**「预览」**（打开右侧抽屉）、**「精选 ★」**、**「解析 ✨」**、**「淘汰 ✕」**、**「重试抓取 ↻」**（失败项显示）。
  - 批量操作浮动条（勾选多篇时出现）：批量标记精选 / 批量淘汰 / 批量触发 LLM 解析。
- **右侧正文预览抽屉（Article Inspector Drawer，宽 `560px`）**：
  - 点击任意文章标题或「预览」按钮平滑滑出，**无需跳转页面**。
  - 展示内容：
    - 顶部元数据诊断区：来源、作者、发布时间、词数、段落数、抓取状态/报错信息、头图缩略图。
    - 正文清洗质量预览：按段落完整展示抽取出的干净英文正文，方便肉眼快速判断是否存在乱码、广告残留或付费墙截断。
    - 底部固定操作栏：直接执行「设为精选」、「立即 LLM 解析」、「编辑标题/头图」或「淘汰」。

#### 页面 3：外刊源管理中心（Sources Manager）
- 卡片/表格视图展示 `config/feeds.yaml` 中所有订阅源：名称、类型（`RSS` / `HN`）、URL、分类、权重滑块/数值、启用开关（Toggle Switch）。
- **关键交互**：
  - **「+ 新增订阅源」弹窗**：填写名称、类型、RSS URL、分类、权重，保存后自动写回 `config/feeds.yaml` 并同步数据库。
  - **「🧪 单源测试」按钮**：立即对该源执行一次试抓（不污染正式库或仅试抽前 3 篇），弹出测试报告显示：RSS 解析是否成功、发现条目数、首篇文章正文抽取词数与耗时。

#### 页面 4：采集任务与实时日志终端（Live Pipeline & Logs）
- **实时流式日志窗口**：深色等宽终端风格面板，通过 `EventSource('/api/logs/stream')` 实时接收后台抓取、正文抽取、LLM 解析、静态构建的每一条日志。
- 支持按级别过滤（`ALL / INFO / WARN / ERROR`）、自动滚动开关、清空视图。
- 顶部展示当前运行中的任务进度条（如 `Fetching sources: 5/8 · Extracted 14 articles`）。

#### 页面 5：构建与发布中心（Publish Center）
- **待发布与已发布清单**：清晰列出已写入 `data/parsed/` 的所有文章，支持切换“是否在首页置顶/是否下线”。
- **一键本地构建与子路径预览**：
  - 点击「重新生成静态站」调用 `SiteBuilder` 输出至 `dist/`。
  - 内置静态文件挂载点 `/LexiPress/`（FastAPI `StaticFiles` 挂载 `dist/`），点击「打开在线效果预览」即可在 `http://127.0.0.1:8088/LexiPress/` 实时验收与 GitHub Pages 完全一致的子路径效果。
- **Git 同步状态面板**：
  - 读取 `git status --short` 展示 `data/parsed/`、`data/index.json` 与 `config/feeds.yaml` 的变动摘要，提示用户一键复制提交命令或（可选开关）在后台点击「Commit & Push 触发 GitHub Workflow」。

---

## 5. 后端 REST API 接口规范（FastAPI）

所有接口返回统一 JSON 结构 `{ "ok": true, "data": ..., "message": "" }`：

| 方法 | 路径 | 功能说明 |
| :--- | :--- | :--- |
| `GET` | `/api/dashboard` | 获取 KPI 统计、最近 `crawl_runs` 与源健康状态 |
| `GET` | `/api/sources` | 获取所有外刊源列表及运行指标 |
| `POST` | `/api/sources` | 新增外刊源并同步写入 `config/feeds.yaml` |
| `PATCH` | `/api/sources/{source_id}` | 修改源配置（启用/停用、权重、分类等） |
| `DELETE` | `/api/sources/{source_id}` | 删除指定外刊源 |
| `POST` | `/api/sources/{source_id}/test` | 单源测试抓取并返回诊断报告 |
| `POST` | `/api/crawl/run` | 异步触发全源或指定源采集任务，返回 `run_id` |
| `GET` | `/api/crawl/runs` | 分页获取历史采集任务记录 |
| `GET` | `/api/articles` | 多维筛选查询候选池文章（`status`, `source_id`, `q`, `sort`, `page`, `page_size`） |
| `GET` | `/api/articles/{article_id}` | 获取单篇文章详情与清洗后的完整分段正文 |
| `POST` | `/api/articles/manual` | 手动提交单个 URL 立即抓取清洗入库 |
| `PATCH` | `/api/articles/{article_id}/status` | 更新文章状态（`shortlisted` / `rejected` / `published` 等） |
| `POST` | `/api/articles/{article_id}/refetch` | 对抓取失败或异常的文章重新拉取清洗 |
| `POST` | `/api/articles/{article_id}/parse` | 触发单篇（或批量）文章的 LLM 精读解析并导出 JSON |
| `POST` | `/api/site/build` | 触发 `SiteBuilder` 重新生成 `dist/` 静态站点 |
| `GET` | `/api/git/status` | 查看当前仓库 `data/` 与 `config/` 的待提交变更 |
| `GET` | `/api/logs/stream` | SSE 实时日志与任务进度流 |

---

## 6. 新增目录结构补充

在原 `LexiPress` 目录下，新增 `src/admin/` 与 `templates/admin/` 以清晰隔离“公开静态阅读站”与“本地管理后台”：

```text
LexiPress/
├── src/
│   ├── harvester/
│   │   ├── base.py             # BaseSourceAdapter 抽象基类
│   │   ├── rss.py              # RSS / Atom 适配器
│   │   ├── hackernews.py       # Hacker News 高热长文适配器
│   │   ├── extractor.py        # trafilatura + readability 正文抽取与付费墙检测
│   │   └── pipeline.py         # 并发调度、去重、初筛打分与任务日志记录
│   ├── admin/
│   │   ├── app.py              # FastAPI 应用入口 + /LexiPress 静态预览挂载
│   │   ├── routes_api.py       # REST API 与 SSE 日志流路由
│   │   └── routes_pages.py     # 管理后台页面渲染路由
│   └── ...
└── templates/
    ├── site/                   # 公开静态阅读站模板（遵循 02_UI_UX_Design_Spec.md）
    └── admin/                  # 本地可视化后台模板（仪表盘/候选池/源管理/日志/发布）
```

---

## 7. 交付验收清单（供实现阶段自检）

- [ ] **采集健壮性**：单个外刊源超时、403 或 XML 格式异常时，不影响其余源正常完成采集，并在数据库与后台正确记录错误原因。
- [ ] **去重与幂等**：连续两次点击「立即全源采集」，不会产生重复文章记录。
- [ ] **正文质量可见**：在「文章候选池」点击任意文章，右侧抽屉能清晰预览清洗后的分段正文、词数、推荐分及抓取状态。
- [ ] **实时反馈**：点击「立即全源采集」后，日志页能通过 SSE 实时滚动显示采集进度，无需刷新页面。
- [ ] **源管理闭环**：在后台新增/停用外刊源或点击「单源测试」均能真实生效并持久化到 `config/feeds.yaml`。
- [ ] **本地预览一致**：后台点击构建后，访问 `http://127.0.0.1:8088/LexiPress/` 能直接看到与 GitHub Pages 一致的完整高端杂志风站点。
