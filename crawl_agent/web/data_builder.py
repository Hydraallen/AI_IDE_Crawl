"""Pre-build JSON data files for the visualization frontend."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from crawl_agent.config import (
    CACHE_DIR,
    REPORTS_DIR,
    date_to_display,
    get_available_dates,
    get_consecutive_pairs,
)
from crawl_agent.warc_loader import compare_two_dates

DATA_DIR = Path(__file__).resolve().parent / "static" / "data"

DOMAIN_DISPLAY = {
    "cursor.com": "Cursor",
    "windsurf.ai": "Windsurf",
    "github.com": "GitHub Copilot",
    "antigravity.com": "Antigravity",
    "trae.ai": "Trae",
    "openclaw.ai": "OpenClaw",
    "docs.openclaw.ai": "OpenClaw Docs",
    "bolt.new": "Bolt.new",
    "replit.com": "Replit",
    "claude.ai": "Claude",
    "claude.com": "Claude",
}


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    # Strip www.
    if host.startswith("www."):
        host = host[4:]
    return host


def _domain_display_name(domain: str) -> str:
    return DOMAIN_DISPLAY.get(domain, domain)


def _extract_domain_key(domain: str) -> str:
    """Normalize domain to a group key (e.g., docs.openclaw.ai -> openclaw)."""
    d = domain.lower()
    for key in ("cursor", "windsurf", "github", "antigravity", "trae", "openclaw", "bolt", "replit", "claude"):
        if key in d:
            return key
    return d.split(".")[0]


def build_all_data() -> None:
    """Build all JSON data files from cached comparisons."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    pairs = get_consecutive_pairs()
    dates = get_available_dates()

    if not pairs:
        print("No consecutive date pairs found.")
        return

    print(f"Building data for {len(pairs)} date pairs...")

    # Collect all data
    all_changes: dict[str, list] = {}  # "old_new" -> text_changes
    all_stats: dict[str, dict] = {}    # "old_new" -> stats
    domain_timeline: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    domain_totals: dict[str, int] = defaultdict(int)

    for old_date, new_date in pairs:
        pair_key = f"{old_date}_{new_date}"
        display_key = f"{date_to_display(new_date)} vs {date_to_display(old_date)}"
        print(f"  Processing {display_key}...")

        try:
            result = compare_two_dates(old_date, new_date)
        except Exception as e:
            print(f"    ERROR: {e}")
            continue

        stats = result.get("comparison", {}).get("stats", {})
        text_changes = result.get("text_changes", [])

        all_stats[pair_key] = stats
        all_changes[pair_key] = []

        new_date_display = date_to_display(new_date)

        for change in text_changes:
            url = change.get("url", "")
            domain = _extract_domain(url)
            domain_key = _extract_domain_key(domain)
            domain_display = _domain_display_name(domain)

            entry = {
                "url": url,
                "title": change.get("title", ""),
                "domain": domain,
                "domain_key": domain_key,
                "domain_display": domain_display,
                "similarity": round(change.get("similarity", 1.0), 3),
                "text_len_change": change.get("text_len_change", 0),
                "added_count": change.get("added_count", 0),
                "removed_count": change.get("removed_count", 0),
                "added": change.get("added", [])[:10],
                "removed": change.get("removed", [])[:10],
            }
            all_changes[pair_key].append(entry)

            domain_timeline[domain_key][new_date_display] += 1
            domain_totals[domain_key] += 1

    # 1. overview.json
    total_added = sum(s.get("added_count", 0) for s in all_stats.values())
    total_removed = sum(s.get("removed_count", 0) for s in all_stats.values())
    total_changed = sum(s.get("changed_count", 0) for s in all_stats.values())
    total_text_changes = sum(len(v) for v in all_changes.values())

    overview = {
        "dates": [date_to_display(d) for d in dates],
        "total_pairs": len(pairs),
        "total_added": total_added,
        "total_removed": total_removed,
        "total_changed": total_changed,
        "total_text_changes": total_text_changes,
        "avg_changes_per_day": round(total_text_changes / len(pairs), 1) if pairs else 0,
        "most_active_domain": max(domain_totals, key=domain_totals.get) if domain_totals else "",
        "domain_totals": {k: v for k, v in sorted(domain_totals.items(), key=lambda x: -x[1])},
    }
    _write_json(DATA_DIR / "overview.json", overview)

    # 2. timeline.json
    timeline_dates = [date_to_display(dates[i + 1]) for i in range(len(dates) - 1)]
    timeline = {
        "dates": timeline_dates,
        "domains": {},
    }
    for domain_key in sorted(domain_totals, key=domain_totals.get, reverse=True):
        timeline["domains"][domain_key] = [
            domain_timeline[domain_key].get(d, 0) for d in timeline_dates
        ]
    _write_json(DATA_DIR / "timeline.json", timeline)

    # 3. changes.json
    _write_json(DATA_DIR / "changes.json", all_changes)

    # 4. stats.json (per-pair stats)
    _write_json(DATA_DIR / "stats.json", all_stats)

    # 5. dates.json
    dates_data = {
        "dates": [date_to_display(d) for d in dates],
        "pairs": [
            {
                "old": old,
                "new": new,
                "old_display": date_to_display(old),
                "new_display": date_to_display(new),
                "label": f"{date_to_display(new)} vs {date_to_display(old)}",
            }
            for old, new in pairs
        ],
    }
    _write_json(DATA_DIR / "dates.json", dates_data)

    # 6. screenshots map
    screenshots_map = _build_screenshots_map()
    _write_json(DATA_DIR / "screenshots.json", screenshots_map)

    print(f"\nDone. Data written to {DATA_DIR}/")


def _write_json(path: Path, data: object) -> None:
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _build_screenshots_map() -> dict[str, list[dict]]:
    """Scan screenshots directory and build a map of available screenshots."""
    shots_dir = REPORTS_DIR / "screenshots"
    if not shots_dir.exists():
        return {}

    result: dict[str, list[dict]] = {}
    for pair_dir in sorted(shots_dir.iterdir()):
        if not pair_dir.is_dir():
            continue
        pair_label = pair_dir.name  # e.g., "2026-03-16_vs_2026-03-15"
        entries: list[dict] = []
        for domain_dir in sorted(pair_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            for png in sorted(domain_dir.glob("*.png")):
                rel_path = png.relative_to(shots_dir)
                entries.append({
                    "path": str(rel_path),
                    "domain": domain_dir.name,
                    "filename": png.stem,
                    "type": "new" if png.stem.endswith("_new") else "old",
                })
        if entries:
            result[pair_label] = entries
    return result


if __name__ == "__main__":
    build_all_data()
