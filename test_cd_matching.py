#!/usr/bin/env python3
"""Test CD ID matching vs name matching"""
import pandas as pd

traits = pd.read_excel('2025 Traits ENRICHED.xlsx')
players = pd.read_excel('Wheelo_Player_Data.xlsx')

# Find traits players with abbreviated names (having '.')
abbrev_players = traits[traits['Player_Full'].str.contains(r'\.', na=False, regex=True)]
print(f'Traits players with abbreviated names: {len(abbrev_players)}')
print(f'With CD ID: {abbrev_players["champion_data_id"].notna().sum()}')

# Check if we can match by CD ID
print()
print('Can these be matched to Wheelo by CD ID?')
matched = 0
for _, row in abbrev_players.head(15).iterrows():
    cd_id = row['champion_data_id']
    if pd.notna(cd_id):
        w = players[players['champion_data_id'] == cd_id]
        if len(w) > 0:
            print(f'  {row["Player_Full"]} -> {w["Player"].iloc[0]} (CD ID {int(cd_id)})')
            matched += 1
        else:
            print(f'  {row["Player_Full"]} - no match in Wheelo for CD ID {int(cd_id)}')
    else:
        print(f'  {row["Player_Full"]} - no CD ID')

print(f'\nMatched: {matched} of {len(abbrev_players.head(15))}')
