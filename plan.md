# Plan: LangChain Web Archive Analysis Agent

## Context

AI Coding Tools 项目每天用 Browsertrix 爬取 9 个 AI 编码工具网站（Cursor, Windsurf, GitHub Copilot, Antigravity, Trae, OpenClaw, Bolt.new, Replit, Claude），存为 WARC.gz 文件。目前有 23 个 daily collections（2026-03-15 到 2026-04-07），共约 180GB。现有的 `compare_script/` 有完整的 WARC 解析和比较代码，但只输出原始 diff，没有 LLM 分析。需要构建一个 LangChain Agent，自动对比每天的爬取差异，用 LLM（GLM-5.1）分析变化原因并生成详细报告。

## Python 环境

**所有 Python 相关操作必须在项目根目录下的虚拟环境中执行。**

```bash
# 在项目根目录创建虚拟环境
cd /Volumes/EDITH/Bots/F.R.I.D.A.Y./workspace/AI Coding Tools_Project
python3 -m venv .venv
source .venv/bin/activate

# 后续所有 python / pip 命令都在 .venv 激活状态下运行
pip install -r crawl_agent/requirements.txt
python crawl_agent/main.py batch
python crawl_agent/main.py agent
```

不使用 `compare_script/venv`（那里没有 langchain），也不创建新的独立 venv，统一用项目根目录 `.venv`。

## Architecture

```
crawl_agent/
    __init__.py
    config.py          # 加载 env 文件，定义路径常量
    cache.py           # WARC 解析结果 JSON 缓存（避免重复解析 180GB）
    warc_loader.py     # 从 compare_script 导入函数 + 缓存层
    llm_client.py      # ChatOpenAI (GLM-5.1 via OpenAI-compatible API)
    prompts.py         # Prompt 模板
    tools.py           # LangChain @tool 定义（6 个工具）
    batch.py           # CLI 批量模式：遍历所有日期对
    agent.py           # 交互模式：REPL Agent
    main.py            # 入口：dispatch batch/agent
    requirements.txt

.venv/                 # 项目根目录虚拟环境
reports/               # 输出报告目录
```

输出：`reports/YYYY-MM-DD_vs_YYYY-MM-DD.md`

## Key Design Decisions

1. **复用 compare_script 代码**：通过 `sys.path.insert` 导入 `crawl_compare.py` 的 `parse_warc_collection()`, `compare_collections()`, `analyze_text_changes()` 等函数，不重写。
2. **JSON 缓存层**：每个 collection 解析一次（30-60s），缓存到 `crawl_agent/.cache/parsed/{date}.json`。23 个 collection 解析约 23 次 vs 无缓存 44 次。
3. **预处理后送 LLM**：LLM 不接触原始 WARC 数据，只接收比较摘要（~2000-4000 tokens/日期对）。
4. **项目根目录 .venv**：在项目根创建 `.venv`，不污染 `compare_script/venv`，所有代码统一使用一个环境。
5. **GLM-5.1 via ChatOpenAI**：`langchain-openai` 的 `ChatOpenAI` 配置 `base_url` 指向智谱 endpoint。

## Implementation Steps

### Step 1: 创建虚拟环境和 crawl_agent 包结构

- 在项目根目录创建 `.venv`：`python3 -m venv .venv`
- 创建 `crawl_agent/` 目录和 `__init__.py`
- 写 `requirements.txt`:
  ```
  langchain>=0.3.0
  langchain-openai>=0.3.0
  langchain-core>=0.3.0
  pydantic>=2.0
  warcio>=1.7
  beautifulsoup4>=4.12
  lxml>=5.0
  ```
- `source .venv/bin/activate && pip install -r crawl_agent/requirements.txt`

### Step 2: config.py

- 从项目根目录 `env` 文件读取 `GLM_ENDPOINT`, `GLM_API_KEY`, `GLM_MODEL_NAME`
- 定义路径常量：`PROJECT_ROOT`, `COLLECTIONS_DIR`, `COMPARE_SCRIPT_DIR`, `REPORTS_DIR`, `CACHE_DIR`
- `get_available_dates()` 扫描 `crawls/collections/` 返回日期列表
- `get_consecutive_pairs()` 生成相邻日期对（跳过不连续日期如 0322→0324）

### Step 3: cache.py

- `get_parsed_collection(date_str, extract_text=True)` — 有缓存则读缓存，否则解析 WARC 并存缓存
- 缓存位置：`crawl_agent/.cache/parsed/{date}.json`
- 缓存内容：`{url: {hash, size, content_type, title, text_hash, text_len}}` + 文本缓存
- 校验机制：WARC 文件名+大小 SHA-256 校验和，不匹配则重新解析
- 实际解析委托给 `crawl_compare.parse_warc_collection()`

### Step 4: warc_loader.py

- `sys.path.insert(0, COMPARE_SCRIPT_DIR)` 导入现有函数
- 封装函数：
  - `get_collection_data(date_str)` → 带缓存的 collection 数据
  - `compare_two_dates(old, new)` → 调用 `compare_collections()` + `analyze_text_changes()`
  - `get_text_diff_for_url(url, old, new)` → 单 URL 详细 diff
  - `get_domains_for_date(date_str)` → 按域名分组
  - `get_page_content(url, date_str)` → 获取页面文本内容

### Step 5: llm_client.py

```python
from langchain_openai import ChatOpenAI

def get_llm(temperature=0.1) -> ChatOpenAI:
    return ChatOpenAI(
        model="glm-5.1",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        api_key=os.environ["GLM_API_KEY"],
        temperature=temperature,
        max_tokens=4096,
        request_timeout=60,
    )
```

### Step 6: prompts.py

- `SYSTEM_PROMPT` — Agent 角色：web archive analyst，专注 AI coding tools
- `ANALYSIS_PROMPT` — 批量模式用，接收结构化比较数据，要求 LLM 输出 markdown 报告
  - 包含：日期、统计、域名分类、每个显著变化的 URL/标题/相似度/增删内容
  - 指导分类：new feature / pricing change / design update / docs update / blog post / infrastructure
- `INTERACTIVE_SYSTEM_PROMPT` — 交互模式 system message

### Step 7: tools.py — 6 个 LangChain @tool

| Tool | 参数 | 功能 |
|------|------|------|
| `compare_dates` | old_date, new_date | 对比两天的 crawl 数据，返回按域名分组的摘要 |
| `get_page_changes` | url, old_date, new_date | 获取特定页面在两天的详细 diff |
| `get_domain_changes` | domain, old_date, new_date | 获取特定域名在两天的所有变化 |
| `list_available_dates` | (无) | 列出所有可用 crawl 日期 |
| `analyze_trend` | domain, start_date, end_date | 分析域名在时间范围内的变化趋势 |
| `search_changes` | keyword, date? | 按关键词搜索变化内容 |

每个 Tool 用 Pydantic `BaseModel` 定义 `args_schema`。

### Step 8: batch.py — CLI 批量模式

流程：
```
1. 获取所有连续日期对
2. 对每一对：
   a. 加载缓存数据（warc_loader）
   b. 运行比较（compare_collections + analyze_text_changes）
   c. 构造 LLM prompt（截断到前 30 个最显著变化）
   d. 调用 LLM 获取 markdown 报告
   e. 写入 reports/YYYY-MM-DD_vs_YYYY-MM-DD.md
   f. sleep(delay_seconds) 控制 rate limit
3. 打印处理摘要
```

关键参数：
- `--start-date` / `--end-date` 限制范围
- `--delay` LLM 调用间隔（默认 1s）
- `--force` 覆盖已有报告
- `--skip-existing` 跳过已有报告（默认）

LLM 错误处理：3 次重试，指数退避（2s, 4s, 8s），失败则跳过继续。

### Step 9: agent.py — 交互模式

- 用 `create_react_agent(llm, tools, prompt)` 创建 LangChain ReAct Agent
- REPL 循环，用户输入问题 → Agent 选择 Tool 执行 → 返回分析结果
- `max_iterations=10`, `handle_parsing_errors=True`

### Step 10: main.py — CLI 入口

```bash
# 激活虚拟环境后
python crawl_agent/main.py batch                              # 全部日期对
python crawl_agent/main.py batch --start-date 2026-03-20       # 从某日开始
python crawl_agent/main.py agent                               # 交互模式
```

## Report Output Format

```markdown
# Web Crawl Change Analysis: 2026-03-16 vs 2026-03-15

## Executive Summary
[LLM 2-3 句话总结当天最重要的变化]

## Statistics
| Metric | Count |
|--------|-------|
| Previous crawl URLs | ... |
| Current crawl URLs | ... |
| Added / Removed / Changed | ... |

## Domain Breakdown
| Domain | Changes | Highlights |
|--------|---------|-----------|

## Significant Changes
### [Domain] - [Page Title]
- **URL:** ...
- **Change type:** [feature/pricing/design/docs/blog/infra]
- **What changed:** ...
- **Why:** [LLM 推理]

## Minor Changes
## Trend Analysis
```

## Verification

1. **缓存正确性**：解析 crawl-20260315，对比缓存 JSON 与 `compare_script/reports_daily/0315_vs_0316/comparison_data.json` 的统计数据
2. **单对测试**：`python crawl_agent/main.py batch --start-date 2026-03-15 --end-date 2026-03-16 --force`，检查生成的 `reports/2026-03-16_vs_2026-03-15.md` 包含所有必需 section
3. **交互测试**：`python crawl_agent/main.py agent`，输入 "what changed on Cursor between March 15 and March 16?"，验证 Agent 正确调用 `compare_dates` 或 `get_domain_changes` tool
4. **Rate limit 测试**：连续处理 3 个日期对，确认不触发 API 限流

---

## Phase 2: Visualization Frontend

### Context

Agent 已生成 22 份每日比较报告（`reports/*.md`）+ 168MB 截图（`reports/screenshots/`），但只能通过读原始文件查看。需要一个 Web 前端，以交互方式展示 25 天内 9 个 AI 编码工具网站的变化演变，适用于 AI Coding Tools 课程项目展示。

### Python 环境

**所有 Python 操作必须使用项目根目录 `.venv`：**

```bash
/Volumes/EDITH/AI Coding Tools_Project/.venv/bin/python   # 运行脚本
/Volumes/EDITH/AI Coding Tools_Project/.venv/bin/pip       # 安装依赖
```

### Tech Stack

- **Backend**: Flask（已在 `.venv` 中安装）
- **Frontend**: Vanilla JS + Chart.js (CDN) + Tailwind CSS (CDN)
- **Data**: 构建时预生成 JSON，Flask 作为静态文件服务

### Architecture

```
crawl_agent/
    web/                        # NEW: 可视化模块
        __init__.py
        app.py                  # Flask app + API routes
        data_builder.py         # 预构建 JSON 数据
        templates/
            index.html          # 单页应用（4 个 tab）
        static/
            style.css           # 样式覆盖
            data/               # 预构建 JSON 数据
                overview.json
                timeline.json
                changes.json
```

### API Routes

| Route | Returns |
|-------|---------|
| `/` | 主页面 |
| `/api/dates` | 可用日期 + 日期对列表 |
| `/api/overview` | 聚合统计数据 |
| `/api/compare/<old>/<new>` | 单个日期对的比较数据 |
| `/api/trend/<domain>` | 单个域名的时间序列数据 |
| `/api/report/<old>/<new>` | 解析后的 markdown 报告 HTML |
| `/api/screenshots/<path>` | 截图 PNG 文件 |

### Page Layout (4 个 Tab)

**Tab 1: Overview Dashboard**
- 时间线折线图（Chart.js）：X=日期, Y=每域名变化数（stacked area）
- 域名分布饼图：哪个域名变化最多
- 关键指标卡片：总爬取 URL 数、总变化数、日均变化、最活跃域名
- 热力图：域名 × 日期矩阵，颜色深浅表示变化强度

**Tab 2: Daily Comparison Browser**
- 日期对选择器（下拉 / 时间线滑块）
- 统计对比：Added / Removed / Changed / Unchanged
- 变化卡片：域名标签 + 页面标题 + URL + 相似度色条 + 可展开 diff（增绿删红）
- 前后截图对比（如有）

**Tab 3: Domain Deep Dive**
- 域名选择器（9 个工具的按钮）
- 变化时间线柱状图
- 该域名下所有变化的 URL 表格

**Tab 4: Search**
- 关键词搜索，跨所有变化
- 结果列表：日期对 + URL + 上下文片段

### Implementation Steps

#### Step 1: `crawl_agent/web/data_builder.py`

- 扫描 `reports/` 中的 markdown 文件
- 调用 `warc_loader.compare_two_dates()` 获取所有日期对数据
- 聚合输出：
  - `overview.json`：统计摘要、域名总量、时间线数据
  - `timeline.json`：每域名每日变化数
  - `changes.json`：所有 text_changes，按日期对索引
- 写入 `crawl_agent/web/static/data/`
- **复用**：`warc_loader.compare_two_dates()`, `config.get_consecutive_pairs()`, `config.get_available_dates()`

#### Step 2: `crawl_agent/web/app.py`

- Flask app + 上述路由
- 截图通过 `send_from_directory(REPORTS_DIR / "screenshots")` 提供
- Markdown 报告通过 `markdown` 库转 HTML
- 预构建 JSON 从 `static/data/` 提供

#### Step 3: `crawl_agent/web/templates/index.html`

- 单页应用，4 个 tab（vanilla JS）
- Chart.js (CDN) 画图
- Tailwind CSS (CDN) 样式
- Diff 渲染：内联彩色 span
- 截图对比：并排展示

#### Step 4: CLI 集成

- 在 `crawl_agent/main.py` 添加 `visualize` 子命令
- `.venv/bin/python -m crawl_agent.main visualize` → 启动 Flask
- `--build-data` 标志：重新生成 JSON 数据
- `--port` 标志：指定端口

### Dependencies

- `flask` — 已在 `.venv` 中安装
- `markdown` — `.venv/bin/pip install markdown`
- `chart.js` — CDN 引入，无需安装

### Files to Create

- `crawl_agent/web/__init__.py`
- `crawl_agent/web/app.py`
- `crawl_agent/web/data_builder.py`
- `crawl_agent/web/templates/index.html`
- `crawl_agent/web/static/style.css`

### Files to Modify

- `crawl_agent/main.py` — 添加 `visualize` 子命令

### Verification

1. `.venv/bin/pip install markdown`
2. `.venv/bin/python -m crawl_agent.main visualize --build-data` — 构建 JSON
3. 打开 `http://localhost:5000` — 看到 Overview Dashboard + 图表
4. 切换到 Daily Comparison — 选择日期对，看到变化卡片和截图
5. 切换到 Domain Deep Dive — 选择域名，看到时间线和所有变化
6. 搜索 "pricing" — 找到 Cursor 定价变化
