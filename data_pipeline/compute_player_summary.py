"""
compute_player_summary.py
=========================
Phase 3: Python computation of player summary data.

Replaces Excel formulas in AFL Player Ratings.xlsx 'Summary' sheet.

Key calculations:
- Career average ratings across all seasons
- Last 2 years average ratings
- Last 20 games average
- Position rankings
- Overall rankings
- Cap value calculations
- Impact calculations
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional


# Maximum matches to use in Rating × Matches calculations
# Capped at 23 (regular season) to avoid over-rating players who played finals
MAX_REGULAR_SEASON_MATCHES = 23

# Path to data directory
DATA_DIR = Path(__file__).parent.parent / "data"


def load_all_season_data(seasons: list[int] = None) -> dict[int, pd.DataFrame]:
    """
    Load player statistics from all available season CSV files.
    
    Args:
        seasons: List of seasons to load. If None, loads all available.
        
    Returns:
        Dictionary mapping season year to DataFrame
    """
    raw_player_dir = DATA_DIR / "raw" / "player"
    season_data = {}
    
    if seasons is None:
        # Find all available season files
        seasons = []
        for f in raw_player_dir.glob("player_stats_*.csv"):
            try:
                year = int(f.stem.split("_")[-1])
                seasons.append(year)
            except ValueError:
                continue
        seasons = sorted(seasons)
    
    for season in seasons:
        csv_path = raw_player_dir / f"player_stats_{season}.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            df.columns = df.columns.str.strip()
            season_data[season] = df
    
    return season_data


def load_squads_data(season: int = 2026) -> pd.DataFrame:
    """Load squad/roster data for a season."""
    csv_path = DATA_DIR / "raw" / "player" / f"squads_{season}.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        return df
    return pd.DataFrame()


def load_contract_data() -> pd.DataFrame:
    """Load contract expiry data."""
    csv_path = DATA_DIR / "raw" / "player" / "contract_expiry.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        return df
    return pd.DataFrame()


def load_draft_data() -> pd.DataFrame:
    """Load draft data."""
    csv_path = DATA_DIR / "raw" / "player" / "draft_data.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        return df
    return pd.DataFrame()


def compute_career_average(
    player_name: str,
    season_data: dict[int, pd.DataFrame],
    rating_col: str = "RatingPoints_Avg",
    min_matches: int = 5
) -> float:
    """
    Compute career average rating for a player.
    
    Args:
        player_name: Player's name
        season_data: Dict of season DataFrames
        rating_col: Column name for rating
        min_matches: Minimum matches in a season to include
        
    Returns:
        Career average rating weighted by matches
    """
    total_rating = 0.0
    total_matches = 0
    
    for season, df in season_data.items():
        if "Player" not in df.columns:
            continue
        
        player_row = df[df["Player"] == player_name]
        if player_row.empty:
            continue
            
        row = player_row.iloc[0]
        matches = row.get("Matches", 0)
        rating = row.get(rating_col, np.nan)
        
        if pd.notna(rating) and matches >= min_matches:
            total_rating += rating * matches
            total_matches += matches
    
    if total_matches > 0:
        return total_rating / total_matches
    return np.nan


def compute_last_n_years_average(
    player_name: str,
    season_data: dict[int, pd.DataFrame],
    current_season: int,
    n_years: int = 2,
    rating_col: str = "RatingPoints_Avg",
    min_matches: int = 5
) -> float:
    """
    Compute average rating over last N years.
    
    Args:
        player_name: Player's name
        season_data: Dict of season DataFrames
        current_season: Current season year
        n_years: Number of years to look back
        rating_col: Column name for rating
        min_matches: Minimum matches in a season to include
        
    Returns:
        Average rating weighted by matches over last N years
    """
    total_rating = 0.0
    total_matches = 0
    
    for year in range(current_season - n_years + 1, current_season + 1):
        if year not in season_data:
            continue
            
        df = season_data[year]
        if "Player" not in df.columns:
            continue
            
        player_row = df[df["Player"] == player_name]
        if player_row.empty:
            continue
            
        row = player_row.iloc[0]
        matches = row.get("Matches", 0)
        rating = row.get(rating_col, np.nan)
        
        if pd.notna(rating) and matches >= min_matches:
            total_rating += rating * matches
            total_matches += matches
    
    if total_matches > 0:
        return total_rating / total_matches
    return np.nan


def compute_player_summary(
    current_season: int = 2026,
    rating_col: str = "RatingPoints_Avg"
) -> pd.DataFrame:
    """
    Compute complete player summary data from raw CSVs.
    
    Replicates Excel Summary sheet calculations.
    
    Args:
        current_season: The current/most recent season
        rating_col: Column name for player rating
        
    Returns:
        DataFrame with player summary including:
        - Basic info (name, team, age, position, height)
        - Draft info
        - Contract info
        - Career statistics
        - Last 2 year averages
        - Rankings
        - Cap calculations
    """
    # Load all data sources
    season_data = load_all_season_data()
    squads_df = load_squads_data(current_season)
    contract_df = load_contract_data()
    draft_df = load_draft_data()
    
    if current_season not in season_data:
        raise ValueError(f"No data available for season {current_season}")
    
    current_df = season_data[current_season]
    
    # Build base summary from current season players
    summary_rows = []
    
    # Get unique players from current season
    if "Player" not in current_df.columns:
        raise ValueError("Player column not found in current season data")
    
    players = current_df["Player"].unique()
    
    for player_name in players:
        player_current = current_df[current_df["Player"] == player_name].iloc[0]
        
        row = {
            "Player": player_name,
            "Team": player_current.get("Team", ""),
            "Age": player_current.get("Age", np.nan),
            "Age_Decimal": player_current.get("Age_Decimal", np.nan),
            "Position": player_current.get("Position", ""),
            "Height": player_current.get("Height", np.nan),
        }
        
        # Add current season stats
        row[f"{current_season} Matches"] = player_current.get("Matches", 0)
        row[f"{current_season} Rating"] = player_current.get(rating_col, np.nan)

        # Total career matches.  Prefer the official AFL career-games count
        # from the current season's squad file (squads_{year}.csv's
        # "Matches_Career" column), because our per-season stats only start
        # in 2012 — summing them undercounts veterans who debuted earlier
        # (e.g. Sidebottom, Pendlebury).  Fall back to the sum only if the
        # squad file doesn't carry that column for this player.
        total_matches = np.nan
        if not squads_df.empty and "Matches_Career" in squads_df.columns and "Player" in squads_df.columns:
            _sq_row = squads_df[squads_df["Player"] == player_name]
            if not _sq_row.empty:
                _career = pd.to_numeric(_sq_row.iloc[0].get("Matches_Career"), errors="coerce")
                if pd.notna(_career):
                    total_matches = int(_career)
        if pd.isna(total_matches):
            _sum = 0
            for season, df in season_data.items():
                if "Player" not in df.columns:
                    continue
                player_row = df[df["Player"] == player_name]
                if not player_row.empty:
                    _sum += player_row.iloc[0].get("Matches", 0) or 0
            total_matches = int(_sum)
        row["Total Matches"] = total_matches
        
        # Compute historical ratings per season
        for season in sorted(season_data.keys()):
            if "Player" not in season_data[season].columns:
                continue
            player_row = season_data[season][season_data[season]["Player"] == player_name]
            if not player_row.empty:
                row[str(season)] = player_row.iloc[0].get(rating_col, np.nan)
            else:
                row[str(season)] = np.nan
        
        # Compute career average
        row["Career"] = compute_career_average(player_name, season_data, rating_col)
        
        # Compute last 2 years average
        row["Last 2 Average"] = compute_last_n_years_average(
            player_name, season_data, current_season, n_years=2, rating_col=rating_col
        )
        
        # Compute year-over-year change
        rating_curr = row.get(str(current_season), np.nan) if str(current_season) in row else np.nan
        rating_prev = row.get(str(current_season - 1), np.nan) if str(current_season - 1) in row else np.nan
        if pd.notna(rating_curr) and pd.notna(rating_prev):
            row[f"{current_season} vs {current_season - 1}"] = rating_curr - rating_prev
        else:
            row[f"{current_season} vs {current_season - 1}"] = np.nan
        
        summary_rows.append(row)
    
    # Create DataFrame
    summary_df = pd.DataFrame(summary_rows)
    
    # Add draft data if available
    if not draft_df.empty and "Player" in draft_df.columns:
        draft_cols = ["Player"]
        for col in ["Draft Year", "Draft Pick", "Draft #", "Draft Round"]:
            if col in draft_df.columns:
                draft_cols.append(col)
        if len(draft_cols) > 1:
            summary_df = summary_df.merge(
                draft_df[draft_cols].drop_duplicates("Player"),
                on="Player",
                how="left"
            )
    
    # Add contract data if available
    if not contract_df.empty and "Player" in contract_df.columns:
        contract_cols = ["Player"]
        for col in ["Contract Expiry", "Contract End"]:
            if col in contract_df.columns:
                contract_cols.append(col)
        if len(contract_cols) > 1:
            summary_df = summary_df.merge(
                contract_df[contract_cols].drop_duplicates("Player"),
                on="Player",
                how="left"
            )
    
    # Add squads data (jumper number, etc) if available
    if not squads_df.empty and "Player" in squads_df.columns:
        squad_cols = ["Player"]
        for col in ["Jumper", "JumperNumber", "Jersey", "Number"]:
            if col in squads_df.columns:
                squad_cols.append(col)
        if len(squad_cols) > 1:
            squads_merge = squads_df[squad_cols].drop_duplicates("Player")
            # Standardize column name to "Jumper"
            if "JumperNumber" in squads_merge.columns and "Jumper" not in squads_merge.columns:
                squads_merge = squads_merge.rename(columns={"JumperNumber": "Jumper"})
            summary_df = summary_df.merge(
                squads_merge,
                on="Player",
                how="left"
            )
    
    # Enrich generic positions (FootyWire uses "Forward", "Defender", "Midfield")
    # with detailed positions (Key Forward, Gen. Forward, Wing, etc.) from Excel summary
    _GENERIC_POSITIONS = {"Forward", "Defender", "Midfield", "Ruck",
                          "DefenderForward", "MidfieldForward", "ForwardRuck",
                          "DefenderMidfield", "DefenderRuck"}
    has_generic = summary_df["Position"].isin(_GENERIC_POSITIONS).any()
    if has_generic:
        _pos_lookup = {}
        # Try Excel summary first
        try:
            _excel_path = DATA_DIR.parent / "AFL Player Ratings.xlsx"
            if _excel_path.exists():
                _xl = pd.ExcelFile(_excel_path)
                if "Summary" in _xl.sheet_names:
                    _sum = _xl.parse("Summary")
                    _sum.columns = _sum.columns.astype(str).str.strip()
                    if "Player" in _sum.columns and "Position" in _sum.columns:
                        for _, r in _sum.iterrows():
                            pname = str(r["Player"]).strip().lower()
                            pos = str(r["Position"]).strip()
                            if pname and pos and pos not in ("nan", ""):
                                _pos_lookup[pname] = pos
        except Exception:
            pass
        
        _FW_MAP = {
            "Forward": "Gen. Forward", "Defender": "Gen. Defender",
            "Midfield": "Midfielder", "DefenderForward": "Gen. Defender",
            "MidfieldForward": "Mid-Forward", "ForwardRuck": "Ruck",
            "DefenderMidfield": "Gen. Defender", "DefenderRuck": "Gen. Defender",
        }
        
        def _enrich_pos(row):
            cur = str(row.get("Position", "")).strip()
            if cur not in _GENERIC_POSITIONS:
                return cur
            player = str(row.get("Player", "")).strip()
            enriched = _pos_lookup.get(player.lower())
            if enriched:
                return enriched
            return _FW_MAP.get(cur, cur)
        
        summary_df["Position"] = summary_df.apply(_enrich_pos, axis=1)
    
    # Compute rankings
    summary_df = compute_rankings(summary_df, current_season)
    
    # Compute cap values (placeholder - needs salary cap constant)
    summary_df = compute_cap_values(summary_df, current_season)
    
    return summary_df


def compute_rankings(df: pd.DataFrame, current_season: int = 2026) -> pd.DataFrame:
    """
    Compute rankings for career, current season, and last 2 years.
    
    Rankings are computed:
    - Overall (all players)
    - By position (within position group)
    """
    # Career rank (only for players with >20 games)
    mask = df["Total Matches"] > 20
    df["Career Rank >20gms"] = np.nan
    df.loc[mask, "Career Rank >20gms"] = df.loc[mask, "Career"].rank(ascending=False)
    
    # Current season ranking
    current_col = str(current_season)
    matches_col = f"{current_season} Matches"
    if current_col in df.columns:
        df[f"{current_season} Rank"] = df[current_col].rank(ascending=False)
    
    # Last 2 years overall rank
    df["L2 Overall Rank"] = df["Last 2 Average"].rank(ascending=False)
    
    # Position-based rankings
    if "Position" in df.columns:
        # Current season position rank
        df[f"{current_season} Pos Rank"] = df.groupby("Position")[current_col].rank(ascending=False) if current_col in df.columns else np.nan
        
        # L2 position rank
        df["L2 Pos Rank"] = df.groupby("Position")["Last 2 Average"].rank(ascending=False)
    
    # Compute impact (difference from median rating)
    # Cap matches at MAX_REGULAR_SEASON_MATCHES (23) to avoid over-rating players who played finals
    if current_col in df.columns and matches_col in df.columns:
        median_rating = df[current_col].median()
        capped_matches = df[matches_col].clip(upper=MAX_REGULAR_SEASON_MATCHES)
        df[f"{current_season} Impact"] = (df[current_col] - median_rating) * capped_matches
    
    if "Last 2 Average" in df.columns:
        median_l2 = df["Last 2 Average"].median()
        # Cap at 2 regular seasons (23 × 2 = 46 matches) to avoid over-rating players who played finals
        l2_matches = df["Total Matches"].clip(upper=MAX_REGULAR_SEASON_MATCHES * 2)
        df["Last 2 Impact"] = (df["Last 2 Average"] - median_l2) * l2_matches
    
    return df


def compute_cap_values(
    df: pd.DataFrame,
    current_season: int = 2026,
    salary_cap: float = 19_000_000,  # 2026 AFL salary cap estimate
    min_cap_pct: float = 1.0,  # Minimum cap % (floor value)
) -> pd.DataFrame:
    """
    Compute cap value calculations for players.
    
    This replicates the Excel cap % and cap value calculations.
    Rating % is calculated as: (Rating × Matches) / Team's Total (Rating × Matches)
    This gives more weight to players who played more games.
    
    Args:
        df: DataFrame with player data including 'Team' and matches columns
        current_season: Season year to calculate for
        salary_cap: Total team salary cap
        min_cap_pct: Minimum cap percentage (floor for all players)
    """
    current_col = str(current_season)
    matches_col = f"{current_season} Matches"
    
    # Calculate current season Rating % using Rating × Matches formula
    if current_col in df.columns and "Team" in df.columns:
        # Get matches - try various column names
        matches = None
        for col in [matches_col, "2025 Matches", "Matches"]:
            if col in df.columns:
                matches = df[col].fillna(0)
                break
        
        if matches is not None:
            # NOTE: Do NOT cap matches for Cap % calculations - players who play more games
            # should have higher cap percentages as they contribute more to their team's output
            # Calculate Rating × Matches for each player
            df["_rating_x_matches"] = df[current_col].fillna(0) * matches
            
            # Calculate team totals for Rating × Matches
            team_rxm_totals = df.groupby("Team")["_rating_x_matches"].transform("sum")
            
            # Calculate player's percentage of their team's total
            df[f"{current_season} Rating %"] = (df["_rating_x_matches"] / team_rxm_totals) * 100
            
            # Handle teams with zero total (shouldn't happen, but safety check)
            df.loc[team_rxm_totals == 0, f"{current_season} Rating %"] = 0
            
            # Apply minimum cap percentage floor
            df[f"{current_season} Rating %"] = df[f"{current_season} Rating %"].clip(lower=min_cap_pct)
            
            # Cleanup temp column
            df = df.drop(columns=["_rating_x_matches"])
        else:
            # Fallback to simple rating / team total if no matches column
            team_totals = df.groupby("Team")[current_col].transform("sum")
            df[f"{current_season} Rating %"] = (df[current_col] / team_totals) * 100
            df[f"{current_season} Rating %"] = df[f"{current_season} Rating %"].clip(lower=min_cap_pct)
            df.loc[team_totals == 0, f"{current_season} Rating %"] = 0
        
        df[f"{current_season} Cap %"] = df[f"{current_season} Rating %"]
        df[f"{current_season} Cap Value"] = (df[f"{current_season} Rating %"] / 100) * salary_cap
    
    # Last 2 years cap calculation (also using weighted formula)
    if "Last 2 Average" in df.columns and "Team" in df.columns:
        # For L2, we use L2 matches if available, otherwise estimate
        l2_matches_col = "L2 Matches"
        l2_matches = None
        
        if l2_matches_col in df.columns:
            l2_matches = df[l2_matches_col].fillna(0)
        elif "Total Matches" in df.columns and matches_col in df.columns:
            # Estimate L2 matches from total - but this isn't accurate
            # Better to use the raw L2 average directly
            pass
        
        if l2_matches is not None:
            df["_l2_rxm"] = df["Last 2 Average"].fillna(0) * l2_matches
            team_l2_rxm = df.groupby("Team")["_l2_rxm"].transform("sum")
            df["L2 Rating %"] = (df["_l2_rxm"] / team_l2_rxm) * 100
            df.loc[team_l2_rxm == 0, "L2 Rating %"] = 0
            df["L2 Rating %"] = df["L2 Rating %"].clip(lower=min_cap_pct)
            df = df.drop(columns=["_l2_rxm"])
        else:
            # Fallback: use simple L2 average / team total
            team_l2_totals = df.groupby("Team")["Last 2 Average"].transform("sum")
            df["L2 Rating %"] = (df["Last 2 Average"] / team_l2_totals) * 100
            df["L2 Rating %"] = df["L2 Rating %"].clip(lower=min_cap_pct)
            df.loc[team_l2_totals == 0, "L2 Rating %"] = 0
        
        df["L2 Cap %"] = df["L2 Rating %"]
        df["Last 2 Years Cap Value"] = (df["L2 Rating %"] / 100) * salary_cap
    
    return df


def compute_last_20_games_average(
    player_name: str,
    season_data: dict[int, pd.DataFrame],
    current_season: int,
    rating_col: str = "RatingPoints_Avg"
) -> float:
    """
    Compute rolling average over last 20 games.
    
    Note: This requires game-by-game data, not season averages.
    For now, approximates using season data weighted by recency.
    """
    # Simplified approximation using last 2 seasons
    # Actual implementation would need game-level data
    return compute_last_n_years_average(
        player_name, season_data, current_season, n_years=2, rating_col=rating_col
    )


def save_player_summary(df: pd.DataFrame, filename: str = "player_summary.csv"):
    """Save computed player summary to CSV."""
    output_path = DATA_DIR / "computed" / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return output_path


# ============================================================
# Module entry point
# ============================================================

if __name__ == "__main__":
    print("Computing player summary from raw CSV data...")
    
    try:
        summary = compute_player_summary(current_season=2026)
        print(f"\n✅ Computed summary for {len(summary)} players")
        print(f"\nColumns: {list(summary.columns)}")
        
        # Show sample
        print("\n=== Sample Data ===")
        cols = ["Player", "Team", "Position", "Total Matches", "Career", "Last 2 Average", "2026 Rank"]
        available_cols = [c for c in cols if c in summary.columns]
        print(summary[available_cols].head(10).to_string())
        
        # Save to CSV
        path = save_player_summary(summary)
        print(f"\n💾 Saved to: {path}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
