from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from crawl_agent.config import get_available_dates, get_consecutive_pairs, date_to_display
from crawl_agent.warc_loader import (
    compare_two_dates,
    get_collection_data,
    get_domains_for_date,
    get_page_content,
    get_text_diff_for_url,
)


class DatePairInput(BaseModel):
    old_date: str = Field(description="Earlier date in YYYYMMDD format")
    new_date: str = Field(description="Later date in YYYYMMDD format")


class URLDatePairInput(BaseModel):
    url: str = Field(description="Full URL to check")
    old_date: str = Field(description="Earlier date in YYYYMMDD format")
    new_date: str = Field(description="Later date in YYYYMMDD format")


class DomainDatePairInput(BaseModel):
    domain: str = Field(description="Domain name (e.g., 'cursor.com')")
    old_date: str = Field(description="Earlier date in YYYYMMDD format")
    new_date: str = Field(description="Later date in YYYYMMDD format")


class TrendInput(BaseModel):
    domain: str = Field(description="Domain name to analyze")
    start_date: str = Field(description="Start date in YYYYMMDD format")
    end_date: str = Field(description="End date in YYYYMMDD format")


class SearchInput(BaseModel):
    keyword: str = Field(description="Keyword to search for in changes")
    date: Optional[str] = Field(default=None, description="Optional date in YYYYMMDD to limit search")


@tool(args_schema=DatePairInput)
def compare_dates(old_date: str, new_date: str) -> str:
    """Compare crawl data between two dates and return a domain-grouped summary."""
    result = compare_two_dates(old_date, new_date)
    comp = result["comparison"]
    text = result["text_changes"]

    summary = f"Comparison: {date_to_display(new_date)} vs {date_to_display(old_date)}\n"
    summary += f"Stats: {comp.get('stats', {})}\n"
    summary += f"Text changes: {len(text)} URLs with text changes\n"

    for change in text[:20]:
        url = change.get("url", "")
        sim = change.get("similarity", 0)
        summary += f"  {url} (similarity: {sim:.2f})\n"

    return summary


@tool(args_schema=URLDatePairInput)
def get_page_changes(url: str, old_date: str, new_date: str) -> str:
    """Get detailed text diff for a specific page between two dates."""
    result = get_text_diff_for_url(url, old_date, new_date)
    if result is None:
        return f"No data found for {url}"

    output = f"Page changes for {url}\n"
    output += f"  {date_to_display(old_date)} -> {date_to_display(new_date)}\n"
    if result.get("old"):
        output += f"  Old title: {result['old'].get('title', 'N/A')}\n"
    if result.get("new"):
        output += f"  New title: {result['new'].get('title', 'N/A')}\n"
    return output


@tool(args_schema=DomainDatePairInput)
def get_domain_changes(domain: str, old_date: str, new_date: str) -> str:
    """Get all changes for a specific domain between two dates."""
    result = compare_two_dates(old_date, new_date)
    text_changes = result["text_changes"]

    filtered = [c for c in text_changes if domain in c.get("url", "")]

    if not filtered:
        return f"No changes found for {domain} between {date_to_display(old_date)} and {date_to_display(new_date)}"

    output = f"Changes for {domain} ({len(filtered)} URLs):\n"
    for change in filtered[:30]:
        url = change.get("url", "")
        sim = change.get("similarity", 0)
        output += f"  {url} (similarity: {sim:.2f})\n"
    return output


@tool
def list_available_dates() -> str:
    """List all available crawl dates."""
    dates = get_available_dates()
    pairs = get_consecutive_pairs()
    output = f"Available dates ({len(dates)} total):\n"
    for d in dates:
        output += f"  {date_to_display(d)} ({d})\n"
    output += f"\nConsecutive pairs available: {len(pairs)}"
    return output


@tool(args_schema=TrendInput)
def analyze_trend(domain: str, start_date: str, end_date: str) -> str:
    """Analyze change trends for a domain over a date range."""
    dates = get_available_dates()
    start_idx = dates.index(start_date) if start_date in dates else 0
    end_idx = dates.index(end_date) if end_date in dates else len(dates) - 1

    relevant_dates = dates[start_idx:end_idx + 1]

    output = f"Trend analysis for {domain} from {date_to_display(start_date)} to {date_to_display(end_date)}\n"

    change_counts: list[int] = []
    for i in range(len(relevant_dates) - 1):
        old_d = relevant_dates[i]
        new_d = relevant_dates[i + 1]
        try:
            result = compare_two_dates(old_d, new_d)
            filtered = [c for c in result["text_changes"] if domain in c.get("url", "")]
            count = len(filtered)
            change_counts.append(count)
            output += f"  {date_to_display(old_d)} -> {date_to_display(new_d)}: {count} changes\n"
        except Exception as e:
            output += f"  {date_to_display(old_d)} -> {date_to_display(new_d)}: Error - {e}\n"

    if change_counts:
        output += f"\nTotal changes: {sum(change_counts)}, Avg: {sum(change_counts)/len(change_counts):.1f}/day"

    return output


@tool(args_schema=SearchInput)
def search_changes(keyword: str, date: Optional[str] = None) -> str:
    """Search for changes containing a keyword."""
    dates = get_available_dates()
    if date:
        dates_to_check = [date] if date in dates else []
    else:
        dates_to_check = dates[-5:]

    matches: list[str] = []
    for i in range(len(dates_to_check) - 1):
        try:
            result = compare_two_dates(dates_to_check[i], dates_to_check[i + 1])
            for change in result["text_changes"]:
                url = change.get("url", "")
                text_diff = json.dumps(change, ensure_ascii=False)
                if keyword.lower() in url.lower() or keyword.lower() in text_diff.lower():
                    matches.append(f"  {date_to_display(dates_to_check[i])} -> {date_to_display(dates_to_check[i+1])}: {url}")
        except Exception:
            continue

    if not matches:
        return f"No changes found matching '{keyword}'"

    output = f"Changes matching '{keyword}' ({len(matches)} results):\n"
    output += "\n".join(matches[:30])
    return output


ALL_TOOLS = [
    compare_dates,
    get_page_changes,
    get_domain_changes,
    list_available_dates,
    analyze_trend,
    search_changes,
]
