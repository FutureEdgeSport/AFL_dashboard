#!/usr/bin/env python3
"""
Examine historical data structure for consolidation planning.
"""
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data/raw")

print("=" * 70)
print("HISTORICAL DATA INVENTORY")
print("=" * 70)

# === PLAYER STATS ===
print("\n=== PLAYER STATS (per season) ===")
player_years = sorted(DATA_DIR.glob("player/player_stats_*.csv"))
for f in player_years:
    df = pd.read_csv(f)
    print(f"  {f.name}: {len(df)} rows, {len(df.columns)} cols")

# Sample columns
p2025 = pd.read_csv("data/raw/player/player_stats_2025.csv")
print(f"\n  Sample columns: {list(p2025.columns)}")

# === TRAITS ===
print("\n=== TRAITS (per season) ===")
traits_years = sorted(DATA_DIR.glob("traits/traits_*.csv"))
for f in traits_years:
    df = pd.read_csv(f)
    print(f"  {f.name}: {len(df)} rows, {len(df.columns)} cols")

t2025 = pd.read_csv("data/raw/traits/traits_2025.csv")
print(f"\n  Sample columns: {list(t2025.columns)[:15]}...")

# === TEAM STATS ===
print("\n=== TEAM STATS ===")
team_files = sorted(DATA_DIR.glob("team/team_stats_*.csv"))
for f in team_files:
    df = pd.read_csv(f)
    print(f"  {f.name}: {len(df)} rows, {len(df.columns)} cols")

# === OTHER FILES ===
print("\n=== OTHER PLAYER FILES ===")
other = ["player/contract_expiry.csv", "player/draft_data.csv", "player/squads_2025.csv"]
for fn in other:
    path = DATA_DIR / fn
    if path.exists():
        df = pd.read_csv(path)
        print(f"  {fn}: {len(df)} rows")
        print(f"    Columns: {list(df.columns)}")

# === EXTERNAL ===
print("\n=== EXTERNAL DATA ===")
ext_files = list(DATA_DIR.glob("external/*.csv"))
for f in ext_files:
    df = pd.read_csv(f)
    print(f"  {f.name}: {len(df)} rows, cols: {list(df.columns)[:8]}...")

# === COMPUTED ===
print("\n=== COMPUTED DATA ===")
computed = list(Path("data/computed").glob("*.csv"))
for f in computed:
    df = pd.read_csv(f)
    print(f"  {f.name}: {len(df)} rows, {len(df.columns)} cols")

# === CACHE ===
print("\n=== CACHE DATA ===")
import json
for cache_file in Path("data/cache").glob("*.json"):
    with open(cache_file) as f:
        data = json.load(f)
    if isinstance(data, dict):
        print(f"  {cache_file.name}: {len(data)} entries")
    elif isinstance(data, list):
        print(f"  {cache_file.name}: {len(data)} items")

# === FOOTYWIRE 2026 ===
print("\n=== FOOTYWIRE 2026 DATA ===")
fw_files = list(DATA_DIR.glob("player/footywire_*.csv"))
for f in fw_files:
    df = pd.read_csv(f)
    print(f"  {f.name}: {len(df)} rows, {len(df.columns)} cols")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("""
Historical data to consolidate (up to end of 2025):
1. Player Stats: 2012-2025 (14 years of season data)
2. Traits: 2021-2025 (5 years)  
3. Team Stats: 2021-2025
4. Contract/Draft data
5. Wheelo ratings
6. DOB cache
7. Traits API cache

This will create a single source of truth for all historical data.
""")
