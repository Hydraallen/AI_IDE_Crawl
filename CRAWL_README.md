# Browsertrix Crawl Configuration

## Quick Start

```bash
# Run full crawl
./crawl.sh

# Or with custom collection name
./crawl.sh my-custom-name
```

## Configuration Overview

### Seeds by Category

#### Native AI IDEs (19 seeds total)
| Tool | Standard | One Page | Total |
|------|----------|----------|-------|
| Cursor | 1 | 4 | 5 |
| Windsurf | 1 | 3 | 4 |
| Antigravity | 1 | 4 | 5 |
| Trae | 1 | 2 | 3 |
| OpenClaw | 1 | 1 | 2 |

#### AI Coding Tools (16 seeds total)
| Tool | Standard | One Page | Total |
|------|----------|----------|-------|
| GitHub Copilot | 1 | 4 | 5 |
| Bolt.new | 1 | 3 | 4 |
| Replit | 1 | 3 | 4 |
| Claude | 1 | 2 | 3 |

### Scope Types Used

| Scope Type | Description | Seeds |
|------------|-------------|-------|
| `domain` | Entire domain + subdomains | Cursor, Windsurf, Trae, OpenClaw, Bolt, Claude |
| `prefix` | URL prefix matching | GitHub Copilot, Replit |

### Exclusions Applied

Common exclusions for all seeds:
- `/dashboard*` - User dashboards
- `/settings*` - User settings
- `/login*` - Login pages
- `/signup*` - Signup pages
- `/account*` - Account pages

Tool-specific exclusions:
- **Cursor**: `/forum/*` (user-generated content)
- **GitHub**: `/marketplace/*`, `/login/*`
- **Replit**: `/~/*`, `/@/*` (user profiles)

## Output Files

```
crawls/
└── collections/
    └── [collection-name]/
        ├── [collection-name].wacz  # Main archive (load in ReplayWeb.page)
        ├── archive/
        │   └── *.warc.gz           # WARC files (import to Archive-It)
        ├── indexes/
        │   └── index.cdx.gz        # CDX index
        ├── pages/
        │   ├── pages.jsonl         # Seed pages
        │   └── extraPages.jsonl    # Discovered pages
        └── logs/
            └── *.log               # Crawl logs
```

## Manual Crawl Command

```bash
docker run -it \
  -v "$(pwd)/crawls:/crawls" \
  -v "$(pwd)/browsertrix-config.yaml:/config.yaml:ro" \
  webrecorder/browsertrix-crawler:latest \
  crawl \
  --config /config.yaml \
  --collection my-collection \
  --generateWACZ
```

## Integration with Archive-It

1. Run Browsertrix crawl → generates WARC files
2. In Archive-It, go to your collection
3. Upload WARC files from `crawls/collections/[name]/archive/`
4. WARC files integrate with existing AIT crawls

## Troubleshooting

### Crawl too slow?
Reduce `maxDepth` from 2 to 1 in the config.

### Missing pages?
Check the exclude patterns - they might be too aggressive.

### File too large?
Reduce `limit` from 500 to a lower number.

## Schedule Recommendations

Based on Collection Plan (daily crawls):

```bash
# Add to crontab (crontab -e)
0 2 * * * /path/to/AI_IDE_Crawl/crawl.sh daily-$(date +\%Y\%m\%d)
```

Or use launchd for macOS:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.auto.browsertrix-crawl</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/AI_IDE_Crawl/crawl.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>2</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
```
