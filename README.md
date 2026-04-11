# The 2026 AI Coding Assistant Evolution

> Automated Web Archiving Pipeline — Tracking the rapid evolution of AI coding tools through daily web archiving and automated change analysis.

## Project Overview

This project captures and analyzes daily changes across **9 AI coding tool websites**:

| Category | Tools |
|----------|-------|
| Native AI IDEs | **Cursor**, **Windsurf**, **Antigravity**, **Trae** |
| AI Coding Assistants | **GitHub Copilot**, **Claude** |
| Cloud AI Coding Platforms | **Bolt.new**, **Replit**, **OpenClaw** |

The system performs daily automated web crawls, compares consecutive snapshots, and uses LLM analysis to identify and classify significant changes (new features, pricing updates, redesigns, documentation changes, blog posts, infrastructure modifications).

**Collection period**: 2026-03-15 to present (daily at 2:00 AM via launchd)

## Architecture

```
AI Coding Tools_Project/
├── crawl.sh                         # Web crawl entry point (Docker + Browsertrix)
├── browsertrix-config-simple.yaml   # Active crawl config (9 seeds, depth 2)
├── com.auto.browsertrix-crawl.plist # macOS launchd daily schedule
│
├── crawl_agent/                     # LLM-powered analysis agent
│   ├── main.py                      # CLI entry: batch / agent / visualize
│   ├── batch.py                     # Batch analysis for all date pairs
│   ├── agent.py                     # Interactive LangChain ReAct agent
│   ├── tools.py                     # 6 LangChain tools (compare, search, trend...)
│   ├── prompts.py                   # LLM prompt templates
│   ├── llm_client.py                # ChatOpenAI wrapper (GLM-5.1)
│   ├── config.py                    # Paths, env, date utilities
│   ├── cache.py                     # WARC parse cache (JSON + SHA-256)
│   ├── warc_loader.py               # WARC data loading layer
│   ├── warc_viewer.py               # Local HTTP server for WARC replay
│   ├── screenshot.py                # Before/after page screenshots
│   ├── requirements.txt
│   └── web/                         # Visualization frontend
│       ├── app.py                   # Flask server + API routes
│       ├── data_builder.py          # Pre-build JSON from crawl data
│       ├── templates/index.html     # Single-page app (4 tabs)
│       └── static/css/style.css
│
├── compare_script/                  # WARC comparison tools
│   ├── crawl_compare.py             # Core: WARC parse + compare + report
│   ├── analyze_changes.py           # Deep content analysis (metadata + diff)
│   ├── categorize_changes.py        # URL type classification by domain
│   ├── text_changes.py              # Text-only comparison (filters HTML noise)
│   └── filter_cloudflare.py         # Remove Cloudflare challenge pages
│
├── visualize.py                     # One-command visualization launcher
├── plan.md                          # Implementation plan & changelog
├── Collection Plan/                 # LaTeX collection plan document
├── Collection Plan Update/          # LaTeX updated collection plan
├── Final Report/                    # LaTeX final project report
└── Project Presentation/            # Slides (HTML, PDF, PPTX)
```

## Quick Start

### Prerequisites

- **Docker** (for Browsertrix Crawler)
- **Python 3.13+** (venv at `.venv/`)
- **GLM-5.1 API key** in `env` file (for LLM analysis)

### 1. Run a Web Crawl

```bash
# Default: creates collection named crawl-YYYYMMDD
./crawl.sh

# Custom collection name
./crawl.sh my-collection-name
```

Uses `webrecorder/browsertrix-crawler:latest` Docker image. Crawls 9 seed URLs with domain/prefix scope rules and exclusion filters (dashboard, login, signup, settings, API endpoints, etc.).

### 2. Compare Two Collections

```bash
cd compare_script
source venv/bin/activate
python crawl_compare.py \
  --old ../crawls/collections/crawl-20260315 \
  --new ../crawls/collections/crawl-20260316 \
  --output ./reports
```

Outputs:
- `summary_report.md` — high-level stats
- `detailed_changes.md` — per-URL diffs
- `comparison_data.json` — machine-readable data

### 3. Run LLM Batch Analysis

```bash
# Analyze all consecutive date pairs
.venv/bin/python crawl_agent/main.py batch

# Analyze a specific date range
.venv/bin/python crawl_agent/main.py batch --start-date 20260320 --end-date 20260325

# Force overwrite existing reports
.venv/bin/python crawl_agent/main.py batch --force
```

Generates markdown reports in `reports/` with:
- Executive Summary (LLM-generated)
- Statistics (added/removed/changed URLs)
- Domain Breakdown
- Significant Changes (classified: feature/pricing/design/docs/blog/infra)
- Before/after screenshots

### 4. Interactive Agent Mode

```bash
.venv/bin/python crawl_agent/main.py agent
```

Starts a REPL agent with 6 tools:

| Tool | Description |
|------|-------------|
| `compare_dates(old, new)` | Compare two crawl dates |
| `get_page_changes(url, old, new)` | Detailed diff for a specific page |
| `get_domain_changes(domain, old, new)` | All changes for a domain |
| `list_available_dates()` | Show all crawl dates |
| `analyze_trend(domain, start, end)` | Change trends over time |
| `search_changes(keyword, date?)` | Keyword search across changes |

### 5. Visualization Frontend

```bash
# Build data + launch (first time or after new crawls)
.venv/bin/python visualize.py --build-data

# Just launch (data already built)
.venv/bin/python visualize.py

# Custom port / no browser
.venv/bin/python visualize.py --port 8080 --no-browser
```

Opens a web dashboard at `http://localhost:5000` with 4 tabs:

#### Tab 1: Overview Dashboard
- **Timeline chart**: Stacked area chart showing changes per domain over time
- **Domain pie chart**: Which tools changed the most across the full period
- **Metric cards**: Total days, total changes, avg/day, most active domain
- **Heatmap**: Domain × Date matrix with color-coded change intensity (clickable)

#### Tab 2: Daily Comparison
- **Date pair selector**: Dropdown with all 22+ consecutive date pairs
- **Stats cards**: Added / Removed / Changed / Unchanged counts
- **Change cards**: Each change shows domain badge, similarity score, expandable diff (green additions, red deletions), before/after screenshots
- **Full report**: Toggle to view the complete LLM-generated markdown analysis

#### Tab 3: Domain Deep Dive
- **9 domain pills**: Click any tool to see its dedicated analysis
- **Trend bar chart**: Daily change counts for the selected domain
- **Stats**: Total changes, unique pages, average similarity
- **Full change table**: All URLs that changed, sorted by similarity (most significant first)

#### Tab 4: Search
- **Keyword search**: Search across all changes (e.g., "pricing", "cursor", "feature")
- Shows matching changes with domain, date, similarity score

## Pipeline Details

### Crawl Pipeline

```
crawl.sh → Docker (Browsertrix Crawler)
         → crawls/collections/crawl-YYYYMMDD/
             ├── archive/    # WARC.gz files
             ├── pages/      # page lists
             └── *.wacz      # bundled archive
```

- Seeds: 9 URLs (one per tool)
- Scope: domain + prefix rules
- Depth: 2 hops from seed
- Exclusions: login, signup, dashboard, API endpoints, non-English locales, etc.
- Schedule: daily at 2:00 AM via `launchctl`

### Comparison Pipeline

```
WARC.gz files → parse_warc_collection() → {url: {hash, size, text, title}}
             → compare_collections()     → {added, removed, changed, unchanged}
             → analyze_text_changes()    → {url, similarity, added[], removed[]}
             → filter noise              → remove Cloudflare, formatting-only, minor
             → categorize by domain      → Cursor / Replit / Claude / ...
```

Thresholds:
- `MIN_TEXT_LENGTH = 100` — ignore pages shorter than this
- `SIMILARITY_THRESHOLD = 0.98` — above this = formatting noise
- `MIN_CHANGED_LINES = 3` — fewer lines = minor change

### Analysis Pipeline

```
compare_two_dates() → raw comparison data
                   → format as prompt (stats, domain breakdown, changes)
                   → LLM (GLM-5.1) → markdown report
                   → screenshot capture (Playwright)
                   → reports/YYYY-MM-DD_vs_YYYY-MM-DD.md
```

### Visualization Pipeline

```
build_all_data() → for each date pair: compare_two_dates()
                → aggregate: overview.json, timeline.json, changes.json
                → scan screenshots/ → screenshots.json
                → crawl_agent/web/static/data/

Flask server → serves index.html + API routes
            → on-demand markdown → HTML conversion
            → screenshot file serving
```

## Key Configuration

### Environment (`env` file)

```
GLM_ENDPOINT=https://open.bigmodel.cn/api/coding/paas/v4
GLM_API_KEY=your-key-here
GLM_MODEL_NAME=glm-5.1
```

### Crawl Exclusion Rules (`browsertrix-config-simple.yaml`)

Common exclusions across all seeds:
- Dashboard, login, signup, settings, API endpoints
- Cursor-specific: forum, trust, status, careers, pagination
- Trae-specific: blog, docs, download, legal, campaign pages
- Claude-specific: non-English locales (/de-de/, /fr-fr/, etc.), pagination, plugins

## Data Summary

As of 2026-04-08:
- **24 crawl dates** (2026-03-15 to 2026-04-08)
- **22 consecutive date pairs** compared
- **1,208 total text changes** detected
- **168 MB** of before/after screenshots

Top changed domains:
| Domain | Changes | Share |
|--------|---------|-------|
| Replit | 376 | 31.1% |
| OpenClaw | 296 | 24.5% |
| Claude | 197 | 16.3% |
| Windsurf | 181 | 15.0% |
| Cursor | 73 | 6.0% |
| Bolt.new | 65 | 5.4% |
| Trae | 9 | 0.7% |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Web Crawler | Browsertrix Crawler (Docker) |
| Archive Format | WARC.gz / WACZ |
| Data Parsing | warcio, BeautifulSoup4, lxml |
| LLM Agent | LangChain + ChatOpenAI (GLM-5.1) |
| Visualization | Flask + Chart.js + Tailwind CSS |
| Screenshots | Playwright (headless Chromium) |
| Scheduling | macOS launchd |
| Report Format | Markdown, LaTeX, PDF |

## Setup from Scratch

```bash
# 1. Clone the repository
git clone <repo-url>
cd AI Coding Tools_Project

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r crawl_agent/requirements.txt
pip install flask markdown

# 4. Configure API key
echo 'GLM_ENDPOINT=https://open.bigmodel.cn/api/coding/paas/v4' > env
echo 'GLM_API_KEY=your-key-here' >> env
echo 'GLM_MODEL_NAME=glm-5.1' >> env

# 5. Run a crawl (requires Docker)
./crawl.sh

# 6. Run batch analysis
python crawl_agent/main.py batch

# 7. Launch visualization
python visualize.py --build-data
```
