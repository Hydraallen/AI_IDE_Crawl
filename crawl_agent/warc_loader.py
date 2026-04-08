import sys
from pathlib import Path
from urllib.parse import urlparse

from crawl_agent.config import COMPARE_SCRIPT_DIR
from crawl_agent.cache import get_parsed_collection

sys.path.insert(0, str(COMPARE_SCRIPT_DIR))

from crawl_compare import compare_collections, analyze_text_changes  # noqa: E402


def get_collection_data(date_str: str) -> dict:
    """Load cached (or freshly parsed) collection data."""
    return get_parsed_collection(date_str, extract_text=True)


def compare_two_dates(old_date: str, new_date: str) -> dict:
    """Compare two dates and return full comparison + text analysis."""
    data_old = get_collection_data(old_date)
    data_new = get_collection_data(new_date)

    comparison = compare_collections(data_old, data_new)
    text_analysis = analyze_text_changes(data_old, data_new)

    return {
        "comparison": comparison,
        "text_changes": text_analysis["text_changes"],
        "text_stats": text_analysis["stats"],
        "old_date": old_date,
        "new_date": new_date,
    }


def get_text_diff_for_url(url: str, old_date: str, new_date: str) -> dict | None:
    """Get detailed text diff for a single URL between two dates."""
    data_old = get_collection_data(old_date)
    data_new = get_collection_data(new_date)

    old_entry = data_old.get(url)
    new_entry = data_new.get(url)

    return {"url": url, "old": old_entry, "new": new_entry}


def get_domains_for_date(date_str: str) -> dict[str, list[str]]:
    """Group URLs by domain for a given date."""
    data = get_collection_data(date_str)
    domains: dict[str, list[str]] = {}
    for url in data:
        domain = urlparse(url).netloc
        domains.setdefault(domain, []).append(url)
    return domains


def get_page_content(url: str, date_str: str) -> dict | None:
    """Get cached page content for a URL on a specific date."""
    data = get_collection_data(date_str)
    return data.get(url)
