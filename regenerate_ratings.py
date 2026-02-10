#!/usr/bin/env python3
"""Regenerate computed team data with the new sophisticated rating system."""

import sys
sys.path.insert(0, '/Users/marcuswagner/coding/AFL_dashboard')
import pandas as pd
from data_pipeline.compute_team_summary import compute_team_summary, compute_team_ladders
from pathlib import Path

data_dir = Path('/Users/marcuswagner/coding/AFL_dashboard/data')

# Process 2025 data
print("="*60)
print("REGENERATING TEAM RATINGS WITH NEW SOPHISTICATED SYSTEM")
print("="*60)

for season in [2025]:
    raw_path = data_dir / 'raw' / 'team' / f'team_stats_{season}.csv'
    
    if not raw_path.exists():
        print(f"Skipping {season} - no raw data")
        continue
    
    print(f"\nProcessing {season}...")
    
    # Load raw data
    raw_df = pd.read_csv(raw_path)
    
    # Remove non-team rows
    raw_df = raw_df[raw_df['Team'].notna()]
    raw_df = raw_df[~raw_df['Team'].astype(str).str.contains('Total|Average|nan', case=False, na=False)]
    raw_df = raw_df[~raw_df['Team'].astype(str).str.match(r'^\d+$')]
    
    print(f"  Found {len(raw_df)} teams")
    
    # Compute
    summary_df = compute_team_summary(raw_df, season)
    ladder_df = compute_team_ladders(summary_df)
    
    # Save
    summary_df.to_csv(data_dir / 'computed' / f'team_summary_{season}.csv', index=False)
    ladder_df.to_csv(data_dir / 'computed' / f'team_ladders_{season}.csv', index=False)
    
    print(f"  Saved team_summary_{season}.csv and team_ladders_{season}.csv")
    print(f"\n  Top 5 teams by Overall Rating:")
    print(summary_df[['Team', 'Overall Rating']].sort_values('Overall Rating', ascending=False).head().to_string(index=False))

print("\n" + "="*60)
print("DONE!")
print("="*60)
