import json
import time
from pathlib import Path

from crawl_agent.config import (
    REPORTS_DIR,
    get_consecutive_pairs,
    date_to_display,
)
from crawl_agent.warc_loader import compare_two_dates
from crawl_agent.llm_client import get_llm, call_llm_with_retry
from crawl_agent.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT


def _format_stats(comparison: dict) -> str:
    stats = comparison.get("stats", {})
    rows = []
    for key, value in stats.items():
        rows.append(f"| {key} | {value} |")
    return "| Metric | Count |\n|--------|-------|\n" + "\n".join(rows)


def _format_domain_breakdown(text_changes: list) -> str:
    from urllib.parse import urlparse

    domain_counts: dict[str, int] = {}
    domain_highlights: dict[str, list[str]] = {}

    for change in text_changes:
        url = change.get("url", "")
        domain = urlparse(url).netloc
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

        sim = change.get("similarity", 0)
        if sim < 0.5:
            highlight = f"{url} (similarity: {sim:.2f})"
            domain_highlights.setdefault(domain, []).append(highlight)

    rows = []
    for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
        highlights = "; ".join(domain_highlights.get(domain, [])[:3])
        rows.append(f"| {domain} | {count} | {highlights} |")

    header = "| Domain | Changes | Highlights |\n|--------|---------|-----------|\n"
    return header + "\n".join(rows)


def _format_changes_data(text_changes: list, max_items: int = 30) -> str:
    items = []
    for change in text_changes[:max_items]:
        items.append(json.dumps(change, ensure_ascii=False, indent=2))
    return "\n\n".join(items)


def run_batch(
    start_date: str | None = None,
    end_date: str | None = None,
    delay: float = 1.0,
    force: bool = False,
) -> None:
    """Run batch analysis on all consecutive date pairs."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    pairs = get_consecutive_pairs()

    if start_date:
        pairs = [(o, n) for o, n in pairs if o >= start_date]
    if end_date:
        pairs = [(o, n) for o, n in pairs if n <= end_date]

    print(f"Processing {len(pairs)} date pairs...")
    llm = get_llm()

    processed = 0
    skipped = 0
    failed = 0

    for old_date, new_date in pairs:
        report_name = f"{date_to_display(new_date)}_vs_{date_to_display(old_date)}.md"
        report_path = REPORTS_DIR / report_name

        if report_path.exists() and not force:
            print(f"  Skipping {report_name} (already exists)")
            skipped += 1
            continue

        print(f"  Comparing {date_to_display(old_date)} vs {date_to_display(new_date)}...")

        try:
            result = compare_two_dates(old_date, new_date)

            prompt = ANALYSIS_PROMPT.format(
                system_prompt=SYSTEM_PROMPT,
                old_date_display=date_to_display(old_date),
                new_date_display=date_to_display(new_date),
                stats=_format_stats(result["comparison"]),
                domain_breakdown=_format_domain_breakdown(result["text_changes"]),
                changes_data=_format_changes_data(result["text_changes"]),
            )

            report_content = call_llm_with_retry(llm, prompt)

            with open(report_path, "w") as f:
                f.write(report_content)

            processed += 1
            print(f"  Written: {report_path}")

        except Exception as e:
            failed += 1
            print(f"  FAILED: {e}")
            continue

        if delay > 0 and processed < len(pairs):
            time.sleep(delay)

    print(f"\nBatch complete: {processed} processed, {skipped} skipped, {failed} failed")
