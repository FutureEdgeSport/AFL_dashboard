#!/usr/bin/env python3
"""Verify the consolidated historical workbook."""
import pandas as pd

xl = pd.ExcelFile('data/AFL_Historical_2012_2025.xlsx')

# Show metadata
print('=== METADATA ===')
meta = pd.read_excel(xl, sheet_name='Metadata')
print(meta.to_string(index=False))
print()

# Check key players across years
print('=== KEY PLAYER HISTORY: Patrick Cripps ===')
stats = pd.read_excel(xl, sheet_name='Player_Stats_All')
cripps = stats[stats.Player == 'Patrick Cripps'][['Season', 'Team', 'Age', 'Matches', 'Disposals', 'Goals_Total']]
print(cripps.to_string(index=False))
print()

# Check traits history
print('=== TRAITS HISTORY: Patrick Cripps ===')
traits = pd.read_excel(xl, sheet_name='Player_Traits_All')
cripps_traits = traits[traits.Player == 'Patrick Cripps'][['Season', 'Team', 'Rating', 'Ball Winning']]
print(cripps_traits.to_string(index=False))
print()

# Registry lookup
print('=== REGISTRY: Patrick Cripps ===')
reg = pd.read_excel(xl, sheet_name='Player_Registry')
cripps_reg = reg[reg.Player == 'Patrick Cripps']
print(cripps_reg.T.to_string())
print()

# Team reference
print('=== TEAM REFERENCE (Sample) ===')
teams = pd.read_excel(xl, sheet_name='Team_Reference')
print(teams[['Team', 'Abbreviation', 'Footywire_Slug']].to_string(index=False))
