#!/usr/bin/env python3
"""
One-off script to manually trigger the Perenual plant fetcher.

Usage (inside the API container):
    python scripts/run_fetch_perenual.py

Or from the host:
    docker exec loambase-loambase-api-1 python scripts/run_fetch_perenual.py
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    stream=sys.stdout,
)

from app.tasks.fetch_perenual import fetch_perenual


async def main() -> None:
    print("Starting Perenual fetcher...\n")
    await fetch_perenual(ctx={})
    print("\nFetcher finished.")


if __name__ == "__main__":
    asyncio.run(main())
