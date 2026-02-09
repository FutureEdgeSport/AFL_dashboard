"""
compute_team_summary.py

Computes Team Summary statistics from raw team data.
Replaces Excel formulas with Python calculations.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

# Team name normalization
TEAM_NAME_MAP = {
    "GWS": "GWS Giants",
    "Greater Western Sydney": "GWS Giants",
    "Adelaide Crows": "Adelaide",
    "Brisbane Lions": "Brisbane",
    "Carlton Blues": "Carlton",
    "Collingwood Magpies": "Collingwood",
    "Essendon Bombers": "Essendon",
    "Fremantle Dockers": "Fremantle",
    "Geelong Cats": "Geelong",
    "Gold Coast Suns": "Gold Coast",
    "Hawthorn Hawks": "Hawthorn",
    "Melbourne Demons": "Melbourne",
    "North Melbourne Kangaroos": "North Melbourne",
    "Port Adelaide Power": "Port Adelaide",
    "Richmond Tigers": "Richmond",
    "St Kilda Saints": "St Kilda",
    "Sydney Swans": "Sydney",
    "West Coast Eagles": "West Coast",
}

# Category definitions - maps category to raw column names
# These are the metrics used to compute each category rating
# 
# NEW SOPHISTICATED RATING SYSTEM (v2.0):
# - Uses Z-scores to standardize metrics across different scales
# - Applies weights based on metric importance (sum to 1.0 within category)
# - Maps to 50-99 scale using sigmoid transformation for better distribution
# - Considers both raw performance and differential metrics where relevant

CATEGORY_METRICS = {
    "Ball Winning": {
        "description": "Ability to win the contested ball",
        "metrics": {
            "Contested Possessions Diff": {
                "compute": lambda df: df["ContestedPossessions"] - df.get("ContestedPossessions_Opposition", df.get("ContestedPossessions_Opp", 0)),
                "higher_is_better": True,
                "weight": 0.25
            },
            "Ground Ball Gets": {
                "compute": lambda df: df["GroundBallGets"],
                "higher_is_better": True,
                "weight": 0.20
            },
            "Clearance Diff": {
                "compute": lambda df: df["TotalClearances"] - df.get("TotalClearances_Opposition", df.get("TotalClearances_Opp", 0)),
                "higher_is_better": True,
                "weight": 0.25
            },
            "1st Poss to Clear %": {
                "compute": lambda df: df["FirstPossessionToClearance"],
                "higher_is_better": True,
                "weight": 0.15
            },
            "Hitouts to Advantage": {
                "compute": lambda df: df.get("HitoutsToAdvantage", 0),
                "higher_is_better": True,
                "weight": 0.15
            },
        }
    },
    "Ball Movement": {
        "description": "Efficiency in moving the ball forward",
        "metrics": {
            "Metres Gained Diff": {
                "compute": lambda df: df["MetresGained"] - df.get("MetresGained_Opposition", df.get("MetresGained_Opp", 0)),
                "higher_is_better": True,
                "weight": 0.25
            },
            "Disposal Efficiency": {
                "compute": lambda df: df["DisposalEfficiency"],
                "higher_is_better": True,
                "weight": 0.25
            },
            "Def Half to Score %": {
                "compute": lambda df: df.get("DefHalfToScore", df.get("DefensiveHalfToScore", 0)),
                "higher_is_better": True,
                "weight": 0.20
            },
            "Inside 50s Diff": {
                "compute": lambda df: df["Inside50s"] - df.get("Inside50s_Opposition", df.get("Inside50s_Opp", 0)),
                "higher_is_better": True,
                "weight": 0.15
            },
            "Retention Rating": {
                "compute": lambda df: df.get("RetentionRating", 0),
                "higher_is_better": True,
                "weight": 0.15
            },
        }
    },
    "Scoring": {
        "description": "Ability to convert opportunities to scores",
        "metrics": {
            "Goals": {
                "compute": lambda df: df.get("Goals", 0),
                "higher_is_better": True,
                "weight": 0.30
            },
            "Goal Accuracy": {
                "compute": lambda df: df.get("GoalAccuracy", 0),
                "higher_is_better": True,
                "weight": 0.25
            },
            "Goals Per Inside 50": {
                "compute": lambda df: df.get("GoalsPerInside50", df.get("Goals", 0) / df["Inside50s"].clip(lower=1) * 100),
                "higher_is_better": True,
                "weight": 0.25
            },
            "xScore Rating": {
                "compute": lambda df: df.get("xScoreRating", 0),
                "higher_is_better": True,
                "weight": 0.20
            },
        }
    },
    "Defence": {
        "description": "Defensive capabilities",
        "metrics": {
            "Goals Against (Opp)": {
                "compute": lambda df: df.get("Goals_Opposition", df.get("Goals_Opp", 0)),
                "higher_is_better": False,  # Lower is better
                "weight": 0.30
            },
            "Intercepts": {
                "compute": lambda df: df["Intercepts"],
                "higher_is_better": True,
                "weight": 0.25
            },
            "Rebound 50s": {
                "compute": lambda df: df.get("Rebound50s", 0),
                "higher_is_better": True,
                "weight": 0.20
            },
            "Spoils": {
                "compute": lambda df: df.get("Spoils", 0),
                "higher_is_better": True,
                "weight": 0.15
            },
            "Contest Def Win %": {
                "compute": lambda df: 100 - df.get("ContestDefensiveLossPercentage", 50),
                "higher_is_better": True,
                "weight": 0.10
            },
        }
    },
    "Pressure": {
        "description": "Ability to apply pressure to opposition",
        "metrics": {
            "Pressure Acts": {
                "compute": lambda df: df.get("PressureActs", 0),
                "higher_is_better": True,
                "weight": 0.35
            },
            "Tackles": {
                "compute": lambda df: df.get("Tackles", 0),
                "higher_is_better": True,
                "weight": 0.30
            },
            "Tackles Inside 50": {
                "compute": lambda df: df.get("TacklesInside50", 0),
                "higher_is_better": True,
                "weight": 0.20
            },
            "Turnovers Forced (Opp)": {
                "compute": lambda df: df.get("Turnovers_Opposition", df.get("Turnovers_Opp", 0)),
                "higher_is_better": True,
                "weight": 0.15
            },
        }
    },
    "Health Check": {
        "description": "List quality and depth indicators",
        "metrics": {
            "Rating Points": {
                "compute": lambda df: df["RatingPoints"],
                "higher_is_better": True,
                "weight": 0.40
            },
            "Experience": {
                "compute": lambda df: df["Experience"],
                "higher_is_better": True,
                "weight": 0.30
            },
            "Average Age (Optimal ~25)": {
                "compute": lambda df: -abs(df["Age"] - 25),  # Closer to 25 is better
                "higher_is_better": True,
                "weight": 0.30
            },
        }
    },
}


def normalize_team_names(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize team names to standard format."""
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip().replace(TEAM_NAME_MAP)
    return df


def compute_metric_rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """Compute rank for a metric series (1 = best)."""
    if higher_is_better:
        return series.rank(ascending=False, method='min')
    else:
        return series.rank(ascending=True, method='min')


def zscore_to_rating(z_score: float, min_rating: int = 50, max_rating: int = 99) -> int:
    """
    Convert a Z-score to a rating using sigmoid transformation.
    
    This maps the continuous Z-score to a bounded 50-99 scale where:
    - Z = 0 (average) maps to ~75
    - Z = +2 (excellent) maps to ~95
    - Z = -2 (poor) maps to ~55
    
    Uses a modified sigmoid for smooth distribution with scale factor of 1.0
    for better spread across the rating range.
    """
    # Sigmoid transformation: maps (-inf, +inf) to (0, 1)
    # Scale factor of 1.0 gives good spread for typical Z-score ranges (-2 to +2)
    sigmoid = 1 / (1 + np.exp(-z_score * 1.0))
    
    # Map sigmoid (0-1) to rating scale (min_rating to max_rating)
    rating = min_rating + sigmoid * (max_rating - min_rating)
    
    return int(round(np.clip(rating, min_rating, max_rating)))


def compute_category_rating(
    df: pd.DataFrame, 
    category: str,
    min_rating: int = 50,
    max_rating: int = 99
) -> tuple[pd.Series, pd.Series]:
    """
    Compute a category rating using sophisticated Z-score methodology.
    
    NEW METHODOLOGY (v2.0):
    1. For each metric, compute Z-scores (standardized to mean=0, std=1)
    2. Flip Z-scores for metrics where lower is better
    3. Apply weighted average using metric weights
    4. Transform combined Z-score to 50-99 scale using sigmoid
    
    Returns:
        Tuple of (rating_score, rank) where rating_score is 50-99
    """
    if category not in CATEGORY_METRICS:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    
    category_def = CATEGORY_METRICS[category]
    weighted_zscores = pd.Series(0.0, index=df.index)
    total_weight = 0.0
    
    for metric_name, metric_def in category_def["metrics"].items():
        try:
            # Compute the metric value
            metric_values = metric_def["compute"](df)
            
            # Skip if all NaN or constant (can't compute Z-score)
            if metric_values.isna().all() or metric_values.std() == 0:
                continue
            
            # Fill NaN with mean for this metric
            metric_values = metric_values.fillna(metric_values.mean())
            
            # Compute Z-score (mean=0, std=1)
            mean_val = metric_values.mean()
            std_val = metric_values.std()
            if std_val > 0:
                z_scores = (metric_values - mean_val) / std_val
            else:
                z_scores = pd.Series(0.0, index=df.index)
            
            # Flip Z-score if lower is better (so positive Z always = good)
            if not metric_def["higher_is_better"]:
                z_scores = -z_scores
            
            # Apply weight
            weight = metric_def.get("weight", 1.0 / len(category_def["metrics"]))
            weighted_zscores += z_scores * weight
            total_weight += weight
            
        except Exception as e:
            print(f"  Warning: Could not compute {metric_name}: {e}")
            continue
    
    # Normalize by total weight
    if total_weight > 0:
        weighted_zscores = weighted_zscores / total_weight
    else:
        # Fallback: return average rating for all teams
        return pd.Series([75] * len(df), index=df.index), pd.Series(range(1, len(df) + 1), index=df.index)
    
    # Convert Z-scores to 50-99 rating scale
    rating_score = weighted_zscores.apply(lambda z: zscore_to_rating(z, min_rating, max_rating))
    
    # Compute rank (1 = best = highest rating)
    rank = rating_score.rank(ascending=False, method='min').astype(int)
    
    return rating_score, rank


# Keep old function name for backwards compatibility
def compute_category_ranking(
    df: pd.DataFrame, 
    category: str
) -> tuple[pd.Series, pd.Series]:
    """
    Compute a category ranking from raw team data.
    
    DEPRECATED: This now calls compute_category_rating() with 50-99 scale.
    
    Returns:
        Tuple of (ranking_score, rank) where ranking_score is 50-99
    """
    return compute_category_rating(df, category, min_rating=50, max_rating=99)


def compute_team_summary(
    raw_df: pd.DataFrame,
    season: int = 2026
) -> pd.DataFrame:
    """
    Compute complete team summary from raw data.
    
    This replaces the Excel Summary sheet calculations.
    
    Args:
        raw_df: Raw team statistics DataFrame
        season: Season year
        
    Returns:
        Summary DataFrame with all category rankings
    """
    df = raw_df.copy()
    df = normalize_team_names(df)
    
    # Start with Team column
    result = pd.DataFrame({"Team": df["Team"]})
    
    # Compute each category
    for category in CATEGORY_METRICS.keys():
        print(f"  Computing {category}...")
        ranking_score, rank = compute_category_ranking(df, category)
        
        result[f"{category} Ranking"] = ranking_score
        result[f"{category} Rank"] = rank
    
    # Compute overall rating (average of category rankings)
    ranking_cols = [c for c in result.columns if c.endswith(" Ranking")]
    result["Overall Rating"] = result[ranking_cols].mean(axis=1).round(0).astype(int)
    result["Overall Rank"] = result["Overall Rating"].rank(ascending=False, method='min').astype(int)
    
    return result


def compute_team_ladders(
    summary_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Compute team ladders from summary data.
    
    This replaces the Excel Ladders sheet.
    """
    # Select the ranking columns for the ladder
    ladder_cols = ["Team"]
    
    for category in ["Ball Winning", "Ball Movement", "Scoring", "Defence", "Pressure", "Health Check"]:
        if f"{category} Ranking" in summary_df.columns:
            ladder_cols.append(f"{category} Ranking")
            ladder_cols.append(f"{category} Rank")
    
    if "Overall Rating" in summary_df.columns:
        ladder_cols.append("Overall Rating")
        ladder_cols.append("Overall Rank")
    
    available_cols = [c for c in ladder_cols if c in summary_df.columns]
    ladder_df = summary_df[available_cols].copy()
    
    # Sort by Overall Rank
    if "Overall Rank" in ladder_df.columns:
        ladder_df = ladder_df.sort_values("Overall Rank").reset_index(drop=True)
    
    return ladder_df


def load_and_compute_summary(
    data_dir: Path,
    season: int = 2026
) -> pd.DataFrame:
    """Load raw data and compute summary."""
    raw_path = data_dir / "raw" / "team" / f"team_stats_{season}.csv"
    
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw team data not found: {raw_path}")
    
    raw_df = pd.read_csv(raw_path)
    
    # Remove any non-team rows (Average, Total, nan, numeric IDs, etc.)
    raw_df = raw_df[raw_df["Team"].notna()]
    raw_df = raw_df[~raw_df["Team"].astype(str).str.contains("Total|Average|nan", case=False, na=False)]
    raw_df = raw_df[~raw_df["Team"].astype(str).str.match(r'^\d+$')]  # Remove numeric-only team names
    
    return compute_team_summary(raw_df, season)


# Demo / test
if __name__ == "__main__":
    import sys
    
    print("="*70)
    print("TEAM SUMMARY COMPUTATION TEST")
    print("="*70)
    
    # Use project root data directory, not relative to this file
    data_dir = Path(__file__).parent.parent / "data"
    
    try:
        print("\nLoading raw team data for 2026...")
        summary_df = load_and_compute_summary(data_dir, 2026)
        
        print(f"\n✅ Computed summary for {len(summary_df)} teams")
        print(f"Columns: {list(summary_df.columns)}")
        
        print("\nTop 5 teams by Overall Rating:")
        top5 = summary_df.sort_values("Overall Rating", ascending=False).head()
        print(top5[["Team", "Overall Rating", "Overall Rank"]].to_string(index=False))
        
        # Compute ladder
        print("\n" + "="*70)
        print("TEAM LADDER")
        print("="*70)
        
        ladder_df = compute_team_ladders(summary_df)
        print(ladder_df.head(10).to_string(index=False))
        
        # Save computed results
        output_dir = data_dir / "computed"
        output_dir.mkdir(exist_ok=True)
        
        summary_df.to_csv(output_dir / "team_summary_2026.csv", index=False)
        ladder_df.to_csv(output_dir / "team_ladders_2026.csv", index=False)
        print(f"\n✅ Saved to {output_dir}/")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
