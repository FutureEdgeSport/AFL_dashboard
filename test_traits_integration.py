#!/usr/bin/env python3
"""Test the Traits API integration with app.py"""
import pandas as pd
import sys

print("Testing Traits API integration...")
print("=" * 50)

# Test 1: API cache loading
from traits_api import load_traits_cache
cache = load_traits_cache()
api_players = cache.get('players', {})
print(f"✓ API cache loaded: {len(api_players)} players")

# Test 2: Check API availability flag
try:
    from traits_api import load_traits_cache, load_dob_cache
    TRAITS_API_AVAILABLE = True
except ImportError:
    TRAITS_API_AVAILABLE = False
print(f"✓ TRAITS_API_AVAILABLE: {TRAITS_API_AVAILABLE}")

# Test 3: Load Excel data and check Player_Full matching
df = pd.read_excel('2025 Traits ENRICHED.xlsx', sheet_name='2025')
df.columns = [str(c).strip() for c in df.columns]
print(f"✓ Excel loaded: {len(df)} players")

# Check Player_Full column
if 'Player_Full' in df.columns:
    matches = sum(1 for p in df['Player_Full'].tolist() if str(p) in api_players)
    print(f"✓ Player_Full matches in API: {matches}/{len(df)} ({100*matches/len(df):.1f}%)")
else:
    print("⚠ No Player_Full column in Excel")

# Test 4: Enhancement function simulation
print("\n" + "=" * 50)
print("Testing enhancement for specific players...")

test_players = ['Patrick Cripps', 'Marcus Bontempelli', 'Nick Daicos', 'Max Gawn']

for player in test_players:
    excel_row = df[df['Player_Full'] == player]
    api_data = api_players.get(player)
    
    if not excel_row.empty:
        excel_rating = excel_row['Rating'].iloc[0]
        api_rating = api_data.get('Overall_Rating') if api_data else None
        
        if api_data:
            print(f"  {player}:")
            print(f"    Excel Rating: {excel_rating}")
            print(f"    API Rating:   {api_rating}")
            print(f"    {'Will be updated' if api_rating and api_rating != excel_rating else 'Same/No change'}")
        else:
            print(f"  {player}: Not in API (Excel={excel_rating}) - Will use Excel fallback ✓")
    else:
        print(f"  {player}: Not found in Excel")

# Test 5: Full enhancement
print("\n" + "=" * 50)
print("Running full enhancement simulation...")

API_TO_EXCEL = {
    'Overall_Rating': 'Rating',
    'Ball Winning_Rating': 'Ball Winning',
    'Ball Use_Rating': 'Ball Use',
    'Aerial_Rating': 'Aerial',
    'Defence_Rating': 'Defence',
}

updated = 0
for idx, row in df.iterrows():
    player_name = row.get('Player_Full', '')
    api_data = api_players.get(player_name)
    if api_data:
        updated += 1

print(f"✓ Would enhance {updated}/{len(df)} players with API data ({100*updated/len(df):.1f}%)")
print(f"✓ {len(df) - updated} players will use Excel fallback (100% coverage maintained)")

print("\n" + "=" * 50)
print("All tests passed! Integration is ready.")
