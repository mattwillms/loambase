#!/usr/bin/env python3
"""
One-off script to manually trigger the Perenual plant seeder.

Usage (inside the API container):
    python scripts/run_seeder.py

Or from the host:
    docker exec loambase-loambase-api-1 python scripts/run_seeder.py
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    stream=sys.stdout,
)

from app.tasks.seed_plants import seed_plants


async def main() -> None:
    print("Starting Perenual seeder...\n")
    await seed_plants(ctx={})
    print("\nSeeder finished.")


if __name__ == "__main__":
    asyncio.run(main())
