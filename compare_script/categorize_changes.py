#!/usr/bin/env python3
"""
Categorize and list all changed URLs by type.
"""

import os
import sys
import gzip
import hashlib
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import json

from warcio import ArchiveIterator
from bs4 import BeautifulSoup


def get_url_from_warc_record(record):
    if record.rec_type == 'response':
        return record.rec_headers.get_header('WARC-Target-URI')
    return None


def get_content_hash(content):
    if isinstance(content, str):
        content = content.encode('utf-8', errors='ignore')
    return hashlib.md5(content).hexdigest()


def extract_title(content, content_type=''):
    if not content:
        return ''
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
    except:
        return ''
    
    if 'text/html' in content_type or not content_type:
        try:
            soup = BeautifulSoup(content, 'lxml')
            if soup.title and soup.title.string:
                return soup.title.string.strip()[:100]
        except:
            pass
    return ''


def parse_warc_files(collection_path):
    archive_path = Path(collection_path) / 'archive'
    if not archive_path.exists():
        return {}
    
    url_data = {}
    warc_files = list(archive_path.glob('*.warc.gz'))
    
    for warc_file in warc_files:
        try:
            with gzip.open(warc_file, 'rb') as stream:
                for record in ArchiveIterator(stream):
                    try:
                        url = get_url_from_warc_record(record)
                        if not url:
                            continue
                        content = record.content_stream().read()
                        content_type = record.http_headers.get_header('Content-Type', '') if record.http_headers else ''
                        
                        url_data[url] = {
                            'hash': get_content_hash(content),
                            'size': len(content),
                            'content_type': content_type,
                            'title': extract_title(content, content_type)
                        }
                    except:
                        continue
        except Exception as e:
            pass
    
    return url_data


def categorize_url(url):
    """Categorize URL by type."""
    url_lower = url.lower()
    
    # Order matters - more specific first
    if any(x in url_lower for x in ['analytics', 'tracking', 'pixel', '/gtm.', '/gtag', 'ads.', 'adsct', 'doubleclick']):
        return 'tracking'
    elif any(x in url_lower for x in ['/auth', '/login', '/signin', '/oauth', '/account', 'authenticate', 'user_management/authorize']):
        return 'auth'
    elif any(x in url_lower for x in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.avif']):
        return 'image'
    elif any(x in url_lower for x in ['.js', '.css', '.woff', '.ttf', '.woff2', '/assets/', '/static/', 'chunks/']):
        return 'static_asset'
    elif any(x in url_lower for x in ['youtube.com', 'youtu.be', 'vimeo.com', 'youtube-nocookie.com']):
        return 'video_embed'
    elif any(x in url_lower for x in ['/api/', 'api.', '.json', 'json?']):
        return 'api'
    elif any(x in url_lower for x in ['challenge', 'captcha', 'turnstile']):
        return 'challenge'
    else:
        return 'page'


def get_domain_category(url):
    """Categorize by domain."""
    domains = {
        'replit': ['replit.com', 'repl.it'],
        'cursor': ['cursor.com', 'cursor.sh'],
        'claude': ['claude.com', 'claude.ai', 'anthropic.com'],
        'windsurf': ['windsurf.com', 'codeium.com'],
        'openclaw': ['openclaw.ai', 'docs.openclaw.ai'],
        'bolt': ['bolt.new'],
        'trae': ['trae.ai', 'traeapi.us'],
        'github': ['github.com'],
        'cloudflare': ['cloudflare.com', 'challenges.cloudflare.com'],
        'google': ['google.com', 'googletagmanager.com', 'google-analytics.com'],
        'youtube': ['youtube.com', 'youtube-nocookie.com', 'youtu.be'],
        'apple': ['apple.com', 'apple-mapkit.com'],
        'launchdarkly': ['launchdarkly.com'],
        'intercom': ['intercom.io', 'intercom.com'],
        'other': []
    }
    
    url_lower = url.lower()
    for category, domain_list in domains.items():
        for domain in domain_list:
            if domain in url_lower:
                return category
    return 'other'


def main():
    coll1 = '../crawls/collections/crawl-20260315'
    coll2 = '../crawls/collections/crawl-20260316'
    
    print("Loading collection 1...")
    data1 = parse_warc_files(coll1)
    print(f"  Loaded {len(data1)} URLs")
    
    print("Loading collection 2...")
    data2 = parse_warc_files(coll2)
    print(f"  Loaded {len(data2)} URLs")
    
    urls1 = set(data1.keys())
    urls2 = set(data2.keys())
    
    added = urls2 - urls1
    removed = urls1 - urls2
    common = urls1 & urls2
    
    # Changed URLs
    changed = []
    for url in common:
        if data1[url]['hash'] != data2[url]['hash']:
            changed.append({
                'url': url,
                'size_diff': data2[url]['size'] - data1[url]['size'],
                'title': data2[url]['title'] or data1[url]['title']
            })
    
    # Sort by size change
    changed.sort(key=lambda x: abs(x['size_diff']), reverse=True)
    
    # Categorize changes
    by_type = defaultdict(list)
    by_domain = defaultdict(list)
    
    for item in changed:
        url = item['url']
        cat = categorize_url(url)
        domain_cat = get_domain_category(url)
        
        by_type[cat].append(item)
        by_domain[domain_cat].append(item)
    
    # Categorize new/removed
    new_by_type = defaultdict(list)
    removed_by_type = defaultdict(list)
    
    for url in added:
        new_by_type[categorize_url(url)].append(url)
    
    for url in removed:
        removed_by_type[categorize_url(url)].append(url)
    
    # Generate report
    report = []
    report.append("# Categorized Changes Report\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Summary
    report.append("## Change Statistics\n")
    report.append(f"| Type | Count |")
    report.append(f"|------|-------|")
    for cat in ['page', 'api', 'static_asset', 'video_embed', 'tracking', 'auth', 'image', 'challenge']:
        report.append(f"| {cat} | {len(by_type[cat])} |")
    report.append("")
    
    report.append("## By Domain\n")
    report.append(f"| Domain | Count |")
    report.append(f"|--------|-------|")
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        report.append(f"| {domain} | {len(items)} |")
    report.append("")
    
    # Page changes (most important)
    report.append("## Page Content Changes (page)\n")
    pages = [p for p in by_type['page'] if p['title']]
    for p in pages[:100]:
        size_str = f"+{p['size_diff']}" if p['size_diff'] > 0 else str(p['size_diff'])
        report.append(f"- **{p['title']}**")
        report.append(f"  - URL: `{p['url'][:120]}`")
        report.append(f"  - Size change: {size_str} bytes")
    if len(pages) > 100:
        report.append(f"\n_...and {len(pages) - 100} more page changes_")
    report.append("")
    
    # API changes
    report.append("## API Changes (api)\n")
    for p in by_type['api'][:50]:
        size_str = f"+{p['size_diff']}" if p['size_diff'] > 0 else str(p['size_diff'])
        report.append(f"- `{p['url'][:100]}` ({size_str} bytes)")
    if len(by_type['api']) > 50:
        report.append(f"\n_...and {len(by_type['api']) - 50} more API changes_")
    report.append("")
    
    # Video embed changes
    report.append("## Video Embed Changes (video_embed)\n")
    for p in by_type['video_embed'][:30]:
        size_str = f"+{p['size_diff']}" if p['size_diff'] > 0 else str(p['size_diff'])
        report.append(f"- `{p['url'][:100]}` ({size_str} bytes)")
    if len(by_type['video_embed']) > 30:
        report.append(f"\n_...and {len(by_type['video_embed']) - 30} more video changes_")
    report.append("")
    
    # Auth changes
    report.append("## Authentication Changes (auth)\n")
    for p in by_type['auth'][:50]:
        size_str = f"+{p['size_diff']}" if p['size_diff'] > 0 else str(p['size_diff'])
        report.append(f"- `{p['url'][:100]}` ({size_str} bytes)")
    if len(by_type['auth']) > 50:
        report.append(f"\n_...and {len(by_type['auth']) - 50} more auth changes_")
    report.append("")
    
    # Tracking changes
    report.append("## Tracking/Analytics Changes (tracking)\n")
    for p in by_type['tracking'][:30]:
        size_str = f"+{p['size_diff']}" if p['size_diff'] > 0 else str(p['size_diff'])
        report.append(f"- `{p['url'][:100]}` ({size_str} bytes)")
    if len(by_type['tracking']) > 30:
        report.append(f"\n_...and {len(by_type['tracking']) - 30} more tracking changes_")
    report.append("")
    
    # Static asset changes
    report.append("## Static Asset Changes (static_asset)\n")
    by_domain_asset = defaultdict(list)
    for p in by_type['static_asset']:
        domain = p['url'].split('/')[2] if '/' in p['url'][8:] else p['url']
        by_domain_asset[domain].append(p)
    
    report.append("### Distribution by Domain\n")
    for domain, items in sorted(by_domain_asset.items(), key=lambda x: -len(x[1])):
        report.append(f"- **{domain}**: {len(items)} files")
    report.append("")
    
    # Show some examples
    report.append("### Examples\n")
    for p in by_type['static_asset'][:20]:
        report.append(f"- `{p['url'][:100]}`")
    if len(by_type['static_asset']) > 20:
        report.append(f"\n_...and {len(by_type['static_asset']) - 20} more static asset changes_")
    report.append("")
    
    # New pages
    report.append("## New Pages\n")
    new_pages = [u for u in new_by_type['page']][:50]
    for url in sorted(new_pages):
        title = data2[url]['title'] if url in data2 else ''
        report.append(f"- [{title or url[:80]}]({url})")
    if len(new_by_type['page']) > 50:
        report.append(f"\n_...and {len(new_by_type['page']) - 50} more new pages_")
    report.append("")
    
    # Removed pages
    report.append("## Removed Pages\n")
    removed_pages = [u for u in removed_by_type['page']][:30]
    for url in sorted(removed_pages):
        report.append(f"- `{url}`")
    if len(removed_by_type['page']) > 30:
        report.append(f"\n_...and {len(removed_by_type['page']) - 30} more removed pages_")
    report.append("")
    
    # Write report
    output_path = Path(__file__).parent / 'categorized_changes.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    print(f"\nReport saved to: {output_path}")
    
    # Also output JSON for further analysis
    json_output = {
        'by_type': {k: len(v) for k, v in by_type.items()},
        'by_domain': {k: len(v) for k, v in by_domain.items()},
        'pages': [{'url': p['url'], 'title': p['title'], 'size_diff': p['size_diff']} for p in by_type['page'][:200]]
    }
    
    json_path = Path(__file__).parent / 'changes_summary.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
    
    print(f"JSON summary: {json_path}")


if __name__ == '__main__':
    main()
