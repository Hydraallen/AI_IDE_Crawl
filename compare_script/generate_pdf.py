#!/usr/bin/env python3
"""
Generate PDF report of text changes using FPDF2.
"""

import json
from pathlib import Path
from datetime import datetime
from fpdf import FPDF


class TextChangePDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)
        
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, 'Web Crawl Text Changes Report', 0, 0, 'L')
        self.cell(0, 10, f'Page {self.page_no()}', 0, 1, 'R')
        self.ln(5)
    
    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}', 0, 0, 'C')


def clean_text(text):
    """Remove special characters that can't be encoded."""
    if not text:
        return ''
    # Replace common special chars
    replacements = {
        '\u2014': '-',  # em dash
        '\u2013': '-',  # en dash
        '\u2018': "'",  # left single quote
        '\u2019': "'",  # right single quote
        '\u201c': '"',  # left double quote
        '\u201d': '"',  # right double quote
        '\u2026': '...',  # ellipsis
        '\u00a0': ' ',  # non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Remove any remaining non-latin1 chars
    text = text.encode('latin-1', errors='replace').decode('latin-1')
    return text


def generate_pdf_report():
    """Generate PDF from JSON data."""
    
    script_dir = Path(__file__).parent
    reports_dir = script_dir / 'reports'
    
    # Find latest JSON
    json_files = list(reports_dir.glob('text_changes_detail_*.json'))
    if not json_files:
        print("No JSON report found!")
        return None
    
    json_file = sorted(json_files)[-1]
    pdf_file = json_file.with_suffix('.pdf')
    
    print(f"Loading: {json_file.name}")
    
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Create PDF
    pdf = TextChangePDF()
    pdf.add_page()
    
    # Title
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(26, 26, 26)
    pdf.cell(0, 15, 'Text Changes Report', 0, 1, 'C')
    
    # Date range
    pdf.set_font('Helvetica', '', 14)
    pdf.set_text_color(74, 158, 255)
    pdf.cell(0, 10, f'{data["old_date"]} -> {data["new_date"]}', 0, 1, 'C')
    
    pdf.ln(10)
    
    # Summary section
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(44, 82, 130)
    pdf.cell(0, 10, 'Summary', 0, 1, 'L')
    
    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(51, 51, 51)
    
    stats = data['stats']
    pdf.cell(0, 8, f"Total text changes: {stats['total_changes']}", 0, 1)
    pdf.cell(0, 8, f"Filtered (formatting): {stats['formatting_only']}", 0, 1)
    pdf.cell(0, 8, f"Filtered (Cloudflare): {stats['cloudflare_filtered']}", 0, 1)
    
    pdf.ln(5)
    
    # Domain breakdown
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 8, 'Changes by domain:', 0, 1)
    
    pdf.set_font('Helvetica', '', 11)
    for domain, count in sorted(stats['by_domain'].items(), key=lambda x: -x[1]):
        pdf.cell(0, 7, f"  - {domain}: {count}", 0, 1)
    
    pdf.ln(10)
    
    # Detailed changes
    pdf.set_font('Helvetica', 'B', 16)
    pdf.set_text_color(44, 82, 130)
    pdf.cell(0, 10, 'Detailed Changes', 0, 1, 'L')
    
    # Group by domain
    by_domain = {}
    for change in data['changes']:
        domain = change['domain']
        if domain not in by_domain:
            by_domain[domain] = []
        by_domain[domain].append(change)
    
    for domain in sorted(by_domain.keys(), key=lambda x: -len(by_domain[x])):
        changes = by_domain[domain]
        
        # Domain header
        pdf.set_font('Helvetica', 'B', 14)
        pdf.set_text_color(26, 54, 93)
        pdf.set_fill_color(237, 242, 247)
        pdf.cell(0, 10, f'{domain.upper()} ({len(changes)} changes)', 0, 1, 'L', fill=True)
        pdf.ln(3)
        
        for i, change in enumerate(changes, 1):
            # Check if we need a new page
            if pdf.get_y() > 240:
                pdf.add_page()
            
            # Change title
            title = clean_text(change.get('title_new') or change.get('title_old') or '(No title)')
            pdf.set_font('Helvetica', 'B', 11)
            pdf.set_text_color(45, 55, 72)
            pdf.cell(0, 8, f'{i}. {title[:100]}', 0, 1)
            
            # URL
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(66, 153, 225)
            url_short = clean_text(change['url'][:100] + '...' if len(change['url']) > 100 else change['url'])
            pdf.cell(0, 6, f'   URL: {url_short}', 0, 1)
            
            # Stats table
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(51, 51, 51)
            sim_pct = change['similarity'] * 100
            len_change = change['text_len_new'] - change['text_len_old']
            len_str = f"+{len_change}" if len_change > 0 else str(len_change)
            
            pdf.cell(0, 6, f'   Similarity: {sim_pct:.1f}% | Text length: {change["text_len_old"]} -> {change["text_len_new"]} ({len_str})', 0, 1)
            pdf.cell(0, 6, f'   Lines: +{change["added_count"]} added, -{change["removed_count"]} removed', 0, 1)
            
            # Removed content (first 5 lines)
            if change.get('removed'):
                pdf.set_font('Helvetica', 'B', 9)
                pdf.set_text_color(252, 129, 129)
                pdf.cell(0, 6, '   Removed:', 0, 1)
                
                pdf.set_font('Courier', '', 8)
                pdf.set_text_color(252, 129, 129)
                for line in change['removed'][:5]:
                    line_clean = clean_text(line[:80].replace('\n', ' '))
                    pdf.cell(0, 5, f'     - {line_clean}', 0, 1)
                if len(change['removed']) > 5:
                    pdf.cell(0, 5, f'     ... and {len(change["removed"]) - 5} more lines', 0, 1)
            
            # Added content (first 5 lines)
            if change.get('added'):
                pdf.set_font('Helvetica', 'B', 9)
                pdf.set_text_color(104, 211, 145)
                pdf.cell(0, 6, '   Added:', 0, 1)
                
                pdf.set_font('Courier', '', 8)
                pdf.set_text_color(104, 211, 145)
                for line in change['added'][:5]:
                    line_clean = clean_text(line[:80].replace('\n', ' '))
                    pdf.cell(0, 5, f'     + {line_clean}', 0, 1)
                if len(change['added']) > 5:
                    pdf.cell(0, 5, f'     ... and {len(change["added"]) - 5} more lines', 0, 1)
            
            pdf.ln(5)
        
        pdf.ln(5)
    
    # Save PDF
    pdf.output(str(pdf_file))
    
    print(f"PDF saved: {pdf_file}")
    print(f"Size: {pdf_file.stat().st_size / 1024:.1f} KB")
    
    return pdf_file


if __name__ == '__main__':
    pdf_path = generate_pdf_report()
    if pdf_path:
        print(f"\nPDF Report: {pdf_path}")
