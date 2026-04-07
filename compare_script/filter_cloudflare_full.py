#!/usr/bin/env python3
"""
Full analysis with Cloudflare pages filtered out.
"""

import os
import gzip
import hashlib
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
        except:
            pass
    
    return url_data


def is_cloudflare_page(title, url):
    """Check if this is a Cloudflare challenge page."""
    title_lower = (title or '').lower()
    url_lower = url.lower()
    
    indicators = [
        'just a moment',
        'checking your browser',
        'please wait',
        'cloudflare',
        'challenge-platform',
        'challenges.cloudflare.com',
        'turnstile'
    ]
    
    for indicator in indicators:
        if indicator in title_lower or indicator in url_lower:
            return True
    return False


def get_domain(url):
    """Extract domain category."""
    if 'windsurf.com' in url or 'docs.windsurf.com' in url:
        return 'windsurf'
    elif 'openclaw.ai' in url or 'docs.openclaw.ai' in url:
        return 'openclaw'
    elif 'cursor.com' in url or 'cursor.sh' in url:
        return 'cursor'
    elif 'claude.com' in url or 'claude.ai' in url or 'anthropic.com' in url:
        return 'claude'
    elif 'replit.com' in url:
        return 'replit'
    elif 'bolt.new' in url or 'support.bolt.new' in url:
        return 'bolt'
    elif 'github.com' in url:
        return 'github'
    elif 'trae.ai' in url or 'traeapi.us' in url:
        return 'trae'
    elif 'youtube.com' in url or 'youtube-nocookie.com' in url:
        return 'youtube'
    elif 'mux.com' in url or 'googlevideo.com' in url:
        return 'video_cdn'
    else:
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
    cloudflare_filtered = 0
    
    for url in common:
        if data1[url]['hash'] != data2[url]['hash']:
            title1 = data1[url]['title']
            title2 = data2[url]['title']
            
            # Filter Cloudflare pages
            if is_cloudflare_page(title1, url) or is_cloudflare_page(title2, url):
                cloudflare_filtered += 1
                continue
            
            changed.append({
                'url': url,
                'size_diff': data2[url]['size'] - data1[url]['size'],
                'title': title2 or title1,
                'domain': get_domain(url)
            })
    
    # Sort by size change
    changed.sort(key=lambda x: abs(x['size_diff']), reverse=True)
    
    # Group by domain
    by_domain = defaultdict(list)
    for item in changed:
        by_domain[item['domain']].append(item)
    
    print(f"\n总变化: {len(changed)} (过滤掉 {cloudflare_filtered} 个 Cloudflare 页面)")
    
    # Generate report
    report = []
    report.append("# 真实内容变化报告 (排除 Cloudflare 验证)\n")
    report.append(f"**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Summary
    report.append("## 统计\n")
    report.append(f"- 原始变化: {len(changed) + cloudflare_filtered} 个")
    report.append(f"- Cloudflare 验证页: {cloudflare_filtered} 个 (已排除)")
    report.append(f"- **真实内容变化: {len(changed)} 个**\n")
    
    report.append("## 按域名分布\n")
    report.append(f"| 域名 | 变化数 |")
    report.append(f"|------|--------|")
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        report.append(f"| {domain} | {len(items)} |")
    report.append("")
    
    # Show changes by domain
    for domain in ['openclaw', 'cursor', 'windsurf', 'claude', 'replit', 'bolt', 'github', 'trae', 'youtube', 'video_cdn', 'other']:
        items = by_domain.get(domain, [])
        if not items:
            continue
        
        report.append(f"## {domain.upper()} ({len(items)})\n")
        
        for p in items[:50]:
            size_diff = p.get('size_diff', 0)
            size_str = f"+{size_diff}" if size_diff > 0 else str(size_diff)
            title = p.get('title', '')[:80] or p['url'][:80]
            url_short = p['url'][:120]
            
            report.append(f"- **{title}**")
            report.append(f"  - `{url_short}`")
            report.append(f"  - {size_str} bytes")
        
        if len(items) > 50:
            report.append(f"\n_...还有 {len(items) - 50} 个_")
        report.append("")
    
    # Write report
    output_path = Path(__file__).parent / 'real_changes_full.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    print(f"\n报告已保存到: {output_path}")
    
    # Save JSON
    json_output = {
        'stats': {
            'total': len(changed),
            'cloudflare_filtered': cloudflare_filtered
        },
        'by_domain': {k: len(v) for k, v in by_domain.items()},
        'changes': changed[:500]
    }
    json_path = Path(__file__).parent / 'real_changes.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
    print(f"JSON: {json_path}")


if __name__ == '__main__':
    main()
