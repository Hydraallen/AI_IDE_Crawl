import os
from pathlib import Path
from datetime import datetime


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / "env"


def _load_env(env_path: Path) -> None:
    """Parse a simple KEY=VALUE env file (no dotenv dependency needed)."""
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_env(_ENV_FILE)

GLM_ENDPOINT: str = os.environ.get("GLM_ENDPOINT", "")
GLM_API_KEY: str = os.environ.get("GLM_API_KEY", "")
GLM_MODEL_NAME: str = os.environ.get("GLM_MODEL_NAME", "glm-5.1")

PROJECT_ROOT: Path = _PROJECT_ROOT
COLLECTIONS_DIR: Path = _PROJECT_ROOT / "crawls" / "collections"
COMPARE_SCRIPT_DIR: Path = _PROJECT_ROOT / "compare_script"
REPORTS_DIR: Path = _PROJECT_ROOT / "reports"
CACHE_DIR: Path = Path(__file__).resolve().parent / ".cache"


def get_available_dates() -> list[str]:
    """Scan crawls/collections/ and return sorted date strings like '20260315'."""
    if not COLLECTIONS_DIR.exists():
        return []
    dates: list[str] = []
    for d in COLLECTIONS_DIR.iterdir():
        if d.is_dir() and d.name.startswith("crawl-"):
            date_str = d.name.replace("crawl-", "")
            if date_str.isdigit() and len(date_str) == 8:
                dates.append(date_str)
    return sorted(dates)


def get_consecutive_pairs() -> list[tuple[str, str]]:
    """Yield pairs of consecutive calendar dates (old, new), skipping gaps."""
    dates = get_available_dates()
    pairs: list[tuple[str, str]] = []
    for i in range(len(dates) - 1):
        old = dates[i]
        new = dates[i + 1]
        try:
            old_dt = datetime.strptime(old, "%Y%m%d")
            new_dt = datetime.strptime(new, "%Y%m%d")
            if (new_dt - old_dt).days == 1:
                pairs.append((old, new))
        except ValueError:
            continue
    return pairs


def date_to_display(date_str: str) -> str:
    """Convert '20260315' to '2026-03-15'."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return dt.strftime("%Y-%m-%d")
