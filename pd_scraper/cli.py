"""Command-line entry point for pd_scraper.

Usage:
    python -m pd_scraper.cli init-db
    python -m pd_scraper.cli backfill --seasons 2025
    python -m pd_scraper.cli backfill --seasons 2025 2026 --rounds 1 2 3 --force
    python -m pd_scraper.cli daily-sync
    python -m pd_scraper.cli ingest        # re-ingest raw JSON into SQLite
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .scrape_season import run as run_seasons
from .scrape_match_pdfs import run as run_pdfs
from .storage import init_db, ingest_raw_dir


def _cli() -> int:
    ap = argparse.ArgumentParser(prog="pd_scraper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")

    bf = sub.add_parser("backfill")
    bf.add_argument("--seasons", nargs="+", type=int, default=[2025])
    bf.add_argument("--rounds", nargs="*", default=None)
    bf.add_argument("--force", action="store_true")
    bf.add_argument("--headed", action="store_true")

    sub.add_parser("daily-sync",
                   help="Rescrape current seasons, ingest, and download new match PDFs")

    sp = sub.add_parser("sync-pdfs",
                        help="Download match report PDFs for MGS rounds (saves to mgs-ams)")
    sp.add_argument("--seasons", nargs="+", type=int, default=[2025, 2026])
    sp.add_argument("--rounds", nargs="*", type=int, default=None)
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--headed", action="store_true")

    ig = sub.add_parser("ingest", help="Re-ingest data/pd/raw/*.json into SQLite")

    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s [%(name)s]: %(message)s")

    if args.cmd == "init-db":
        init_db()
        print("DB initialised")
        return 0

    if args.cmd == "backfill":
        async def _go():
            await run_seasons(
                args.seasons,
                rounds=args.rounds,
                skip_existing=not args.force,
                headless=not args.headed,
            )
        asyncio.run(_go())
        n = ingest_raw_dir()
        print(f"Ingested {n} match files → SQLite")
        return 0

    if args.cmd == "daily-sync":
        # 1. Scrape stats, 2. ingest to DB, 3. download PDFs (needs DB for round lookup)
        async def _go():
            await run_seasons([2025, 2026], skip_existing=True, headless=True)
        asyncio.run(_go())
        n = ingest_raw_dir()
        print(f"Ingested {n} match files → SQLite")
        async def _pdfs():
            await run_pdfs([2025, 2026], skip_existing=True, headless=True)
        asyncio.run(_pdfs())
        return 0

    if args.cmd == "sync-pdfs":
        async def _go_pdfs():
            saved = await run_pdfs(
                args.seasons,
                rounds=args.rounds,
                skip_existing=not args.force,
                headless=not args.headed,
            )
            print(f"PDFs saved: {len(saved)}")
            for p in saved:
                print(f"  {p}")
        asyncio.run(_go_pdfs())
        return 0

    if args.cmd == "ingest":
        n = ingest_raw_dir()
        print(f"Ingested {n} match files → SQLite")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
