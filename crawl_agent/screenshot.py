"""Screenshot module — capture before/after WARC-archived pages.

For every changed page, captures TWO screenshots:
  - {filename}_old.png  (the earlier crawl date)
  - {filename}_new.png  (the later crawl date)

Directory layout:
    reports/
        screenshots/
            2026-03-16_vs_2026-03-15/
                cursor.com/
                    pricing_old.png
                    pricing_new.png
                docs.openclaw.ai/
                    gateway_sandboxing_old.png
                    gateway_sandboxing_new.png
"""

import re
import threading
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import urlparse, quote

from playwright.sync_api import sync_playwright

from crawl_agent.config import REPORTS_DIR, date_to_display

_VIEWER_PORT = 8091
_VIEWER_READY = threading.Event()


def _start_viewer_server() -> None:
    """Start warc_viewer in a daemon thread."""
    import socket
    from crawl_agent.warc_viewer import WARCViewerHandler

    # Check if port already in use (viewer running from previous session)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", _VIEWER_PORT)) == 0:
            _VIEWER_READY.set()
            return

    server = HTTPServer(("127.0.0.1", _VIEWER_PORT), WARCViewerHandler)
    server.daemon_threads = True
    _VIEWER_READY.set()
    server.serve_forever()


def _ensure_viewer() -> None:
    """Start the viewer server if not already running."""
    if _VIEWER_READY.is_set():
        return
    t = threading.Thread(target=_start_viewer_server, daemon=True)
    t.start()
    _VIEWER_READY.wait(timeout=10)


def _sanitize_filename(url: str) -> str:
    """Convert a URL to a safe filename stem."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").rstrip("/")
    if not path:
        path = "_root"
    name = re.sub(r"[^\w\-.]", "_", path)
    if len(name) > 80:
        name = name[:80]
    return name


def _screenshot_dir(old_date: str, new_date: str) -> Path:
    """Return the screenshot directory for a date pair."""
    pair_label = f"{date_to_display(new_date)}_vs_{date_to_display(old_date)}"
    d = REPORTS_DIR / "screenshots" / pair_label
    d.mkdir(parents=True, exist_ok=True)
    return d


def _screenshot_page(context, url: str, output_path: Path) -> bool:
    """Navigate to a URL and take a full-page screenshot. Returns True on success."""
    page = context.new_page()
    try:
        resp = page.goto(url, wait_until="networkidle", timeout=30000)
        if resp and resp.status >= 400:
            page.close()
            return False
        page.wait_for_timeout(1000)
        page.screenshot(path=str(output_path), full_page=True)
        return True
    except Exception:
        return False
    finally:
        page.close()


ScreenshotPair = tuple[Path | None, Path | None]


def capture_screenshots(
    text_changes: list[dict],
    old_date: str,
    new_date: str,
    max_screenshots: int = 15,
) -> dict[str, ScreenshotPair]:
    """Capture old + new screenshots for the most significant page changes.

    Returns:
        Mapping of url -> (old_path, new_path). Either path may be None
        if that version wasn't available in the WARC.
    """
    if not text_changes:
        return {}

    _ensure_viewer()
    shot_dir = _screenshot_dir(old_date, new_date)
    base_url = f"http://127.0.0.1:{_VIEWER_PORT}"

    # Pre-build CSS/JS resource caches so subresources can be served
    from crawl_agent.warc_viewer import ensure_resource_cache
    print(f"    Building resource cache for {old_date}...")
    ensure_resource_cache(old_date)
    print(f"    Building resource cache for {new_date}...")
    ensure_resource_cache(new_date)

    ranked = sorted(text_changes, key=lambda c: c.get("similarity", 1.0))
    targets = ranked[:max_screenshots]

    results: dict[str, ScreenshotPair] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

        for change in targets:
            url = change.get("url", "")
            if not url:
                continue

            domain = urlparse(url).netloc
            domain_dir = shot_dir / re.sub(r"[^\w\-.]", "_", domain)
            domain_dir.mkdir(parents=True, exist_ok=True)

            filename = _sanitize_filename(url)
            old_path = domain_dir / f"{filename}_old.png"
            new_path = domain_dir / f"{filename}_new.png"

            old_ok = False
            new_ok = False

            # Screenshot OLD version
            try:
                old_ok = _screenshot_page(
                    context,
                    f"{base_url}/api/page?date={old_date}&url={quote(url, safe='')}",
                    old_path,
                )
            except Exception as e:
                print(f"    Old screenshot failed for {url}: {e}")

            # Screenshot NEW version
            try:
                new_ok = _screenshot_page(
                    context,
                    f"{base_url}/api/page?date={new_date}&url={quote(url, safe='')}",
                    new_path,
                )
            except Exception as e:
                print(f"    New screenshot failed for {url}: {e}")

            if old_ok or new_ok:
                results[url] = (
                    old_path if old_ok else None,
                    new_path if new_ok else None,
                )
                print(f"    Screenshot: {domain}/{filename} (old={'OK' if old_ok else 'N/A'} new={'OK' if new_ok else 'N/A'})")

            # Clean up files for completely failed captures
            if not old_ok and old_path.exists():
                old_path.unlink()
            if not new_ok and new_path.exists():
                new_path.unlink()

        browser.close()

    return results


def build_screenshot_section(
    screenshots: dict[str, ScreenshotPair],
    text_changes: list[dict],
) -> str:
    """Build markdown with side-by-side old vs new screenshots."""
    if not screenshots:
        return ""

    url_meta: dict[str, dict] = {}
    for change in text_changes:
        url_meta[change.get("url", "")] = change

    lines = ["## Screenshots\n"]

    from urllib.parse import urlparse
    domain_groups: dict[str, list[str]] = {}
    for url in screenshots:
        domain = urlparse(url).netloc
        domain_groups.setdefault(domain, []).append(url)

    for domain, urls in domain_groups.items():
        lines.append(f"### {domain}\n")
        for url in urls:
            meta = url_meta.get(url, {})
            title = meta.get("title", url)
            sim = meta.get("similarity", 1.0)
            old_path, new_path = screenshots[url]

            lines.append(f"**{title}** (similarity: {sim:.2f})")
            lines.append(f"URL: `{url}`\n")

            # Build side-by-side comparison
            if old_path and new_path:
                old_rel = old_path.relative_to(REPORTS_DIR)
                new_rel = new_path.relative_to(REPORTS_DIR)
                lines.append("| Before | After |")
                lines.append("|--------|-------|")
                lines.append(f"| ![{title} (before)]({old_rel}) | ![{title} (after)]({new_rel}) |")
            elif new_path:
                new_rel = new_path.relative_to(REPORTS_DIR)
                lines.append(f"*After:*\n")
                lines.append(f"![{title} (after)]({new_rel})")
            elif old_path:
                old_rel = old_path.relative_to(REPORTS_DIR)
                lines.append(f"*Before (page removed):*\n")
                lines.append(f"![{title} (before)]({old_rel})")

            lines.append("")

    return "\n".join(lines)
