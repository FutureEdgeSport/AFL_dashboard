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
# These are the metrics used to compute each category ranking

CATEGORY_METRICS = {
    "Ball Winning": {
        "description": "Ability to win the contested ball",
        "metrics": {
            "Post Clear CP Diff": {
                "compute": lambda df: df["PostClearanceContestedPossessions"] - df.get("PostClearanceContestedPossessions_Opp", 0),
                "higher_is_better": True
            },
            "Ground Ball Diff": {
                "compute": lambda df: df["GroundBallGets"] - df.get("GroundBallGets_Opp", 0),
                "higher_is_better": True
            },
            "1st Poss to Clear %": {
                "compute": lambda df: df["FirstPossessionToClearance"],
                "higher_is_better": True
            },
            "Clearance Diff": {
                "compute": lambda df: df["TotalClearances"] - df.get("TotalClearances_Opp", 0),
                "higher_is_better": True
            },
        }
    },
    "Ball Movement": {
        "description": "Efficiency in moving the ball forward",
        "metrics": {
            "Def Half to Score %": {
                "compute": lambda df: df.get("DefensiveHalfToScore", 0),
                "higher_is_better": True
            },
            "Chain to Score %": {
                "compute": lambda df: df.get("ChainToScore", 0),
                "higher_is_better": True
            },
            "Metres Gained": {
                "compute": lambda df: df["MetresGained"],
                "higher_is_better": True
            },
            "Disposal Efficiency": {
                "compute": lambda df: df["DisposalEfficiency"],
                "higher_is_better": True
            },
        }
    },
    "Scoring": {
        "description": "Ability to convert opportunities to scores",
        "metrics": {
            "Points Per Inside 50": {
                "compute": lambda df: df.get("PointsPerInside50", df.get("Goals", 0) * 6 / df["Inside50s"].clip(lower=1)),
                "higher_is_better": True
            },
            "Goals": {
                "compute": lambda df: df.get("Goals", 0),
                "higher_is_better": True
            },
            "Goal Accuracy": {
                "compute": lambda df: df.get("GoalAccuracy", 0),
                "higher_is_better": True
            },
            "Score per Entry": {
                "compute": lambda df: df.get("ScorePerForward50Entry", 0),
                "higher_is_better": True
            },
        }
    },
    "Defence": {
        "description": "Defensive capabilities",
        "metrics": {
            "Points Against": {
                "compute": lambda df: df.get("PointsAgainst", 0),
                "higher_is_better": False  # Lower is better
            },
            "Intercepts": {
                "compute": lambda df: df["Intercepts"],
                "higher_is_better": True
            },
            "Tackles": {
                "compute": lambda df: df.get("Tackles", 0),
                "higher_is_better": True
            },
            "Spoils": {
                "compute": lambda df: df.get("Spoils", 0),
                "higher_is_better": True
            },
        }
    },
    "Pressure": {
        "description": "Ability to apply pressure to opposition",
        "metrics": {
            "Pressure Acts": {
                "compute": lambda df: df.get("PressureActs", 0),
                "higher_is_better": True
            },
            "Tackles": {
                "compute": lambda df: df.get("Tackles", 0),
                "higher_is_better": True
            },
            "Forward Pressure": {
                "compute": lambda df: df.get("PressureActsForward50", 0),
                "higher_is_better": True
            },
        }
    },
    "Health Check": {
        "description": "List quality and depth indicators",
        "metrics": {
            "Average Age": {
                "compute": lambda df: df["Age"],
                "higher_is_better": False  # Younger is generally better for list health
            },
            "Experience": {
                "compute": lambda df: df["Experience"],
                "higher_is_better": True
            },
            "Rating Points": {
                "compute": lambda df: df["RatingPoints"],
                "higher_is_better": True
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


def compute_category_ranking(
    df: pd.DataFrame, 
    category: str
) -> tuple[pd.Series, pd.Series]:
    """
    Compute a category ranking from raw team data.
    
    Returns:
        Tuple of (ranking_score, rank) where ranking_score is 0-100
    """
    if category not in CATEGORY_METRICS:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    
    category_def = CATEGORY_METRICS[category]
    metric_ranks = []
    
    for metric_name, metric_def in category_def["metrics"].items():
        try:
            # Compute the metric value
            metric_values = metric_def["compute"](df)
            
            # Skip if all NaN
            if metric_values.isna().all():
                continue
            
            # Compute percentile rank (0-100, higher is better)
            if metric_def["higher_is_better"]:
                pct_rank = metric_values.rank(pct=True) * 100
            else:
                pct_rank = (1 - metric_values.rank(pct=True)) * 100
            
            metric_ranks.append(pct_rank)
            
        except Exception as e:
            print(f"  Warning: Could not compute {metric_name}: {e}")
            continue
    
    if not metric_ranks:
        return pd.Series([50] * len(df)), pd.Series(range(1, len(df) + 1))
    
    # Average the percentile ranks
    combined = pd.concat(metric_ranks, axis=1).mean(axis=1)
    
    # Convert to 1-100 scale and compute rank
    ranking_score = combined.round(0).astype(int)
    rank = ranking_score.rank(ascending=False, method='min').astype(int)
    
    return ranking_score, rank


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
    
    # Remove any non-team rows
    raw_df = raw_df[raw_df["Team"].notna()]
    raw_df = raw_df[~raw_df["Team"].astype(str).str.contains("Total|Average", case=False, na=False)]
    
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
