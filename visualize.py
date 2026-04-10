"""Launch the crawl visualization web server.

Usage:
    python visualize.py              # Start server (opens browser)
    python visualize.py --build-data # Rebuild JSON data first
    python visualize.py --port 8080  # Use custom port
    python visualize.py --no-browser # Don't open browser
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl Visualization Web Server")
    parser.add_argument("--build-data", action="store_true", help="Rebuild JSON data before starting")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    args = parser.parse_args()

    if args.build_data:
        from crawl_agent.web.data_builder import build_all_data
        build_all_data()

    if not args.no_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{args.port}")

    from crawl_agent.web.app import run_server
    run_server(port=args.port, debug=False)


if __name__ == "__main__":
    main()
