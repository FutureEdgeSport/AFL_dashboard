#!/usr/bin/env python3
"""
Fetch traits from API for all players.
"""
import pandas as pd
import time
from traits_api import (
    load_dob_cache,
    query_traits_api, 
    parse_traits_response,
    load_traits_cache,
    save_traits_cache
)

def main():
    # Load player data
    print("Loading player data...")
    df = pd.read_excel('AFL Player Ratings.xlsx', sheet_name='2025')
    
    # Load DOB cache (used to construct data_provider_id for uncached players)
    dob_cache = load_dob_cache()
    dobs_with_values = {k: v for k, v in dob_cache.items() if v}
    print(f"DOBs available: {len(dobs_with_values)}")
    
    # Load existing traits cache
    traits_cache = load_traits_cache()
    cached_count = len(traits_cache.get('players', {}))
    print(f"Existing traits cache: {cached_count} players")
    
    # Get unique players
    players = df['Player'].unique()
    print(f"Total players to process: {len(players)}")
    
    # Filter to those not cached
    to_fetch = []
    for player in players:
        if player not in traits_cache.get('players', {}):
            dob = dobs_with_values.get(player)
            to_fetch.append((player, dob))
    
    print(f"Players to fetch: {len(to_fetch)}")
    
    if not to_fetch:
        print("All players already cached!")
        return
    
    # Fetch in batches
    success = 0
    not_found = []
    
    for idx, (player, dob) in enumerate(to_fetch):
        print(f"[{idx+1}/{len(to_fetch)}] {player}...", end=' ', flush=True)
        
        result = query_traits_api(player, dob)
        
        if result:
            parsed = parse_traits_response(result)
            if parsed:
                traits_cache.setdefault('players', {})[player] = parsed
                success += 1
                overall = parsed.get('Overall_Rating', 'N/A')
                print(f"✓ (Rating: {overall})")
            else:
                print("✗ (parse error)")
        else:
            not_found.append(player)
            print("✗")
        
        # Save periodically
        if (idx + 1) % 20 == 0:
            save_traits_cache(traits_cache)
            print(f"  [Cache saved: {len(traits_cache.get('players', {}))} players]")
        
        # Rate limiting
        time.sleep(0.3)
    
    # Final save
    save_traits_cache(traits_cache)
    
    # Summary
    print("\n" + "=" * 50)
    print(f"SUMMARY:")
    print(f"  Attempted: {len(to_fetch)}")
    print(f"  Success: {success}")
    print(f"  Not found: {len(not_found)}")
    print(f"  Total cached: {len(traits_cache.get('players', {}))}")
    
    if not_found:
        print(f"\nPlayers not found in API ({len(not_found)}):")
        for p in not_found[:20]:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
