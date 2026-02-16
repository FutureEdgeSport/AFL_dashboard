"""
compute_ratings.py

Moves ALL compute logic from Excel into Python so Excel files contain raw data only.
The app can:
- Auto-discover seasons from sheet names
- Compute Season / L10 / L5 tables consistently
- Never require precomputed "Ladders" tabs or Excel formulas
"""

import re
import logging
from typing import Optional
import pandas as pd
import numpy as np

# Configure logging
logger = logging.getLogger(__name__)

# Team name normalization mapping - imported from centralized config
try:
    from config.constants import TEAM_NAME_NORMALIZE_MAP as TEAM_NAME_MAP
except ImportError:
    # Fallback if config not available (e.g. running standalone)
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

# ============================================================================
# SHEET DISCOVERY
# ============================================================================

def get_player_seasons(xl: pd.ExcelFile) -> list[int]:
    """
    Discover player seasons from sheet names matching r"^\\d{4}$".
    
    Args:
        xl: ExcelFile object for player ratings workbook
        
    Returns:
        List of season years (integers), sorted descending
    """
    seasons = []
    pattern = re.compile(r"^\d{4}$")
    for sheet_name in xl.sheet_names:
        if pattern.match(str(sheet_name)):
            try:
                seasons.append(int(sheet_name))
            except ValueError:
                continue
    return sorted(seasons, reverse=True)


def get_team_seasons(xl: pd.ExcelFile) -> list[int]:
    """
    Discover team seasons from sheet names.
    Looks for patterns like "{year} Summary" or "{year} Last 10 Summary".
    
    Args:
        xl: ExcelFile object for team ratings workbook
        
    Returns:
        List of unique season years (integers), sorted descending
    """
    seasons = set()
    patterns = [
        re.compile(r"^(\d{4}) Summary$"),
        re.compile(r"^(\d{4}) Last \d+ Summary$"),
        re.compile(r"^(\d{4}) Season All$"),
    ]
    
    for sheet_name in xl.sheet_names:
        for pattern in patterns:
            match = pattern.match(str(sheet_name))
            if match:
                try:
                    seasons.add(int(match.group(1)))
                except ValueError:
                    continue
                break
    
    return sorted(list(seasons), reverse=True)


# ============================================================================
# ROBUST PARSING FOR REPORT-STYLE SHEETS
# ============================================================================

def _find_header_row(df: pd.DataFrame, key: str = "Team") -> Optional[int]:
    """
    Find the row index where the header containing 'key' (e.g., 'Team') is located.
    
    Args:
        df: DataFrame read with header=None
        key: Column header to search for (case-insensitive)
        
    Returns:
        Row index of header, or None if not found
    """
    key_lower = key.lower().strip()
    
    for idx in range(min(10, len(df))):  # Check first 10 rows only
        row = df.iloc[idx]
        for val in row:
            if pd.notna(val) and str(val).strip().lower() == key_lower:
                return idx
    
    return None


def _has_subheader_row(df: pd.DataFrame, header_idx: int) -> bool:
    """
    Check if the row after the header is a subheader row (contains many 'Rank' labels).
    
    Args:
        df: DataFrame read with header=None
        header_idx: Index of the detected header row
        
    Returns:
        True if next row appears to be a subheader row
    """
    if header_idx + 1 >= len(df):
        return False
    
    subheader_row = df.iloc[header_idx + 1]
    rank_count = sum(1 for val in subheader_row 
                     if pd.notna(val) and str(val).strip().lower() == "rank")
    
    # If more than 3 "Rank" entries, likely a subheader row
    return rank_count > 3


def _build_flattened_columns(header_row: pd.Series, subheader_row: Optional[pd.Series]) -> list[str]:
    """
    Build flattened column names by forward-filling group headers.
    
    For summary sheets with multi-level headers:
    - Row 2: Group headers (e.g., "Team", "Ball Winning", "Ball Movement", ...)
    - Row 3: Sub-headers (e.g., "Post Clear CP Diff", "Rank", "Ground Ball Diff", ...)
    
    Result: "Ball Winning | Post Clear CP Diff", "Ball Winning | Rank", etc.
    """
    columns = []
    current_group = ""
    
    for i, header_val in enumerate(header_row):
        header_str = str(header_val).strip() if pd.notna(header_val) else ""
        
        # Update current group if we have a non-empty header
        if header_str and header_str.lower() not in ["nan", "none", ""]:
            current_group = header_str
        
        if subheader_row is not None:
            sub_val = subheader_row.iloc[i] if i < len(subheader_row) else None
            sub_str = str(sub_val).strip() if pd.notna(sub_val) else ""
            
            # Handle special case: "Team" column has no subheader
            if current_group.lower() == "team" and not sub_str:
                columns.append("Team")
            elif sub_str and sub_str.lower() not in ["nan", "none", ""]:
                # Combine group + subheader
                if current_group and current_group.lower() != "team":
                    columns.append(f"{current_group} | {sub_str}")
                else:
                    columns.append(sub_str)
            else:
                # Empty subheader - use group name or generate placeholder
                columns.append(current_group if current_group else f"Col_{i}")
        else:
            # No subheader row - use header directly
            columns.append(header_str if header_str else f"Col_{i}")
    
    return columns


def parse_table_with_detected_header(
    xl: pd.ExcelFile,
    sheet_name: str,
    key: str = "Team"
) -> pd.DataFrame:
    """
    Parse a report-style sheet with detected header row.
    
    Many Team sheets have:
    - 2 blank rows
    - Header row with group labels (Team, Ball Winning, Ball Movement, etc.)
    - Optional subheader row with metric names and "Rank" labels
    - Data rows
    
    Args:
        xl: ExcelFile object
        sheet_name: Name of sheet to parse
        key: Column header to search for (default "Team")
        
    Returns:
        DataFrame with flattened column names, or empty DataFrame on error
    """
    try:
        raw = xl.parse(sheet_name, header=None)
    except Exception as e:
        logger.warning(f"Could not read sheet '{sheet_name}': {e}")
        return pd.DataFrame()
    
    if raw.empty:
        logger.warning(f"Sheet '{sheet_name}' is empty")
        return pd.DataFrame()
    
    # Find header row
    header_idx = _find_header_row(raw, key)
    if header_idx is None:
        logger.warning(f"Could not find '{key}' header in sheet '{sheet_name}'")
        return pd.DataFrame()
    
    header_row = raw.iloc[header_idx]
    
    # Check for subheader row
    has_subheader = _has_subheader_row(raw, header_idx)
    subheader_row = raw.iloc[header_idx + 1] if has_subheader else None
    
    # Build column names
    columns = _build_flattened_columns(header_row, subheader_row)
    
    # Get data rows (after header + optional subheader)
    data_start = header_idx + 2 if has_subheader else header_idx + 1
    data_df = raw.iloc[data_start:].copy()
    
    # Assign columns
    if len(columns) == data_df.shape[1]:
        data_df.columns = columns
    else:
        # Fallback: use header row directly
        data_df.columns = header_row.values
    
    # Clean up
    # Drop fully empty columns
    data_df = data_df.dropna(axis=1, how="all")
    
    # Make column names unique to avoid duplicate column issues
    cols = list(data_df.columns)
    seen = {}
    unique_cols = []
    for c in cols:
        c_str = str(c).strip() if pd.notna(c) else "unnamed"
        if c_str in seen:
            seen[c_str] += 1
            unique_cols.append(f"{c_str}_{seen[c_str]}")
        else:
            seen[c_str] = 0
            unique_cols.append(c_str)
    data_df.columns = unique_cols
    
    # Strip whitespace from string columns
    for col in data_df.columns:
        col_data = data_df[col]
        if hasattr(col_data, 'dtype') and col_data.dtype == "object":
            data_df[col] = col_data.astype(str).str.strip()
    
    # Filter out empty Team rows and summary rows
    if "Team" in data_df.columns:
        data_df = data_df[data_df["Team"].notna()].copy()
        data_df = data_df[data_df["Team"].astype(str).str.strip() != ""].copy()
        data_df = data_df[~data_df["Team"].isin(["Total", "Totals", "Average", "Averages", "League", "Overall", "nan", "None"])].copy()
        
        # Normalize team names
        data_df["Team"] = data_df["Team"].replace(TEAM_NAME_MAP)
    
    return data_df.reset_index(drop=True)


# ============================================================================
# TEAM COMPUTE (REPLACE EXCEL VLOOKUP + LADDER SHEETS)
# ============================================================================

def compute_team_category_rankings(team_summary_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute team ladder rankings from a parsed summary DataFrame.
    
    Takes the summary data with category rankings (Ball Winning Ranking, etc.)
    and produces a normalized ladder DataFrame.
    
    Args:
        team_summary_df: DataFrame from parse_table_with_detected_header
        
    Returns:
        Normalized ladder DataFrame with Team and metric/rank columns
    """
    if team_summary_df.empty or "Team" not in team_summary_df.columns:
        return pd.DataFrame()
    
    # Find ranking columns (contain "Ranking" in name)
    ranking_cols = [c for c in team_summary_df.columns 
                    if "ranking" in str(c).lower() or "rating" in str(c).lower()]
    
    # Build output DataFrame
    result = pd.DataFrame()
    result["Team"] = team_summary_df["Team"].copy()
    
    # Map column patterns to expected output format
    # Looking for: "Ball Winning | Ball Winning Ranking", "Ball Movement | Ball Movement Ranking", etc.
    # Or direct columns: "Ball Winning Ranking", "Ball Movement Ranking", etc.
    
    category_mapping = {
        "ball winning": "Ball Winning Ranking",
        "ball movement": "Ball Movement Ranking", 
        "scoring": "Scoring Ranking",
        "defence": "Defence Ranking",
        "pressure": "Pressure Ranking",
        "health check": "Health Check Ranking",
        "attack rating": "Attack Rating",
        "defence rating": "Defence Rating",
        "overall rating": "Overall Rating",
        "team rating": "Team Rating",
    }
    
    for pattern, output_name in category_mapping.items():
        # Find the value column: endswith '| {output_name}' or equals output_name
        value_col = None
        rank_col = None
        for i, col in enumerate(team_summary_df.columns):
            col_str = str(col).strip()
            if col_str.endswith(f"| {output_name}") or col_str == output_name:
                value_col = col
                # The rank column is usually the next column and ends with '| Rank' or similar
                if i + 1 < len(team_summary_df.columns):
                    next_col = team_summary_df.columns[i + 1]
                    next_col_str = str(next_col).strip().lower()
                    if next_col_str.endswith("rank") or "rank" in next_col_str:
                        rank_col = next_col
                break
        if value_col is not None:
            result[output_name] = pd.to_numeric(team_summary_df[value_col], errors="coerce")
            if rank_col is not None:
                result[f"{output_name} Rank"] = pd.to_numeric(team_summary_df[rank_col], errors="coerce")
    
    # If we didn't find the expected columns, try a simpler approach
    # Look for columns that end with "Ranking" directly in the summary sheet
    if len(result.columns) <= 1:
        for col in team_summary_df.columns:
            if col == "Team":
                continue
            col_str = str(col)
            # Try to extract just the last part after "|" if present
            if "|" in col_str:
                metric_name = col_str.split("|")[-1].strip()
            else:
                metric_name = col_str
            
            if "ranking" in metric_name.lower() or "rating" in metric_name.lower():
                values = pd.to_numeric(team_summary_df[col], errors="coerce")
                result[metric_name] = values
    
    # Ensure numeric conversion for all non-Team columns
    for col in result.columns:
        if col != "Team":
            result[col] = pd.to_numeric(result[col], errors="coerce")
    
    # Drop duplicates and reset index
    result = result.drop_duplicates(subset=["Team"], keep="first").reset_index(drop=True)
    
    return result


def _extract_ranking_columns_from_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract the category ranking columns from a parsed summary DataFrame.
    Handles both flat and pipe-delimited column formats.
    
    Returns a DataFrame with Team and the ranking columns normalized.
    """
    if summary_df.empty:
        return pd.DataFrame()
    
    result = pd.DataFrame()
    result["Team"] = summary_df["Team"].copy()
    
    # Expected ranking column patterns
    ranking_patterns = [
        ("Ball Winning Ranking", ["ball winning | ball winning ranking", "ball winning ranking"]),
        ("Ball Movement Ranking", ["ball movement | ball movement ranking", "ball movement ranking"]),
        ("Scoring Ranking", ["scoring | scoring ranking", "scoring ranking"]),
        ("Defence Ranking", ["defence | defence ranking", "defence ranking"]),
        ("Pressure Ranking", ["pressure | pressure ranking", "pressure ranking"]),
        ("Health Check Ranking", ["health check | health check ranking", "health check ranking"]),
    ]
    
    # Wheelo Ratings patterns  
    rating_patterns = [
        ("Attack Rating", ["wheelo ratings | attack rating", "attack rating"]),
        ("Defence Rating", ["wheelo ratings | defence rating", "defence rating"]),
        ("Overall Rating", ["wheelo ratings | overall rating", "overall rating"]),
        ("Team Rating", ["team rating"]),
    ]
    
    # Convert column names to lowercase for matching
    col_lower_map = {str(c).lower().strip(): c for c in summary_df.columns}
    
    # Extract rankings
    for output_name, patterns in ranking_patterns + rating_patterns:
        for pattern in patterns:
            if pattern in col_lower_map:
                actual_col = col_lower_map[pattern]
                values = pd.to_numeric(summary_df[actual_col], errors="coerce")
                result[output_name] = values
                
                # Look for rank column
                actual_idx = list(summary_df.columns).index(actual_col)
                if actual_idx + 1 < len(summary_df.columns):
                    next_col = summary_df.columns[actual_idx + 1]
                    if "rank" in str(next_col).lower():
                        rank_values = pd.to_numeric(summary_df[next_col], errors="coerce")
                        result[f"{output_name} Rank"] = rank_values
                break
    
    return result.drop_duplicates(subset=["Team"], keep="first").reset_index(drop=True)


def load_team_block(
    xl: pd.ExcelFile,
    season: int,
    block: str = "Season"
) -> pd.DataFrame:
    """
    Load team data for a specific block (Season, L10, L5).
    
    Args:
        xl: ExcelFile object for team ratings workbook
        block: One of "Season", "L10", "L5"
        season: Season year
        
    Returns:
        Parsed DataFrame or empty DataFrame if not available
    """
    # Determine sheet name based on block
    if block == "Season":
        sheet_name = f"{season} Summary"
    elif block == "L10":
        sheet_name = f"{season} Last 10 Summary"
    elif block == "L5":
        sheet_name = f"{season} Last 5 Summary"
    else:
        logger.warning(f"Unknown block type: {block}")
        return pd.DataFrame()
    
    # Check if sheet exists
    if sheet_name not in xl.sheet_names:
        logger.warning(f"Sheet '{sheet_name}' not found in workbook")
        
        # For L5, try to compute from match-level data
        if block == "L5":
            matches_sheet = f"{season} Season All"
            if matches_sheet in xl.sheet_names:
                logger.info(f"Computing L5 from match-level data")
                matches_df = parse_table_with_detected_header(xl, matches_sheet, "Team")
                return compute_last_n_from_matches(matches_df, n=5)
        
        return pd.DataFrame()
    
    return parse_table_with_detected_header(xl, sheet_name, "Team")


# ============================================================================
# LAST-N COMPUTATION (REMOVES NEED FOR EXCEL L10/L5 SHEETS)
# ============================================================================

def compute_last_n_from_matches(
    matches_df: pd.DataFrame,
    n: int,
    group_col: str = "Team",
    order_cols: Optional[list[str]] = None
) -> pd.DataFrame:
    """
    Compute last N games aggregation from match-level data.
    
    Note: This function assumes match-level data is available.
    If match data isn't available (only summary data), this returns empty DataFrame.
    
    Args:
        matches_df: Match-level DataFrame with one row per team per game
        n: Number of recent games to include
        group_col: Column to group by (default "Team")
        order_cols: Columns to sort by for recency (default ["Round", "Date"])
        
    Returns:
        Aggregated DataFrame with mean of numeric columns
    """
    if matches_df.empty:
        logger.warning("Match-level data is empty, cannot compute last N")
        return pd.DataFrame()
    
    if group_col not in matches_df.columns:
        logger.warning(f"Group column '{group_col}' not found in matches data")
        return pd.DataFrame()
    
    # Default order columns
    if order_cols is None:
        order_cols = ["Round", "Date"]
    
    # Check which order columns exist
    available_order_cols = [c for c in order_cols if c in matches_df.columns]
    if not available_order_cols:
        # If no order columns, assume data is already sorted
        logger.warning("No order columns found, using data as-is")
        available_order_cols = []
    
    # Convert order columns to sortable format
    df = matches_df.copy()
    for col in available_order_cols:
        if "date" in col.lower():
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif "round" in col.lower():
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Sort and take last N per team
    if available_order_cols:
        df = df.sort_values(available_order_cols, ascending=False)
    
    last_n = df.groupby(group_col).head(n)
    
    # Aggregate numeric columns (mean)
    numeric_cols = last_n.select_dtypes(include=[np.number]).columns.tolist()
    if group_col in numeric_cols:
        numeric_cols.remove(group_col)
    
    agg_dict = {col: "mean" for col in numeric_cols}
    result = last_n.groupby(group_col).agg(agg_dict).reset_index()
    
    return result


# ============================================================================
# PLAYER COMPUTE (REMOVE DEPENDENCY ON EXCEL SUMMARY FORMULAS)
# ============================================================================

def compute_player_summary_from_seasons(
    player_xl: pd.ExcelFile,
    seasons: Optional[list[int]] = None
) -> pd.DataFrame:
    """
    Compute player summary from per-season data.
    
    This removes dependency on the Excel "Summary" sheet which uses VLOOKUPs.
    
    Args:
        player_xl: ExcelFile object for player ratings workbook
        seasons: List of seasons to include (default: auto-discover)
        
    Returns:
        Summary DataFrame with aggregated player statistics
    """
    if seasons is None:
        seasons = get_player_seasons(player_xl)
    
    if not seasons:
        logger.warning("No seasons found for player summary")
        return pd.DataFrame()
    
    all_season_data = []
    
    for season in seasons:
        sheet_name = str(season)
        if sheet_name not in player_xl.sheet_names:
            continue
        
        try:
            df = player_xl.parse(sheet_name)
            df.columns = df.columns.astype(str).str.strip()
            df["Season"] = season
            all_season_data.append(df)
        except Exception as e:
            logger.warning(f"Could not load player data for {season}: {e}")
            continue
    
    if not all_season_data:
        return pd.DataFrame()
    
    combined = pd.concat(all_season_data, ignore_index=True)
    
    # Normalize column names
    rating_candidates = ["RatingPoints_Avg", "Rating", "AvgRating", "Avg Rating"]
    for cand in rating_candidates:
        if cand in combined.columns:
            if cand != "RatingPoints_Avg":
                combined = combined.rename(columns={cand: "RatingPoints_Avg"})
            break
    
    # Clean team names
    if "Team" in combined.columns:
        combined["Team"] = combined["Team"].astype(str).str.strip().replace(TEAM_NAME_MAP)
    
    # Clean player names
    if "Player" in combined.columns:
        combined["Player"] = combined["Player"].astype(str).str.strip()
    
    # Compute summary statistics per player
    summary_cols = ["Player", "Team"]
    agg_cols = {
        "Matches": "sum",
        "RatingPoints_Avg": "mean",
        "CoachesVotes_Avg": "mean",
        "TimeOnGround": "mean",
    }
    
    # Filter to available columns
    available_agg = {k: v for k, v in agg_cols.items() if k in combined.columns}
    
    if not available_agg:
        logger.warning("No aggregatable columns found in player data")
        return combined
    
    # Group by player and team, aggregate
    group_cols = [c for c in summary_cols if c in combined.columns]
    summary = combined.groupby(group_cols).agg(available_agg).reset_index()
    
    # Add season range
    season_range = combined.groupby(group_cols)["Season"].agg(["min", "max"]).reset_index()
    season_range.columns = group_cols + ["First_Season", "Last_Season"]
    summary = summary.merge(season_range, on=group_cols, how="left")
    
    return summary


# ============================================================================
# VALIDATION / MIGRATION HELPERS
# ============================================================================

def compare_to_excel_snapshot(
    computed_df: pd.DataFrame,
    excel_df: pd.DataFrame,
    key_cols: list[str] = None,
    tolerance: float = 1e-6
) -> dict:
    """
    Compare a computed DataFrame to an Excel snapshot for migration validation.
    
    Args:
        computed_df: DataFrame computed by Python
        excel_df: DataFrame read from Excel (existing ladder/summary sheet)
        key_cols: Columns to use as keys for comparison (default ["Team"])
        tolerance: Tolerance for numeric comparisons
        
    Returns:
        Dictionary with comparison results:
        - "missing_in_computed": Teams in Excel but not in computed
        - "missing_in_excel": Teams in computed but not in Excel
        - "numeric_diffs": List of (team, column, computed_val, excel_val, diff)
        - "match_pct": Percentage of values that match
    """
    if key_cols is None:
        key_cols = ["Team"]
    
    results = {
        "missing_in_computed": [],
        "missing_in_excel": [],
        "numeric_diffs": [],
        "match_pct": 0.0,
    }
    
    if computed_df.empty or excel_df.empty:
        logger.warning("One or both DataFrames are empty")
        return results
    
    # Normalize team names in both
    for df in [computed_df, excel_df]:
        if "Team" in df.columns:
            df["Team"] = df["Team"].astype(str).str.strip().replace(TEAM_NAME_MAP)
    
    # Get sets of keys
    computed_keys = set(computed_df[key_cols[0]].unique())
    excel_keys = set(excel_df[key_cols[0]].unique())
    
    results["missing_in_computed"] = list(excel_keys - computed_keys)
    results["missing_in_excel"] = list(computed_keys - excel_keys)
    
    # Log missing teams
    if results["missing_in_computed"]:
        logger.warning(f"Teams in Excel but not computed: {results['missing_in_computed']}")
    if results["missing_in_excel"]:
        logger.warning(f"Teams computed but not in Excel: {results['missing_in_excel']}")
    
    # Compare numeric values for matching teams
    common_keys = computed_keys & excel_keys
    common_cols = set(computed_df.columns) & set(excel_df.columns) - set(key_cols)
    
    total_comparisons = 0
    matching_values = 0
    
    for key in common_keys:
        comp_row = computed_df[computed_df[key_cols[0]] == key].iloc[0]
        excel_row = excel_df[excel_df[key_cols[0]] == key].iloc[0]
        
        for col in common_cols:
            comp_val = comp_row.get(col)
            excel_val = excel_row.get(col)
            
            # Skip non-numeric comparisons
            try:
                comp_num = float(comp_val) if pd.notna(comp_val) else None
                excel_num = float(excel_val) if pd.notna(excel_val) else None
            except (ValueError, TypeError):
                continue
            
            if comp_num is None and excel_num is None:
                continue
            
            total_comparisons += 1
            
            if comp_num is None or excel_num is None:
                diff = float("inf")
            else:
                diff = abs(comp_num - excel_num)
            
            if diff <= tolerance:
                matching_values += 1
            else:
                results["numeric_diffs"].append({
                    "team": key,
                    "column": col,
                    "computed": comp_num,
                    "excel": excel_num,
                    "diff": diff,
                })
                logger.info(f"Diff: {key} | {col} | computed={comp_num} | excel={excel_num} | diff={diff}")
    
    results["match_pct"] = (matching_values / total_comparisons * 100) if total_comparisons > 0 else 0.0
    
    return results


# ============================================================================
# CONVENIENCE FUNCTIONS FOR APP.PY INTEGRATION
# ============================================================================

def load_team_ladders_computed(
    xl: pd.ExcelFile,
    season: int,
    block: str = "Season"
) -> pd.DataFrame:
    """
    Load and compute team ladder data (replaces reading from Excel ladder sheets).
    
    This is the main function to replace Excel-based ladder loading.
    
    Args:
        xl: ExcelFile object for team ratings workbook
        season: Season year
        block: "Season", "L10", or "L5"
        
    Returns:
        Normalized ladder DataFrame ready for app.py consumption
    """
    # Load the appropriate summary block
    summary_df = load_team_block(xl, season, block)
    
    if summary_df.empty:
        logger.warning(f"Could not load {block} data for {season}")
        return pd.DataFrame()
    
    # Compute rankings from summary
    ladder_df = compute_team_category_rankings(summary_df)
    
    # If computed ladder is too sparse, try direct extraction
    if len(ladder_df.columns) <= 2:
        ladder_df = _extract_ranking_columns_from_summary(summary_df)
    
    return ladder_df
