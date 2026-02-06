#!/usr/bin/env python3
"""Test that API enhancement only applies to current season"""
import pandas as pd

# Load Excel directly for different seasons
print("Testing season-specific data (direct from Excel)...")
print("=" * 60)

xl = pd.ExcelFile('2025 Traits ENRICHED.xlsx')
print(f"Available sheets: {xl.sheet_names}")

# Check Patrick Cripps across seasons
for season in ['2025', '2024', '2023']:
    if season in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name=season)
        cripps = df[df['Player'].str.contains('Cripps', case=False, na=False)]
        if not cripps.empty:
            r = cripps.iloc[0]
            print(f"\n{season}: Patrick Cripps (from Excel)")
            print(f"  Rating: {r.get('Rating', 'N/A')}")
            print(f"  Ball Winning: {r.get('Ball Winning', 'N/A')}")
            print(f"  Ball Use: {r.get('Ball Use', 'N/A')}")

# Now test what the API has
print("\n" + "=" * 60)
print("API data (latest only):")
from traits_api import load_traits_cache
cache = load_traits_cache()
api_data = cache.get('players', {}).get('Patrick Cripps', {})
if api_data:
    print(f"  Rating: {api_data.get('Overall_Rating')}")
    print(f"  Ball Winning: {api_data.get('Ball Winning_Rating')}")
    print(f"  Ball Use: {api_data.get('Ball Use_Rating')}")

print("\n" + "=" * 60)
print("Expected behavior:")
print("  - 2025: May be enhanced with API data (same or updated)")
print("  - 2024: Should use Excel data ONLY (historical)")
print("  - 2023: Should use Excel data ONLY (historical)")
