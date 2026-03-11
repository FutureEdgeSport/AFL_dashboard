#!/usr/bin/env python3
"""
Run Traits API against the new Footywire 2026 DOB data.

This script:
1. Loads DOBs from the Footywire 2026 scrape
2. Updates the DOB cache
3. Queries the Traits API for all players
4. Saves enhanced data back to the 2026 dataset
"""
import pandas as pd
import json
import time
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent))
from config.constants import CURRENT_SEASON

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
    path = Path(f"data/raw/player/footywire_{CURRENT_SEASON}_complete.csv")
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


def run_traits_api_for_2026_players():
    """Query Traits API for all 2026 players."""
    print("\n" + "=" * 60)
    print(f"Running Traits API for {CURRENT_SEASON} Players")
    print("=" * 60 + "\n")
    
    # Load player data
    df = pd.read_csv(f"data/raw/player/footywire_{CURRENT_SEASON}_complete.csv")
    print(f"Loaded {len(df)} players from {CURRENT_SEASON} dataset")
    
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
        dob = row['DOB'] if pd.notna(row['DOB']) else dob_cache.get(player)
        
        # Progress indicator
        if (idx + 1) % 50 == 0 or idx == 0:
            print(f"  Progress: {idx + 1}/{total} ({(idx+1)/total*100:.1f}%)")
        
        # Check traits cache first
        if player in traits_cache.get('players', {}):
            results[player] = traits_cache['players'][player]
            cached_count += 1
            continue
        
        # Skip if no DOB
        if not dob:
            no_dob += 1
            continue
        
        # Query API
        try:
            response = query_traits_api(player, dob)
        except Exception as e:
            print(f"  API exception for {player}: {e}")
            api_failed += 1
            continue
        api_calls += 1
        
        if response:
            parsed = parse_traits_response(response, competition="AFL")
            if parsed:
                results[player] = parsed
                traits_cache.setdefault('players', {})[player] = parsed
                api_success += 1
            else:
                # No AFL participation (VFL-only or no data)
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


def enhance_2026_dataset_with_traits(traits_results):
    """Add Traits API data to the 2026 dataset."""
    print("\n" + "=" * 60)
    print("Enhancing 2026 Dataset with Traits Data")
    print("=" * 60 + "\n")
    
    # Load base data
    df = pd.read_csv(f"data/raw/player/footywire_{CURRENT_SEASON}_complete.csv")
    
    # Key traits columns to add
    trait_columns = [
        'Overall_Rating',
        'data_provider_id',
        'Team_API',
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
    
    # Save enhanced dataset
    output_path = Path(f"data/raw/player/footywire_{CURRENT_SEASON}_with_traits.csv")
    df.to_csv(output_path, index=False)
    print(f"\nSaved to: {output_path}")
    
    # Show sample
    print("\nSample of players with traits:")
    sample_cols = ['Player', 'Team', 'Overall_Rating', 'Athleticism_Rating', 'Kicking_Rating']
    sample = df[df['Overall_Rating'].notna()][sample_cols].head(10)
    print(sample.to_string())
    
    # Show top rated players
    print("\nTop 10 Overall Rated Players:")
    top_rated = df[df['Overall_Rating'].notna()].nlargest(10, 'Overall_Rating')[sample_cols]
    print(top_rated.to_string(index=False))
    
    return df


def main():
    print("=" * 60)
    print(f"Traits API Integration for {CURRENT_SEASON} Footywire Data")
    print("=" * 60)
    print()
    
    # Step 1: Update DOB cache with Footywire data
    try:
        update_dob_cache_from_footywire()
    except Exception as e:
        print(f"\n\u26a0\ufe0f  DOB cache update failed: {e}")
    
    # Step 2: Run Traits API for all players
    try:
        traits_results = run_traits_api_for_2026_players()
    except Exception as e:
        print(f"\n\u26a0\ufe0f  Traits API query failed: {e}")
        traits_results = {}
    
    # Step 3: Enhance the 2026 dataset
    if traits_results:
        try:
            enhance_2026_dataset_with_traits(traits_results)
        except Exception as e:
            print(f"\n\u26a0\ufe0f  Dataset enhancement failed: {e}")
    else:
        print("\nNo traits data retrieved!")


if __name__ == "__main__":
    main()
