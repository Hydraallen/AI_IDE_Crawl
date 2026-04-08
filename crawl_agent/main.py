import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path for package imports
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Web Archive Analysis Agent for AI Coding Tools"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    batch_parser = subparsers.add_parser("batch", help="Batch analysis mode")
    batch_parser.add_argument("--start-date", help="Start date (YYYYMMDD)")
    batch_parser.add_argument("--end-date", help="End date (YYYYMMDD)")
    batch_parser.add_argument("--delay", type=float, default=1.0, help="Delay between LLM calls (seconds)")
    batch_parser.add_argument("--force", action="store_true", help="Overwrite existing reports")
    batch_parser.add_argument("--no-screenshots", action="store_true", help="Skip screenshot capture")

    subparsers.add_parser("agent", help="Interactive agent mode")

    args = parser.parse_args()

    if args.command == "batch":
        from crawl_agent.batch import run_batch
        run_batch(
            start_date=args.start_date,
            end_date=args.end_date,
            delay=args.delay,
            force=args.force,
            screenshots=not args.no_screenshots,
        )
    elif args.command == "agent":
        from crawl_agent.agent import run_agent
        run_agent()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
