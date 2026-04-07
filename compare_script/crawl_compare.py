#!/usr/bin/env python3
"""
Web Crawl Comparison Tool
=========================

Compare two web archive (WARC/WACZ) collections and generate reports:
1. Basic comparison (URLs added/removed/changed)
2. Detailed content changes
3. Text-only changes (filter out formatting)
4. Categorized by domain and change type

Usage:
    python crawl_compare.py --old <old_collection> --new <new_collection> --output <output_dir>
    
Example:
    python crawl_compare.py --old ./crawls/collections/crawl-20260315 --new ./crawls/collections/crawl-20260316 --output ./reports
"""

import os
import sys
import gzip
import hashlib
import re
import argparse
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import difflib

from warcio import ArchiveIterator
from bs4 import BeautifulSoup, Comment


# =============================================================================
# CONFIGURATION
# =============================================================================

# Minimum text length to consider a page as having meaningful content
MIN_TEXT_LENGTH = 100

# Similarity threshold - pages above this are considered "formatting only" changes
SIMILARITY_THRESHOLD = 0.98

# Minimum changed lines to report as a real content change
MIN_CHANGED_LINES = 3

# Domains to categorize
DOMAIN_PATTERNS = {
    'windsurf': ['windsurf.com', 'docs.windsurf.com', 'codeium.com'],
    'openclaw': ['openclaw.ai', 'docs.openclaw.ai'],
    'cursor': ['cursor.com', 'cursor.sh'],
    'claude': ['claude.com', 'claude.ai', 'anthropic.com', 'platform.claude.com'],
    'replit': ['replit.com', 'repl.it'],
    'bolt': ['bolt.new', 'support.bolt.new'],
    'github': ['github.com'],
    'trae': ['trae.ai', 'traeapi.us'],
    'youtube': ['youtube.com', 'youtube-nocookie.com', 'youtu.be'],
}

# Cloudflare challenge page indicators
CLOUDFLARE_INDICATORS = [
    'just a moment',
    'checking your browser',
    'please wait',
    'cloudflare',
    'challenge-platform',
    'challenges.cloudflare.com',
]


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def setup_virtual_env():
    """Check and setup virtual environment with required packages."""
    venv_path = Path(__file__).parent / 'venv'
    
    if not venv_path.exists():
        print("Creating virtual environment...")
        import subprocess
        subprocess.run([sys.executable, '-m', 'venv', str(venv_path)], check=True)
        
        # Install dependencies
        pip_path = venv_path / 'bin' / 'pip'
        subprocess.run([str(pip_path), 'install', 'warcio', 'beautifulsoup4', 'lxml'], check=True)
        print("Virtual environment created and dependencies installed.")
    
    return venv_path


def get_domain_category(url):
    """Categorize URL by domain."""
    url_lower = url.lower()
    for category, patterns in DOMAIN_PATTERNS.items():
        for pattern in patterns:
            if pattern in url_lower:
                return category
    return 'other'


def get_content_type_category(content_type, url):
    """Categorize by content type."""
    content_type = (content_type or '').lower()
    url_lower = url.lower()
    
    # Order matters - more specific first
    if any(x in url_lower for x in ['analytics', 'tracking', 'pixel', '/gtm.', '/gtag', 'ads.']):
        return 'tracking'
    elif any(x in url_lower for x in ['/auth', '/login', '/signin', '/oauth', 'authenticate']):
        return 'auth'
    elif any(x in url_lower for x in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico']):
        return 'image'
    elif any(x in url_lower for x in ['.js', '.css', '.woff', '/assets/', '/static/', 'chunks/']):
        return 'static_asset'
    elif any(x in url_lower for x in ['youtube.com', 'youtu.be', 'vimeo.com', 'youtube-nocookie.com']):
        return 'video_embed'
    elif any(x in url_lower for x in ['/api/', 'api.', '.json', 'json?']):
        return 'api'
    elif 'text/html' in content_type or not content_type:
        return 'page'
    else:
        return 'other'


# =============================================================================
# WARC PARSING
# =============================================================================

def parse_warc_collection(collection_path, extract_text=False):
    """
    Parse all WARC files in a collection.
    
    Args:
        collection_path: Path to collection folder (contains archive/ subfolder)
        extract_text: If True, extract clean text content (slower but more useful)
    
    Returns:
        dict: {url: {data}}
    """
    archive_path = Path(collection_path) / 'archive'
    if not archive_path.exists():
        print(f"Warning: No archive folder at {archive_path}")
        return {}
    
    url_data = {}
    warc_files = list(archive_path.glob('*.warc.gz'))
    
    print(f"  Parsing {len(warc_files)} WARC files...")
    
    for warc_file in warc_files:
        try:
            with gzip.open(warc_file, 'rb') as stream:
                for record in ArchiveIterator(stream):
                    try:
                        # Only process response records
                        if record.rec_type != 'response':
                            continue
                        
                        url = record.rec_headers.get_header('WARC-Target-URI')
                        if not url:
                            continue
                        
                        content = record.content_stream().read()
                        content_type = record.http_headers.get_header('Content-Type', '') if record.http_headers else ''
                        
                        # Build data dict
                        data = {
                            'hash': hashlib.md5(content).hexdigest(),
                            'size': len(content),
                            'content_type': content_type,
                            'type_category': get_content_type_category(content_type, url),
                        }
                        
                        # Extract text if requested
                        if extract_text and 'text/html' in content_type:
                            title, text = extract_readable_text(content, content_type)
                            data['title'] = title
                            data['text'] = text
                            data['text_hash'] = get_text_hash(text)
                            data['text_len'] = len(text)
                        
                        url_data[url] = data
                        
                    except Exception as e:
                        continue
                        
        except Exception as e:
            print(f"  Error reading {warc_file.name}: {e}")
    
    return url_data


def extract_readable_text(content, content_type=''):
    """
    Extract clean, readable text from HTML.
    Removes scripts, styles, navigation, etc.
    """
    if not content:
        return '', ''
    
    try:
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
    except:
        return '', ''
    
    title = ''
    
    try:
        soup = BeautifulSoup(content, 'lxml')
        
        # Get title
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        # Remove non-content elements
        for element in soup(['script', 'style', 'noscript', 'iframe', 'svg', 'canvas', 'img', 'video', 'audio']):
            element.decompose()
        
        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Remove navigation/header/footer
        for element in soup.find_all(['nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        # Remove common non-content classes
        for selector in ['.nav', '.navigation', '.menu', '.sidebar', '.footer', '.header',
                          '.breadcrumb', '.pagination', '.social', '.share']:
            for element in soup.select(selector):
                element.decompose()
        
        # Get main content
        main = soup.find('main') or soup.find('article') or soup.find('body') or soup
        
        # Extract text
        text = main.get_text(separator='\n', strip=True)
        
        # Clean up
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if len(line) < 3:
                continue
            # Skip UI elements
            if line.lower() in ['skip to content', 'menu', 'search', 'login', 'sign up']:
                continue
            lines.append(line)
        
        return title, '\n'.join(lines)
        
    except:
        return '', ''


def get_text_hash(text):
    """Get hash of normalized text."""
    if not text:
        return ''
    normalized = ' '.join(text.split())
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


# =============================================================================
# COMPARISON LOGIC
# =============================================================================

def is_cloudflare_page(title, url):
    """Check if page is a Cloudflare challenge."""
    title_lower = (title or '').lower()
    url_lower = url.lower()
    
    for indicator in CLOUDFLARE_INDICATORS:
        if indicator in title_lower or indicator in url_lower:
            return True
    return False


def get_text_diff(text1, text2):
    """Get difference between two texts."""
    lines1 = text1.split('\n')[:50]
    lines2 = text2.split('\n')[:50]
    
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
        'added': added[:10],
        'removed': removed[:10],
        'added_count': len(added),
        'removed_count': len(removed)
    }


def compare_collections(data1, data2):
    """
    Compare two parsed collections.
    
    Returns dict with:
        - added: URLs in new but not old
        - removed: URLs in old but not new
        - changed: URLs with different content
        - stats: summary statistics
    """
    urls1 = set(data1.keys())
    urls2 = set(data2.keys())
    
    added = urls2 - urls1
    removed = urls1 - urls2
    common = urls1 & urls2
    
    # Find changed URLs
    changed = []
    for url in common:
        if data1[url]['hash'] != data2[url]['hash']:
            changed.append({
                'url': url,
                'domain': get_domain_category(url),
                'type': data2[url].get('type_category', 'page'),
                'size_diff': data2[url]['size'] - data1[url]['size'],
                'title': data2[url].get('title', data1[url].get('title', '')),
            })
    
    # Sort by size change
    changed.sort(key=lambda x: abs(x['size_diff']), reverse=True)
    
    return {
        'added': sorted(added),
        'removed': sorted(removed),
        'changed': changed,
        'stats': {
            'total_old': len(urls1),
            'total_new': len(urls2),
            'added_count': len(added),
            'removed_count': len(removed),
            'changed_count': len(changed),
            'unchanged_count': len(common) - len(changed),
        }
    }


def analyze_text_changes(data1, data2):
    """
    Analyze TEXT content changes only.
    Filters out formatting changes and focuses on readable content.
    """
    urls1 = set(data1.keys())
    urls2 = set(data2.keys())
    common = urls1 & urls2
    
    text_changes = []
    cloudflare_filtered = 0
    formatting_only = 0
    
    for url in common:
        # Skip if no text data
        if 'text_hash' not in data1[url] or 'text_hash' not in data2[url]:
            continue
        
        # Check if text changed
        if data1[url]['text_hash'] == data2[url]['text_hash']:
            continue
        
        title1 = data1[url].get('title', '')
        title2 = data2[url].get('title', '')
        
        # Filter Cloudflare
        if is_cloudflare_page(title1, url) or is_cloudflare_page(title2, url):
            cloudflare_filtered += 1
            continue
        
        # Get diff
        diff = get_text_diff(
            data1[url].get('text', ''),
            data2[url].get('text', '')
        )
        
        # Skip formatting-only changes
        if diff['similarity'] > SIMILARITY_THRESHOLD:
            formatting_only += 1
            continue
        
        # Skip minor changes
        if diff['added_count'] < MIN_CHANGED_LINES and diff['removed_count'] < MIN_CHANGED_LINES:
            formatting_only += 1
            continue
        
        text_changes.append({
            'url': url,
            'title': title2 or title1,
            'domain': get_domain_category(url),
            'similarity': diff['similarity'],
            'text_len_change': data2[url].get('text_len', 0) - data1[url].get('text_len', 0),
            'added': diff['added'],
            'removed': diff['removed'],
            'added_count': diff['added_count'],
            'removed_count': diff['removed_count'],
        })
    
    # Sort by similarity (lowest = most change)
    text_changes.sort(key=lambda x: x['similarity'])
    
    return {
        'text_changes': text_changes,
        'stats': {
            'total_text_changes': len(text_changes),
            'cloudflare_filtered': cloudflare_filtered,
            'formatting_only': formatting_only,
        }
    }


# =============================================================================
# REPORT GENERATION
# =============================================================================

def generate_summary_report(comparison, text_analysis, output_dir):
    """Generate main summary report."""
    report = []
    report.append("# Web Crawl Comparison Report\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Basic stats
    stats = comparison['stats']
    report.append("## Summary Statistics\n")
    report.append(f"| Metric | Count |")
    report.append(f"|--------|-------|")
    report.append(f"| Old Collection URLs | {stats['total_old']} |")
    report.append(f"| New Collection URLs | {stats['total_new']} |")
    report.append(f"| Added URLs | {stats['added_count']} |")
    report.append(f"| Removed URLs | {stats['removed_count']} |")
    report.append(f"| Changed (any) | {stats['changed_count']} |")
    report.append(f"| **Text Content Changed** | **{text_analysis['stats']['total_text_changes']}** |")
    report.append("")
    
    # Text changes stats
    ts = text_analysis['stats']
    report.append("### Text Change Filtering\n")
    report.append(f"- Cloudflare pages filtered: {ts['cloudflare_filtered']}")
    report.append(f"- Formatting-only changes: {ts['formatting_only']}")
    report.append(f"- **Real text content changes: {ts['total_text_changes']}**\n")
    
    # Changed by domain
    by_domain = defaultdict(list)
    for item in text_analysis['text_changes']:
        by_domain[item['domain']].append(item)
    
    report.append("## Text Changes by Domain\n")
    report.append(f"| Domain | Changes |")
    report.append(f"|--------|---------|")
    for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
        report.append(f"| {domain} | {len(items)} |")
    report.append("")
    
    # Write report
    output_path = output_dir / 'summary_report.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    return output_path


def generate_detailed_report(text_analysis, output_dir):
    """Generate detailed report showing actual content changes."""
    report = []
    report.append("# Detailed Text Content Changes\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append("Only pages with substantial text content changes.\n")
    
    # Group by domain
    by_domain = defaultdict(list)
    for item in text_analysis['text_changes']:
        by_domain[item['domain']].append(item)
    
    # Generate sections by domain
    for domain in sorted(by_domain.keys(), key=lambda x: -len(by_domain[x])):
        items = by_domain[domain]
        
        report.append(f"## {domain.upper()} ({len(items)})\n")
        
        for item in items[:50]:  # Limit per domain
            sim_pct = item['similarity'] * 100
            len_change = item['text_len_change']
            len_str = f"+{len_change}" if len_change > 0 else str(len_change)
            
            report.append(f"### {item['title'][:80]}\n")
            report.append(f"**URL:** `{item['url'][:120]}`\n")
            report.append(f"**Similarity:** {sim_pct:.1f}% | **Text Length:** {len_str} chars")
            report.append(f"**Lines:** +{item['added_count']}, -{item['removed_count']}\n")
            
            if item['removed']:
                report.append(f"**Removed:**")
                for line in item['removed'][:5]:
                    if line.strip():
                        report.append(f"- {line[:150]}")
                report.append("")
            
            if item['added']:
                report.append(f"**Added:**")
                for line in item['added'][:5]:
                    if line.strip():
                        report.append(f"+ {line[:150]}")
                report.append("")
        
        if len(items) > 50:
            report.append(f"\n_... and {len(items) - 50} more changes_\n")
    
    output_path = output_dir / 'detailed_changes.md'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    return output_path


def generate_json_data(comparison, text_analysis, output_dir):
    """Generate JSON data for further analysis."""
    
    # Group by domain
    by_domain = defaultdict(list)
    for item in text_analysis['text_changes']:
        by_domain[item['domain']].append({
            'url': item['url'],
            'title': item['title'],
            'similarity': round(item['similarity'] * 100, 1),
            'text_len_change': item['text_len_change'],
        })
    
    json_data = {
        'generated': datetime.now().isoformat(),
        'stats': {
            'comparison': comparison['stats'],
            'text_analysis': text_analysis['stats'],
        },
        'by_domain': {k: len(v) for k, v in by_domain.items()},
        'text_changes': text_analysis['text_changes'][:200],
    }
    
    output_path = output_dir / 'comparison_data.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    return output_path


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Compare two web archive collections',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python crawl_compare.py --old ./old_collection --new ./new_collection
  python crawl_compare.py --old ./crawls/crawl-20260315 --new ./crawls/crawl-20260316 --output ./reports
        """
    )
    parser.add_argument('--old', required=True, help='Path to old collection')
    parser.add_argument('--new', required=True, help='Path to new collection')
    parser.add_argument('--output', '-o', default='./comparison_output', help='Output directory')
    parser.add_argument('--no-text', action='store_true', help='Skip text extraction (faster)')
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("Web Crawl Comparison Tool")
    print("=" * 60)
    
    # Parse collections
    print(f"\n[1/4] Parsing OLD collection: {args.old}")
    data1 = parse_warc_collection(args.old, extract_text=not args.no_text)
    print(f"      Found {len(data1)} URLs")
    
    print(f"\n[2/4] Parsing NEW collection: {args.new}")
    data2 = parse_warc_collection(args.new, extract_text=not args.no_text)
    print(f"      Found {len(data2)} URLs")
    
    # Compare
    print("\n[3/4] Comparing collections...")
    comparison = compare_collections(data1, data2)
    
    # Analyze text changes (if text was extracted)
    if not args.no_text:
        print("      Analyzing text content changes...")
        text_analysis = analyze_text_changes(data1, data2)
    else:
        text_analysis = {'text_changes': [], 'stats': {'total_text_changes': 0, 'cloudflare_filtered': 0, 'formatting_only': 0}}
    
    # Generate reports
    print("\n[4/4] Generating reports...")
    
    summary_path = generate_summary_report(comparison, text_analysis, output_dir)
    print(f"      Summary: {summary_path}")
    
    if not args.no_text and text_analysis['text_changes']:
        detailed_path = generate_detailed_report(text_analysis, output_dir)
        print(f"      Detailed: {detailed_path}")
    
    json_path = generate_json_data(comparison, text_analysis, output_dir)
    print(f"      JSON data: {json_path}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"URLs Added:    {comparison['stats']['added_count']}")
    print(f"URLs Removed: {comparison['stats']['removed_count']}")
    print(f"URLs Changed: {comparison['stats']['changed_count']}")
    print(f"Text Changes: {text_analysis['stats']['total_text_changes']}")
    print(f"\nReports saved to: {output_dir}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
