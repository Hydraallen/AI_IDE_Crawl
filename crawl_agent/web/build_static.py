"""Build a static site for GitHub Pages deployment.

Reads pre-built JSON data + markdown reports + screenshots,
produces a self-contained static site under docs/ that can be
deployed directly to GitHub Pages.

Usage:
    .venv/bin/python crawl_agent/web/build_static.py
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
DATA_DIR = Path(__file__).resolve().parent / "static" / "data"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "index.html"
OUTPUT_DIR = PROJECT_ROOT / "docs"

# Screenshot compression settings
SCREENSHOT_MAX_WIDTH = 800
SCREENSHOT_QUALITY = 60  # JPEG quality


def build_static() -> None:
    if not DATA_DIR.exists():
        print("ERROR: No pre-built data found. Run data_builder first:")
        print("  .venv/bin/python visualize.py --build-data")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Embed reports into reports.json
    print("Embedding markdown reports...")
    reports_data = _build_reports_json()
    _write_json(OUTPUT_DIR / "reports.json", reports_data)

    # 2. Copy data JSON files
    print("Copying data files...")
    data_out = OUTPUT_DIR / "data"
    data_out.mkdir(exist_ok=True)
    for f in DATA_DIR.glob("*.json"):
        shutil.copy2(f, data_out / f.name)

    # 3. Compress and copy screenshots
    print("Compressing screenshots...")
    shots_out = OUTPUT_DIR / "screenshots"
    if shots_out.exists():
        shutil.rmtree(shots_out)
    shot_count = _compress_screenshots(shots_out)
    print(f"  {shot_count} screenshots compressed")

    # 4. Update screenshots.json paths (now relative to docs/)
    _update_screenshot_paths(data_out / "screenshots.json")

    # 5. Generate static index.html
    print("Generating static index.html...")
    _generate_static_html(OUTPUT_DIR / "index.html")

    # 6. Copy CSS
    css_src = Path(__file__).resolve().parent / "static" / "css" / "style.css"
    css_out = OUTPUT_DIR / "css"
    css_out.mkdir(exist_ok=True)
    if css_src.exists():
        shutil.copy2(css_src, css_out / "style.css")

    # Summary
    total_size = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file())
    print(f"\nStatic site built at {OUTPUT_DIR}/")
    print(f"Total size: {total_size / 1024 / 1024:.1f} MB")


def _build_reports_json() -> dict[str, str]:
    """Read all markdown reports and convert to HTML."""
    import markdown

    reports: dict[str, str] = {}
    if not REPORTS_DIR.exists():
        return reports

    for md_file in sorted(REPORTS_DIR.glob("*.md")):
        pair_label = md_file.stem  # e.g., "2026-03-16_vs_2026-03-15"
        with open(md_file) as f:
            md_content = f.read()

        html = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
        # Rewrite screenshot paths to relative
        html = html.replace('src="screenshots/', 'src="screenshots/')
        reports[pair_label] = html

    print(f"  Embedded {len(reports)} reports")
    return reports


def _compress_screenshots(output_dir: Path) -> int:
    """Compress screenshots using sips (macOS built-in) and convert to JPEG."""
    shots_dir = REPORTS_DIR / "screenshots"
    if not shots_dir.exists():
        return 0

    count = 0
    for pair_dir in sorted(shots_dir.iterdir()):
        if not pair_dir.is_dir():
            continue
        for domain_dir in sorted(pair_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            for png in sorted(domain_dir.glob("*.png")):
                rel = png.relative_to(shots_dir)
                # Change extension to .jpg
                jpg_rel = rel.with_suffix(".jpg")
                out_path = output_dir / jpg_rel
                out_path.parent.mkdir(parents=True, exist_ok=True)

                # Use sips to resize and convert to JPEG
                try:
                    subprocess.run(
                        [
                            "sips",
                            "-Z", str(SCREENSHOT_MAX_WIDTH),
                            "-s", "format", "jpeg",
                            "-s", "formatOptions", str(SCREENSHOT_QUALITY),
                            str(png),
                            "--out", str(out_path),
                        ],
                        capture_output=True,
                        timeout=30,
                    )
                    count += 1
                except Exception as e:
                    # Fallback: just copy as-is
                    shutil.copy2(png, out_path.with_suffix(".png"))
                    count += 1

    return count


def _update_screenshot_paths(screenshots_json: Path) -> None:
    """Update screenshot paths from .png to .jpg in screenshots.json."""
    if not screenshots_json.exists():
        return

    with open(screenshots_json) as f:
        data = json.load(f)

    for pair_label, entries in data.items():
        for entry in entries:
            # Change .png to .jpg in path
            entry["path"] = entry["path"].replace(".png", ".jpg")

    with open(screenshots_json, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def _generate_static_html(output_path: Path) -> None:
    """Generate a self-contained index.html that loads data from relative paths."""
    with open(TEMPLATE) as f:
        html = f.read()

    # Replace Flask template tags
    html = html.replace('{{ url_for(\'static\', filename=\'css/style.css\') }}', 'css/style.css')

    # Replace all /api/ fetch calls with relative file paths
    replacements = {
        "fetch('/api/overview')": "fetch('data/overview.json')",
        "fetch('/api/timeline')": "fetch('data/timeline.json')",
        "fetch('/api/changes')": "fetch('data/changes.json')",
        "fetch('/api/stats')": "fetch('data/stats.json')",
        "fetch('/api/dates')": "fetch('data/dates.json')",
        "fetch('/api/screenshots-map')": "fetch('data/screenshots.json')",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)

    # Replace the report fetch to read from reports.json (pre-loaded)
    html = html.replace(
        "const resp = await fetch(`/api/report/${old_d}/${new_d}`);\n    if (resp.ok) {\n      const data = await resp.json();\n      document.getElementById('reportContent').innerHTML = data.html || '<p class=\"text-gray-400\">No report available.</p>';\n    } else {\n      document.getElementById('reportContent').innerHTML = '<p class=\"text-gray-400\">Report not found.</p>';\n    }",
        "const pairLabel = `${new_d.substring(0,4)}-${new_d.substring(4,6)}-${new_d.substring(6)}_vs_${old_d.substring(0,4)}-${old_d.substring(4,6)}-${old_d.substring(6)}`;\n    document.getElementById('reportContent').innerHTML = reportsData[pairLabel] || '<p class=\"text-gray-400\">No report available.</p>';"
    )

    # Replace screenshot URL construction
    html = html.replace(
        "`/api/screenshots/${s.path}`",
        "`screenshots/${s.path}`"
    )

    # Add reports data preload: declare global + load in init()
    html = html.replace(
        "async function init() {",
        "let reportsData = null;\n\nasync function init() {"
    )
    # After Promise.all resolves, add reports loading
    html = html.replace(
        "  ]);\n  overviewData = ov;",
        "  ]);\n  const rp = await fetch('reports.json').then(r => r.json());\n  reportsData = rp;\n  overviewData = ov;"
    )

    with open(output_path, "w") as f:
        f.write(html)


def _write_json(path: Path, data: object) -> None:
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    build_static()
