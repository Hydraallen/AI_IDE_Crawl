#!/usr/bin/env python3
"""
Generate detailed text change report with before/after content.
"""

import json
import gzip
import hashlib
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import difflib

from warcio import ArchiveIterator
from bs4 import BeautifulSoup, Comment


# Configuration
MIN_TEXT_LENGTH = 100
SIMILARITY_THRESHOLD = 0.98
MIN_CHANGED_LINES = 3

DOMAIN_PATTERNS = {
    'windsurf': ['windsurf.com', 'docs.windsurf.com', 'codeium.com'],
    'openclaw': ['openclaw.ai', 'docs.openclaw.ai'],
    'cursor': ['cursor.com', 'cursor.sh'],
    'claude': ['claude.com', 'claude.ai', 'anthropic.com', 'platform.claude.com'],
    'replit': ['replit.com', 'repl.it'],
    'bolt': ['bolt.new', 'support.bolt.new'],
    'github': ['github.com'],
    'trae': ['trae.ai', 'traeapi.us'],
}

CLOUDFLARE_INDICATORS = [
    'just a moment',
    'checking your browser',
    'please wait',
    'cloudflare',
    'challenge-platform',
]


def get_domain_category(url):
    url_lower = url.lower()
    for category, patterns in DOMAIN_PATTERNS.items():
        for pattern in patterns:
            if pattern in url_lower:
                return category
    return 'other'


def extract_readable_text(content, content_type=''):
    if not content:
        return '', ''
    
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
    except:
        return '', ''
    
    title = ''
    
    if 'text/html' not in content_type and content_type:
        return '', ''
    
    try:
        soup = BeautifulSoup(content, 'lxml')
        
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        for element in soup(['script', 'style', 'noscript', 'iframe', 'svg', 'canvas', 'img', 'video', 'audio']):
            element.decompose()
        
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        for element in soup.find_all(['nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        for selector in ['.nav', '.navigation', '.menu', '.sidebar', '.footer', '.header',
                          '.breadcrumb', '.pagination', '.social', '.share']:
            for element in soup.select(selector):
                element.decompose()
        
        main = soup.find('main') or soup.find('article') or soup.find('body') or soup
        
        text = main.get_text(separator='\n', strip=True)
        
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if len(line) < 3:
                continue
            if line.lower() in ['skip to content', 'menu', 'search', 'login', 'sign up']:
                continue
            lines.append(line)
        
        return title, '\n'.join(lines)
        
    except:
        return '', ''


def get_text_hash(text):
    if not text:
        return ''
    normalized = ' '.join(text.split())
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


def parse_warc_collection(collection_path):
    archive_path = Path(collection_path) / 'archive'
    if not archive_path.exists():
        return {}
    
    url_data = {}
    warc_files = list(archive_path.glob('*.warc.gz'))
    
    print(f"  Parsing {len(warc_files)} WARC files...")
    
    for warc_file in warc_files:
        try:
            with gzip.open(warc_file, 'rb') as stream:
                for record in ArchiveIterator(stream):
                    try:
                        if record.rec_type != 'response':
                            continue
                        
                        url = record.rec_headers.get_header('WARC-Target-URI')
                        if not url:
                            continue
                        
                        content = record.content_stream().read()
                        content_type = record.http_headers.get_header('Content-Type', '') if record.http_headers else ''
                        
                        if 'text/html' not in content_type and content_type:
                            continue
                        
                        title, text = extract_readable_text(content, content_type)
                        
                        if len(text) < MIN_TEXT_LENGTH:
                            continue
                        
                        # Get timestamp
                        timestamp = record.rec_headers.get_header('WARC-Date', '')
                        
                        url_data[url] = {
                            'text_hash': get_text_hash(text),
                            'text': text,
                            'full_text': text,  # Keep full text
                            'title': title,
                            'text_len': len(text),
                            'timestamp': timestamp,
                        }
                        
                    except:
                        continue
                        
        except Exception as e:
            print(f"  Error reading {warc_file.name}: {e}")
    
    return url_data


def is_cloudflare_page(title, url):
    title_lower = (title or '').lower()
    url_lower = url.lower()
    
    for indicator in CLOUDFLARE_INDICATORS:
        if indicator in title_lower or indicator in url_lower:
            return True
    return False


def get_full_diff(text1, text2):
    """Get complete diff between two texts."""
    lines1 = text1.split('\n')
    lines2 = text2.split('\n')
    
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    ratio = matcher.ratio()
    
    added = []
    removed = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'insert':
            added.extend(lines2[j1:j2])
        elif tag == 'delete':
            removed.extend(lines1[i1:i2])
        elif tag == 'replace':
            removed.extend(lines1[i1:i2])
            added.extend(lines2[j1:j2])
    
    return {
        'similarity': ratio,
        'added': added,
        'removed': removed,
        'added_count': len(added),
        'removed_count': len(removed)
    }


def main():
    coll1_path = '../crawls/collections/crawl-20260315'
    coll2_path = '../crawls/collections/crawl-20260316'
    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract dates from collection names
    old_date = '2026-03-15'
    new_date = '2026-03-16'
    
    print("Loading OLD collection...")
    data1 = parse_warc_collection(coll1_path)
    print(f"  Found {len(data1)} pages with text")
    
    print("Loading NEW collection...")
    data2 = parse_warc_collection(coll2_path)
    print(f"  Found {len(data2)} pages with text")
    
    urls1 = set(data1.keys())
    urls2 = set(data2.keys())
    common = urls1 & urls2
    
    # Analyze text changes
    print("\nAnalyzing text changes...")
    text_changes = []
    cloudflare_filtered = 0
    formatting_only = 0
    
    for url in common:
        if data1[url]['text_hash'] == data2[url]['text_hash']:
            continue
        
        title1 = data1[url].get('title', '')
        title2 = data2[url].get('title', '')
        
        if is_cloudflare_page(title1, url) or is_cloudflare_page(title2, url):
            cloudflare_filtered += 1
            continue
        
        diff = get_full_diff(
            data1[url].get('full_text', ''),
            data2[url].get('full_text', '')
        )
        
        if diff['similarity'] > SIMILARITY_THRESHOLD:
            formatting_only += 1
            continue
        
        if diff['added_count'] < MIN_CHANGED_LINES and diff['removed_count'] < MIN_CHANGED_LINES:
            formatting_only += 1
            continue
        
        text_changes.append({
            'url': url,
            'title_old': title1,
            'title_new': title2,
            'domain': get_domain_category(url),
            'similarity': diff['similarity'],
            'text_len_old': data1[url].get('text_len', 0),
            'text_len_new': data2[url].get('text_len', 0),
            'added': diff['added'],
            'removed': diff['removed'],
            'added_count': diff['added_count'],
            'removed_count': diff['removed_count'],
            'timestamp_old': data1[url].get('timestamp', ''),
            'timestamp_new': data2[url].get('timestamp', ''),
        })
    
    text_changes.sort(key=lambda x: x['similarity'])
    
    print(f"  Found {len(text_changes)} real text changes")
    print(f"  Filtered: {cloudflare_filtered} Cloudflare, {formatting_only} formatting")
    
    # Generate detailed report
    report = []
    report.append("# 文本内容变化详细报告\n")
    report.append(f"**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append(f"**比较日期:** {old_date} → {new_date}\n")
    report.append("")
    report.append("---\n")
    
    # Group by domain
    by_domain = defaultdict(list)
    for item in text_changes:
        by_domain[item['domain']].append(item)
    
    # Summary
    report.append("## 变化统计\n")
    report.append(f"| 域名 | 变化数 |")
    report.append(f"|------|--------|")
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        report.append(f"| {domain} | {len(items)} |")
    report.append("")
    report.append("---\n")
    
    # Detailed changes by domain
    for domain in sorted(by_domain.keys(), key=lambda x: -len(by_domain[x])):
        items = by_domain[domain]
        
        report.append(f"\n## {domain.upper()} ({len(items)} 个变化)\n")
        report.append("---\n")
        
        for i, item in enumerate(items, 1):
            sim_pct = item['similarity'] * 100
            len_change = item['text_len_new'] - item['text_len_old']
            len_str = f"+{len_change}" if len_change > 0 else str(len_change)
            
            report.append(f"\n### {i}. {item['title_new'] or item['title_old'] or '(无标题)'}\n")
            
            # URL
            report.append(f"**URL:** `{item['url']}`\n")
            
            # Meta info
            report.append(f"| 属性 | 旧值 ({old_date}) | 新值 ({new_date}) |")
            report.append(f"|------|------------------|------------------|")
            report.append(f"| 相似度 | - | {sim_pct:.1f}% |")
            report.append(f"| 文本长度 | {item['text_len_old']} | {item['text_len_new']} ({len_str}) |")
            if item['title_old'] != item['title_new']:
                report.append(f"| 标题 | {item['title_old'][:50] if item['title_old'] else '-'} | {item['title_new'][:50] if item['title_new'] else '-'} |")
            report.append("")
            
            # Content changes
            if item['removed']:
                report.append(f"\n#### 删除的内容 ({item['removed_count']} 行)\n")
                report.append("```diff")
                for line in item['removed'][:30]:
                    report.append(f"- {line}")
                if len(item['removed']) > 30:
                    report.append(f"... 还有 {len(item['removed']) - 30} 行")
                report.append("```\n")
            
            if item['added']:
                report.append(f"\n#### 新增的内容 ({item['added_count']} 行)\n")
                report.append("```diff")
                for line in item['added'][:30]:
                    report.append(f"+ {line}")
                if len(item['added']) > 30:
                    report.append(f"... 还有 {len(item['added']) - 30} 行")
                report.append("```\n")
            
            report.append("\n---\n")
    
    # Write report
    output_file = output_dir / f'text_changes_detail_{old_date}_to_{new_date}.md'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    print(f"\n报告已保存到: {output_file}")
    
    # Also save JSON for machine processing
    json_file = output_dir / f'text_changes_detail_{old_date}_to_{new_date}.json'
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump({
            'generated': datetime.now().isoformat(),
            'old_date': old_date,
            'new_date': new_date,
            'stats': {
                'total_changes': len(text_changes),
                'by_domain': {k: len(v) for k, v in by_domain.items()},
                'cloudflare_filtered': cloudflare_filtered,
                'formatting_only': formatting_only,
            },
            'changes': text_changes,
        }, f, indent=2, ensure_ascii=False)
    
    print(f"JSON 已保存到: {json_file}")


if __name__ == '__main__':
    main()
