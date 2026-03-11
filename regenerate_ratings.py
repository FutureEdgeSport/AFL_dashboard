#!/usr/bin/env python3
"""Regenerate computed team data with the new sophisticated rating system."""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd
from data_pipeline.compute_team_summary import compute_team_summary, compute_team_ladders
from config.constants import CURRENT_SEASON
from utils.safe_io import safe_csv_write

data_dir = BASE_DIR / 'data'

# Process 2025 data
print("="*60)
print("REGENERATING TEAM RATINGS WITH NEW SOPHISTICATED SYSTEM")
print("="*60)

for season in [CURRENT_SEASON, CURRENT_SEASON - 1]:
    for block_suffix, block_label in [("", "Season"), ("_L10", "Last 10"), ("_L5", "Last 5")]:
        raw_path = data_dir / 'raw' / 'team' / f'team_stats_{season}{block_suffix}.csv'
        
        if not raw_path.exists():
            print(f"Skipping {season} {block_label} - no raw data")
            continue
        
        print(f"\nProcessing {season} {block_label}...")
        
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
        
        # Save with block suffix
        safe_csv_write(summary_df, data_dir / 'computed' / f'team_summary_{season}{block_suffix}.csv')
        safe_csv_write(ladder_df, data_dir / 'computed' / f'team_ladders_{season}{block_suffix}.csv')
        
        print(f"  Saved team_summary_{season}{block_suffix}.csv and team_ladders_{season}{block_suffix}.csv")
        print(f"\n  Top 5 teams by Overall Rating:")
        print(summary_df[['Team', 'Overall Rating']].sort_values('Overall Rating', ascending=False).head().to_string(index=False))

print("\n" + "="*60)
print("DONE!")
print("="*60)
