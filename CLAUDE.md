# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated web archiving pipeline: **"The 2026 AI Coding Assistant Evolution"** — a web archiving collection that captures the rapid evolution of AI coding tools (Cursor, Windsurf, GitHub Copilot, Antigravity, Trae, OpenClaw, Bolt.new, Replit, Claude). The project uses Browsertrix Crawler for daily web archiving and Python scripts for comparing crawl snapshots over time.

## Commands

### Run a Web Crawl
```bash
# Default: creates collection named crawl-YYYYMMDD
./crawl.sh

# Custom collection name
./crawl.sh my-collection-name
```
Requires Docker (uses `webrecorder/browsertrix-crawler:latest`). Crawl config is `browsertrix-config-simple.yaml` (active); `browsertrix-config.yaml` is an older version.

### Compare Two Crawl Collections
```bash
cd compare_script
source venv/bin/activate
python crawl_compare.py \
  --old ../crawls/collections/crawl-20260315 \
  --new ../crawls/collections/crawl-20260316 \
  --output ./reports
```
Outputs: `summary_report.md`, `detailed_changes.md`, `comparison_data.json`

### Compile LaTeX Collection Plans
```bash
cd "Collection Plan" && pdflatex Collection_Plan.tex && bibtex Collection_Plan && pdflatex Collection_Plan.tex && pdflatex Collection_Plan.tex
cd "../Collection Plan Update" && pdflatex Collection_Update.tex && bibtex Collection_Update && pdflatex Collection_Update.tex && pdflatex Collection_Update.tex
```

## Architecture

```
├── crawl.sh                         # Entry point: runs Browsertrix via Docker
├── browsertrix-config-simple.yaml   # Active crawl config (9 seeds, depth 2)
├── crawls/collections/              # Daily WARC/WACZ archives (crawl-YYYYMMDD)
├── compare_script/                  # Python tools for diffing crawl snapshots
│   ├── crawl_compare.py             # Main comparison script (WARC → diff → reports)
│   ├── analyze_changes.py           # Change analysis
│   ├── categorize_changes.py        # Domain-based categorization
│   ├── text_changes.py              # Text-only diff (filters HTML structure noise)
│   ├── filter_cloudflare.py         # Removes Cloudflare challenge pages
│   ├── venv/                        # Python 3.14 venv (warcio, beautifulsoup4, frictionless)
│   └── reports*/                    # Generated comparison reports
├── Collection Plan/                 # LaTeX collection plan document
└── Collection Plan Update/          # LaTeX updated collection plan
```

### Crawl Pipeline
1. `crawl.sh` mounts `crawls/` and config into Docker container
2. Browsertrix crawls all 9 seeds (Native AI IDEs + AI Coding Tools) with domain/prefix scope
3. Output: WACZ file (viewable via replayweb.page) + WARC files (import to Archive-It)

### Comparison Pipeline
1. `crawl_compare.py` parses WARC.gz files from two collection directories
2. Extracts URLs, content hashes, and readable text (BeautifulSoup strips scripts/nav/etc.)
3. Compares: added URLs, removed URLs, changed content (via hash diff)
4. Filters noise: Cloudflare challenges (>98% similarity = formatting only, <3 changed lines = minor)
5. Categorizes by domain (DOMAIN_PATTERNS maps URLs to tool names)

### Scheduled Crawls
A launchd plist (`com.auto.browsertrix-crawl.plist`) runs daily at 2:00 AM. Logs go to `crawls/crawl.log` and `crawls/crawl-error.log`.

## Key Configuration

### Crawl Exclusion Rules (browsertrix-config-simple.yaml)
- Common: dashboard, login, signup, settings, API endpoints
- Cursor: also excludes forum, trust, status, careers, pagination
- Trae: also excludes blog, docs, download, legal pages, campaign pages
- Claude: also excludes non-English locales (/de-de/, /fr-fr/, etc.), pagination, plugins

### Compare Script Thresholds
- `MIN_TEXT_LENGTH = 100` — pages shorter than this are ignored
- `SIMILARITY_THRESHOLD = 0.98` — changes above 98% similarity treated as formatting noise
- `MIN_CHANGED_LINES = 3` — fewer changed lines treated as minor
