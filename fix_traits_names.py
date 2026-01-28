#!/usr/bin/env python3
"""
Fix abbreviated player names in 2025 Traits ENRICHED using CD ID lookup
"""
import pandas as pd

# Load files
traits = pd.read_excel('2025 Traits ENRICHED.xlsx')
cd_lookup = pd.read_excel('champion_data_player_ids.xlsx')

print(f"Loaded {len(traits)} traits rows")
print(f"Loaded {len(cd_lookup)} CD ID entries")

# Create lookup from CD ID to full name
cd_to_name = {}
for _, row in cd_lookup.iterrows():
    if pd.notna(row.get('champion_data_id')):
        cd_to_name[int(row['champion_data_id'])] = row['full_name']

# Manual mapping for abbreviated names to full names
# Based on team rosters and common knowledge
ABBREV_TO_FULL = {
    # Brisbane
    'C. Ah Chee': 'Callum Ah Chee',
    
    # Carlton
    'T. De Koning': 'Tom De Koning',
    
    # Collingwood
    'J. De Goey': 'Jordan De Goey',
    
    # Geelong
    'S. De Koning': 'Sam De Koning',
    
    # Melbourne
    'J. van Rooyen': 'Jacob van Rooyen',
    
    # Port Adelaide
    'La. Jones': 'Lachie Jones',
    
    # North Melbourne
    'R. Hansen Jr': 'Rory Hansen Jr',
    
    # Sydney
    'E. Gulden': 'Errol Gulden',
    'B. Grundy': 'Brodie Grundy',
    'C. Mills': 'Callum Mills',
    'I. Heeney': 'Isaac Heeney',
    'N. Blakey': 'Nick Blakey',
    'T. McCartin': 'Tom McCartin',
    'T. Papley': 'Tom Papley',
    'Ch. Warner': 'Chad Warner',
    'Co. Warner': 'Corey Warner',
    'J. Lloyd': 'Jake Lloyd',
    'W. Hayward': 'Will Hayward',
    'M. Roberts': 'Matt Roberts',
    'C. Cleary': 'Caiden Cleary',
    'B. Campbell': 'Braeden Campbell',
    'P. Ladhams': 'Peter Ladhams',
    'J. Amartey': 'Joel Amartey',
    'H. McLean': 'Hayden McLean',
    'J. Rowbottom': 'James Rowbottom',
    'R. Bice': 'Ryan Bice',
    'J. McInerney': 'Justin McInerney',
    'O. Florent': 'Oliver Florent',
    'J. Buller': 'Jacob Buller',
    'L. Melican': 'Lewis Melican',
    'T. Adams': 'Taylor Adams',
    'D. Rampe': 'Dane Rampe',
    'A. Sheldrick': 'Angus Sheldrick',
    'H. Cunningham': 'Harry Cunningham',
    'S. Wicks': 'Sam Wicks',
    'J. Jordon': 'James Jordon',
    'T. Hanily': 'Toby Hanily',
    'A. Francis': 'Aaron Francis',
    'J. Hamling': 'Joel Hamling',
    'J. Dattoli': 'Jack Dattoli',
    'B. Paton': 'Ben Paton',
    
    # West Coast
    'Bailey J. Williams': 'Bailey Williams',
}

# Fix the abbreviated names
fixed_count = 0
for idx, row in traits.iterrows():
    player_full = row['Player_Full']
    if pd.notna(player_full) and player_full in ABBREV_TO_FULL:
        new_name = ABBREV_TO_FULL[player_full]
        traits.at[idx, 'Player_Full'] = new_name
        fixed_count += 1
        
        # Also try to add CD ID if missing
        if pd.isna(row['champion_data_id']):
            # Find CD ID for the full name
            match = cd_lookup[cd_lookup['full_name'].str.lower() == new_name.lower()]
            if len(match) > 0 and pd.notna(match['champion_data_id'].iloc[0]):
                traits.at[idx, 'champion_data_id'] = match['champion_data_id'].iloc[0]
                print(f"  Fixed: {player_full} -> {new_name} (added CD ID {int(match['champion_data_id'].iloc[0])})")
            else:
                print(f"  Fixed: {player_full} -> {new_name} (no CD ID found)")
        else:
            print(f"  Fixed: {player_full} -> {new_name}")

print(f"\nFixed {fixed_count} abbreviated names")

# Save
traits.to_excel('2025 Traits ENRICHED.xlsx', index=False)
print("Saved 2025 Traits ENRICHED.xlsx")

# Verify
remaining = traits[traits['Player_Full'].str.contains(r'\.', na=False)]
if len(remaining) > 0:
    print(f"\nRemaining abbreviated names ({len(remaining)}):")
    for name in remaining['Player_Full'].unique():
        print(f"  {name}")
else:
    print("\n✅ All abbreviated names have been fixed!")
