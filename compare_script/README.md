# Web Crawl Comparison Tool

Compare content changes between two web archive (WARC/WACZ) crawls.

## Quick Start

```bash
cd /Volumes/EDITH/Bots/F.R.I.D.A.Y./workspace/AI Coding Tools_Project/compare_script
source venv/bin/activate

python crawl_compare.py \
  --old ../crawls/collections/crawl-20260315 \
  --new ../crawls/collections/crawl-20260316 \
  --output ./reports
```

## Output Files

- `summary_report.md` - Summary of change statistics
- `detailed_changes.md` - Detailed text content changes
- `comparison_data.json` - JSON format data (for further analysis)

---

## Script Logic

### Overall Pipeline

```
┌─────────────────────┐
│ 1. Parse Old Collection │
│    (WARC → URL data)    │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 2. Parse New Collection │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 3. Compare              │
│    - URL list diff       │
│    - Content hash diff   │
│    - Text content diff   │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 4. Filter Noise         │
│    - Cloudflare pages    │
│    - Formatting changes  │
│    - Minor edits         │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ 5. Generate Reports     │
└─────────────────────┘
```

### Core Modules

#### 1. WARC Parsing (`parse_warc_collection`)

```
Input: collection/ folder path
     └── archive/
         ├── *.warc.gz
         └── ...

Processing:
1. Iterate over all .warc.gz files
2. Decompress and iterate each WARC record
3. Extract:
   - URL (WARC-Target-URI)
   - Content (HTTP response body)
   - Content-Type
   - Content hash (MD5)
4. If HTML:
   - Extract title
   - Extract readable text (strip scripts, styles, navigation, etc.)
   - Compute text hash

Output: {url: {hash, size, content_type, title, text, text_hash, ...}}
```

#### 2. Text Extraction (`extract_readable_text`)

```
Input: HTML content
Processing:
1. Parse HTML (BeautifulSoup)
2. Remove non-content elements:
   - script, style, noscript
   - iframe, svg, canvas
   - nav, header, footer, aside
   - Common UI class names (.nav, .menu, .sidebar...)
3. Extract main content area (main > article > body)
4. Clean text:
   - Remove overly short lines
   - Remove UI elements ("Skip to content", "Menu"...)
5. Normalize whitespace

Output: (title, clean_text)
```

#### 3. Content Comparison (`compare_collections`)

```
Input: data1 (old), data2 (new)

URL level:
- added = urls2 - urls1    (newly added pages)
- removed = urls1 - urls2  (removed pages)
- common = urls1 ∩ urls2   (pages present in both)

Content level:
for url in common:
    if hash1 != hash2:
        → Page content changed

Output: {added, removed, changed, stats}
```

#### 4. Text Change Analysis (`analyze_text_changes`)

```
Input: data1 (old), data2 (new)

for url in common:
    if text_hash matches:
        skip (no text change)

    if is Cloudflare verification page:
        skip (noise)

    Compute text similarity (difflib)

    if similarity > 98%:
        skip (formatting change only)

    if changed lines < 3:
        skip (minor edit)

    Record as genuine text change:
        - Similarity score
        - Added/removed content
        - Line count statistics

Output: {text_changes, stats}
```

### Filtering Strategy

| Filter Type | Detection Method | Reason |
|---------|---------|------|
| Cloudflare verification pages | Title/URL contains "just a moment", etc. | Not actual content |
| Formatting changes | Text similarity > 98% | Only HTML structure changes |
| Minor edits | Changed lines < 3 | Likely dates, counters, etc. |
| Non-HTML | Content-Type check | API responses, images, etc. |
| Short pages | Text length < 100 | Insignificant content |

### Domain Categorization

```python
DOMAIN_PATTERNS = {
    'windsurf': ['windsurf.com', 'docs.windsurf.com'],
    'openclaw': ['openclaw.ai', 'docs.openclaw.ai'],
    'cursor': ['cursor.com', 'cursor.sh'],
    'claude': ['claude.com', 'anthropic.com'],
    'replit': ['replit.com'],
    # ...
}
```

### Content Type Classification

```python
def get_content_type_category(content_type, url):
    if 'analytics' in url or 'tracking' in url:
        return 'tracking'
    elif '/auth' in url or '/login' in url:
        return 'auth'
    elif '.js' in url or '.css' in url:
        return 'static_asset'
    elif 'youtube.com' in url:
        return 'video_embed'
    elif '/api/' in url:
        return 'api'
    else:
        return 'page'
```

---

## Configuration Parameters

```python
# Minimum text length (pages shorter than this are ignored)
MIN_TEXT_LENGTH = 100

# Similarity threshold (above this value, changes are treated as formatting only)
SIMILARITY_THRESHOLD = 0.98

# Minimum changed lines (fewer than this is treated as a minor edit)
MIN_CHANGED_LINES = 3
```

---

## Data Flow Example

```
Collection 1 (crawl-20260315)
    │
    ▼ parse_warc_collection
{
  "https://docs.openclaw.ai/tools/firecrawl": {
    "hash": "abc123",
    "text": "Configure Firecrawl...",
    "text_hash": "def456"
  }
}

Collection 2 (crawl-20260316)
    │
    ▼ parse_warc_collection
{
  "https://docs.openclaw.ai/tools/firecrawl": {
    "hash": "xyz789",        ← hash changed
    "text": "Configure Firecrawl search...",
    "text_hash": "ghi012"    ← text_hash also changed
  }
}

    │
    ▼ analyze_text_changes
{
  "url": "https://docs.openclaw.ai/tools/firecrawl",
  "similarity": 0.68,        ← 68% similar, substantive change
  "added": ["Configure Firecrawl search", ...],
  "removed": ["Configure Firecrawl", ...]
}
```

---

## Extensions

### Adding a New Domain Category

Edit `DOMAIN_PATTERNS`:

```python
DOMAIN_PATTERNS['newsite'] = ['newsite.com', 'docs.newsite.com']
```

### Adjusting Filter Strictness

```python
# Stricter (only report major changes)
SIMILARITY_THRESHOLD = 0.90
MIN_CHANGED_LINES = 10

# More lenient (report more minor changes)
SIMILARITY_THRESHOLD = 0.99
MIN_CHANGED_LINES = 1
```
