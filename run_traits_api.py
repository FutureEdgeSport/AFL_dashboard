#!/usr/bin/env python3
"""
Run Traits API against Footywire player DOB data.

Accepts --season flag (defaults to CURRENT_SEASON from config).

This script:
1. Loads DOBs from the Footywire season scrape
2. Updates the DOB cache
3. Queries the Traits API for all players
4. Saves enhanced data back to the season dataset
"""
import argparse
import pandas as pd
import json
import time
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent))
from config.constants import CURRENT_SEASON
from utils.safe_io import safe_csv_write

# Module-level season, overridden by --season arg in main()
SEASON = CURRENT_SEASON

# Import from traits_api module
from traits_api import (
    query_traits_api,
    parse_traits_response,
    load_dob_cache,
    save_dob_cache,
    load_traits_cache,
    save_traits_cache
)


def load_footywire_dobs():
    """Load DOBs from the Footywire scrape."""
    path = Path(f"data/raw/player/footywire_{SEASON}_complete.csv")
    if not path.exists():
        print(f"Error: {path} not found")
        return {}
    
    df = pd.read_csv(path)
    dob_dict = {}
    
    for _, row in df.iterrows():
        player = row['Player']
        dob = row['DOB']
        if pd.notna(player) and pd.notna(dob):
            dob_dict[player] = dob
    
    return dob_dict


def update_dob_cache_from_footywire():
    """Update the DOB cache with Footywire data."""
    print("Loading existing DOB cache...")
    dob_cache = load_dob_cache()
    original_count = len(dob_cache)
    
    print("Loading Footywire DOBs...")
    footywire_dobs = load_footywire_dobs()
    print(f"  Found {len(footywire_dobs)} players with DOBs")
    
    # Update cache with new DOBs (Footywire is authoritative for current lists)
    new_count = 0
    updated_count = 0
    
    for player, dob in footywire_dobs.items():
        if player not in dob_cache:
            dob_cache[player] = dob
            new_count += 1
        elif dob_cache[player] != dob:
            # Update if different (Footywire is more recent)
            dob_cache[player] = dob
            updated_count += 1
    
    save_dob_cache(dob_cache)
    print(f"  DOB cache updated: {new_count} new, {updated_count} updated")
    print(f"  Total DOBs in cache: {len(dob_cache)}")
    
    return dob_cache


def run_traits_api_for_season():
    """Query Traits API for all players in the target season."""
    print("\n" + "=" * 60)
    print(f"Running Traits API for {SEASON} Players")
    print("=" * 60 + "\n")
    
    # Load player data
    df = pd.read_csv(f"data/raw/player/footywire_{SEASON}_complete.csv")
    print(f"Loaded {len(df)} players from {SEASON} dataset")
    
    # Load caches
    dob_cache = load_dob_cache()
    traits_cache = load_traits_cache()
    
    # Stats
    cached_count = 0
    api_success = 0
    api_failed = 0
    no_dob = 0
    api_calls = 0
    
    results = {}
    
    print("\nQuerying Traits API...")
    total = len(df)
    last_save = 0  # Track when we last saved cache
    
    for idx, row in df.iterrows():
        player = row['Player']
        dob = row['DOB'] if pd.notna(row.get('DOB')) else dob_cache.get(player)
        
        # Progress indicator
        if (idx + 1) % 50 == 0 or idx == 0:
            print(f"  Progress: {idx + 1}/{total} ({(idx+1)/total*100:.1f}%)")
        
        # Check traits cache first — but re-query if cached data is from a previous season
        if player in traits_cache.get('players', {}):
            cached = traits_cache['players'][player]
            cached_season = str(cached.get('Season_API', ''))
            if str(SEASON) in cached_season:
                results[player] = cached
                cached_count += 1
                continue
            # Stale season — fall through to re-query
        
        # Query API (DOB used to construct data_provider_id, not sent directly)
        try:
            response = query_traits_api(player, dob)
        except Exception as e:
            print(f"  API exception for {player}: {e}")
            api_failed += 1
            continue
        api_calls += 1
        
        if response:
            parsed = parse_traits_response(response)
            if parsed:
                results[player] = parsed
                traits_cache.setdefault('players', {})[player] = parsed
                api_success += 1
            else:
                api_failed += 1
        else:
            api_failed += 1
        
        # Rate limiting - be nice to the API
        if api_calls % 10 == 0:
            time.sleep(1)
        elif api_calls % 3 == 0:
            time.sleep(0.3)
        
        # Incremental cache save every 25 API calls to prevent data loss on timeout
        if api_calls - last_save >= 25:
            traits_cache['timestamp'] = datetime.now().isoformat()
            save_traits_cache(traits_cache)
            last_save = api_calls
            print(f"  💾  Cache saved ({api_success} successes so far)")
    
    # Save updated cache
    traits_cache['timestamp'] = datetime.now().isoformat()
    save_traits_cache(traits_cache)
    
    print(f"\n{'=' * 60}")
    print("API Query Results:")
    print(f"  From cache: {cached_count}")
    print(f"  API success: {api_success}")
    print(f"  API failed/not found: {api_failed}")
    print(f"  No DOB: {no_dob}")
    print(f"  Total with traits: {len(results)}")
    print(f"  Coverage: {len(results)/len(df)*100:.1f}%")
    
    return results


def enhance_dataset_with_traits(traits_results):
    """Add Traits API data to the season dataset."""
    print("\n" + "=" * 60)
    print(f"Enhancing {SEASON} Dataset with Traits Data")
    print("=" * 60 + "\n")
    
    # Load base data
    df = pd.read_csv(f"data/raw/player/footywire_{SEASON}_complete.csv")
    
    # Key traits columns to add
    trait_columns = [
        'Overall_Rating',
        'data_provider_id',
        'Team_API',
        'Season_API',
        'Position_API',
        # Individual trait ratings
        'Athleticism_Rating',
        'Kicking_Rating', 
        'Marking_Rating',
        'Handballing_Rating',
        'Tackling & Pressure_Rating',
        'Hit-Ups & Groundball_Rating',
        'Ruck_Rating'
    ]
    
    # Initialize columns
    for col in trait_columns:
        df[col] = None
    
    # Apply traits data
    matched = 0
    for idx, row in df.iterrows():
        player = row['Player']
        if player in traits_results:
            traits = traits_results[player]
            for col in trait_columns:
                if col in traits:
                    df.at[idx, col] = traits[col]
            matched += 1
    
    print(f"Matched traits for {matched}/{len(df)} players ({matched/len(df)*100:.1f}%)")
    
    # Save enhanced dataset (atomic write with backup)
    output_path = Path(f"data/raw/player/footywire_{SEASON}_with_traits.csv")
    safe_csv_write(df, output_path)
    print(f"\nSaved to: {output_path}")
    
    # Show sample
    print("\nSample of players with traits:")
    sample_cols = ['Player', 'Team', 'Overall_Rating', 'Athleticism_Rating', 'Kicking_Rating']
    sample = df[df['Overall_Rating'].notna()][sample_cols].head(10)
    print(sample.to_string())
    
    # Show top rated players
    print("\nTop 10 Overall Rated Players:")
    df['Overall_Rating'] = pd.to_numeric(df['Overall_Rating'], errors='coerce')
    top_rated = df[df['Overall_Rating'].notna()].nlargest(10, 'Overall_Rating')[sample_cols]
    print(top_rated.to_string(index=False))
    
    return df


def main():
    global SEASON

    parser = argparse.ArgumentParser(description="Run Traits API for AFL player data")
    parser.add_argument("--season", type=int, default=CURRENT_SEASON,
                        help=f"Season year (default: {CURRENT_SEASON})")
    args = parser.parse_args()
    SEASON = args.season

    print("=" * 60)
    print(f"Traits API Integration for {SEASON} Footywire Data")
    print("=" * 60)
    print()

    # Step 1: Update DOB cache with Footywire data
    try:
        update_dob_cache_from_footywire()
    except Exception as e:
        print(f"\n⚠️  DOB cache update failed: {e}")

    # Step 2: Run Traits API for all players
    try:
        traits_results = run_traits_api_for_season()
    except Exception as e:
        print(f"\n⚠️  Traits API query failed: {e}")
        traits_results = {}

    # Step 3: Enhance the dataset
    if traits_results:
        try:
            enhance_dataset_with_traits(traits_results)
        except Exception as e:
            print(f"\n⚠️  Dataset enhancement failed: {e}")
    else:
        print("\nNo traits data retrieved!")

    # Step 4: Snapshot traits for the current round (for Trait Rating Matrix)
    try:
        snapshot_traits_to_history()
    except Exception as e:
        print(f"\n⚠️  Traits snapshot failed: {e}")


def snapshot_traits_to_history():
    """Save current traits as a per-round snapshot for the Trait Rating Matrix.

    Overwrites the snapshot for the current round so re-running the API
    with fresh Traits Insights values updates the history correctly.
    """
    match_ratings_path = Path(f"data/raw/player/match_ratings_{SEASON}.csv")
    traits_path = Path(f"data/raw/traits/traits_{SEASON}.csv")

    if not match_ratings_path.exists() or not traits_path.exists():
        print("\nSnapshot: Missing match_ratings or traits file, skipping")
        return

    mr = pd.read_csv(match_ratings_path)
    if "Round" not in mr.columns or mr.empty:
        print("\nSnapshot: No round data in match_ratings, skipping")
        return
    current_round = int(mr["Round"].max())
    if current_round <= 0:
        return

    traits = pd.read_csv(traits_path)
    if "Overall_Rating" not in traits.columns:
        print("\nSnapshot: No Overall_Rating in traits file, skipping")
        return

    history_path = Path(f"data/raw/traits/traits_history_{SEASON}.csv")
    if history_path.exists():
        history = pd.read_csv(history_path)
    else:
        history = pd.DataFrame(columns=["Player", "Team", "Round", "Overall_Rating"])

    # Remove existing snapshot for current round (overwrite with fresh data)
    history = history[history["Round"] != current_round]

    snapshot = traits[["Player", "Team", "Overall_Rating"]].copy()
    snapshot["Round"] = current_round
    snapshot = snapshot[snapshot["Overall_Rating"].notna()]

    history = pd.concat([history, snapshot], ignore_index=True)
    safe_csv_write(history, history_path)
    print(f"\nSnapshot: Saved traits_history_{SEASON}.csv for R{current_round} ({len(snapshot)} players)")


if __name__ == "__main__":
    main()
