#!/usr/bin/env python3
"""
Convert text changes report to PDF.
"""

import markdown2
from weasyprint import HTML, CSS
from pathlib import Path
from datetime import datetime

def convert_markdown_to_pdf():
    """Convert markdown report to PDF."""
    
    # Paths
    script_dir = Path(__file__).parent
    reports_dir = script_dir / 'reports'
    
    # Find the latest detail report
    md_files = list(reports_dir.glob('text_changes_detail_*.md'))
    if not md_files:
        print("No detail report found!")
        return None
    
    # Use the latest one
    md_file = sorted(md_files)[-1]
    pdf_file = md_file.with_suffix('.pdf')
    
    print(f"Converting: {md_file.name}")
    
    # Read markdown
    with open(md_file, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # Convert to HTML
    html_content = markdown2.markdown(
        md_content,
        extras=['tables', 'fenced-code-blocks', 'code-friendly']
    )
    
    # Wrap in full HTML document with styling
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                font-size: 11pt;
                line-height: 1.5;
                color: #333;
            }}
            h1 {{
                font-size: 24pt;
                color: #1a1a1a;
                border-bottom: 2px solid #4a9eff;
                padding-bottom: 10px;
                margin-top: 30px;
            }}
            h2 {{
                font-size: 18pt;
                color: #2c5282;
                margin-top: 25px;
                page-break-after: avoid;
            }}
            h3 {{
                font-size: 14pt;
                color: #1a365d;
                margin-top: 20px;
                page-break-after: avoid;
            }}
            h4 {{
                font-size: 12pt;
                color: #2d3748;
                margin-top: 15px;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 15px 0;
                font-size: 10pt;
                page-break-inside: avoid;
            }}
            th, td {{
                border: 1px solid #cbd5e0;
                padding: 8px 12px;
                text-align: left;
            }}
            th {{
                background-color: #edf2f7;
                font-weight: bold;
                color: #2d3748;
            }}
            tr:nth-child(even) {{
                background-color: #f7fafc;
            }}
            code {{
                font-family: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
                font-size: 9pt;
                background-color: #edf2f7;
                padding: 2px 5px;
                border-radius: 3px;
            }}
            pre {{
                background-color: #1a202c;
                color: #e2e8f0;
                padding: 12px;
                border-radius: 5px;
                overflow-x: auto;
                font-size: 9pt;
                line-height: 1.4;
                page-break-inside: avoid;
            }}
            pre code {{
                background-color: transparent;
                padding: 0;
            }}
            .diff-deleted {{
                color: #fc8181;
            }}
            .diff-added {{
                color: #68d391;
            }}
            strong {{
                color: #1a202c;
            }}
            hr {{
                border: none;
                border-top: 1px solid #e2e8f0;
                margin: 20px 0;
            }}
            p {{
                margin: 10px 0;
            }}
            a {{
                color: #4299e1;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """
    
    # Convert to PDF
    print("Generating PDF...")
    html = HTML(string=full_html)
    html.write_pdf(pdf_file)
    
    print(f"✅ PDF saved: {pdf_file}")
    print(f"   Size: {pdf_file.stat().st_size / 1024:.1f} KB")
    
    return pdf_file


if __name__ == '__main__':
    pdf_path = convert_markdown_to_pdf()
    if pdf_path:
        print(f"\nPDF report generated: {pdf_path}")
