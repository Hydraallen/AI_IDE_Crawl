import hashlib
import json
import sys
from pathlib import Path

from crawl_agent.config import COLLECTIONS_DIR, CACHE_DIR


def _collection_path(date_str: str) -> Path:
    return COLLECTIONS_DIR / f"crawl-{date_str}"


def _cache_path(date_str: str) -> Path:
    return CACHE_DIR / "parsed" / f"{date_str}.json"


def _compute_checksum(date_str: str) -> str:
    """SHA-256 checksum of WARC filenames + sizes for cache invalidation."""
    archive_dir = _collection_path(date_str) / "archive"
    if not archive_dir.exists():
        return ""
    parts: list[str] = []
    for f in sorted(archive_dir.glob("*.warc.gz")):
        parts.append(f"{f.name}:{f.stat().st_size}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def get_parsed_collection(date_str: str, extract_text: bool = True) -> dict:
    """Parse a WARC collection with JSON caching and checksum validation."""
    cache_file = _cache_path(date_str)
    current_checksum = _compute_checksum(date_str)

    if cache_file.exists():
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            if cached.get("checksum") == current_checksum:
                return cached["data"]
        except (json.JSONDecodeError, KeyError):
            pass

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compare_script"))
    from crawl_compare import parse_warc_collection

    col_path = str(_collection_path(date_str))
    data = parse_warc_collection(col_path, extract_text=extract_text)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_entry = {"checksum": current_checksum, "date": date_str, "data": data}
    with open(cache_file, "w") as f:
        json.dump(cache_entry, f, ensure_ascii=False)

    return data
