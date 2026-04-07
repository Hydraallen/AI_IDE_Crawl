#!/usr/bin/env python3
"""
Compare two web crawls (WARC/WACZ) and report differences.

Compares:
1. URL lists - new/removed pages
2. Content changes - same URL, different content
3. Statistics summary
"""

import os
import sys
import gzip
import hashlib
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from urllib.parse import urlparse

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
        return ''
    
    # Only parse HTML content
    if 'text/html' in content_type or not content_type:
        try:
            soup = BeautifulSoup(content, 'lxml')
            # Remove script and style elements
            for element in soup(['script', 'style', 'noscript']):
                element.decompose()
            return soup.get_text(separator=' ', strip=True)
        except Exception:
            pass
    
    # Return raw content for non-HTML
    if isinstance(content, bytes):
        return content.decode('utf-8', errors='ignore')
    return str(content)


def parse_warc_files(collection_path):
    """
    Parse all WARC files in a collection and extract URL -> content mapping.
    
    Returns:
        dict: {url: {'hash': str, 'size': int, 'content_type': str, 'timestamp': str}}
    """
    archive_path = Path(collection_path) / 'archive'
    if not archive_path.exists():
        print(f"  Warning: No archive folder found in {collection_path}")
        return {}
    
    url_data = {}
    warc_files = list(archive_path.glob('*.warc.gz'))
    
    print(f"  Found {len(warc_files)} WARC files")
    
    for warc_file in warc_files:
        try:
            with gzip.open(warc_file, 'rb') as stream:
                for record in ArchiveIterator(stream):
                    url = get_url_from_warc_record(record)
                    if url:
                        content = record.content_stream().read()
                        content_type = record.http_headers.get_header('Content-Type', '') if record.http_headers else ''
                        timestamp = record.rec_headers.get_header('WARC-Date', '')
                        
                        url_data[url] = {
                            'hash': get_content_hash(content),
                            'size': len(content),
                            'content_type': content_type,
                            'timestamp': timestamp,
                            'text': extract_text_content(content, content_type)[:1000]  # Store first 1000 chars
                        }
        except Exception as e:
            print(f"  Error reading {warc_file.name}: {e}")
    
    return url_data


def parse_cdx_files(collection_path):
    """
    Parse CDX index files for quick URL listing.
    
    Returns:
        set: URLs in the collection
    """
    cdx_path = Path(collection_path) / 'warc-cdx'
    if not cdx_path.exists():
        return set()
    
    urls = set()
    cdx_files = list(cdx_path.glob('*.cdx'))
    
    for cdx_file in cdx_files:
        try:
            with open(cdx_file, 'r') as f:
                for line in f:
                    parts = line.strip().split(' ')
                    if len(parts) >= 2:
                        urls.add(parts[0])  # URL is typically first field
        except Exception as e:
            print(f"  Error reading CDX {cdx_file.name}: {e}")
    
    return urls


def compare_collections(data1, data2, name1, name2):
    """
    Compare two collections and return differences.
    
    Returns:
        dict: Comparison results
    """
    urls1 = set(data1.keys())
    urls2 = set(data2.keys())
    
    # URL differences
    added_urls = urls2 - urls1
    removed_urls = urls1 - urls2
    common_urls = urls1 & urls2
    
    # Content changes in common URLs
    changed_urls = []
    unchanged_urls = []
    
    for url in common_urls:
        if data1[url]['hash'] != data2[url]['hash']:
            changed_urls.append({
                'url': url,
                'old_size': data1[url]['size'],
                'new_size': data2[url]['size'],
                'old_timestamp': data1[url]['timestamp'],
                'new_timestamp': data2[url]['timestamp']
            })
        else:
            unchanged_urls.append(url)
    
    return {
        'added': sorted(added_urls),
        'removed': sorted(removed_urls),
        'changed': changed_urls,
        'unchanged': unchanged_urls,
        'stats': {
            'total_1': len(urls1),
            'total_2': len(urls2),
            'added_count': len(added_urls),
            'removed_count': len(removed_urls),
            'changed_count': len(changed_urls),
            'unchanged_count': len(unchanged_urls)
        }
    }


def generate_report(results, name1, name2, output_path=None):
    """Generate a markdown report of the comparison."""
    report = []
    report.append(f"# Crawl Comparison Report\n")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append(f"**Collections:** `{name1}` vs `{name2}`\n")
    
    # Summary statistics
    stats = results['stats']
    report.append(f"## Summary Statistics\n")
    report.append(f"| Metric | {name1} | {name2} |")
    report.append(f"|--------|--------|--------|")
    report.append(f"| Total URLs | {stats['total_1']} | {stats['total_2']} |")
    report.append(f"")
    report.append(f"| Change Type | Count |")
    report.append(f"|-------------|-------|")
    report.append(f"| Added URLs | {stats['added_count']} |")
    report.append(f"| Removed URLs | {stats['removed_count']} |")
    report.append(f"| Changed Content | {stats['changed_count']} |")
    report.append(f"| Unchanged | {stats['unchanged_count']} |")
    report.append(f"")
    
    # Added URLs
    if results['added']:
        report.append(f"## Added URLs ({len(results['added'])})\n")
        for url in results['added'][:50]:  # Limit to 50
            report.append(f"- {url}")
        if len(results['added']) > 50:
            report.append(f"\n_... and {len(results['added']) - 50} more_")
        report.append(f"")
    
    # Removed URLs
    if results['removed']:
        report.append(f"## Removed URLs ({len(results['removed'])})\n")
        for url in results['removed'][:50]:
            report.append(f"- {url}")
        if len(results['removed']) > 50:
            report.append(f"\n_... and {len(results['removed']) - 50} more_")
        report.append(f"")
    
    # Changed content
    if results['changed']:
        report.append(f"## Changed Content ({len(results['changed'])})\n")
        for item in results['changed'][:30]:
            size_diff = item['new_size'] - item['old_size']
            size_str = f"+{size_diff}" if size_diff > 0 else str(size_diff)
            report.append(f"- **{item['url']}**")
            report.append(f"  - Size: {item['old_size']} → {item['new_size']} bytes ({size_str})")
        if len(results['changed']) > 30:
            report.append(f"\n_... and {len(results['changed']) - 30} more_")
        report.append(f"")
    
    report_text = '\n'.join(report)
    
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"\nReport saved to: {output_path}")
    
    return report_text


def main():
    parser = argparse.ArgumentParser(description='Compare two web crawl collections')
    parser.add_argument('collection1', help='Path to first collection (older)')
    parser.add_argument('collection2', help='Path to second collection (newer)')
    parser.add_argument('-o', '--output', help='Output report file (markdown)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    print(f"Parsing collection 1: {args.collection1}")
    data1 = parse_warc_files(args.collection1)
    print(f"  Found {len(data1)} URLs\n")
    
    print(f"Parsing collection 2: {args.collection2}")
    data2 = parse_warc_files(args.collection2)
    print(f"  Found {len(data2)} URLs\n")
    
    print("Comparing collections...")
    results = compare_collections(data1, data2, 
                                   Path(args.collection1).name,
                                   Path(args.collection2).name)
    
    # Print summary
    stats = results['stats']
    print(f"\n{'='*50}")
    print("COMPARISON RESULTS")
    print(f"{'='*50}")
    print(f"Collection 1 URLs: {stats['total_1']}")
    print(f"Collection 2 URLs: {stats['total_2']}")
    print(f"Added URLs:        {stats['added_count']}")
    print(f"Removed URLs:      {stats['removed_count']}")
    print(f"Changed Content:   {stats['changed_count']}")
    print(f"Unchanged:         {stats['unchanged_count']}")
    
    # Generate report
    output_path = args.output or 'comparison_report.md'
    report_path = Path(output_path)
    
    # If relative path, save in compare_script directory
    if not report_path.is_absolute():
        script_dir = Path(__file__).parent
        report_path = script_dir / output_path
    
    generate_report(results,
                    Path(args.collection1).name,
                    Path(args.collection2).name,
                    report_path)
    
    return results


if __name__ == '__main__':
    main()
