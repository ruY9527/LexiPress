# LexiPress · About 全部内容

> 本文件集中存放 GitHub 仓库 About 与站点 About 页面所需的全部文案，可直接复制使用。

---

## 一、提示词式描述（核心文案 · 写入 GitHub Description）

下面这段是「提示词式」项目描述——像给 AI 下指令一样描述这个项目是什么、做什么、怎么运作。已控制在 GitHub Description 的 350 字符上限内。

```
Build LexiPress: a Python + LLM English reading studio. Harvest RSS/HN → dedupe → trafilatura extract → score → two-stage LLM (indexed paragraph translation + vocab/sentence breakdown, Pydantic-validated, rule-only fallback) → editorial-luxury Jinja2 site with 3 themes, Cmd+K search, vocab popover & Anki export → GitHub Pages via Actions.
```

### 中文提示词版（备选）

```
搭建 LexiPress：Python + LLM 英文精读工坊。多源采集 → URL 去重 → 正文抽取 → 综合打分 → 两阶段 LLM（带 index 的逐段翻译 + 生词/长难句提炼，Pydantic 校验，失败自动规则降级）→ 高端杂志风静态站（三主题、Cmd+K 搜索、生词浮窗、Anki 导出）→ GitHub Actions 自动发布。
```

---

## 二、GitHub About 其余字段

### Website

```
https://ruy9527.github.io/LexiPress/
```

### Topics（按顺序逐个添加）

```
english-learning
reading
vocabulary
journalism
rss-feed
content-curation
static-site
jinja2
python
fastapi
llm
github-pages
education
language-learning
deepseek
editorial-design
```

---

## 三、站点 About 页面正文（已写入 templates/site/about.html）

### 页头标语

> **A reading studio, not a feed.**
> 精读工坊，而非信息流。

### 介绍段落

LexiPress 是一个本地 Python 驱动 + GitHub Actions 自动发布的英文外刊精读系统。它从 RSS / Atom 与 Hacker News 等高质量外刊源采集文章，经过 URL 归一化、双重去重、`trafilatura` 正文抽取与付费墙检测后，按「来源权重 × 时效性 × 篇幅适配度」综合打分，精选出最值得读的文章。

精读解析采用两阶段结构化 LLM 调用：先分批带显式 `index` 翻译逐段对照，杜绝中英错位；再全篇提炼导读、语境生词与长难句拆解，并用 Pydantic v2 强校验与重试保障质量。未配置 `LLM_API_KEY` 时自动降级为规则模式，站点照常发布。

前台以 *Editorial Luxury* 高端杂志美学呈现：三套护眼主题、玻璃拟态顶栏、Cmd+K 全局搜索、Hero 头版与印刷排版艺术封面兜底、沉浸式双栏精读、生词浮窗发音、词表联动、盲读保护罩与 LocalStorage 生词本（支持一键导出 Anki CSV / Markdown）。

职责边界清晰：采集、解析与本地可视化后台只在本地运行；GitHub Actions 仅负责将已就绪的博客源文件以 `--build-only` 渲染为静态站并部署到 GitHub Pages。

### 站点 About 页展示的提示词（可一键复制）

```
Build LexiPress: a Python + LLM English reading studio. Harvest RSS/HN → dedupe → trafilatura extract → score → two-stage LLM (indexed paragraph translation + vocab/sentence breakdown, Pydantic-validated, rule-only fallback) → editorial-luxury Jinja2 site with 3 themes, Cmd+K search, vocab popover & Anki export → GitHub Pages via Actions.
```

---

## 四、README 徽章（可选）

```markdown
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Site](https://img.shields.io/badge/site-GitHub%20Pages-9B2C2C?logo=github&logoColor=white)
![Pipeline](https://img.shields.io/badge/pipeline-deploy--site-success)
```
