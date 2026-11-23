# LexiPress · 外刊精读工坊

> 本地 Python 驱动 + GitHub Actions 全自动的**外刊精选、英语精读解析与高端杂志风静态阅读站**。

从多个高质量英文外刊源自动筛选最新、最值得读的文章，完成正文清洗与英语精读解析，渲染出优雅、惊艳且极度顺手的在线精读界面，并通过 GitHub Actions 自动构建、发布至带仓库子路径的 GitHub Pages（`https://<username>.github.io/LexiPress/`）。

---

## ✨ 核心特性

| 能力 | 说明 |
| :--- | :--- |
| **多源采集器** | 插件化 RSS / Atom + Hacker News 高热长文，异步限流并发、指数退避重试 |
| **正文精准抽取** | `trafilatura` 主抽取 + `readability-lxml` + RSS 富文本三级兜底，付费墙自动识别 |
| **综合初筛打分** | 来源权重 × 时效性 × 篇幅适配度，自动选出「最值得读」的 Top N |
| **LLM 精读解析** | 两阶段结构化调用：分批带 `index` 翻译防错位 + 全篇导读/生词/长难句，Pydantic 强校验重试 |
| **优雅降级** | 未配置 `LLM_API_KEY` 或调用失败时，自动降级为 `RuleOnlyParser`，站点照常发布 |
| **高端杂志风前台** | Editorial Luxury 美学，三套护眼主题、Hero 头版 + Bento 网格、沉浸式精读页 |
| **本地可视化后台** | FastAPI + SSE 实时日志，仪表盘/候选池/源管理/日志/发布五大页面 |
| **全自动发布** | GitHub Actions 双 Workflow：每日定时采集 + push 秒级重建部署 |

---

## 🏗️ 架构

```
[1. SourceHarvester 采集器]     多源发现 → URL 归一化 → 双重去重 → 正文抽取 → 初筛打分
        ↓
[2. ValueRanker 精选器]         按综合分取 Top N 最值得读的文章
        ↓
[3. StudyParser 精读解析器]     两阶段 LLM → 结构化 JSON 落盘（无 Key 自动降级规则模式）
        ↓
[4. SiteBuilder 站点生成器]     Jinja2 + 现代原生 CSS + Vanilla JS → 高端杂志风静态站
        ↓
[5. GitHub Workflow 发布流]     actions/deploy-pages → https://<user>.github.io/LexiPress/
```

### 双层存储

- **本地管理库** `data/lexipress.db`（SQLite，WAL + busy_timeout=5000，`.gitignore` 忽略）
- **发布真理源** `data/index.json` + `data/parsed/<id>.json`（提交 Git，是 GitHub Actions 的唯一依据）

启动时自动 `sync_git_assets_to_db()` 把云端资产回填本地库，形成「本地候选池 ↔ 线上发布」双向闭环。

### 目录结构

```
LexiPress/
├── .github/workflows/         # daily-publish.yml + deploy-site.yml
├── config/                    # settings.yaml（站点/采集/LLM/后台）+ feeds.yaml（订阅源）
├── src/
│   ├── models.py              # Pydantic v2 数据契约
│   ├── config.py              # 配置加载与 feeds.yaml 读写
│   ├── storage.py             # 双层存储 + 双向同步
│   ├── utils.py               # URL 归一化 / 打分 / 难度评估 / 词表
│   ├── parser.py              # StudyParser + RuleOnlyParser
│   ├── builder.py             # 静态站生成器（含生词高亮注入）
│   ├── harvester/             # base / rss / hackernews / extractor / pipeline
│   └── admin/                 # app / routes_api / routes_pages / tasks
├── templates/
│   ├── site/                  # 前台 Jinja2 模板 + static/(css/js)
│   └── admin/                 # 后台模板 + static/(admin.css/js)
├── data/                      # index.json + parsed/ + lexipress.db（运行时）
├── dist/                      # 静态构建产物（.gitignore 忽略）
├── scripts/                   # seed_demo.py + e2e_check.py
├── tests/                     # pytest 单元/集成测试
├── main.py                    # 统一 CLI 入口
├── requirements.txt
└── README.md
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

> 需要 Python 3.11+。

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY（可选，不填则自动降级规则模式）
```

站点子路径、采集阈值、LLM 模型等均在 `config/settings.yaml`，订阅源在 `config/feeds.yaml`。

### 3. 运行

```bash
# 本地可视化后台（含 /LexiPress 预览）
python main.py --admin

# 全自动流水线：采集 → 精选 → 解析 → 构建
python main.py --pipeline full

# 仅采集入库
python main.py --crawl-only

# 仅基于 data/parsed/ 重建静态站
python main.py --build-only
```

详细使用说明见 [USER_USE.md](./USER_USE.md)。

---

## 🧪 测试

```bash
python -m pytest tests -q            # 133 项单元/集成测试
python scripts/e2e_check.py --shots  # 浏览器端到端验收（需 Playwright）
```

---

## 📦 部署到 GitHub Pages

1. 在 GitHub 创建名为 `LexiPress` 的仓库。
2. 打开仓库 **Settings → Pages → Source** 选择 **GitHub Actions**。
3. 在 **Settings → Secrets and variables → Actions** 添加（可选）：
   - `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`（不配则规则降级）
4. 推送代码后，`deploy-site.yml` 自动构建部署；`daily-publish.yml` 每日 07:00（北京时间）自动采集更新，也可在 Actions 页手动 **Run workflow**。

---

## 📄 许可证

采集源优先选择开放协议/友好媒体（The Conversation、Aeon 等），每篇文章显著标注原刊来源与原文链接，版权归原刊所有。
