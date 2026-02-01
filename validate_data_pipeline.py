"""
Validation Script - Compare Python-computed values against Excel
Run this to verify the data pipeline produces correct results.
"""

import pandas as pd
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from data_pipeline.compute_ratings import (
    load_team_ladders_computed,
    compare_to_excel_snapshot,
)

TEAM_FILE = "AFL Team Ratings.xlsx"


def validate_team_ladders(season: int = 2025):
    """Compare computed team ladders against Excel version."""
    
    print(f"\n{'='*70}")
    print(f"VALIDATING TEAM LADDERS - {season}")
    print(f"{'='*70}")
    
    xl = pd.ExcelFile(TEAM_FILE)
    
    # Test Season ladders
    print(f"\n📊 Season Ladders ({season})...")
    
    # Load Excel version (ground truth)
    try:
        excel_df = xl.parse(f"{season} Ladders")
        # Find header row
        for i, row in excel_df.iterrows():
            if "Team" in str(row.values):
                excel_df.columns = excel_df.iloc[i]
                excel_df = excel_df.iloc[i+1:].reset_index(drop=True)
                break
        excel_df = excel_df.dropna(how='all')
        print(f"   Excel: {len(excel_df)} teams, {len(excel_df.columns)} columns")
    except Exception as e:
        print(f"   ❌ Could not load Excel ladders: {e}")
        return
    
    # Load computed version
    try:
        computed_df = load_team_ladders_computed(xl, season, "Season")
        print(f"   Computed: {len(computed_df)} teams, {len(computed_df.columns)} columns")
    except Exception as e:
        print(f"   ❌ Could not compute ladders: {e}")
        return
    
    # Compare
    if computed_df.empty:
        print("   ⚠️ Computed DataFrame is empty - check compute_ratings.py")
    else:
        results = compare_to_excel_snapshot(computed_df, excel_df)
        
        print(f"\n   📈 RESULTS:")
        print(f"   Match Rate: {results['match_pct']:.1f}%")
        print(f"   Missing in computed: {results['missing_in_computed']}")
        print(f"   Missing in Excel: {results['missing_in_excel']}")
        print(f"   Numeric differences: {len(results['numeric_diffs'])}")
        
        if results['numeric_diffs']:
            print(f"\n   Top differences:")
            for diff in results['numeric_diffs'][:5]:
                print(f"      {diff['team']} | {diff['column']}: computed={diff['computed']}, excel={diff['excel']}, diff={diff['diff']:.4f}")
    
    # Test L10 ladders
    print(f"\n📊 Last 10 Ladders ({season})...")
    
    try:
        excel_l10 = xl.parse(f"{season} Ladders (L10)")
        for i, row in excel_l10.iterrows():
            if "Team" in str(row.values):
                excel_l10.columns = excel_l10.iloc[i]
                excel_l10 = excel_l10.iloc[i+1:].reset_index(drop=True)
                break
        excel_l10 = excel_l10.dropna(how='all')
        print(f"   Excel L10: {len(excel_l10)} teams")
        
        computed_l10 = load_team_ladders_computed(xl, season, "L10")
        print(f"   Computed L10: {len(computed_l10)} teams")
        
        if not computed_l10.empty:
            results_l10 = compare_to_excel_snapshot(computed_l10, excel_l10)
            print(f"   L10 Match Rate: {results_l10['match_pct']:.1f}%")
    except Exception as e:
        print(f"   ⚠️ L10 validation skipped: {e}")


def show_excel_structure():
    """Show the structure of key Excel sheets."""
    
    print(f"\n{'='*70}")
    print("EXCEL SHEET STRUCTURE")
    print(f"{'='*70}")
    
    xl = pd.ExcelFile(TEAM_FILE)
    
    for sheet in ["2025 Ladders", "2025 Summary"]:
        print(f"\n📋 {sheet}:")
        df = xl.parse(sheet, nrows=5, header=None)
        for i, row in df.iterrows():
            vals = [str(v)[:25] if pd.notna(v) else '' for v in row.values[:8]]
            print(f"   Row {i}: {vals}")


def show_computed_structure():
    """Show what the computed functions produce."""
    
    print(f"\n{'='*70}")
    print("COMPUTED OUTPUT STRUCTURE")
    print(f"{'='*70}")
    
    xl = pd.ExcelFile(TEAM_FILE)
    
    computed = load_team_ladders_computed(xl, 2025, "Season")
    
    print(f"\n📊 Computed Team Ladders (2025 Season):")
    print(f"   Shape: {computed.shape}")
    print(f"   Columns: {list(computed.columns)}")
    
    if not computed.empty:
        print(f"\n   Sample data (first 3 teams):")
        print(computed.head(3).to_string())


if __name__ == "__main__":
    print("="*70)
    print("AFL DASHBOARD - DATA VALIDATION")
    print("="*70)
    
    # Show structures
    show_excel_structure()
    show_computed_structure()
    
    # Run validation
    validate_team_ladders(2025)
    
    print(f"\n{'='*70}")
    print("VALIDATION COMPLETE")
    print(f"{'='*70}")
