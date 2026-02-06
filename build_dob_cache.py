#!/usr/bin/env python3
"""
Build DOB database for all AFL players by scraping Wikipedia.
This should be run once to populate the cache, then incrementally
for new players.
"""
import pandas as pd
import time
import sys
from traits_api import get_dob_from_wikipedia, load_dob_cache, save_dob_cache

def main():
    # Load player data
    print("Loading player data...")
    df = pd.read_excel('AFL Player Ratings.xlsx', sheet_name='2025')
    
    # Get unique players with teams
    players = df[['Player', 'Team']].drop_duplicates()
    print(f"Found {len(players)} unique players")
    
    # Load existing cache
    cache = load_dob_cache()
    print(f"Existing cache has {len(cache)} entries")
    
    # Find players missing from cache
    missing = []
    for _, row in players.iterrows():
        if row['Player'] not in cache:
            missing.append(row)
    
    print(f"Need to fetch DOBs for {len(missing)} players")
    
    if not missing:
        print("All players already in cache!")
        return
    
    # Scrape DOBs
    found = 0
    not_found = []
    
    for idx, row in enumerate(missing):
        player = row['Player']
        team = row['Team']
        
        print(f"[{idx+1}/{len(missing)}] {player} ({team})...", end=' ', flush=True)
        
        dob = get_dob_from_wikipedia(player, team)
        
        if dob:
            cache[player] = dob
            found += 1
            print(f"✓ {dob}")
        else:
            cache[player] = None  # Mark as attempted but not found
            not_found.append(f"{player} ({team})")
            print("✗")
        
        # Save cache periodically
        if (idx + 1) % 20 == 0:
            save_dob_cache(cache)
            print(f"  [Cache saved: {len([k for k,v in cache.items() if v])} DOBs]")
        
        # Be nice to Wikipedia
        time.sleep(0.5)
    
    # Final save
    save_dob_cache(cache)
    
    # Summary
    print("\n" + "=" * 50)
    print(f"SUMMARY:")
    print(f"  Total players: {len(players)}")
    print(f"  DOBs found: {len([k for k,v in cache.items() if v])}")
    print(f"  DOBs missing: {len([k for k,v in cache.items() if v is None])}")
    print(f"  Success rate: {100 * len([k for k,v in cache.items() if v]) / len(players):.1f}%")
    
    if not_found:
        print(f"\nPlayers not found on Wikipedia ({len(not_found)}):")
        for p in not_found[:20]:
            print(f"  - {p}")
        if len(not_found) > 20:
            print(f"  ... and {len(not_found) - 20} more")


if __name__ == "__main__":
    main()
