# LexiPress — 全链路闭环审查与技术代码级实现规范

> **文档用途**：本文档是对前序三份规划文档的**逻辑闭环审计与底层代码级补全**，专门解决模块衔接处的隐蔽边界问题（如云端 Actions 与本地 SQLite 同步、LLM 长文翻译防错位、安全生词高亮算法、并发锁与配置契约），确保 DeepSeek Harness 实现时逻辑 100% 闭环、零歧义。

---

## 1. 逻辑闭环审计：6 个关键边界问题与彻底解法

### 1.1 闭环漏洞 1：本地 SQLite 与 GitHub Actions 无状态运行的数据割裂
- **问题分析**：`data/lexipress.db` 属于本地高频变动库（被 `.gitignore` 忽略），而 GitHub Actions 每次运行都是全新容器，没有本地 `lexipress.db`。若只查 SQLite 去重，Actions 会反复抓取并消耗 LLM 额度；且 Actions 回写新文章到 Git 后，用户 `git pull` 回本地，本地后台 SQLite 看不到云端新发布的文章。
- **彻底闭环方案（双层真理源 + 自动双向同步）**：
  1. **发布真理源**：`data/index.json`（提交至 Git）记录所有已发布文章的 `id`, `url_hash`, `canonical_url`, `title`, `source`, `published_at`, `score`, `difficulty` 等摘要元数据。
  2. **去重双检**：`SourceHarvester` 去重时，同时加载 `data/index.json` 中的 `url_hash` 集合与本地 `lexipress.db`（若存在）的 `url_hash` 集合，取并集判定。这样 Actions 即使无 SQLite 也绝对幂等。
  3. **本地启动自动回填（`sync_git_assets_to_db()`）**：每次启动本地后台（`--admin`）或执行本地 CLI 时，自动扫描 `data/index.json` 与 `data/parsed/*.json`，将云端新增的已发布文章 `UPSERT` 进本地 SQLite（状态置为 `published`）。

### 1.2 闭环漏洞 2：无 LLM API Key 时的冷启动与优雅降级
- **问题分析**：在 Phase 1 或用户尚未配置 `LLM_API_KEY` 时，如果流水线强依赖 LLM，整个采集→构建→发布闭环会直接报错卡死。
- **彻底闭环方案**：
  - 在 `StudyParser` 中内置 `mode`:
    - 当 `LLM_API_KEY` 存在且 `enable_llm: true` 时，执行完整 LLM 精读解析（导读 + 语境生词 + 长难句 + 分段译文）。
    - 当 `LLM_API_KEY` 为空或单篇 LLM 调用全部重试失败时，自动降级为 **`RuleOnlyParser`**：仍生成合法的标准 `data/parsed/<id>.json`（保留完整英文分段、词数、阅读时长、基于内置词表/启发式算法的难度等级，译文与生词字段为空数组/空字符串），确保前台页面与 GitHub Pages 发布 100% 正常跑通；后续配置 Key 后可在后台一键「重新解析」。

### 1.3 闭环漏洞 3：长文章 LLM 分段翻译错位与非法 JSON 崩溃
- **问题分析**：将 25 段外刊一次性交给 LLM 翻译，模型极易合并段落或遗漏段落，导致中英文对照错位；且模型偶发输出 Markdown 代码块包裹的 JSON。
- **彻底闭环方案（两阶段结构化调用 + Pydantic v2 强校验）**：
  1. **阶段 A（逐段索引翻译，分批执行）**：将 `paragraphs` 按每批 `batch_size = 10` 段切分，输入带显式序号的 JSON `[{"index": 0, "en": "..."}, ...]`，强制要求返回 `{"translations": [{"index": 0, "zh": "..."}]}`，按 `index` 精确回填到对应段落，杜绝错位。
  2. **阶段 B（全篇精读提炼）**：将全文（超 3500 词时智能截断保留首尾与关键段）发给 LLM，要求严格按 Pydantic Schema 输出 `overview`、`vocab`（10~15 词）与 `sentences`（3~5 句）。
  3. **容错提取与重试**：使用 `response_format={"type": "json_object"}`，并对返回文本做容错剥离（去除可能存在的 ````json ... ```` 围栏）后通过 Pydantic 校验；校验失败自动指数退避重试最多 2 次。

### 1.4 闭环漏洞 4：文内生词高亮注入破坏 HTML 或错误匹配子串
- **问题分析**：若简单用 `str.replace("art", "<mark>art</mark>")`，会破坏 `start`、`article` 等单词，或破坏已有 HTML 标签属性。
- **彻底闭环方案（编译期纯文本词边界单遍替换算法）**：
  - 在 Python 端 `SiteBuilder` 渲染阶段处理（而非浏览器运行时正则）：
    1. 先对原始英文段落执行 `html.escape(text)`，确保输入为安全纯文本。
    2. 将该文章的 `vocab` 列表按 `len(term)` **从长到短排序**（优先匹配短语如 `take for granted`，再匹配单词）。
    3. 构造单遍联合正则：`r'(?<![A-Za-z])(' + '|'.join(re.escape(t) for t in sorted_terms) + r')(?![A-Za-z])'`（开启 `re.IGNORECASE`）。
    4. 使用 `re.sub(pattern, replace_fn, escaped_text)` 一次性替换为 `<mark class="vocab-term" data-vocab-id="{vid}">{matched}</mark>`。因为单遍扫描不会二次扫描已插入的标签，从根本上杜绝嵌套 `<mark>` 与属性污染。

### 1.5 闭环漏洞 5：本地后台并发点击冲突与 SQLite 锁死
- **问题分析**：用户在后台连点两次「立即全源采集」，或在采集写入时刷新候选池列表，容易触发 SQLite `database is locked` 或重复抓取。
- **彻底闭环方案**：
  - **SQLite 并发配置**：所有连接初始化强制执行 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`。
  - **全局任务锁（`TaskManager`）**：后台维护内存级 `asyncio.Lock` 与任务状态机，同时只允许一个全源采集任务运行；重复点击返回 `409 Conflict` 并提示前端直接切到实时日志流查看当前进度。
  - **JSON 原子落盘**：写入 `data/index.json` 和 `data/parsed/*.json` 时一律先写临时文件 `.tmp` 再 `os.replace()` 原子替换，防止中途异常写坏文件。

### 1.6 闭环漏洞 6：GitHub Pages 静态产物与子路径陷阱
- **问题分析**：GitHub Pages 默认启用 Jekyll 处理，可能吞掉特定文件；且仓库子路径 `/LexiPress/` 下 404 页面和静态资源极易失效。
- **彻底闭环方案**：
  - `SiteBuilder` 每次构建 `dist/` 必须产出以下完整文件树：
    ```text
    dist/
    ├── .nojekyll                        # 必须！禁用 GitHub Pages Jekyll 解析
    ├── index.html                       # 杂志画报风首页
    ├── 404.html                         # 优雅杂志风 404 页面（带返回首页按钮）
    ├── search-index.json                # 供 Cmd+K 命令面板使用的全站搜索索引
    ├── articles/
    │   └── <article_id>/
    │       └── index.html               # Clean URL 精读页
    └── static/
        ├── css/ (tokens.css, site.css)
        └── js/  (app.js, reader.js, search.js, vocab.js)
    ```
  - 本地管理后台 `src/admin/app.py` 启动时若 `dist/` 尚不存在，自动创建空目录并在 `/LexiPress` 路径提供友好引导页（提示点击「立即构建」），避免 FastAPI 启动崩溃。

---

## 2. 统一配置契约与环境变量

### 2.1 `config/settings.yaml`
```yaml
site:
  title: "LexiPress"
  subtitle: "Curated English Reading Studio"
  base_url: "/LexiPress"            # GitHub Pages 仓库子路径，无末尾斜杠；本地根路径预览可设为 ""
  articles_per_page: 24
  default_theme: "paper"            # paper | sepia | ink

harvester:
  max_concurrency: 5
  request_timeout_sec: 15
  max_retries: 2
  freshness_hours: 72               # 优先保留最近 72 小时内的文章
  min_word_count: 500
  max_word_count: 4500
  daily_publish_limit: 3            # Actions 全自动模式每日最多精选解析篇数
  user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

llm:
  enabled: true                     # 若环境变量 LLM_API_KEY 为空则自动降级为规则模式
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-chat"
  temperature: 0.3
  translate_batch_size: 10
  max_retries: 2

admin:
  host: "127.0.0.1"
  port: 8088
```

### 2.2 `config/feeds.yaml`（首批开箱即用的高质量开放源）
```yaml
sources:
  - id: "aeon"
    name: "Aeon"
    type: "rss"
    url: "https://aeon.co/feed.rss"
    category: "Culture & Ideas"
    weight: 1.0
    enabled: true

  - id: "the-conversation"
    name: "The Conversation"
    type: "rss"
    url: "https://theconversation.com/global/articles.atom"
    category: "Science & Society"
    weight: 0.95
    enabled: true

  - id: "guardian-longread"
    name: "The Guardian Long Read"
    type: "rss"
    url: "https://www.theguardian.com/news/series/the-long-read/rss"
    category: "In-Depth"
    weight: 1.0
    enabled: true

  - id: "quanta"
    name: "Quanta Magazine"
    type: "rss"
    url: "https://api.quantamagazine.org/feed/"
    category: "Science & Tech"
    weight: 0.95
    enabled: true

  - id: "mit-tech-review"
    name: "MIT Technology Review"
    type: "rss"
    url: "https://www.technologyreview.com/feed/"
    category: "Technology"
    weight: 0.9
    enabled: true

  - id: "hackernews"
    name: "Hacker News Top"
    type: "hackernews"
    url: "https://hacker-news.firebaseio.com/v0/topstories.json"
    category: "Tech & Engineering"
    weight: 0.85
    min_score: 180
    limit: 20
    enabled: true
```

### 2.3 `.env.example`（敏感信息严禁入库）
```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 2.4 `requirements.txt`（核心 Python 依赖清单）
```txt
httpx>=0.27.0
feedparser>=6.0.11
trafilatura>=1.12.0
readability-lxml>=0.8.1
beautifulsoup4>=4.12.3
lxml>=5.2.0
pydantic>=2.7.0
PyYAML>=6.0.1
python-dotenv>=1.0.1
Jinja2>=3.1.4
openai>=1.35.0
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
```

---

## 3. 核心 Python 模块接口契约（供代码实现对齐）

为了确保各模块低耦合、易测试，约定核心类与 CLI 入口如下：

### 3.1 数据模型（`src/models.py`，基于 Pydantic v2）
- `SourceConfig`：对应 `feeds.yaml` 单条配置。
- `RawArticle`：采集器输出的标准清洗文章（`url_hash`, `canonical_url`, `source_id`, `source_name`, `title`, `author`, `published_at`, `cover_image`, `paragraphs: list[str]`, `word_count`, `read_time_min`, `score`, `status`, `error_message`）。
- `VocabItem` / `SentenceAnalysis` / `ArticleOverview` / `ParagraphPair` / `ParsedArticle`：严格对应 `02_UI_UX_Design_Spec.md` 第 6.1 节的 JSON Schema，作为 `StudyParser` 的校验目标与 `SiteBuilder` 的输入对象。

### 3.2 核心服务类方法签名
- **`Storage`（`src/storage.py`）**：
  - `init_db()`：初始化 SQLite（开启 WAL）与三张表。
  - `sync_git_assets_to_db()`：读取 `data/index.json` + `data/parsed/*.json` 回填本地 DB。
  - `get_known_url_hashes() -> set[str]`：合并 `index.json` 与 DB 的去重集合。
  - `export_parsed_article(article: ParsedArticle)`：原子写入 `data/parsed/<id>.json` 并更新 `data/index.json`。
- **`HarvesterPipeline`（`src/harvester/pipeline.py`）**：
  - `async def run_all(trigger_type: str = "manual", log_cb=None) -> CrawlRunResult`
  - `async def run_single_source(source_id: str, dry_run: bool = False) -> SourceTestResult`
  - `async def fetch_manual_url(url: str) -> RawArticle`
- **`StudyParser`（`src/parser.py`）**：
  - `async def parse_article(raw: RawArticle, force_rule_only: bool = False) -> ParsedArticle`
- **`SiteBuilder`（`src/builder.py`）**：
  - `def build(output_dir: Path = Path("dist")) -> BuildSummary`：读取 `data/index.json` 与 `data/parsed/*.json`，注入安全生词高亮，渲染全部 HTML、`search-index.json`、`.nojekyll`、`404.html` 并复制静态资源。

### 3.3 统一命令行入口（`main.py`）
使用 `argparse` 提供清晰的 CLI 子命令，兼顾本地开发与 GitHub Actions：
- `python main.py --admin`：启动本地可视化后台（`http://127.0.0.1:8088`）并挂载 `/LexiPress` 预览。
- `python main.py --pipeline full`：全自动流水线（同步去重 → 全源采集 → 按评分取 Top N → 精读解析 → 导出 JSON → 构建 `dist/`），供 GitHub Actions 定时任务使用。
- `python main.py --crawl-only`：仅执行采集入库（进入本地候选池供人工筛选）。
- `python main.py --build-only`：跳过采集与 LLM，仅基于 `data/parsed/` 重新构建 `dist/`。

---

## 4. GitHub Workflow 实现蓝图（防坑细节）

### 4.1 `.github/workflows/daily-publish.yml` 关键实现要求
- **权限声明**：
  ```yaml
  permissions:
    contents: write   # 允许回写 data/parsed/ 与 data/index.json
    pages: write      # 允许部署 GitHub Pages
    id-token: write   # OIDC 部署凭证
  concurrency:
    group: "pages"
    cancel-in-progress: false
  ```
- **环境变量注入**：从 Repository Secrets 读取 `LLM_API_KEY`（可选，未配置时自动走规则降级）、`LLM_BASE_URL`、`LLM_MODEL`。
- **安全回写逻辑**（防止无变更报错或推送冲突）：
  ```bash
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git add data/index.json data/parsed/
  if ! git diff --staged --quiet; then
    git commit -m "chore(content): daily curated issues [skip ci]"
    git pull --rebase origin main
    git push origin main
  fi
  ```
- **标准部署步骤**：`actions/configure-pages@v5` → `actions/upload-pages-artifact@v3`（`path: ./dist`）→ `actions/deploy-pages@v4`。

### 4.2 `.github/workflows/deploy-site.yml` 关键实现要求
- 仅监听 `push` 到 `main` 且路径匹配 `templates/**`、`src/builder.py`、`data/**`、`config/settings.yaml`。
- 仅需 `pages: write` 与 `id-token: write` 权限；直接执行 `python main.py --build-only` 后部署 `dist/`，实现改 UI 样式或本地推送精选文章后约 30 秒自动上线。

---

## 5. 端到端闭环验证场景（上线前必测）

1. **场景 A（本地人工精选闭环）**：
   - 运行 `python main.py --admin` → 浏览器打开 `http://127.0.0.1:8088` → 点击「立即全源采集」并在日志页观察 SSE 实时流 → 进入「文章候选池」点开右侧抽屉预览正文 → 选 2 篇点击「解析」→ 进入「发布中心」点击「构建静态站」→ 打开 `http://127.0.0.1:8088/LexiPress/` 验证三套主题、生词浮窗、双语切换、搜索与生词本导出 → `git push` 触发 `deploy-site.yml` 成功上线。
2. **场景 B（云端全自动定时闭环）**：
   - 在 GitHub Actions 网页端手动点击 `daily-publish.yml` 的 **Run workflow** → 自动采集去重（不重复抓取场景 A 已发文章）→ 自动精选并解析 → 自动回写 `data/parsed/` 到 `main` → 自动部署至 `https://<username>.github.io/LexiPress/` → 本地 `git pull` 后启动 `--admin`，本地后台自动同步显示云端新发布的文章。
3. **场景 C（异常降级闭环）**：
   - 故意填入一个失效 RSS 源 + 不配置 `LLM_API_KEY` 运行流水线 → 失效源被隔离记录在后台健康雷达中，其余源正常入库；`StudyParser` 自动降级为规则模式，前台页面无报错、无空白尴尬区块，站点正常上线。
