#!/usr/bin/env python3
"""Quick test to verify computed files are loaded correctly."""
from pathlib import Path
import pandas as pd

scenarios = [
    (2025, False, 'team_summary_2025.csv'),
    (2025, True, 'team_summary_2025_L10.csv'),
    (2024, False, 'team_summary_2024.csv'),
    (2023, False, 'team_summary_2023.csv'),
    (2022, False, 'team_summary_2022.csv'),
    (2021, False, 'team_summary_2021.csv'),
]

base_path = Path('data/computed')

print("Verifying FIFA-style ratings in computed files:")
print("-" * 60)

for season, last10, expected_file in scenarios:
    if last10:
        computed_path = base_path / f'team_summary_{season}_L10.csv'
    else:
        computed_path = base_path / f'team_summary_{season}.csv'
    
    if computed_path.exists():
        df = pd.read_csv(computed_path)
        overall_range = f'{df["Overall Rating"].min()}-{df["Overall Rating"].max()}'
        top_team = df.sort_values('Overall Rating', ascending=False).iloc[0]['Team']
        print(f'OK {season} {"L10" if last10 else "Season"}: Range {overall_range}, Top: {top_team}')
    else:
        print(f'MISSING {season} {"L10" if last10 else "Season"}: {computed_path}')
