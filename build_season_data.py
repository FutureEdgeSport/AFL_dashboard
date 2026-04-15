#!/usr/bin/env python3
"""
Build Season Data for AFL Dashboard
=====================================
Accepts --season flag (defaults to CURRENT_SEASON from config).

Prepares all season data files needed for the app:
1. Merges fresh squad list with existing contracts/draft data
2. Creates squads_{season}.csv in the format the app expects
3. Creates a player stats placeholder (with previous ratings fallback)
4. Runs photo update for any new players
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import json

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from config.constants import CURRENT_SEASON
from utils.safe_io import safe_csv_write

SEASON = CURRENT_SEASON  # Overridden by --season arg

def build_2026_data():
    print("=" * 60)
    print(f"BUILDING {SEASON} SEASON DATA")
    print("=" * 60)
    
    # ---- 1. Load fresh squad list ----
    print(f"\n1. Loading fresh {SEASON} squad list...")
    lists_path = BASE_DIR / "data" / "raw" / "player" / f"footywire_{SEASON}_lists.csv"
    df = pd.read_csv(lists_path)
    print(f"   {len(df)} players from {df['Team'].nunique()} teams")
    
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
    
    # ---- 4. Save updated complete file ----
    print("\n4. Saving updated complete file...")
    complete_out = BASE_DIR / "data" / "raw" / "player" / f"footywire_{SEASON}_complete.csv"
    safe_csv_write(merged, complete_out)
    print(f"   Saved {complete_out.name}: {len(merged)} players, {len(merged.columns)} columns")
    
    # ---- 5. Create squads CSV in app format ----
    print(f"\n5. Creating squads_{SEASON}.csv...")
    squads = merged.copy()
    
    # Map positions to app format
    pos_map = {
        "Forward": "Forward",
        "Defender": "Defender", 
        "Midfield": "Midfielder",
        "MidfieldForward": "Mid-Forward",
        "Ruck": "Ruck",
        "DefenderMidfield": "Defender",
        "ForwardRuck": "Ruck",
        "DefenderForward": "Defender",
        "DefenderRuck": "Defender",
    }
    squads["Position_Mapped"] = squads["Position"].map(pos_map).fillna("Midfielder")
    
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
    safe_csv_write(squads_out, squads_path)
    print(f"   Saved squads_{SEASON}.csv: {len(squads_out)} players")
    
    # ---- 6. Create player stats (metadata only – no carry-forward) ----
    print(f"\n6. Creating player_stats_{SEASON}.csv (metadata only, ratings come from Wheelo)...")
    stats = squads_out[["Player", "Team", "Jumper", "Position", "Height", "DOB", "Age_Decimal", "Matches_Career"]].copy()
    stats.rename(columns={"Matches_Career": "Matches", "Age_Decimal": "Age"}, inplace=True)
    stats["Matches"] = 0  # Actual match data comes from wheelo_player_to_raw step
    stats_path = BASE_DIR / "data" / "raw" / "player" / f"player_stats_{SEASON}.csv"
    safe_csv_write(stats, stats_path)
    print(f"   Saved player_stats_{SEASON}.csv: {len(stats)} players, {len(stats.columns)} columns")
    
    # ---- 7. Merge traits data ----
    print("\n7. Merging traits data...")
    traits_path = BASE_DIR / "data" / "raw" / "player" / f"footywire_{SEASON}_with_traits.csv"
    if traits_path.exists():
        traits_df = pd.read_csv(traits_path)
        # Keep columns with "Rating", "Overall", or "data_provider" in the name,
        # plus the 16 sub-trait metric short names used by the app.
        _METRIC_SHORT_NAMES = {
            'Stoppage', 'Contest', 'Power', 'Receives',
            'Handballing', 'Kicking', 'Goal Kicking', 'Connecting',
            'Marking', 'Contested', 'Moks', 'Ruck',
            'Pressure', 'Tackling', 'Intercepting', 'Neutralise',
        }
        trait_cols = [
            c for c in traits_df.columns
            if "Rating" in c or "Overall" in c or "data_provider" in c or c in _METRIC_SHORT_NAMES
        ]
        if trait_cols:
            traits_subset = traits_df[["Player", "Team"] + trait_cols].copy()
            traits_out_path = BASE_DIR / "data" / "raw" / "traits" / f"traits_{SEASON}.csv"
            safe_csv_write(traits_subset, traits_out_path)
            has_traits = traits_subset["Overall_Rating"].notna().sum() if "Overall_Rating" in traits_subset.columns else 0
            print(f"   Saved traits_{SEASON}.csv: {has_traits} players with trait ratings")

            # ---- 7b. Snapshot traits per round (for Trait Rating Matrix) ----
            match_ratings_path = BASE_DIR / "data" / "raw" / "player" / f"match_ratings_{SEASON}.csv"
            if match_ratings_path.exists() and "Overall_Rating" in traits_subset.columns:
                mr_df = pd.read_csv(match_ratings_path)
                current_round = int(mr_df["Round"].max()) if "Round" in mr_df.columns and not mr_df.empty else None
                if current_round is not None and current_round > 0:
                    history_path = BASE_DIR / "data" / "raw" / "traits" / f"traits_history_{SEASON}.csv"
                    # Load existing history
                    if history_path.exists():
                        history_df = pd.read_csv(history_path)
                    else:
                        history_df = pd.DataFrame(columns=["Player", "Team", "Round", "Overall_Rating"])
                    # Only add snapshot if this round hasn't been recorded yet
                    existing_rounds = set(history_df["Round"].unique()) if not history_df.empty else set()
                    if current_round not in existing_rounds:
                        snapshot = traits_subset[["Player", "Team", "Overall_Rating"]].copy()
                        snapshot["Round"] = current_round
                        snapshot = snapshot[snapshot["Overall_Rating"].notna()]
                        history_df = pd.concat([history_df, snapshot], ignore_index=True)
                        safe_csv_write(history_df, history_path)
                        print(f"   Saved traits_history_{SEASON}.csv: snapshotted R{current_round} ({len(snapshot)} players)")
                    else:
                        print(f"   traits_history_{SEASON}.csv: R{current_round} already snapshotted, skipping")
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
    parser = argparse.ArgumentParser(description="Build season data for AFL Dashboard")
    parser.add_argument("--season", type=int, default=CURRENT_SEASON,
                        help=f"Season year (default: {CURRENT_SEASON})")
    args = parser.parse_args()
    SEASON = args.season
    build_2026_data()
