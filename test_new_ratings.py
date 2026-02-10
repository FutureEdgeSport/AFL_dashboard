#!/usr/bin/env python3
"""Test script for the new sophisticated rating system."""

import sys
sys.path.insert(0, '.')
import pandas as pd
import numpy as np
from data_pipeline.compute_team_summary import compute_team_summary, zscore_to_rating

print("Testing zscore_to_rating function:")
print("-" * 40)
for z in [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]:
    rating = zscore_to_rating(z)
    print(f"  Z={z:+5.1f} -> Rating={rating}")

print("\n" + "="*80)

# Load raw team data with proper filtering
raw_df = pd.read_csv('data/raw/team/team_stats_2025.csv')

# Remove any non-team rows
raw_df = raw_df[raw_df['Team'].notna()]
raw_df = raw_df[~raw_df['Team'].astype(str).str.contains('Total|Average|nan', case=False, na=False)]
raw_df = raw_df[~raw_df['Team'].astype(str).str.match(r'^\d+$')]

print(f"Computing ratings for {len(raw_df)} teams...")

# Compute new summary
summary_df = compute_team_summary(raw_df, 2025)

# Show results
print("\nNEW SOPHISTICATED RATING SYSTEM (50-99 scale):")
print("-" * 80)
cols_to_show = ['Team', 'Ball Winning Ranking', 'Ball Movement Ranking', 'Scoring Ranking', 
                'Defence Ranking', 'Pressure Ranking', 'Health Check Ranking', 'Overall Rating']
result = summary_df[cols_to_show].sort_values('Overall Rating', ascending=False)
print(result.to_string(index=False))

print("\n\nRATING DISTRIBUTION STATS:")
print("-" * 80)
for col in cols_to_show[1:]:
    vals = summary_df[col].dropna()
    print(f"{col:25} | Min:{vals.min():3.0f} | Max:{vals.max():3.0f} | Mean:{vals.mean():5.1f} | Std:{vals.std():5.1f}")
