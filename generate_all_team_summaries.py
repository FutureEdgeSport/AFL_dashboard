#!/usr/bin/env python3
"""
generate_all_team_summaries.py

Generates FIFA-style team summary ratings (50-99 scale) for:
- All seasons (2021-2025)
- L10 (Last 10 games) data
- L5 (Last 5 games) data if available

This ensures consistency with the 2025 Season rating system across all data blocks.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Add parent directory to path to import compute_team_summary
sys.path.insert(0, str(Path(__file__).parent))

from data_pipeline.compute_team_summary import (
    compute_team_summary,
    compute_team_ladders,
    normalize_team_names,
    CATEGORY_METRICS
)


def load_raw_team_data(data_dir: Path, season_or_block: str) -> pd.DataFrame:
    """
    Load raw team data for a season or block.
    
    Args:
        data_dir: Path to data directory
        season_or_block: Either a year like "2025" or a block like "L10"
    """
    raw_path = data_dir / "raw" / "team" / f"team_stats_{season_or_block}.csv"
    
    if not raw_path.exists():
        print(f"  ⚠️ Raw data not found: {raw_path}")
        return pd.DataFrame()
    
    raw_df = pd.read_csv(raw_path)
    
    # Clean up - remove any non-team rows
    raw_df = raw_df[raw_df["Team"].notna()]
    raw_df = raw_df[~raw_df["Team"].astype(str).str.contains("Total|Average|nan", case=False, na=False)]
    raw_df = raw_df[~raw_df["Team"].astype(str).str.match(r'^\d+$')]  # Remove numeric-only team names
    
    return raw_df


def generate_season_summaries(data_dir: Path, seasons: list[int] = None):
    """
    Generate computed team summaries for all specified seasons.
    """
    if seasons is None:
        seasons = [2021, 2022, 2023, 2024, 2025]
    
    output_dir = data_dir / "computed"
    output_dir.mkdir(exist_ok=True)
    
    results = {}
    
    for season in seasons:
        print(f"\n📊 Processing {season} Season...")
        
        raw_df = load_raw_team_data(data_dir, str(season))
        
        if raw_df.empty:
            print(f"  ❌ No data available for {season}")
            continue
        
        # Compute summary using FIFA-style ratings
        try:
            summary_df = compute_team_summary(raw_df, season)
            ladder_df = compute_team_ladders(summary_df)
            
            # Save summary
            summary_path = output_dir / f"team_summary_{season}.csv"
            summary_df.to_csv(summary_path, index=False)
            print(f"  ✅ Saved {summary_path.name}")
            
            # Save ladder
            ladder_path = output_dir / f"team_ladders_{season}.csv"
            ladder_df.to_csv(ladder_path, index=False)
            print(f"  ✅ Saved {ladder_path.name}")
            
            # Show top 5 teams
            top5 = summary_df.sort_values("Overall Rating", ascending=False).head()
            print(f"  Top 5: {', '.join(top5['Team'].tolist())}")
            
            results[f"{season}_Season"] = summary_df
            
        except Exception as e:
            print(f"  ❌ Error computing {season}: {e}")
            import traceback
            traceback.print_exc()
    
    return results


def generate_block_summaries(data_dir: Path, blocks: list[str] = None, season: int = 2025):
    """
    Generate computed team summaries for L10/L5 blocks.
    """
    if blocks is None:
        blocks = ["L10", "L5"]
    
    output_dir = data_dir / "computed"
    output_dir.mkdir(exist_ok=True)
    
    results = {}
    
    for block in blocks:
        print(f"\n📊 Processing {season} {block}...")
        
        raw_df = load_raw_team_data(data_dir, block)
        
        if raw_df.empty:
            print(f"  ❌ No data available for {block}")
            continue
        
        # Compute summary using FIFA-style ratings
        try:
            summary_df = compute_team_summary(raw_df, season)
            ladder_df = compute_team_ladders(summary_df)
            
            # Save summary with block suffix
            summary_path = output_dir / f"team_summary_{season}_{block}.csv"
            summary_df.to_csv(summary_path, index=False)
            print(f"  ✅ Saved {summary_path.name}")
            
            # Save ladder
            ladder_path = output_dir / f"team_ladders_{season}_{block}.csv"
            ladder_df.to_csv(ladder_path, index=False)
            print(f"  ✅ Saved {ladder_path.name}")
            
            # Show top 5 teams
            top5 = summary_df.sort_values("Overall Rating", ascending=False).head()
            print(f"  Top 5: {', '.join(top5['Team'].tolist())}")
            
            results[f"{season}_{block}"] = summary_df
            
        except Exception as e:
            print(f"  ❌ Error computing {block}: {e}")
            import traceback
            traceback.print_exc()
    
    return results


def verify_rating_consistency(results: dict):
    """
    Verify that all computed ratings use the same 50-99 scale.
    """
    print("\n" + "="*70)
    print("RATING SCALE VERIFICATION")
    print("="*70)
    
    for name, df in results.items():
        if df.empty:
            continue
        
        overall_min = df["Overall Rating"].min()
        overall_max = df["Overall Rating"].max()
        overall_mean = df["Overall Rating"].mean()
        
        print(f"{name}: Rating range [{overall_min}-{overall_max}], mean={overall_mean:.1f}")
        
        if overall_min < 50 or overall_max > 99:
            print(f"  ⚠️ WARNING: Ratings outside 50-99 scale!")
        else:
            print(f"  ✅ Within FIFA-style 50-99 scale")


def main():
    """Main entry point."""
    print("="*70)
    print("GENERATING FIFA-STYLE TEAM RATINGS FOR ALL SEASONS & BLOCKS")
    print("="*70)
    print("\nRating System: Z-score normalized, sigmoid transformation, 50-99 scale")
    print("  - 90-99: Elite")
    print("  - 80-89: Good")
    print("  - 70-79: Average")
    print("  - 60-69: Below Average")
    print("  - 50-59: Poor")
    
    data_dir = Path(__file__).parent / "data"
    
    # Check what raw data files exist
    raw_dir = data_dir / "raw" / "team"
    available_files = list(raw_dir.glob("team_stats_*.csv"))
    print(f"\nFound {len(available_files)} raw data files:")
    for f in available_files:
        print(f"  - {f.name}")
    
    all_results = {}
    
    # Generate season summaries
    seasons = [2021, 2022, 2023, 2024, 2025]
    season_results = generate_season_summaries(data_dir, seasons)
    all_results.update(season_results)
    
    # Generate L10/L5 block summaries
    block_results = generate_block_summaries(data_dir, ["L10", "L5"], season=2025)
    all_results.update(block_results)
    
    # Verify consistency
    verify_rating_consistency(all_results)
    
    print("\n" + "="*70)
    print("✅ COMPLETE - All team summaries generated with FIFA-style ratings")
    print("="*70)
    
    # List output files
    output_dir = data_dir / "computed"
    team_files = list(output_dir.glob("team_*.csv"))
    print(f"\nGenerated {len(team_files)} files in {output_dir}:")
    for f in sorted(team_files):
        print(f"  - {f.name}")


if __name__ == "__main__":
    main()
