"""Lightweight local WARC viewer — browse crawled web pages in your browser.

Usage:
    source .venv/bin/activate
    python crawl_agent/warc_viewer.py                  # serve all dates on port 8090
    python crawl_agent/warc_viewer.py --port 9000       # custom port
    python crawl_agent/warc_viewer.py --date 20260315   # single date
"""

import argparse
import gzip
import html
import io
import json
import mimetypes
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from warcio import ArchiveIterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLLECTIONS_DIR = PROJECT_ROOT / "crawls" / "collections"


def _warc_files(date_str: str) -> list[Path]:
    """Get all WARC.gz files for a date."""
    archive_dir = COLLECTIONS_DIR / f"crawl-{date_str}" / "archive"
    if not archive_dir.exists():
        return []
    return sorted(archive_dir.glob("*.warc.gz"))


def list_urls_for_date(date_str: str) -> list[dict]:
    """List all URLs and their metadata from a date's WARC files."""
    urls: list[dict] = []
    seen: set[str] = set()
    for warc_path in _warc_files(date_str):
        with gzip.open(str(warc_path), "rb") as stream:
            for record in ArchiveIterator(stream):
                if record.rec_type != "response":
                    continue
                url = record.rec_headers.get_header("WARC-Target-URI", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                http_headers = record.http_headers
                content_type = ""
                content_length = 0
                if http_headers:
                    content_type = http_headers.get_header("Content-Type", "")
                    content_length = int(http_headers.get_header("Content-Length", "0") or "0")
                payload = record.content_stream().read()
                actual_len = len(payload)
                urls.append({
                    "url": url,
                    "content_type": content_type.split(";")[0].strip(),
                    "content_length": actual_len,
                    "date": date_str,
                })
    return urls


def get_page_content(date_str: str, target_url: str) -> tuple[bytes, str] | None:
    """Get raw content and content-type for a URL from a date's WARC files."""
    for warc_path in _warc_files(date_str):
        with gzip.open(str(warc_path), "rb") as stream:
            for record in ArchiveIterator(stream):
                if record.rec_type != "response":
                    continue
                url = record.rec_headers.get_header("WARC-Target-URI", "")
                if url == target_url:
                    content_type = "application/octet-stream"
                    if record.http_headers:
                        ct = record.http_headers.get_header("Content-Type", "")
                        if ct:
                            content_type = ct.split(";")[0].strip()
                    payload = record.content_stream().read()
                    return payload, content_type
    return None


def get_available_dates() -> list[str]:
    """List available crawl dates."""
    if not COLLECTIONS_DIR.exists():
        return []
    dates: list[str] = []
    for d in COLLECTIONS_DIR.iterdir():
        if d.is_dir() and d.name.startswith("crawl-"):
            date_str = d.name.replace("crawl-", "")
            if date_str.isdigit() and len(date_str) == 8:
                dates.append(date_str)
    return sorted(dates)


_cache_lock = threading.Lock()
_url_cache: dict[str, list[dict]] = {}

# CSS/JS resource cache: date -> {url: (content_bytes, content_type)}
_resource_cache: dict[str, dict[str, tuple[bytes, str]]] = {}

_RESOURCE_TYPES = frozenset({
    "text/css", "text/javascript", "application/javascript",
    "application/x-javascript",
})

_MAX_RESOURCE_SIZE = 2_000_000  # 2MB per file


def _build_resource_cache(date_str: str) -> None:
    """Build CSS/JS resource cache for a date by scanning WARC files."""
    with _cache_lock:
        if date_str in _resource_cache:
            return

    resources: dict[str, tuple[bytes, str]] = {}
    for warc_path in _warc_files(date_str):
        with gzip.open(str(warc_path), "rb") as stream:
            for record in ArchiveIterator(stream):
                if record.rec_type != "response":
                    continue
                url = record.rec_headers.get_header("WARC-Target-URI", "")
                if not url:
                    continue
                content_type = ""
                if record.http_headers:
                    ct = record.http_headers.get_header("Content-Type", "")
                    content_type = ct.split(";")[0].strip()
                if content_type in _RESOURCE_TYPES:
                    payload = record.content_stream().read()
                    if len(payload) <= _MAX_RESOURCE_SIZE:
                        resources[url] = (payload, content_type)

    with _cache_lock:
        _resource_cache[date_str] = resources
    print(f"    Resource cache built for {date_str}: {len(resources)} CSS/JS files")


def ensure_resource_cache(date_str: str) -> None:
    """Public API: build resource cache for a date."""
    _build_resource_cache(date_str)


def _get_urls_cached(date_str: str) -> list[dict]:
    with _cache_lock:
        if date_str not in _url_cache:
            _url_cache[date_str] = list_urls_for_date(date_str)
        return _url_cache[date_str]


class WARCViewerHandler(BaseHTTPRequestHandler):
    """HTTP handler for WARC viewer."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "":
            self._serve_index(params.get("date", [get_available_dates()[-1]])[0])
        elif path == "/api/dates":
            self._serve_json(get_available_dates())
        elif path == "/api/urls":
            date_str = params.get("date", [""])[0]
            if not date_str:
                self._serve_json({"error": "date parameter required"}, 400)
                return
            urls = _get_urls_cached(date_str)
            self._serve_json(urls)
        elif path == "/api/page":
            date_str = params.get("date", [""])[0]
            url = params.get("url", [""])[0]
            if not date_str or not url:
                self._serve_json({"error": "date and url parameters required"}, 400)
                return
            result = get_page_content(date_str, url)
            if result is None:
                self._serve_json({"error": "Page not found in WARC"}, 404)
                return
            content, content_type = result
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        elif path == "/view":
            date_str = params.get("date", [""])[0]
            url = params.get("url", [""])[0]
            if not date_str or not url:
                self._serve_json({"error": "date and url required"}, 400)
                return
            self._serve_viewer(date_str, url)
        else:
            # Try to serve subresource (CSS/JS) using Referer header
            referer = self.headers.get("Referer", "")
            if "/api/page" in referer:
                ref_params = parse_qs(urlparse(referer).query)
                ref_date = ref_params.get("date", [""])[0]
                ref_url = ref_params.get("url", [""])[0]
                if ref_date and ref_url:
                    origin = f"{urlparse(ref_url).scheme}://{urlparse(ref_url).netloc}"
                    full_url = f"{origin}{path}"
                    if parsed.query:
                        full_url += f"?{parsed.query}"
                    # Look up in resource cache
                    cache = _resource_cache.get(ref_date, {})
                    if full_url in cache:
                        content, content_type = cache[full_url]
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(content)))
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(content)
                        return
            self.send_error(404)

    def _serve_json(self, data: object, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_index(self, date_str: str) -> None:
        dates = get_available_dates()
        date_options = "\n".join(
            f'<option value="{d}" {"selected" if d == date_str else ""}>{d[:4]}-{d[4:6]}-{d[6:8]}</option>'
            for d in dates
        )
        page = f"""<!DOCTYPE html>
<html><head><title>WARC Viewer - AI Coding Tools Web Archive</title>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: #eee; }}
h1 {{ color: #e94560; }}
.controls {{ display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }}
select, button, input {{ padding: 8px 14px; border-radius: 6px; border: 1px solid #444; background: #16213e; color: #eee; font-size: 14px; }}
button {{ cursor: pointer; background: #e94560; border: none; font-weight: bold; }}
button:hover {{ background: #c73652; }}
.stats {{ color: #aaa; font-size: 13px; margin-bottom: 12px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ text-align: left; padding: 8px; background: #16213e; color: #e94560; position: sticky; top: 0; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #333; font-size: 13px; }}
tr:hover {{ background: #16213e; }}
a {{ color: #4ea8de; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
.html {{ background: #1b4332; color: #95d5b2; }}
.json {{ background: #3c1642; color: #e0aaff; }}
.css {{ background: #2d6a4f; color: #b7e4c7; }}
.js {{ background: #5a189a; color: #e0aaff; }}
.img {{ background: #6b2737; color: #ffb4a2; }}
.other {{ background: #444; color: #ccc; }}
#search {{ width: 300px; }}
iframe {{ width: 100%; height: 80vh; border: 1px solid #444; border-radius: 8px; margin-top: 12px; }}
</style>
</head><body>
<h1>AI Coding Tools WARC Viewer</h1>
<div class="controls">
  <label>Date:</label>
  <select id="dateSelect">{date_options}</select>
  <input id="search" type="text" placeholder="Filter URLs...">
  <button onclick="loadUrls()">Load</button>
  <span class="stats" id="stats"></span>
</div>
<table>
  <thead><tr><th>URL</th><th>Type</th><th>Size</th></tr></thead>
  <tbody id="urlTable"></tbody>
</table>
<script>
const dateSelect = document.getElementById('dateSelect');
const search = document.getElementById('search');
const urlTable = document.getElementById('urlTable');
const stats = document.getElementById('stats');
let allUrls = [];

async function loadUrls() {{
  const date = dateSelect.value;
  stats.textContent = 'Loading...';
  const resp = await fetch('/api/urls?date=' + date);
  allUrls = await resp.json();
  stats.textContent = allUrls.length + ' URLs';
  renderUrls();
}}

function renderUrls() {{
  const q = search.value.toLowerCase();
  const filtered = q ? allUrls.filter(u => u.url.toLowerCase().includes(q)) : allUrls;
  urlTable.innerHTML = filtered.map(u => {{
    const typeClass = u.content_type.includes('html') ? 'html'
      : u.content_type.includes('json') ? 'json'
      : u.content_type.includes('css') ? 'css'
      : u.content_type.includes('javascript') ? 'js'
      : u.content_type.includes('image') ? 'img' : 'other';
    const size = u.content_length > 1024 ? (u.content_length/1024).toFixed(1)+'KB' : u.content_length+'B';
    const date = dateSelect.value;
    const viewUrl = '/view?date='+date+'&url='+encodeURIComponent(u.url);
    const isHtml = u.content_type.includes('html');
    return '<tr><td><a href="'+(isHtml ? viewUrl : '/api/page?date='+date+'&url='+encodeURIComponent(u.url))+'" target="_blank">'+u.url+'</a></td>'
      +'<td><span class="badge '+typeClass+'">'+u.content_type+'</span></td>'
      +'<td>'+size+'</td></tr>';
  }}).join('');
}}

search.addEventListener('input', renderUrls);
loadUrls();
</script>
</body></html>"""
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_viewer(self, date_str: str, url: str) -> None:
        """Serve a page viewer with content in an iframe."""
        encoded_url = html.escape(url, quote=True)
        page = f"""<!DOCTYPE html>
<html><head><title>WARC Viewer - {encoded_url}</title>
<style>
body {{ margin: 0; font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; }}
.info {{ padding: 10px 16px; background: #16213e; border-bottom: 1px solid #444; font-size: 13px; }}
.info a {{ color: #4ea8de; }}
iframe {{ width: 100%; height: calc(100vh - 50px); border: none; }}
</style>
</head><body>
<div class="info">
  <strong>Date:</strong> {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} |
  <strong>URL:</strong> <a href="{encoded_url}" target="_blank">{encoded_url}</a>
</div>
<iframe src="/api/page?date={date_str}&url={encodeURIComponent(url)}"></iframe>
</body></html>"""
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:
        print(f"  {args[0]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local WARC Viewer for AI Coding Tools Web Archive")
    parser.add_argument("--port", type=int, default=8090, help="Port to serve on (default: 8090)")
    parser.add_argument("--date", help="Pre-select a specific date (YYYYMMDD)")
    args = parser.parse_args()

    dates = get_available_dates()
    if not dates:
        print("No crawl data found in crawls/collections/")
        sys.exit(1)

    print(f"AI Coding Tools WARC Viewer — {len(dates)} dates available")
    print(f"  From: {dates[0]} to {dates[-1]}")
    print(f"  URL list will be cached after first load per date")
    print(f"\n  Open http://localhost:{args.port} in your browser\n")

    server = HTTPServer(("0.0.0.0", args.port), WARCViewerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
