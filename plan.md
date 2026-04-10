# Plan: LangChain Web Archive Analysis Agent

## Context

The automated web archiving pipeline uses Browsertrix to crawl 9 AI coding tool websites daily (Cursor, Windsurf, GitHub Copilot, Antigravity, Trae, OpenClaw, Bolt.new, Replit, Claude), storing results as WARC.gz files. There are currently 23 daily collections (2026-03-15 to 2026-04-07), totaling approximately 180GB. The existing `compare_script/` has complete WARC parsing and comparison code, but only outputs raw diffs without LLM analysis. We need to build a LangChain Agent that automatically compares daily crawl differences, uses an LLM (GLM-5.1) to analyze the reasons for changes, and generates detailed reports.

## Python Environment

**All Python-related operations must be executed within the virtual environment in the project root directory.**

```bash
# Create virtual environment in the project root
cd /path/to/project
python3 -m venv .venv
source .venv/bin/activate

# All subsequent python / pip commands should be run with .venv activated
pip install -r crawl_agent/requirements.txt
python crawl_agent/main.py batch
python crawl_agent/main.py agent
```

Do not use `compare_script/venv` (it does not have langchain installed), and do not create a separate venv. Use the project root `.venv` exclusively.

## Architecture

```
crawl_agent/
    __init__.py
    config.py          # Load env file, define path constants
    cache.py           # WARC parsed result JSON cache (avoids re-parsing 180GB)
    warc_loader.py     # Import functions from compare_script + cache layer
    llm_client.py      # ChatOpenAI (GLM-5.1 via OpenAI-compatible API)
    prompts.py         # Prompt templates
    tools.py           # LangChain @tool definitions (6 tools)
    batch.py           # CLI batch mode: iterate all date pairs
    agent.py           # Interactive mode: REPL Agent
    main.py            # Entry point: dispatch batch/agent
    requirements.txt

.venv/                 # Project root virtual environment
reports/               # Output reports directory
```

Output: `reports/YYYY-MM-DD_vs_YYYY-MM-DD.md`

## Key Design Decisions

1. **Reuse compare_script code**: Import functions like `parse_warc_collection()`, `compare_collections()`, and `analyze_text_changes()` from `crawl_compare.py` via `sys.path.insert` instead of rewriting them.
2. **JSON cache layer**: Each collection is parsed once (30-60s), then cached to `crawl_agent/.cache/parsed/{date}.json`. With caching, 23 collections are parsed ~23 times vs. 44 times without caching.
3. **Pre-process before sending to LLM**: The LLM never touches raw WARC data; it only receives comparison summaries (~2000-4000 tokens per date pair).
4. **Project root .venv**: Create `.venv` in the project root to avoid polluting `compare_script/venv`; all code uses a single unified environment.
5. **GLM-5.1 via ChatOpenAI**: Configure `langchain-openai`'s `ChatOpenAI` with `base_url` pointing to the Zhipu endpoint.

## Implementation Steps

### Step 1: Create virtual environment and crawl_agent package structure

- Create `.venv` in the project root: `python3 -m venv .venv`
- Create the `crawl_agent/` directory and `__init__.py`
- Write `requirements.txt`:
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

- Read `GLM_ENDPOINT`, `GLM_API_KEY`, `GLM_MODEL_NAME` from the `env` file in the project root
- Define path constants: `PROJECT_ROOT`, `COLLECTIONS_DIR`, `COMPARE_SCRIPT_DIR`, `REPORTS_DIR`, `CACHE_DIR`
- `get_available_dates()` scans `crawls/collections/` and returns a list of dates
- `get_consecutive_pairs()` generates consecutive date pairs (skipping non-consecutive dates like 0322->0324)

### Step 3: cache.py

- `get_parsed_collection(date_str, extract_text=True)` -- reads cache if available, otherwise parses WARC and stores the result in cache
- Cache location: `crawl_agent/.cache/parsed/{date}.json`
- Cache content: `{url: {hash, size, content_type, title, text_hash, text_len}}` + text cache
- Validation: SHA-256 checksum of WARC filename + size; re-parses if checksum does not match
- Actual parsing is delegated to `crawl_compare.parse_warc_collection()`

### Step 4: warc_loader.py

- `sys.path.insert(0, COMPARE_SCRIPT_DIR)` to import existing functions
- Wrapper functions:
  - `get_collection_data(date_str)` -> cached collection data
  - `compare_two_dates(old, new)` -> calls `compare_collections()` + `analyze_text_changes()`
  - `get_text_diff_for_url(url, old, new)` -> detailed diff for a single URL
  - `get_domains_for_date(date_str)` -> groups by domain
  - `get_page_content(url, date_str)` -> retrieves page text content

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

- `SYSTEM_PROMPT` -- Agent role: web archive analyst, focused on AI coding tools
- `ANALYSIS_PROMPT` -- used in batch mode; receives structured comparison data and instructs the LLM to output a markdown report
  - Includes: dates, statistics, domain categorization, URL/title/similarity/additions-deletions for each significant change
  - Guides classification: new feature / pricing change / design update / docs update / blog post / infrastructure
- `INTERACTIVE_SYSTEM_PROMPT` -- system message for interactive mode

### Step 7: tools.py -- 6 LangChain @tool definitions

| Tool | Parameters | Description |
|------|------------|-------------|
| `compare_dates` | old_date, new_date | Compares crawl data between two dates, returns a summary grouped by domain |
| `get_page_changes` | url, old_date, new_date | Gets detailed diff for a specific page between two dates |
| `get_domain_changes` | domain, old_date, new_date | Gets all changes for a specific domain between two dates |
| `list_available_dates` | (none) | Lists all available crawl dates |
| `analyze_trend` | domain, start_date, end_date | Analyzes change trends for a domain within a date range |
| `search_changes` | keyword, date? | Searches change content by keyword |

Each tool uses a Pydantic `BaseModel` to define its `args_schema`.

### Step 8: batch.py -- CLI batch mode

Process:
```
1. Get all consecutive date pairs
2. For each pair:
   a. Load cached data (warc_loader)
   b. Run comparison (compare_collections + analyze_text_changes)
   c. Build LLM prompt (truncated to top 30 most significant changes)
   d. Call LLM to get markdown report
   e. Write to reports/YYYY-MM-DD_vs_YYYY-MM-DD.md
   f. sleep(delay_seconds) to control rate limit
3. Print processing summary
```

Key parameters:
- `--start-date` / `--end-date` to limit the date range
- `--delay` interval between LLM calls (default 1s)
- `--force` overwrite existing reports
- `--skip-existing` skip existing reports (default)

LLM error handling: 3 retries with exponential backoff (2s, 4s, 8s); skip and continue on failure.

### Step 9: agent.py -- Interactive mode

- Create a LangChain ReAct Agent with `create_react_agent(llm, tools, prompt)`
- REPL loop: user inputs a question -> Agent selects a Tool to execute -> returns analysis results
- `max_iterations=10`, `handle_parsing_errors=True`

### Step 10: main.py -- CLI entry point

```bash
# After activating the virtual environment
python crawl_agent/main.py batch                              # All date pairs
python crawl_agent/main.py batch --start-date 2026-03-20       # Starting from a specific date
python crawl_agent/main.py agent                               # Interactive mode
```

## Report Output Format

```markdown
# Web Crawl Change Analysis: 2026-03-16 vs 2026-03-15

## Executive Summary
[LLM: 2-3 sentence summary of the most important changes for the day]

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
- **Why:** [LLM reasoning]

## Minor Changes
## Trend Analysis
```

## Verification

1. **Cache correctness**: Parse crawl-20260315, compare cached JSON statistics against `compare_script/reports_daily/0315_vs_0316/comparison_data.json`
2. **Single pair test**: `python crawl_agent/main.py batch --start-date 2026-03-15 --end-date 2026-03-16 --force`, verify the generated `reports/2026-03-16_vs_2026-03-15.md` contains all required sections
3. **Interactive test**: `python crawl_agent/main.py agent`, enter "what changed on Cursor between March 15 and March 16?", verify the Agent correctly calls `compare_dates` or `get_domain_changes` tool
4. **Rate limit test**: Process 3 consecutive date pairs, confirm no API rate limiting triggered

---

## Phase 2: Visualization Frontend

### Context

The Agent has generated 22 daily comparison reports (`reports/*.md`) + 168MB of screenshots (`reports/screenshots/`), but they can only be viewed by reading the raw files. A web frontend is needed to interactively display the evolution of 9 AI coding tool websites over 25 days.

### Python Environment

**All Python operations must use the project root `.venv`:**

```bash
.venv/bin/python   # Run scripts
.venv/bin/pip       # Install dependencies
```

### Tech Stack

- **Backend**: Flask (already installed in `.venv`)
- **Frontend**: Vanilla JS + Chart.js (CDN) + Tailwind CSS (CDN)
- **Data**: Pre-generated JSON at build time; Flask serves as a static file server

### Architecture

```
crawl_agent/
    web/                        # NEW: visualization module
        __init__.py
        app.py                  # Flask app + API routes
        data_builder.py         # Pre-build JSON data
        templates/
            index.html          # Single-page app (4 tabs)
        static/
            style.css           # Style overrides
            data/               # Pre-built JSON data
                overview.json
                timeline.json
                changes.json
```

### API Routes

| Route | Returns |
|-------|---------|
| `/` | Main page |
| `/api/dates` | Available dates + date pair list |
| `/api/overview` | Aggregated statistics |
| `/api/compare/<old>/<new>` | Comparison data for a single date pair |
| `/api/trend/<domain>` | Time series data for a single domain |
| `/api/report/<old>/<new>` | Parsed markdown report as HTML |
| `/api/screenshots/<path>` | Screenshot PNG files |

### Page Layout (4 Tabs)

**Tab 1: Overview Dashboard**
- Timeline line chart (Chart.js): X=date, Y=changes per domain (stacked area)
- Domain distribution pie chart: which domain had the most changes
- Key metric cards: total crawled URLs, total changes, daily average changes, most active domain
- Heatmap: domain x date matrix, color intensity indicates change magnitude

**Tab 2: Daily Comparison Browser**
- Date pair selector (dropdown / timeline slider)
- Statistics comparison: Added / Removed / Changed / Unchanged
- Change cards: domain tag + page title + URL + similarity color bar + expandable diff (additions in green, deletions in red)
- Before/after screenshot comparison (if available)

**Tab 3: Domain Deep Dive**
- Domain selector (buttons for 9 tools)
- Change timeline bar chart
- URL table for all changes under the selected domain

**Tab 4: Search**
- Keyword search across all changes
- Results list: date pair + URL + context snippet

### Implementation Steps

#### Step 1: `crawl_agent/web/data_builder.py`

- Scan markdown files in `reports/`
- Call `warc_loader.compare_two_dates()` to get data for all date pairs
- Aggregated output:
  - `overview.json`: statistical summary, domain totals, timeline data
  - `timeline.json`: daily change counts per domain
  - `changes.json`: all text_changes, indexed by date pair
- Write to `crawl_agent/web/static/data/`
- **Reuse**: `warc_loader.compare_two_dates()`, `config.get_consecutive_pairs()`, `config.get_available_dates()`

#### Step 2: `crawl_agent/web/app.py`

- Flask app + the routes listed above
- Screenshots served via `send_from_directory(REPORTS_DIR / "screenshots")`
- Markdown reports converted to HTML via the `markdown` library
- Pre-built JSON served from `static/data/`

#### Step 3: `crawl_agent/web/templates/index.html`

- Single-page application with 4 tabs (vanilla JS)
- Chart.js (CDN) for charts
- Tailwind CSS (CDN) for styling
- Diff rendering: inline colored spans
- Screenshot comparison: side-by-side display

#### Step 4: CLI integration

- Add `visualize` subcommand to `crawl_agent/main.py`
- `.venv/bin/python -m crawl_agent.main visualize` -> starts Flask
- `--build-data` flag: regenerate JSON data
- `--port` flag: specify port

### Dependencies

- `flask` -- already installed in `.venv`
- `markdown` -- `.venv/bin/pip install markdown`
- `chart.js` -- loaded via CDN, no install needed

### Files to Create

- `crawl_agent/web/__init__.py`
- `crawl_agent/web/app.py`
- `crawl_agent/web/data_builder.py`
- `crawl_agent/web/templates/index.html`
- `crawl_agent/web/static/style.css`

### Files to Modify

- `crawl_agent/main.py` -- add `visualize` subcommand

### Verification

1. `.venv/bin/pip install markdown`
2. `.venv/bin/python -m crawl_agent.main visualize --build-data` -- build JSON
3. Open `http://localhost:5000` -- see the Overview Dashboard + charts
4. Switch to Daily Comparison -- select a date pair, see change cards and screenshots
5. Switch to Domain Deep Dive -- select a domain, see timeline and all changes
6. Search "pricing" -- find Cursor pricing changes
