"""
Consolidate paged Traits Insights historical exports into per-season CSVs.

Input: 31 `export (N).csv` files from Desktop/Trasits Historical Data
(each is a 200-row page covering all 18 teams; 3 pages per season for
2011-2020).

Output: data/raw/traits/traits_{season}.csv — one file per season,
compatible with the existing load_traits_for_season() CSV fallback.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

SOURCE_DIR = Path("/Users/marcuswagner/Desktop/Trasits Historical Data")
OUT_DIR = Path(__file__).parent / "data" / "raw" / "traits"


def main() -> int:
    if not SOURCE_DIR.exists():
        print(f"Source dir not found: {SOURCE_DIR}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    for csv_path in sorted(SOURCE_DIR.glob("export*.csv")):
        df = pd.read_csv(csv_path)
        df.columns = [str(c).strip() for c in df.columns]
        if "Season" not in df.columns:
            print(f"Skipping {csv_path.name}: no Season column")
            continue
        frames.append(df)

    if not frames:
        print("No input CSVs found", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    combined["Season"] = pd.to_numeric(combined["Season"], errors="coerce").astype("Int64")

    # Dedup within (Season, Player, Team) — pages may overlap
    dedup_cols = [c for c in ("Season", "Player", "Team") if c in combined.columns]
    before = len(combined)
    combined = combined.drop_duplicates(subset=dedup_cols, keep="first")
    print(f"Loaded {before} rows -> {len(combined)} after dedup")

    for season, group in combined.groupby("Season", dropna=True):
        season_int = int(season)
        out_path = OUT_DIR / f"traits_{season_int}.csv"
        group_sorted = group.sort_values(
            by=[c for c in ("Team", "Player") if c in group.columns]
        )
        group_sorted.to_csv(out_path, index=False)
        teams = group_sorted["Team"].nunique() if "Team" in group_sorted.columns else 0
        print(f"  {season_int}: {len(group_sorted)} rows, {teams} teams -> {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
