#!/usr/bin/env python3
"""
One-off script to manually trigger the Permapeople plant fetcher.

Usage (inside the API container):
    python scripts/run_fetch_permapeople.py          # incremental (Pass 2 only)
    python scripts/run_fetch_permapeople.py --full    # full re-scan (Pass 1 + 2)

Or from the host:
    docker exec loambase-loambase-api-1 python scripts/run_fetch_permapeople.py
    docker exec loambase-loambase-api-1 python scripts/run_fetch_permapeople.py --full
"""
import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    stream=sys.stdout,
)

from app.tasks.fetch_permapeople import fetch_permapeople

parser = argparse.ArgumentParser(description="Permapeople plant fetcher")
parser.add_argument("--full", action="store_true", help="Force full re-scan instead of incremental")


async def main() -> None:
    args = parser.parse_args()
    mode = "full" if args.full else "incremental"
    print(f"Starting Permapeople fetcher ({mode} mode)...\n")
    await fetch_permapeople(ctx={}, triggered_by="manual", force_full=args.full)
    print("\nFetcher finished.")


if __name__ == "__main__":
    asyncio.run(main())
