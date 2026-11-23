# LexiPress · 使用手册

本文档面向**最终使用者**，详细说明如何从零把 LexiPress 跑起来、如何日常使用本地后台、如何部署到 GitHub Pages，以及遇到问题时的排查思路。

---

## 目录

1. [环境准备](#1-环境准备)
2. [第一次运行](#2-第一次运行)
3. [本地可视化后台详解](#3-本地可视化后台详解)
4. [命令行用法](#4-命令行用法)
5. [外刊源管理](#5-外刊源管理)
6. [英语精读解析（LLM）](#6-英语精读解析llm)
7. [前台阅读站使用](#7-前台阅读站使用)
8. [GitHub Pages 部署](#8-github-pages-部署)
9. [常见问题](#9-常见问题)

---

## 1. 环境准备

| 依赖 | 版本要求 | 说明 |
| :--- | :--- | :--- |
| Python | 3.11+ | 本地开发与 GitHub Actions 统一 |
| pip | 最新 | 安装依赖 |
| Git | 任意 | 部署与回写缓存 |
| (可选) 网络代理 | — | 采集外刊站点需要能访问公网 |

### 安装依赖

```bash
# 建议使用虚拟环境
python -m venv .venv

# Windows 激活
.venv\Scripts\activate
# Linux / macOS 激活
source .venv/bin/activate

pip install -r requirements.txt
```

> 如果国内网络较慢，可先给 pip 配置镜像源（如清华源）再安装。

---

## 2. 第一次运行

### 2.1 生成配置文件

项目已内置开箱即用的配置，无需手动创建。两个关键配置：

- `config/settings.yaml` — 站点标题、子路径 `base_url`、采集阈值、LLM、后台端口等。
- `config/feeds.yaml` — 外刊订阅源列表（默认 8 个高质量源）。

### 2.2 配置 LLM（可选，但强烈建议）

复制环境变量示例：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

> **不配置 `LLM_API_KEY` 也能完整运行**：精读解析会自动降级为 `RuleOnlyParser`，
> 产出合法的站点（英文分段 + 难度等级 + 结构提示），只是没有中文译文、语境生词与长难句拆解。
> 之后补上 Key，在后台点「重新解析」即可补齐。

### 2.3 验证安装

```bash
python main.py --build-only
```

若输出 `✓ 构建成功`，说明依赖与数据链路正常。

---

## 3. 本地可视化后台详解

### 3.1 启动

```bash
python main.py --admin
```

浏览器打开 <http://127.0.0.1:8088>（仅本机可访问）。

左侧固定导航包含五个页面：

#### ① 总览仪表盘（`/`）

- **KPI 卡片**：今日新入库、精选待解析、已发布总数、订阅源健康度。
- **快捷操作**：一键全源采集、手动粘贴 URL 抓取、打开阅读站预览。
- **下半区**：最近采集任务记录 + 外刊源健康雷达（绿/黄/红状态点）。

#### ② 文章候选池（`/articles`）

日常最常用的页面：

- **状态页签**：全部 / 新抓取 / 已精选 / 已解析 / 已发布 / 异常付费墙 / 已淘汰。
- **筛选排序**：按来源、关键词、推荐分、发布时间、词数。
- **单行操作**：预览、精选 ★、解析 ✨、淘汰 ✕、重试 ↻。
- **右侧预览抽屉**：点任意文章标题或「预览」，无需跳转即可查看清洗后的正文、词数、推荐分与抓取状态。
- **批量操作**：勾选多篇后底部浮出「批量精选 / 批量解析 / 批量淘汰」。

#### ③ 外刊源管理（`/sources`）

- 查看/新增/编辑/删除订阅源，改动自动写回 `config/feeds.yaml`。
- **启用开关**：一键停用失效源，不影响其它源。
- **单源测试**：试抽前 3 篇，弹出诊断报告（发现条目数、首篇词数、耗时、错误原因）。

#### ④ 实时日志（`/logs`）

- 深色终端风格，通过 SSE 实时滚动采集/解析/构建日志。
- 支持级别过滤（ALL/INFO/WARN/ERROR）、自动滚动、清空。
- 顶部显示当前任务进度条。

#### ⑤ 构建与发布中心（`/publish`）

- **构建状态**：显示 `dist/` 的构建时间、文章页数、必备产物是否齐全。
- **一键构建**：`重新生成静态站`，随后访问 <http://127.0.0.1:8088/LexiPress/> 预览。
- **文章上线/下线开关**：控制哪些文章出现在前台。
- **Git 同步状态**：展示 `data/`、`config/` 的待提交变更，一键复制提交命令。

---

## 4. 命令行用法

```bash
python main.py --admin                 # 启动本地后台 + /LexiPress 预览
python main.py --pipeline full         # 全自动：采集 → 精选 → 解析 → 构建
python main.py --crawl-only            # 仅采集入库
python main.py --build-only            # 仅重建静态站
```

可选参数：

| 参数 | 说明 |
| :--- | :--- |
| `--limit N` | 覆盖每日解析篇数 |
| `--force-rule-only` | 强制规则解析，不调用 LLM |
| `--source ID` | 只采集指定源（可重复） |
| `--host / --port` | 后台绑定地址 |
| `--backfill-index` | 把 `data/parsed/` 中未上线的资产重新上线 |
| `--output` | 构建输出目录（默认 `dist/`） |

### 典型工作流

```bash
# 1. 全量抓取（或直接走 full）
python main.py --crawl-only

# 2. 打开后台，人工筛选 + 精选 + 解析
python main.py --admin

# 3. 满意后构建 + 提交 + 推送（触发 GitHub Pages 发布）
python main.py --build-only
git add data/ config/ templates/ src/ main.py requirements.txt .github/
git commit -m "chore(content): curated issues"
git push
```

---

## 5. 外刊源管理

### 默认订阅源

| ID | 名称 | 类型 | 分类 |
| :--- | :--- | :--- | :--- |
| aeon | Aeon | RSS | Culture & Ideas |
| the-conversation | The Conversation | RSS | Science & Society |
| guardian-longread | The Guardian Long Read | RSS | In-Depth |
| quanta | Quanta Magazine | RSS | Science & Tech |
| mit-tech-review | MIT Technology Review | RSS | Technology |
| bbc-future | BBC Future | RSS | Science & Society |
| the-verge | The Verge | RSS | Technology |
| hackernews | Hacker News Top | HN | Tech & Engineering |

### 新增源（后台操作）

1. 进入「外刊源管理」，点右上角「+ 新增订阅源」。
2. 填写 ID（英文小写唯一）、名称、类型（RSS / HN）、Feed URL、分类、权重。
3. 保存后自动写回 `config/feeds.yaml`，并立即出现在健康雷达中。

### 新增源（手动编辑）

直接编辑 `config/feeds.yaml`：

```yaml
sources:
  - id: "my-feed"
    name: "My Feed"
    type: "rss"
    url: "https://example.com/feed.xml"
    category: "Custom"
    weight: 0.9
    enabled: true
```

> 保存后重启后台（或后台自动同步），即可生效。

---

## 6. 英语精读解析（LLM）

### 解析流程（两阶段）

1. **阶段 A — 逐段翻译**：按 `batch_size`（默认 10）分批，带显式 `index` 翻译，按 index 精确回填，杜绝中英错位。
2. **阶段 B — 精读提炼**：全篇导读、核心词汇（音标/词性/语境释义）、长难句拆解（语法主干 + 地道意译）。

### 容错与降级

- 返回文本自动剥离 ```` ```json ```` 围栏，Pydantic v2 强校验。
- 校验失败自动指数退避重试（默认 2 次）。
- 全部失败或未配置 Key → 自动降级 `RuleOnlyParser`。

### 触发解析

- **后台**：候选池里对单篇点「✨ 解析」，或勾选多篇点「批量解析」。
- **CLI**：`python main.py --pipeline full --limit 3` 自动解析 Top 3。

---

## 7. 前台阅读站使用

访问 <http://127.0.0.1:8088/LexiPress/>（本地）或 <https://<user>.github.io/LexiPress/>（线上）。

### 首页

- **Hero 今日头条**：综合评分最高的文章以杂志头版形态呈现；无封面图时自动渲染印刷排版艺术封面。
- **筛选胶囊**：按来源 / 难度 / 已读状态即时过滤。
- **全局搜索**：`Ctrl/Cmd + K` 唤起，模糊匹配标题、来源、标签、生词。

### 精读页

| 交互 | 说明 |
| :--- | :--- |
| 阅读模式 | 纯英 / 生词高亮 / 双语对照，一键切换 |
| 单段译文 | 点击段落右上角「译」按钮，按需展开该段中文 |
| 生词浮窗 | 点击带虚线下划线的词，弹出音标 + 语境释义，`🔊` 发音，`★` 收藏 |
| 排版调节 | `Aa` 面板：字号 S/M/L + 三套主题色块 |
| 禅模式 | 收起右侧助手栏，正文居中沉浸 |
| 精读助手 | 右侧「导读 / 词表 / 长难句」三个 Tab；词表点击可联动滚动到正文 |
| 盲读保护罩 | 导读默认模糊，点击揭晓（建议先读英文） |
| 已读打卡 | 文末「标记为已读」，自动记录连续打卡天数 |

### 快捷键

| 按键 | 功能 |
| :--- | :--- |
| `Ctrl/Cmd + K` | 打开全局搜索 |
| `Esc` | 关闭弹窗 / 生词浮窗 / 抽屉 |
| `1` / `2` / `3` | 纯英 / 生词 / 双语 |
| `Z` | 禅模式 |
| `T` | 循环切换主题 |

### 学习工作台

点击顶栏书签图标打开右侧抽屉：

- **学习数据**：连续打卡、已读篇数、生词数。
- **生词本**：按时间倒序展示，支持搜索、发音、删除。
- **导出**：一键生成 **Anki CSV**（UTF-8 BOM，直接导入 Anki）或 **Markdown** 复习清单。

> 所有学习数据保存在浏览器 `localStorage`，键统一 `lexipress_` 前缀，换浏览器/设备不互通。

---

## 8. GitHub Pages 部署

### 8.1 核心模式：后端本地跑，GitHub 只渲染

**采集、LLM 精读解析、后台管理全部只在本地运行。** GitHub Actions 只做一件事：
把已经提交到仓库的博客源文件（`data/parsed/*.json` + `data/index.json`）用
`python main.py --build-only` 渲染成静态站，然后部署到 GitHub Pages。

因此 **GitHub 上不需要配置 LLM 密钥，也不会运行任何采集/解析逻辑**。

### 8.2 准备仓库

1. 在 GitHub 创建名为 **`LexiPress`** 的仓库。
2. 进入 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。

### 8.3 本地准备博客源文件

```bash
# 本地：采集 → 精选 → 解析（可反复调整，直到满意）
python main.py --admin          # 后台可视化操作，或
python main.py --pipeline full  # 一键全自动

# 本地可随时预览效果
python main.py --build-only
```

### 8.4 提交并推送（触发部署）

```bash
git add data/ templates/ src/ config/ main.py requirements-build.txt .github/
git commit -m "chore(content): update curated issues"
git push
```

推送后，`.github/workflows/deploy-site.yml` 自动：
1. 安装 `requirements-build.txt`（仅 4 个轻量包）
2. `python main.py --build-only` 渲染静态站
3. 上传并部署到 GitHub Pages

约 30 秒后即可访问 `https://<你的用户名>.github.io/LexiPress/`。

### 8.5 日常更新流程

- **有新文章**：本地跑 `--pipeline full` 或后台操作，生成新的 `data/parsed/*.json`，提交推送即可。
- **改 UI / 样式**：改 `templates/` 或 `src/builder.py`，提交推送即可。
- **下架文章**：在后台「发布中心」关闭对应文章的上线开关，提交推送。
- 全程无需在 GitHub 上做任何操作，只需本地准备好源文件后 push。

---

## 9. 常见问题

### Q1：不配置 LLM_API_KEY 会怎样？

解析自动降级规则模式：站点照常构建发布，只是没有中文译文/生词/长难句。补上 Key 后在后台「重新解析」即可。

### Q2：某个外刊源抓取失败怎么办？

单源失败会被隔离，不影响其它源。进入「外刊源管理」看健康雷达（红点 = 连续失败 ≥3），点「单源测试」查看具体报错。

### Q3：连续点两次「立即采集」会重复入库吗？

不会。后端有全局并发锁，第二次触发返回 409；且 URL 去重（`index.json` ∪ SQLite）保证幂等。

### Q4：为什么后台候选池有文章，但前台看不到？

只有「已解析并上线」的文章才会进入前台。流程是：抓取 → 精选 → 解析 → 上线（或 `--pipeline full` 全自动）。在「发布中心」检查文章的上线开关。

### Q5：站点部署到子路径 `/LexiPress/` 会 404 吗？

不会。所有资源与内链都通过 `base_url` 动态拼接，`dist/.nojekyll` 禁用了 Jekyll，本地 `/LexiPress/` 预览与线上行为完全一致。

### Q6：如何修改站点主题、子路径、采集阈值？

编辑 `config/settings.yaml`：

```yaml
site:
  base_url: "/LexiPress"    # 改成 "" 则为根路径部署
  default_theme: "paper"    # paper | sepia | ink

harvester:
  min_word_count: 500       # 最小词数
  max_word_count: 4500      # 最大词数
  daily_publish_limit: 3    # 每日最多解析篇数
```

### Q7：生词本数据在哪里？

浏览器 `localStorage`，键名 `lexipress_vocab_book`。清空浏览器数据会丢失，建议定期导出 Anki CSV 备份。

### Q8：如何跑测试？

```bash
python -m pytest tests -q            # 单元/集成测试
python scripts/e2e_check.py --shots  # 浏览器端到端验收（需 Playwright + Chromium）
```

---

## 附：数据文件说明

| 路径 | 是否提交 Git | 说明 |
| :--- | :--- | :--- |
| `data/index.json` | ✅ 提交 | 已发布文章摘要索引（发布真理源） |
| `data/parsed/*.json` | ✅ 提交 | 精读解析资产（供构建与 Actions 复用） |
| `data/lexipress.db` | ❌ 忽略 | 本地候选池数据库，启动时自动从 Git 资产同步 |
| `dist/` | ❌ 忽略 | 构建产物，由 Actions 部署 |
| `.env` | ❌ 忽略 | 本地密钥，用 `.env.example` 模板 |
| `logs/` | ❌ 忽略 | 运行日志 |
