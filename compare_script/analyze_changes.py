#!/usr/bin/env python3
"""
Deep analysis of content changes between two crawls.
Shows what actually changed in each page.
"""

import os
import sys
import gzip
import hashlib
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import difflib

from warcio import ArchiveIterator
from bs4 import BeautifulSoup


def get_url_from_warc_record(record):
    """Extract URL from a WARC record."""
    if record.rec_type == 'response':
        return record.rec_headers.get_header('WARC-Target-URI')
    return None


def get_content_hash(content):
    """Generate MD5 hash of content for comparison."""
    if isinstance(content, str):
        content = content.encode('utf-8', errors='ignore')
    return hashlib.md5(content).hexdigest()


def extract_text_content(content, content_type=''):
    """Extract text content from HTML for comparison."""
    if not content:
        return '', ''
    
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
    except Exception:
        return '', ''
    
    # Only parse HTML content
    if 'text/html' in content_type or not content_type:
        try:
            soup = BeautifulSoup(content, 'lxml')
            # Remove script, style, noscript, and other non-content elements
            for element in soup(['script', 'style', 'noscript', 'header', 'footer', 'nav', 'aside']):
                element.decompose()
            
            # Get title
            title = ''
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            
            # Get main content
            main = soup.find('main') or soup.find('article') or soup.find('body') or soup
            text = main.get_text(separator='\n', strip=True)
            
            # Clean up whitespace
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            
            return title, '\n'.join(lines)
        except Exception as e:
            return '', str(content)[:5000] if content else ''
    
    return '', str(content)[:5000] if content else ''


def extract_metadata(content, content_type=''):
    """Extract metadata from HTML (meta tags, links, etc.)"""
    if not content:
        return {}
    
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
    except Exception:
        return {}
    
    if 'text/html' not in content_type:
        return {}
    
    metadata = {
        'title': '',
        'description': '',
        'keywords': '',
        'h1': [],
        'h2': [],
        'links': [],
        'images': 0,
        'scripts': 0
    }
    
    try:
        soup = BeautifulSoup(content, 'lxml')
        
        # Title
        if soup.title and soup.title.string:
            metadata['title'] = soup.title.string.strip()
        
        # Meta tags
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            metadata['description'] = meta_desc.get('content', '')
        
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords:
            metadata['keywords'] = meta_keywords.get('content', '')
        
        # Headings
        for h1 in soup.find_all('h1'):
            text = h1.get_text(strip=True)
            if text:
                metadata['h1'].append(text[:100])
        
        for h2 in soup.find_all('h2')[:10]:
            text = h2.get_text(strip=True)
            if text:
                metadata['h2'].append(text[:100])
        
        # Count links (internal/external)
        for link in soup.find_all('a', href=True)[:20]:
            href = link.get('href', '')
            text = link.get_text(strip=True)[:50]
            if text:
                metadata['links'].append({'href': href, 'text': text})
        
        # Count resources
        metadata['images'] = len(soup.find_all('img'))
        metadata['scripts'] = len(soup.find_all('script'))
        
    except Exception:
        pass
    
    return metadata


def parse_warc_content(collection_path):
    """Parse WARC files and extract content by URL."""
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
                        timestamp = record.rec_headers.get_header('WARC-Date', '')
                        status = record.http_headers.get_statuscode() if record.http_headers else ''
                        
                        title, text = extract_text_content(content, content_type)
                        metadata = extract_metadata(content, content_type)
                        
                        # Use title from metadata if available
                        if metadata.get('title') and not title:
                            title = metadata['title']
                        
                        url_data[url] = {
                            'hash': get_content_hash(content),
                            'size': len(content),
                            'content_type': content_type,
                            'timestamp': timestamp,
                            'status': status,
                            'title': title,
                            'text': text,
                            'text_hash': get_content_hash(text),
                            'metadata': metadata
                        }
                    except Exception as e:
                        continue  # Skip problematic records
        except Exception as e:
            print(f"  Error reading {warc_file.name}: {e}")
    
    return url_data


def analyze_change(url, old_data, new_data):
    """Analyze what changed between two versions of a URL."""
    changes = {
        'url': url,
        'title_old': old_data.get('title', ''),
        'title_new': new_data.get('title', ''),
        'title_changed': False,
        'size_diff': 0,
        'text_diff': None,
        'metadata_changes': {},
        'significant': False
    }
    
    changes['size_diff'] = new_data['size'] - old_data['size']
    
    # Check title change
    if changes['title_old'] != changes['title_new']:
        changes['title_changed'] = True
        changes['significant'] = True
    
    # Check text content change
    if old_data['text_hash'] != new_data['text_hash']:
        old_lines = old_data['text'].split('\n')
        new_lines = new_data['text'].split('\n')
        
        # Calculate diff ratio
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        ratio = matcher.ratio()
        
        # Get actual changes
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=0))
        
        # Extract added/removed lines
        added = [line[1:] for line in diff if line.startswith('+') and not line.startswith('+++')]
        removed = [line[1:] for line in diff if line.startswith('-') and not line.startswith('---')]
        
        # Limit output
        added = [l[:200] for l in added[:20]]
        removed = [l[:200] for l in removed[:20]]
        
        changes['text_diff'] = {
            'ratio': ratio,
            'added_count': len(added),
            'removed_count': len(removed),
            'added': added,
            'removed': removed
        }
        
        if ratio < 0.9:  # More than 10% change
            changes['significant'] = True
    
    # Check metadata changes
    old_meta = old_data.get('metadata', {})
    new_meta = new_data.get('metadata', {})
    
    for key in ['description', 'keywords']:
        if old_meta.get(key) != new_meta.get(key):
            changes['metadata_changes'][key] = {
                'old': old_meta.get(key, '')[:100],
                'new': new_meta.get(key, '')[:100]
            }
    
    # Check heading changes
    if old_meta.get('h1') != new_meta.get('h1'):
        changes['metadata_changes']['h1'] = {
            'old': old_meta.get('h1', [])[:5],
            'new': new_meta.get('h1', [])[:5]
        }
        changes['significant'] = True
    
    if old_meta.get('h2') != new_meta.get('h2'):
        changes['metadata_changes']['h2'] = {
            'old': old_meta.get('h2', [])[:10],
            'new': new_meta.get('h2', [])[:10]
        }
    
    return changes


def categorize_url(url):
    """Categorize URL by type."""
    url_lower = url.lower()
    
    if any(x in url_lower for x in ['.js', '.css', '.woff', '.ttf', 'assets/', 'static/']):
        return 'static_asset'
    elif any(x in url_lower for x in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']):
        return 'image'
    elif any(x in url_lower for x in ['api/', '/api/', 'json?', '.json']):
        return 'api'
    elif any(x in url_lower for x in ['youtube.com', 'vimeo.com', 'video']):
        return 'video_embed'
    elif any(x in url_lower for x in ['analytics', 'tracking', 'pixel', 'ads', 'gtm', 'gtag']):
        return 'tracking'
    elif any(x in url_lower for x in ['auth', 'login', 'signin', 'oauth', 'account']):
        return 'auth'
    else:
        return 'page'


def generate_detailed_report(data1, data2, output_path=None):
    """Generate a detailed report of all changes."""
    urls1 = set(data1.keys())
    urls2 = set(data2.keys())
    
    added_urls = urls2 - urls1
    removed_urls = urls1 - urls2
    common_urls = urls1 & urls2
    
    # Analyze changes
    changes = []
    unchanged = []
    
    for url in common_urls:
        if data1[url]['hash'] != data2[url]['hash']:
            change = analyze_change(url, data1[url], data2[url])
            changes.append(change)
        else:
            unchanged.append(url)
    
    # Sort by significance and size diff
    changes.sort(key=lambda x: (not x['significant'], abs(x['size_diff'])), reverse=True)
    
    # Categorize changes
    by_category = defaultdict(list)
    for change in changes:
        cat = categorize_url(change['url'])
        by_category[cat].append(change)
    
    # Generate report
    report = []
    report.append(f"# Detailed Crawl Change Analysis\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append(f"**Comparison:** crawl-20260315 vs crawl-20260316\n")
    
    # Summary
    report.append(f"## Summary\n")
    report.append(f"| Category | Count |")
    report.append(f"|----------|-------|")
    report.append(f"| Total Changed | {len(changes)} |")
    report.append(f"| Significant Changes | {sum(1 for c in changes if c['significant'])} |")
    report.append(f"| Unchanged | {len(unchanged)} |")
    report.append(f"| New URLs | {len(added_urls)} |")
    report.append(f"| Removed URLs | {len(removed_urls)} |")
    report.append(f"")
    
    # Changes by category
    report.append(f"## Changes by Category\n")
    for cat in ['page', 'api', 'static_asset', 'video_embed', 'tracking', 'auth', 'image']:
        if cat in by_category:
            report.append(f"| {cat} | {len(by_category[cat])} |")
    report.append(f"")
    
    # Significant page changes first
    page_changes = [c for c in by_category.get('page', []) if c['significant']]
    if page_changes:
        report.append(f"## Significant Page Content Changes ({len(page_changes)})\n")
        for c in page_changes[:30]:
            report.append(f"### {c['title_new'] or c['url'][:80]}\n")
            report.append(f"**URL:** `{c['url']}`\n")
            report.append(f"**Size:** {c['size_diff']:+d} bytes\n")
            
            if c['title_changed']:
                report.append(f"- Title: \"{c['title_old']}\" → \"{c['title_new']}\"\n")
            
            if c['text_diff']:
                td = c['text_diff']
                report.append(f"- Content similarity: {td['ratio']*100:.1f}%")
                report.append(f"- Lines added: {td['added_count']}, removed: {td['removed_count']}")
                
                if td['added']:
                    report.append(f"\n**Added content:**")
                    for line in td['added'][:5]:
                        if line.strip():
                            report.append(f"  + {line[:150]}")
                
                if td['removed']:
                    report.append(f"\n**Removed content:**")
                    for line in td['removed'][:5]:
                        if line.strip():
                            report.append(f"  - {line[:150]}")
            
            if c['metadata_changes']:
                for key, val in c['metadata_changes'].items():
                    report.append(f"\n**{key} changed:**")
                    if isinstance(val, dict) and 'old' in val:
                        if isinstance(val['old'], list):
                            report.append(f"  - Old: {val['old'][:3]}")
                            report.append(f"  - New: {val['new'][:3]}")
                        else:
                            report.append(f"  - Old: {val['old'][:100]}")
                            report.append(f"  - New: {val['new'][:100]}")
            
            report.append(f"")
        
        if len(page_changes) > 30:
            report.append(f"\n_... and {len(page_changes) - 30} more significant page changes_\n")
    
    # API changes
    api_changes = by_category.get('api', [])
    if api_changes:
        report.append(f"## API/JSON Changes ({len(api_changes)})\n")
        for c in api_changes[:20]:
            report.append(f"- **{c['url'][:100]}**")
            report.append(f"  Size: {c['size_diff']:+d} bytes")
        if len(api_changes) > 20:
            report.append(f"\n_... and {len(api_changes) - 20} more_")
        report.append(f"")
    
    # Static asset changes (just list)
    static_changes = by_category.get('static_asset', [])
    if static_changes:
        report.append(f"## Static Asset Changes ({len(static_changes)})\n")
        report.append(f"Most assets changed due to cache-busting hash changes in filenames.\n")
        
        # Group by domain
        by_domain = defaultdict(int)
        for c in static_changes:
            domain = c['url'].split('/')[2] if '/' in c['url'][8:] else c['url']
            by_domain[domain] += 1
        
        report.append(f"\nBy domain:")
        for domain, count in sorted(by_domain.items(), key=lambda x: -x[1])[:10]:
            report.append(f"- {domain}: {count} files")
        report.append(f"")
    
    # New pages worth noting
    new_pages = [u for u in added_urls if categorize_url(u) == 'page']
    if new_pages:
        report.append(f"## New Pages ({len(new_pages)})\n")
        for url in sorted(new_pages)[:30]:
            title = data2[url]['title'] if url in data2 else ''
            report.append(f"- [{title or url[:80]}]({url})")
        if len(new_pages) > 30:
            report.append(f"\n_... and {len(new_pages) - 30} more_")
        report.append(f"")
    
    # Removed pages
    removed_pages = [u for u in removed_urls if categorize_url(u) == 'page']
    if removed_pages:
        report.append(f"## Removed Pages ({len(removed_pages)})\n")
        for url in sorted(removed_pages)[:20]:
            report.append(f"- {url}")
        if len(removed_pages) > 20:
            report.append(f"\n_... and {len(removed_pages) - 20} more_")
        report.append(f"")
    
    report_text = '\n'.join(report)
    
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"Report saved to: {output_path}")
    
    return report_text, changes


def main():
    parser = argparse.ArgumentParser(description='Deep analysis of crawl content changes')
    parser.add_argument('collection1', help='Path to first collection (older)')
    parser.add_argument('collection2', help='Path to second collection (newer)')
    parser.add_argument('-o', '--output', default='detailed_changes.md', help='Output report file')
    
    args = parser.parse_args()
    
    print(f"Loading collection 1: {args.collection1}")
    data1 = parse_warc_content(args.collection1)
    print(f"  Loaded {len(data1)} URLs")
    
    print(f"\nLoading collection 2: {args.collection2}")
    data2 = parse_warc_content(args.collection2)
    print(f"  Loaded {len(data2)} URLs")
    
    print(f"\nAnalyzing changes...")
    
    output_path = args.output
    if not Path(output_path).is_absolute():
        output_path = Path(__file__).parent / output_path
    
    report, changes = generate_detailed_report(data1, data2, output_path)
    
    # Print summary
    sig_count = sum(1 for c in changes if c['significant'])
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"Total changes: {len(changes)}")
    print(f"Significant changes: {sig_count}")
    print(f"Minor changes: {len(changes) - sig_count}")
    
    return changes


if __name__ == '__main__':
    main()
