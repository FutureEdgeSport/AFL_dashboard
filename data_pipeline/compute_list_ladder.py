"""
compute_list_ladder.py
======================
Phase 4: Python computation of List Ladder and Age Profile data.

Replaces Excel formulas in AFL Player Ratings.xlsx:
- 'List Ladder L2' sheet
- 'List Ladder Career' sheet
- 'Age Profile (2yr)' sheet
- 'Age Profile (1yr)' sheet

Key calculations:
- Count players per rating tier per position per team
- Sum ratings by age band per team
- Compute rankings
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional


# Path to data directory
DATA_DIR = Path(__file__).parent.parent / "data"

# Rating thresholds for tiering
RATING_TIERS = {
    "Elite": (13.0, float("inf")),   # 13+ rating
    "A-Grade": (10.0, 13.0),         # 10-13 rating
    "B-Grade": (7.0, 10.0),          # 7-10 rating
}

# Position groups
POSITIONS = [
    "Midfielder",
    "Mid-Forward", 
    "Ruck",
    "Key Forward",
    "Wing",
    "Gen. Forward",
    "Gen. Defender",
    "Key Defender",
]

# Age bands for age profile
AGE_BANDS = [
    ("18 to 22", 0, 21.9999),
    ("22 to 26", 22, 25.9999),
    ("26 to 30", 26, 29.9999),
    ("30+", 30, 99),
]


def load_player_summary() -> pd.DataFrame:
    """Load computed player summary CSV."""
    csv_path = DATA_DIR / "computed" / "player_summary.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    
    # Fallback: try to compute it
    from .compute_player_summary import compute_player_summary
    return compute_player_summary()


def get_rating_tier(rating: float) -> Optional[str]:
    """
    Classify a rating into Elite/A-Grade/B-Grade tier.
    
    Returns None if rating is below B-Grade threshold.
    """
    for tier_name, (min_val, max_val) in RATING_TIERS.items():
        if min_val <= rating < max_val:
            return tier_name
    return None


def compute_list_ladder(
    summary_df: pd.DataFrame = None,
    rating_col: str = "Last 2 Average",
    include_positions: list = None
) -> pd.DataFrame:
    """
    Compute List Ladder - count of players per tier per position per team.
    
    Args:
        summary_df: Player summary DataFrame. If None, loads from CSV.
        rating_col: Column to use for rating (e.g., "Last 2 Average", "Career")
        include_positions: List of positions to include. If None, uses all.
        
    Returns:
        DataFrame with columns:
        - Team
        - Rank (overall quality rank)
        - <Position>_Elite, <Position>_A-Grade, <Position>_B-Grade for each position
        - Elite_Total, A-Grade_Total, B-Grade_Total
        - Total (count of tiered players)
        - Points (weighted score: Elite*3 + A-Grade*2 + B-Grade*1)
    """
    if summary_df is None:
        summary_df = load_player_summary()
    
    if include_positions is None:
        include_positions = POSITIONS
    
    teams = summary_df["Team"].dropna().unique()
    
    results = []
    
    for team in sorted(teams):
        team_df = summary_df[summary_df["Team"] == team]
        
        row = {"Team": team}
        
        elite_total = 0
        a_grade_total = 0
        b_grade_total = 0
        
        for position in include_positions:
            pos_df = team_df[team_df["Position"] == position]
            
            for tier_name in ["Elite", "A-Grade", "B-Grade"]:
                min_val, max_val = RATING_TIERS[tier_name]
                
                # Count players in this tier
                count = len(pos_df[
                    (pos_df[rating_col] >= min_val) & 
                    (pos_df[rating_col] < max_val)
                ])
                
                col_name = f"{position}_{tier_name}"
                row[col_name] = count
                
                # Update totals
                if tier_name == "Elite":
                    elite_total += count
                elif tier_name == "A-Grade":
                    a_grade_total += count
                else:
                    b_grade_total += count
        
        row["Elite_Total"] = elite_total
        row["A-Grade_Total"] = a_grade_total
        row["B-Grade_Total"] = b_grade_total
        row["Total"] = elite_total + a_grade_total + b_grade_total
        row["Points"] = elite_total * 3 + a_grade_total * 2 + b_grade_total * 1
        
        results.append(row)
    
    result_df = pd.DataFrame(results)
    
    # Add ranking by Points (descending)
    result_df["Rank"] = result_df["Points"].rank(ascending=False, method="min").astype(int)
    
    # Sort by rank
    result_df = result_df.sort_values("Rank").reset_index(drop=True)
    
    # Reorder columns
    cols = ["Rank", "Team"]
    for pos in include_positions:
        cols.extend([f"{pos}_Elite", f"{pos}_A-Grade", f"{pos}_B-Grade"])
    cols.extend(["Elite_Total", "A-Grade_Total", "B-Grade_Total", "Total", "Points"])
    
    result_df = result_df[[c for c in cols if c in result_df.columns]]
    
    return result_df


def compute_age_profile(
    summary_df: pd.DataFrame = None,
    rating_col: str = "Last 2 Average",
    age_col: str = "Age"
) -> pd.DataFrame:
    """
    Compute Age Profile - total ratings by age band per team.
    
    Args:
        summary_df: Player summary DataFrame. If None, loads from CSV.
        rating_col: Column to use for rating
        age_col: Column to use for age
        
    Returns:
        DataFrame with columns:
        - Team
        - Total (sum of ratings)
        - <Age Band> (sum of ratings in band)
        - <Age Band>_% (percentage of total)
        - <Age Band>_Rank (rank for that age band)
        - Total_Rank (overall rank)
    """
    if summary_df is None:
        summary_df = load_player_summary()
    
    teams = summary_df["Team"].dropna().unique()
    
    results = []
    
    for team in sorted(teams):
        team_df = summary_df[summary_df["Team"] == team]
        
        row = {"Team": team}
        
        # Filter to players with valid ratings
        rated_df = team_df[team_df[rating_col].notna()]
        
        total_rating = rated_df[rating_col].sum()
        row["Total"] = total_rating
        
        # Calculate ratings per age band
        for band_name, age_min, age_max in AGE_BANDS:
            band_df = rated_df[
                (rated_df[age_col] >= age_min) & 
                (rated_df[age_col] <= age_max)
            ]
            
            band_rating = band_df[rating_col].sum()
            row[band_name] = band_rating
            
            if total_rating > 0:
                row[f"{band_name}_%"] = band_rating / total_rating
            else:
                row[f"{band_name}_%"] = 0
        
        results.append(row)
    
    result_df = pd.DataFrame(results)
    
    # Add rankings
    result_df["Total_Rank"] = result_df["Total"].rank(ascending=False, method="min").astype(int)
    
    for band_name, _, _ in AGE_BANDS:
        result_df[f"{band_name}_Rank"] = result_df[band_name].rank(ascending=False, method="min").astype(int)
    
    # Sort by total rank
    result_df = result_df.sort_values("Total_Rank").reset_index(drop=True)
    
    # Reorder columns
    cols = ["Team", "Total", "Total_Rank"]
    for band_name, _, _ in AGE_BANDS:
        cols.extend([band_name, f"{band_name}_%", f"{band_name}_Rank"])
    
    result_df = result_df[[c for c in cols if c in result_df.columns]]
    
    return result_df


def compute_list_ladder_l2() -> pd.DataFrame:
    """Compute List Ladder using Last 2 Years Average rating."""
    return compute_list_ladder(rating_col="Last 2 Average")


def compute_list_ladder_career() -> pd.DataFrame:
    """Compute List Ladder using Career Average rating."""
    return compute_list_ladder(rating_col="Career")


def compute_age_profile_2yr() -> pd.DataFrame:
    """Compute Age Profile using Last 2 Years Average rating."""
    return compute_age_profile(rating_col="Last 2 Average")


def compute_age_profile_1yr(current_season: int = 2025) -> pd.DataFrame:
    """Compute Age Profile using current season rating only."""
    return compute_age_profile(rating_col=str(current_season))


def save_list_ladder(df: pd.DataFrame, filename: str):
    """Save list ladder to CSV."""
    output_path = DATA_DIR / "computed" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path


def save_age_profile(df: pd.DataFrame, filename: str):
    """Save age profile to CSV."""
    output_path = DATA_DIR / "computed" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path


# ============================================================
# Module entry point
# ============================================================

if __name__ == "__main__":
    print("Computing List Ladder and Age Profile from player summary...")
    
    try:
        # Load player summary
        summary = load_player_summary()
        print(f"Loaded {len(summary)} players")
        
        # Compute List Ladder L2
        print("\n=== List Ladder (Last 2 Years) ===")
        ll_l2 = compute_list_ladder_l2()
        print(ll_l2[["Rank", "Team", "Elite_Total", "A-Grade_Total", "B-Grade_Total", "Points"]].head(10).to_string())
        save_list_ladder(ll_l2, "list_ladder_l2.csv")
        print("💾 Saved list_ladder_l2.csv")
        
        # Compute List Ladder Career
        print("\n=== List Ladder (Career) ===")
        ll_career = compute_list_ladder_career()
        print(ll_career[["Rank", "Team", "Elite_Total", "A-Grade_Total", "B-Grade_Total", "Points"]].head(10).to_string())
        save_list_ladder(ll_career, "list_ladder_career.csv")
        print("💾 Saved list_ladder_career.csv")
        
        # Compute Age Profile 2yr
        print("\n=== Age Profile (2yr) ===")
        ap_2yr = compute_age_profile_2yr()
        cols = ["Team", "Total", "Total_Rank", "18 to 22_%", "22 to 26_%", "26 to 30_%", "30+_%"]
        print(ap_2yr[[c for c in cols if c in ap_2yr.columns]].head(10).to_string())
        save_age_profile(ap_2yr, "age_profile_2yr.csv")
        print("💾 Saved age_profile_2yr.csv")
        
        # Compute Age Profile 1yr (2025)
        print("\n=== Age Profile (2025) ===")
        ap_1yr = compute_age_profile_1yr(2025)
        save_age_profile(ap_1yr, "age_profile_1yr.csv")
        print("💾 Saved age_profile_1yr.csv")
        
        print("\n✅ All List Ladder and Age Profile computations complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
