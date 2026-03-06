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

def build_2026_data():
    print("=" * 60)
    print("BUILDING 2026 SEASON DATA")
    print("=" * 60)
    
    # ---- 1. Load fresh 2026 squad list ----
    print("\n1. Loading fresh 2026 squad list...")
    lists_path = BASE_DIR / "data" / "raw" / "player" / "footywire_2026_lists.csv"
    df = pd.read_csv(lists_path)
    print(f"   {len(df)} players from {df['Team'].nunique()} teams")
    
    # ---- 2. Merge with existing contract data ----
    print("\n2. Merging contract data...")
    contracts_path = BASE_DIR / "data" / "raw" / "player" / "footywire_contracts_2026.csv"
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
    complete_path = BASE_DIR / "data" / "raw" / "player" / "footywire_2026_complete.csv"
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
    complete_out = BASE_DIR / "data" / "raw" / "player" / "footywire_2026_complete.csv"
    merged.to_csv(complete_out, index=False)
    print(f"   Saved {complete_out.name}: {len(merged)} players, {len(merged.columns)} columns")
    
    # ---- 5. Create squads_2026.csv in app format ----
    print("\n5. Creating squads_2026.csv...")
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
    squads_out["Season"] = 2026
    squads_out["Matches_Current"] = 0  # No games played yet
    
    squads_path = BASE_DIR / "data" / "raw" / "player" / "squads_2026.csv"
    squads_out.to_csv(squads_path, index=False)
    print(f"   Saved squads_2026.csv: {len(squads_out)} players")
    
    # ---- 6. Create 2026 player stats with 2025 fallback ----
    print("\n6. Creating player_stats_2026.csv with 2025 ratings fallback...")
    stats_2025_path = BASE_DIR / "data" / "raw" / "player" / "player_stats_2025.csv"
    
    if stats_2025_path.exists():
        stats_2025 = pd.read_csv(stats_2025_path)
        print(f"   Loaded 2025 stats: {len(stats_2025)} players, {len(stats_2025.columns)} columns")
        
        # Key rating columns to carry forward
        rating_cols = [c for c in stats_2025.columns if any(k in c.lower() for k in 
            ["rating", "average", "avg", "rank", "percentage", "efficiency",
             "disposal", "goal", "tackle", "mark", "inside50", "clearance",
             "contested", "metres", "intercept", "rebound", "spoil", "pressure"])]
        
        # Also include the standard per-game averages
        keep_cols = ["Player", "Team"] + rating_cols
        keep_cols = [c for c in keep_cols if c in stats_2025.columns]
        
        stats_2025_subset = stats_2025[keep_cols].copy()
        stats_2025_subset.rename(columns={"Team": "Team_2025"}, inplace=True)
        
        # Merge: use 2026 squad as base, bring in 2025 ratings
        stats_2026 = squads_out[["Player", "Team", "Jumper", "Position", "Height", "DOB", "Age_Decimal", "Matches_Career"]].copy()
        stats_2026.rename(columns={"Matches_Career": "Matches", "Age_Decimal": "Age"}, inplace=True)
        stats_2026["Matches"] = 0  # No 2026 games played yet
        stats_2026 = stats_2026.merge(stats_2025_subset, on="Player", how="left", suffixes=("", "_2025"))
        
        # Clean up: use 2026 team, drop the 2025 team column
        if "Team_2025" in stats_2026.columns:
            stats_2026.drop(columns=["Team_2025"], inplace=True)
        
        matched = stats_2026[rating_cols[0] if rating_cols else "Player"].notna().sum() if rating_cols else 0
        print(f"   Matched {matched}/{len(stats_2026)} players with 2025 ratings")
        
        stats_2026_path = BASE_DIR / "data" / "raw" / "player" / "player_stats_2026.csv"
        stats_2026.to_csv(stats_2026_path, index=False)
        print(f"   Saved player_stats_2026.csv: {len(stats_2026)} players, {len(stats_2026.columns)} columns")
    else:
        print("   ⚠️ No 2025 stats file found - creating minimal 2026 stats")
        stats_2026 = squads_out[["Player", "Team", "Jumper", "Position", "Height", "DOB", "Age_Decimal", "Matches_Career"]].copy()
        stats_2026.rename(columns={"Matches_Career": "Matches", "Age_Decimal": "Age"}, inplace=True)
        stats_2026["Matches"] = 0
        stats_2026_path = BASE_DIR / "data" / "raw" / "player" / "player_stats_2026.csv"
        stats_2026.to_csv(stats_2026_path, index=False)
    
    # ---- 7. Merge traits data ----
    print("\n7. Merging traits data...")
    traits_path = BASE_DIR / "data" / "raw" / "player" / "footywire_2026_with_traits.csv"
    if traits_path.exists():
        traits_df = pd.read_csv(traits_path)
        trait_cols = [c for c in traits_df.columns if "Rating" in c or "Overall" in c or "data_provider" in c]
        if trait_cols:
            traits_subset = traits_df[["Player", "Team"] + trait_cols].copy()
            traits_out_path = BASE_DIR / "data" / "raw" / "traits" / "traits_2026.csv"
            traits_subset.to_csv(traits_out_path, index=False)
            has_traits = traits_subset["Overall_Rating"].notna().sum() if "Overall_Rating" in traits_subset.columns else 0
            print(f"   Saved traits_2026.csv: {has_traits} players with trait ratings")
    else:
        print("   ⚠️ No traits data found for 2026")
    
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
    print("✅ 2026 DATA BUILD COMPLETE")
    print("=" * 60)
    
    return len(squads_out)


if __name__ == "__main__":
    build_2026_data()
