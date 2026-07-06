#!/usr/bin/env python3
"""
Build 2026 Season Data for AFL Dashboard
=========================================
Prepares all 2026 data files needed for the app:
1. Merges fresh squad list with existing contracts/draft data
2. Creates squads_2026.csv in the format the app expects
3. Creates a 2026 player stats placeholder (with 2025 ratings fallback)
4. Runs photo update for any new players
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys
import json

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from config.constants import CURRENT_SEASON
from utils.player_positions import (
    EXPECTED_AFL_TEAM_COUNT,
    count_unique_teams,
    load_csv_with_team_fallback,
    resolve_positions_for_output,
)
from utils.safe_io import safe_csv_write

SEASON = CURRENT_SEASON  # Parameterized — no hardcoded year

def build_2026_data():
    print("=" * 60)
    print(f"BUILDING {SEASON} SEASON DATA")
    print("=" * 60)
    
    # ---- 1. Load fresh squad list ----
    print(f"\n1. Loading fresh {SEASON} squad list...")
    lists_path = BASE_DIR / "data" / "raw" / "player" / f"footywire_{SEASON}_lists.csv"
    df, source_path, used_backup = load_csv_with_team_fallback(lists_path)
    if used_backup:
        print(f"   Warning: current list file had only {count_unique_teams(pd.read_csv(lists_path))} teams")
        print(f"   Restoring from last good {EXPECTED_AFL_TEAM_COUNT}-team backup: {source_path.name}")
        safe_csv_write(df, lists_path)
    print(f"   {len(df)} players from {df['Team'].nunique()} teams")

    if df['Team'].nunique() != EXPECTED_AFL_TEAM_COUNT:
        raise ValueError(f"Expected {EXPECTED_AFL_TEAM_COUNT} teams in {lists_path.name}, found {df['Team'].nunique()}")
    
    # ---- 2. Merge with existing contract data ----
    print("\n2. Merging contract data...")
    contracts_path = BASE_DIR / "data" / "raw" / "player" / f"footywire_contracts_{SEASON}.csv"
    if contracts_path.exists():
        contracts = pd.read_csv(contracts_path)
        # Normalize names for matching
        contracts["Player_match"] = contracts["Player_Raw"].str.strip()
        df["Player_match"] = df["Player"].str.strip()
        
        # Match by Team + similar name
        merged = df.merge(
            contracts[["Team", "Player_match", "Contract_Expiry", "FA_Status"]],
            on=["Team", "Player_match"],
            how="left"
        )
        merged.drop(columns=["Player_match"], inplace=True)
        matched = merged["Contract_Expiry"].notna().sum()
        print(f"   Matched {matched}/{len(df)} players with contracts")
    else:
        merged = df.copy()
        merged["Contract_Expiry"] = np.nan
        merged["FA_Status"] = np.nan
        print("   No contract data found")
    
    # ---- 3. Merge with existing draft data ----
    print("\n3. Merging draft data...")
    complete_path = BASE_DIR / "data" / "raw" / "player" / f"footywire_{SEASON}_complete.csv"
    if complete_path.exists():
        complete = pd.read_csv(complete_path)
        draft_cols = ["Draft_Year", "Draft_Type", "Draft_Round", "Draft_Pick"]
        existing_draft = [c for c in draft_cols if c in complete.columns]
        if existing_draft:
            complete["Player_match"] = complete["Player"].str.strip()
            merged["Player_match"] = merged["Player"].str.strip()
            merged = merged.merge(
                complete[["Team", "Player_match"] + existing_draft],
                on=["Team", "Player_match"],
                how="left",
                suffixes=("", "_old")
            )
            merged.drop(columns=["Player_match"], inplace=True)
            # Remove any duplicate columns
            for c in merged.columns:
                if c.endswith("_old"):
                    merged.drop(columns=[c], inplace=True)
            matched = merged[existing_draft[0]].notna().sum()
            print(f"   Matched {matched}/{len(df)} players with draft data")
    
    merged = resolve_positions_for_output(merged, SEASON, BASE_DIR)

    # ---- 4. Save updated complete file ----
    print("\n4. Saving updated complete file...")
    complete_out = BASE_DIR / "data" / "raw" / "player" / f"footywire_{SEASON}_complete.csv"
    merged.to_csv(complete_out, index=False)
    print(f"   Saved {complete_out.name}: {len(merged)} players, {len(merged.columns)} columns")
    
    # ---- 5. Create squads CSV in app format ----
    print(f"\n5. Creating squads_{SEASON}.csv...")
    squads = merged.copy()
    
    squads["Position_Mapped"] = squads["Position_Resolved"].fillna("")
    
    # Parse age to numeric
    def parse_age(age_str):
        if pd.isna(age_str):
            return np.nan
        try:
            return float(str(age_str).split("yr")[0].strip())
        except:
            return np.nan
    
    squads["Age_Numeric"] = squads["Age"].apply(parse_age)
    
    # Build squads file
    squads_out = squads.rename(columns={
        "Jumper_No": "Jumper",
        "Position_Mapped": "Position_Clean",
        "Games": "Matches_Career",
        "Age_Numeric": "Age_Decimal",
    })
    squads_out["Season"] = SEASON
    squads_out["Matches_Current"] = 0  # No games played yet
    
    squads_path = BASE_DIR / "data" / "raw" / "player" / f"squads_{SEASON}.csv"
    squads_out.to_csv(squads_path, index=False)
    print(f"   Saved squads_{SEASON}.csv: {len(squads_out)} players")
    
    # ---- 6. Create player stats (metadata only – no carry-forward) ----
    print(f"\n6. Creating player_stats_{SEASON}.csv (metadata only, ratings come from Wheelo)...")
    stats = squads_out[["Player", "Team", "Jumper", "Position", "Height", "DOB", "Age_Decimal", "Matches_Career"]].copy()
    stats.rename(columns={"Matches_Career": "Matches", "Age_Decimal": "Age"}, inplace=True)
    if "Position_Resolved" in squads_out.columns:
        stats["Position"] = squads_out["Position_Resolved"]
    stats["Matches"] = 0  # Actual match data comes from wheelo_player_to_raw step
    stats_path = BASE_DIR / "data" / "raw" / "player" / f"player_stats_{SEASON}.csv"
    stats.to_csv(stats_path, index=False)
    print(f"   Saved player_stats_{SEASON}.csv: {len(stats)} players, {len(stats.columns)} columns")
    
    # ---- 7. Merge traits data ----
    print("\n7. Merging traits data...")
    traits_path = BASE_DIR / "data" / "raw" / "player" / f"footywire_{SEASON}_with_traits.csv"
    if traits_path.exists():
        traits_df = pd.read_csv(traits_path)
        trait_cols = [c for c in traits_df.columns if "Rating" in c or "Overall" in c or "data_provider" in c]
        if trait_cols:
            traits_subset = traits_df[["Player", "Team"] + trait_cols].copy()
            traits_out_path = BASE_DIR / "data" / "raw" / "traits" / f"traits_{SEASON}.csv"
            traits_subset.to_csv(traits_out_path, index=False)
            has_traits = traits_subset["Overall_Rating"].notna().sum() if "Overall_Rating" in traits_subset.columns else 0
            print(f"   Saved traits_{SEASON}.csv: {has_traits} players with trait ratings")
    else:
        print(f"   ⚠️ No traits data found for {SEASON}")
    
    # ---- 8. Summary of new players (need photos) ----
    print("\n8. Checking for new players needing photos...")
    photos_dir = BASE_DIR / "player_photos"
    if photos_dir.exists():
        existing_photos = {f.stem.lower() for f in photos_dir.glob("*.png")} | \
                         {f.stem.lower() for f in photos_dir.glob("*.jpg")} | \
                         {f.stem.lower() for f in photos_dir.glob("*.jpeg")}
        
        missing_photos = []
        for _, row in squads_out.iterrows():
            player = row["Player"]
            # Try various name formats
            name_variants = [
                player.lower().replace(" ", "_"),
                player.lower().replace(" ", "-"),
                player.lower().replace(" ", ""),
                f"{row['Team'].lower().replace(' ', '_')}_{player.lower().replace(' ', '_')}",
            ]
            if not any(v in existing_photos for v in name_variants):
                missing_photos.append((row["Team"], player))
        
        print(f"   Players missing photos: {len(missing_photos)}")
        if missing_photos:
            print(f"   First 20:")
            for team, player in missing_photos[:20]:
                print(f"     {team}: {player}")
    
    # ---- 9. Print team-by-team summary ----
    print("\n" + "=" * 60)
    print("TEAM SUMMARY")
    print("-" * 60)
    for team in sorted(squads_out["Team"].unique()):
        team_df = squads_out[squads_out["Team"] == team]
        avg_age = team_df["Age_Decimal"].mean() if "Age_Decimal" in team_df.columns else team_df["Age"].apply(lambda x: float(str(x).split("yr")[0].strip()) if pd.notna(x) else np.nan).mean()
        avg_games = team_df["Matches_Career"].mean() if "Matches_Career" in team_df.columns else team_df["Games"].mean() if "Games" in team_df.columns else 0
        print(f"  {team:20s}  {len(team_df):2d} players  Avg Age: {avg_age:.1f}  Avg Games: {avg_games:.0f}")
    
    print("\n" + "=" * 60)
    print(f"\u2705 {SEASON} DATA BUILD COMPLETE")
    print("=" * 60)
    
    return len(squads_out)


if __name__ == "__main__":
    build_2026_data()
