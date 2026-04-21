"""
Append 2011-2020 traits rows from data/raw/traits/traits_{year}.csv into the
Player_Traits_Historical sheet of AFL_Master_2012_2025.xlsx.

- Reads existing Player_Traits_Historical (currently 2021-2022).
- Loads all historical per-season CSVs.
- Applies team-code -> team-full mapping for the Team_Full / Position_Full
  / Player_Full helper columns so the new rows match the existing schema.
- Replaces the Player_Traits_Historical sheet with the combined result.

A timestamped backup of the workbook is written first.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).parent
MASTER = ROOT / "AFL_Master_2012_2025.xlsx"
TRAITS_DIR = ROOT / "data" / "raw" / "traits"

# Same mapping the app uses (keep in sync with config/constants.TEAM_CODE_TO_NAME).
TEAM_CODE_TO_NAME = {
    "AFC": "Adelaide",
    "BFC": "Brisbane Lions",
    "CFC": "Collingwood",
    "COFC": "Carlton",
    "EFC": "Essendon",
    "FRFC": "Fremantle",
    "GCFC": "Gold Coast",
    "GFC": "Geelong",
    "GWS": "GWS Giants",
    "HFC": "Hawthorn",
    "MFC": "Melbourne",
    "NMFC": "North Melbourne",
    "PAFC": "Port Adelaide",
    "RFC": "Richmond",
    "SKFC": "St Kilda",
    "SYFC": "Sydney",
    "WBFC": "Western Bulldogs",
    "WCFC": "West Coast",
}

POSITION_ABBREV_TO_FULL = {
    "R": "Ruck",
    "M": "Midfielder",
    "MF": "Mid-Forward",
    "GD": "Gen. Defender",
    "W": "Wing",
    "GF": "Gen. Forward",
    "KF": "Key Forward",
    "KD": "Key Defender",
}


def main() -> int:
    if not MASTER.exists():
        print(f"Master workbook not found: {MASTER}", file=sys.stderr)
        return 1

    # 1. Load existing historical sheet
    existing = pd.read_excel(MASTER, sheet_name="Player_Traits_Historical")
    existing.columns = [str(c).strip() for c in existing.columns]
    existing_seasons = sorted(pd.to_numeric(existing["Season"], errors="coerce").dropna().astype(int).unique())
    print(f"Existing Player_Traits_Historical rows: {len(existing)} seasons={existing_seasons}")

    # 2. Gather 2011-2020 CSVs
    new_frames: list[pd.DataFrame] = []
    for yr in range(2011, 2021):
        csv = TRAITS_DIR / f"traits_{yr}.csv"
        if not csv.exists():
            print(f"  missing {csv.name} - skipping")
            continue
        df = pd.read_csv(csv)
        df.columns = [str(c).strip() for c in df.columns]
        new_frames.append(df)
        print(f"  loaded {csv.name}: {len(df)} rows")

    if not new_frames:
        print("No historical CSVs found", file=sys.stderr)
        return 1

    new_df = pd.concat(new_frames, ignore_index=True)

    # 3. Enrich new rows to match historical schema
    if "Team" in new_df.columns:
        new_df["Team_Full"] = (
            new_df["Team"].astype(str).str.strip().map(TEAM_CODE_TO_NAME).fillna(new_df["Team"].astype(str).str.strip())
        )
    if "Position" in new_df.columns:
        new_df["Position_Full"] = (
            new_df["Position"].astype(str).str.strip().map(POSITION_ABBREV_TO_FULL)
            .fillna(new_df["Position"].astype(str).str.strip())
        )
    if "Player" in new_df.columns:
        new_df["Player_Full"] = new_df["Player"].astype(str).str.strip()

    # Add any columns existing has but new lacks, and vice versa
    all_cols = list(dict.fromkeys(list(existing.columns) + list(new_df.columns)))
    for c in all_cols:
        if c not in existing.columns:
            existing[c] = pd.NA
        if c not in new_df.columns:
            new_df[c] = pd.NA
    existing = existing[all_cols]
    new_df = new_df[all_cols]

    # 4. Combine + dedup by (Season, Player, Team)
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined["Season"] = pd.to_numeric(combined["Season"], errors="coerce").astype("Int64")
    dedup_cols = [c for c in ("Season", "Player", "Team") if c in combined.columns]
    before = len(combined)
    combined = combined.drop_duplicates(subset=dedup_cols, keep="first")
    combined = combined.sort_values(["Season", "Team", "Player"])
    print(f"Combined {before} -> {len(combined)} rows after dedup")
    print(f"Seasons now in sheet: {sorted(combined['Season'].dropna().astype(int).unique().tolist())}")

    # 5. Backup and write
    backup = MASTER.with_name(MASTER.stem + f".backup-{datetime.now():%Y%m%d-%H%M%S}.xlsx")
    shutil.copy2(MASTER, backup)
    print(f"Backup -> {backup.name}")

    # Use openpyxl to replace only the target sheet and keep others intact.
    with pd.ExcelWriter(MASTER, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        combined.to_excel(writer, sheet_name="Player_Traits_Historical", index=False)

    print("Wrote Player_Traits_Historical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
