#!/usr/bin/env python3
"""
Pipeline Data Freshness Validator
==================================
Lightweight validation step for the scheduled update pipeline.
Checks that key output files exist and are recent.

Exit codes:
  0 = All checks passed
  1 = One or more checks failed (stale or missing data)
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent

# Maximum age (hours) for files considered "fresh" after a successful pipeline run.
MAX_AGE_HOURS = 4

# Files that MUST be updated on each successful run
REQUIRED_FILES = [
    "data/raw/player/squads_{season}.csv",
    "data/raw/player/player_stats_{season}.csv",
    "data/raw/player/footywire_{season}_complete.csv",
    "data/raw/team/team_stats_{season}.csv",
    "data/computed/team_summary_{season}.csv",
    "data/computed/team_ladders_{season}.csv",
]

# Files that SHOULD be updated but are not critical (e.g. contract data may timeout)
OPTIONAL_FILES = [
    "data/raw/player/footywire_contracts_{season}.csv",
    "data/raw/player/footywire_drafts_history.csv",
    "data/raw/player/footywire_{season}_with_traits.csv",
    "data/raw/traits/traits_{season}.csv",
]


def validate_freshness(season: int) -> bool:
    """Check that pipeline output files exist and are fresh."""
    now = datetime.now()
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    all_ok = True

    print("=" * 60)
    print(f"PIPELINE VALIDATION — Season {season}")
    print(f"Freshness cutoff: {cutoff:%Y-%m-%d %H:%M}")
    print("=" * 60)

    for template in REQUIRED_FILES:
        path = BASE_DIR / template.format(season=season)
        if not path.exists():
            print(f"  ✗ MISSING  {path.name}")
            all_ok = False
        else:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            age = now - mtime
            if mtime < cutoff:
                print(f"  ⚠ STALE    {path.name}  (last updated {mtime:%Y-%m-%d %H:%M}, {age.total_seconds()/3600:.1f}h ago)")
                all_ok = False
            else:
                print(f"  ✓ FRESH    {path.name}  ({mtime:%H:%M})")

    print()
    for template in OPTIONAL_FILES:
        path = BASE_DIR / template.format(season=season)
        if not path.exists():
            print(f"  ⊘ OPTIONAL {path.name}  (not found)")
        else:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            age = now - mtime
            if mtime < cutoff:
                print(f"  ⊘ OPTIONAL {path.name}  (stale — {age.total_seconds()/3600:.1f}h ago)")
            else:
                print(f"  ✓ FRESH    {path.name}  ({mtime:%H:%M})")

    print()
    if all_ok:
        print("✅ All required files are present and fresh.")
    else:
        print("⚠️  Some required files are missing or stale.")

    return all_ok


if __name__ == "__main__":
    # Import CURRENT_SEASON dynamically to avoid import errors when run standalone
    try:
        from config.constants import CURRENT_SEASON
        season = CURRENT_SEASON
    except ImportError:
        season = 2026

    ok = validate_freshness(season)
    sys.exit(0 if ok else 1)
