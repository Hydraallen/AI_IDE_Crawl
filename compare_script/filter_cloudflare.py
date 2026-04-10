#!/usr/bin/env python3
"""
Filter out Cloudflare challenge pages and re-analyze changes.
"""

import json
from pathlib import Path
from collections import defaultdict

# Load the JSON summary
json_path = Path(__file__).parent / 'changes_summary.json'
with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Filter out Cloudflare challenge pages
cloudflare_indicators = [
    'just a moment',
    'cloudflare',
    'challenge-platform',
    'challenges.cloudflare.com',
    'turnstile'
]

def is_cloudflare_page(item):
    """Check if this is a Cloudflare challenge page."""
    title = item.get('title', '').lower()
    url = item.get('url', '').lower()
    
    for indicator in cloudflare_indicators:
        if indicator in title or indicator in url:
            return True
    return False

# Filter pages
all_pages = data.get('pages', [])
real_pages = [p for p in all_pages if not is_cloudflare_page(p)]
cloudflare_pages = [p for p in all_pages if is_cloudflare_page(p)]

print(f"Total page changes: {len(all_pages)}")
print(f"Cloudflare challenge pages: {len(cloudflare_pages)}")
print(f"Real content changes: {len(real_pages)}")
print()

# Categorize real pages by domain
by_domain = defaultdict(list)
for p in real_pages:
    url = p['url']
    if 'windsurf.com' in url or 'codeium.com' in url or 'docs.windsurf.com' in url:
        by_domain['windsurf'].append(p)
    elif 'openclaw.ai' in url or 'docs.openclaw.ai' in url:
        by_domain['openclaw'].append(p)
    elif 'cursor.com' in url or 'cursor.sh' in url:
        by_domain['cursor'].append(p)
    elif 'claude.com' in url or 'claude.ai' in url or 'anthropic.com' in url:
        by_domain['claude'].append(p)
    elif 'replit.com' in url:
        by_domain['replit'].append(p)
    elif 'bolt.new' in url or 'support.bolt.new' in url:
        by_domain['bolt'].append(p)
    elif 'github.com' in url:
        by_domain['github'].append(p)
    elif 'trae.ai' in url or 'traeapi.us' in url:
        by_domain['trae'].append(p)
    else:
        by_domain['other'].append(p)

# Generate filtered report
report = []
report.append("# Real Content Changes Report (Cloudflare Excluded)\n")
report.append(f"**Generated:** 2026-03-16\n")
report.append("")

# Summary
report.append("## Filter Statistics\n")
report.append(f"| Category | Count |")
report.append(f"|----------|-------|")
report.append(f"| Original page changes | {len(all_pages)} |")
report.append(f"| Cloudflare challenge pages | {len(cloudflare_pages)} |")
report.append(f"| **Real content changes** | **{len(real_pages)}** |")
report.append("")

report.append("## Distribution by Domain\n")
report.append(f"| Domain | Changes |")
report.append(f"|--------|---------|")
for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
    report.append(f"| {domain} | {len(items)} |")
report.append("")

# Show real changes by domain
for domain in ['openclaw', 'cursor', 'windsurf', 'claude', 'replit', 'bolt', 'github', 'trae', 'other']:
    items = by_domain.get(domain, [])
    if not items:
        continue
    
    report.append(f"## {domain.upper()} Changes ({len(items)})\n")
    
    # Sort by absolute size change
    items_sorted = sorted(items, key=lambda x: abs(x.get('size_diff', 0)), reverse=True)
    
    for p in items_sorted[:30]:
        size_diff = p.get('size_diff', 0)
        size_str = f"+{size_diff}" if size_diff > 0 else str(size_diff)
        title = p.get('title', '')[:60] or p['url'][:60]
        url_short = p['url'][:100]
        
        report.append(f"- **{title}**")
        report.append(f"  - `{url_short}`")
        report.append(f"  - Size: {size_str} bytes")
    
    if len(items) > 30:
        report.append(f"\n_...and {len(items) - 30} more changes_")
    report.append("")

# Write report
output_path = Path(__file__).parent / 'real_changes.md'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report))

print(f"\nReport saved to: {output_path}")
