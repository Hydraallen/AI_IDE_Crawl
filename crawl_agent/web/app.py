"""Flask web application for crawl visualization."""

from __future__ import annotations

import json
import markdown
from pathlib import Path
from flask import Flask, jsonify, render_template, send_from_directory

from crawl_agent.config import REPORTS_DIR, date_to_display

DATA_DIR = Path(__file__).resolve().parent / "static" / "data"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATES_DIR),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/dates")
    def api_dates():
        return _load_json("dates.json")

    @app.route("/api/overview")
    def api_overview():
        return _load_json("overview.json")

    @app.route("/api/timeline")
    def api_timeline():
        return _load_json("timeline.json")

    @app.route("/api/changes")
    def api_changes():
        return _load_json("changes.json")

    @app.route("/api/stats")
    def api_stats():
        return _load_json("stats.json")

    @app.route("/api/screenshots-map")
    def api_screenshots_map():
        return _load_json("screenshots.json")

    @app.route("/api/compare/<old>/<new>")
    def api_compare(old: str, new: str):
        pair_key = f"{old}_{new}"
        changes = _load_json("changes.json")
        if isinstance(changes, dict) and pair_key in changes:
            return jsonify({pair_key: changes[pair_key]})
        stats = _load_json("stats.json")
        result = {}
        if isinstance(stats, dict) and pair_key in stats:
            result["stats"] = stats[pair_key]
        if pair_key in (changes if isinstance(changes, dict) else {}):
            result["text_changes"] = changes[pair_key]
        return jsonify(result)

    @app.route("/api/trend/<domain>")
    def api_trend(domain: str):
        timeline = _load_json("timeline.json")
        if isinstance(timeline, dict):
            domains = timeline.get("domains", {})
            if domain in domains:
                return jsonify({
                    "domain": domain,
                    "dates": timeline.get("dates", []),
                    "counts": domains[domain],
                })
        return jsonify({"domain": domain, "dates": [], "counts": []})

    @app.route("/api/report/<old>/<new>")
    def api_report(old: str, new: str):
        report_name = f"{date_to_display(new)}_vs_{date_to_display(old)}.md"
        report_path = REPORTS_DIR / report_name
        if report_path.exists():
            with open(report_path) as f:
                md_content = f.read()
            html = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
            # Rewrite relative screenshot paths to /api/screenshots/
            html = html.replace('src="screenshots/', 'src="/api/screenshots/')
            html = html.replace('href="screenshots/', 'href="/api/screenshots/')
            return jsonify({"html": html, "markdown": md_content})
        return jsonify({"html": "", "markdown": ""}), 404

    @app.route("/api/screenshots/<path:filepath>")
    def api_screenshots(filepath: str):
        shots_dir = REPORTS_DIR / "screenshots"
        return send_from_directory(str(shots_dir), filepath)

    return app


def _load_json(filename: str):
    path = DATA_DIR / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return jsonify({})


def run_server(port: int = 5000, debug: bool = True) -> None:
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=debug)
