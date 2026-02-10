#!/usr/bin/env python
"""Quick test for Team Compare changes."""
import sys
sys.path.insert(0, '.')

from app import load_team_ladders

print("Testing Team Compare data loading...")

# Test 2025 Season
ladders1 = load_team_ladders(2025, last10=False)
print(f"2025 Season: {len(ladders1)} teams")

# Test 2025 Last 10
ladders2 = load_team_ladders(2025, last10=True)
print(f"2025 Last 10: {len(ladders2)} teams")

# Test 2024 
ladders3 = load_team_ladders(2024, last10=False)
print(f"2024 Season: {len(ladders3)} teams")

# Get Fremantle data from each
fre1 = ladders1[ladders1["Team"].str.contains("Fremantle", case=False)]
fre2 = ladders2[ladders2["Team"].str.contains("Fremantle", case=False)]
fre3 = ladders3[ladders3["Team"].str.contains("Fremantle", case=False)]

print("\nFremantle Ball Winning Ranking:")
print(f"  2025 Season: {fre1.iloc[0]['Ball Winning Ranking'] if not fre1.empty else 'N/A'}")
print(f"  2025 Last 10: {fre2.iloc[0]['Ball Winning Ranking'] if not fre2.empty else 'N/A'}")
print(f"  2024 Season: {fre3.iloc[0]['Ball Winning Ranking'] if not fre3.empty else 'N/A'}")

print("\n✅ Team Compare data loading works!")
