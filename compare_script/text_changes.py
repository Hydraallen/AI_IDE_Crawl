#!/usr/bin/env python3
"""
Compare TEXT content changes only - ignore formatting, HTML structure, JS, CSS.
Focus on what humans actually read.
"""

import os
import gzip
import hashlib
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import json

from warcio import ArchiveIterator
from bs4 import BeautifulSoup, Comment


def get_url_from_warc_record(record):
    if record.rec_type == 'response':
        return record.rec_headers.get_header('WARC-Target-URI')
    return None


def get_text_hash(text):
    """Hash of normalized text."""
    if not text:
        return ''
    # Normalize whitespace
    normalized = ' '.join(text.split())
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


def extract_readable_text(content, content_type=''):
    """
    Extract clean, readable text from HTML content.
    Remove scripts, styles, navigation, footers, etc.
    """
    if not content:
        return '', ''
    
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
    except:
        return '', ''
    
    title = ''
    
    # Only process HTML
    if 'text/html' not in content_type and content_type:
        # For non-HTML, just return the raw content if it looks like text
        if 'text/' in content_type or 'json' in content_type or 'javascript' in content_type:
            return '', content[:500]  # Don't process non-HTML as text changes
        return '', ''
    
    try:
        soup = BeautifulSoup(content, 'lxml')
        
        # Get title
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        # Remove non-content elements
        for element in soup(['script', 'style', 'noscript', 'iframe', 'svg', 'canvas', 'img', 'video', 'audio', 'source', 'track', 'embed', 'object', 'param']):
            element.decompose()
        
        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Remove navigation, header, footer, aside (usually not main content)
        for element in soup.find_all(['nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        # Remove elements with common non-content classes/ids
        for selector in ['.nav', '.navigation', '.menu', '.sidebar', '.footer', '.header', 
                          '.breadcrumb', '.pagination', '.social', '.share', '.comment',
                          '#nav', '#navigation', '#menu', '#sidebar', '#footer', '#header',
                          '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]']:
            for element in soup.select(selector):
                element.decompose()
        
        # Get main content area if exists
        main = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main|article|post|entry', re.I)) or soup.find('body') or soup
        
        # Extract text
        text = main.get_text(separator='\n', strip=True)
        
        # Clean up: remove excessive whitespace and empty lines
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            # Skip very short lines that are likely UI elements
            if len(line) < 3:
                continue
            # Skip lines that look like UI elements
            if line.lower() in ['skip to content', 'menu', 'search', 'login', 'sign up', 
                                  'subscribe', 'newsletter', 'follow us', 'share', 'tweet', 'like']:
                continue
            lines.append(line)
        
        clean_text = '\n'.join(lines)
        
        return title, clean_text
        
    except Exception as e:
        return '', ''


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
    ]
    
    for indicator in indicators:
        if indicator in title_lower or indicator in url_lower:
            return True
    return False


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
                        
                        # Only process HTML pages
                        if 'text/html' not in content_type and content_type:
                            continue
                        
                        title, text = extract_readable_text(content, content_type)
                        
                        # Skip if no meaningful text
                        if len(text) < 100:
                            continue
                        
                        url_data[url] = {
                            'text_hash': get_text_hash(text),
                            'text': text[:5000],  # Store first 5000 chars for diff
                            'title': title,
                            'text_len': len(text)
                        }
                    except:
                        continue
        except:
            pass
    
    return url_data


def get_text_diff(text1, text2):
    """Get a simple diff of two texts."""
    import difflib
    
    lines1 = text1.split('\n')[:50]  # Limit for performance
    lines2 = text2.split('\n')[:50]
    
    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    ratio = matcher.ratio()
    
    # Find changed lines
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
        'added': added[:10],
        'removed': removed[:10],
        'added_count': len(added),
        'removed_count': len(removed)
    }


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
    else:
        return 'other'


def main():
    coll1 = '../crawls/collections/crawl-20260315'
    coll2 = '../crawls/collections/crawl-20260329'
    
    print("Loading collection 1...")
    data1 = parse_warc_files(coll1)
    print(f"  Loaded {len(data1)} HTML pages with readable text")
    
    print("Loading collection 2...")
    data2 = parse_warc_files(coll2)
    print(f"  Loaded {len(data2)} HTML pages with readable text")
    
    urls1 = set(data1.keys())
    urls2 = set(data2.keys())
    
    common = urls1 & urls2
    
    # Find text content changes
    text_changes = []
    cloudflare_filtered = 0
    no_real_change = 0
    
    for url in common:
        if data1[url]['text_hash'] != data2[url]['text_hash']:
            title1 = data1[url]['title']
            title2 = data2[url]['title']
            
            # Filter Cloudflare
            if is_cloudflare_page(title1, url) or is_cloudflare_page(title2, url):
                cloudflare_filtered += 1
                continue
            
            # Get text diff
            diff = get_text_diff(data1[url]['text'], data2[url]['text'])
            
            # Skip if similarity is very high (likely just formatting changes)
            if diff['similarity'] > 0.98:
                no_real_change += 1
                continue
            
            # Skip if very few lines changed (likely minor edits)
            if diff['added_count'] < 3 and diff['removed_count'] < 3:
                no_real_change += 1
                continue
            
            text_changes.append({
                'url': url,
                'title': title2 or title1,
                'domain': get_domain(url),
                'similarity': diff['similarity'],
                'text_len_change': data2[url]['text_len'] - data1[url]['text_len'],
                'added': diff['added'],
                'removed': diff['removed'],
                'added_count': diff['added_count'],
                'removed_count': diff['removed_count']
            })
    
    # Sort by significance (lower similarity = more change)
    text_changes.sort(key=lambda x: x['similarity'])
    
    # Group by domain
    by_domain = defaultdict(list)
    for item in text_changes:
        by_domain[item['domain']].append(item)
    
    print(f"\nText content changes: {len(text_changes)}")
    print(f"  Cloudflare filtered: {cloudflare_filtered}")
    print(f"  No real change: {no_real_change}")
    
    # Generate report
    report = []
    report.append("# Text Content Changes Report\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append("Only pages with substantive text content changes are reported; formatting and HTML structure changes are ignored.\n")
    
    # Summary
    report.append("## Statistics\n")
    report.append(f"- **Text content changes: {len(text_changes)} pages**")
    report.append(f"- Cloudflare challenge pages: {cloudflare_filtered} (excluded)")
    report.append(f"- Formatting/minor changes: {no_real_change} (ignored)\n")
    
    report.append("## Distribution by Domain\n")
    report.append(f"| Domain | Changes |")
    report.append(f"|--------|---------|")
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        report.append(f"| {domain} | {len(items)} |")
    report.append("")
    
    # Show changes by domain
    for domain in ['openclaw', 'cursor', 'windsurf', 'claude', 'replit', 'bolt', 'github', 'trae', 'other']:
        items = by_domain.get(domain, [])
        if not items:
            continue
        
        report.append(f"## {domain.upper()} ({len(items)})\n")
        
        for p in items[:30]:
            sim_pct = p['similarity'] * 100
            len_change = p['text_len_change']
            len_str = f"+{len_change}" if len_change > 0 else str(len_change)
            
            report.append(f"### {p['title'][:80]}\n")
            report.append(f"**URL:** `{p['url'][:120]}`\n")
            report.append(f"**Similarity:** {sim_pct:.1f}% | **Text length change:** {len_str} chars")
            report.append(f"**Changes:** +{p['added_count']} lines, -{p['removed_count']} lines\n")
            
            if p['removed']:
                report.append(f"**Removed content:**")
                for line in p['removed'][:5]:
                    if line.strip():
                        report.append(f"- {line[:150]}")
                report.append("")
            
            if p['added']:
                report.append(f"**Added content:**")
                for line in p['added'][:5]:
                    if line.strip():
                        report.append(f"+ {line[:150]}")
                report.append("")
        
        if len(items) > 30:
            report.append(f"\n_...and {len(items) - 30} more changes_")
        report.append("")
    
    # Write report
    output_path = Path(__file__).parent / 'text_changes.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    print(f"\nReport saved to: {output_path}")


if __name__ == '__main__':
    main()
