"""
AFL Dashboard Constants and Configuration
==========================================
Centralized configuration for the AFL Dashboard application.
This file contains all constants, mappings, and configuration values.
"""

from typing import Dict, List, Tuple

# ============================================================================
# SEASON CONFIGURATION
# ============================================================================
CURRENT_SEASON: int = 2025
AVAILABLE_SEASONS: List[int] = [2025, 2024, 2023, 2022]
DEFAULT_SEASON: int = 2025

# ============================================================================
# FILE PATHS
# ============================================================================
TEAM_FILE: str = "AFL Team Ratings.xlsx"
PLAYER_FILE: str = "AFL Player Ratings.xlsx"
TRAITS_FILE: str = "2025 Traits ENRICHED.xlsx"
LADDERS_FILE: str = "afl_ladders_2011_2025.xlsx"

LOGO_FOLDER: str = "team_logos"
PLAYER_PHOTO_FOLDER: str = "player_photos"

# ============================================================================
# TEAM MAPPINGS
# ============================================================================
TEAM_CODE_MAP: Dict[str, str] = {
    "Adelaide": "afc",
    "Brisbane": "lions",
    "Carlton": "cfc",
    "Collingwood": "cofc",
    "Essendon": "efc",
    "Fremantle": "ffc",
    "Geelong": "gfc",
    "Gold Coast": "gcfc",
    "GWS": "gws",
    "GWS Giants": "gws",
    "Hawthorn": "hfc",
    "Melbourne": "mfc",
    "North Melbourne": "nmfc",
    "Port Adelaide": "pafc",
    "Richmond": "rfc",
    "St Kilda": "skfc",
    "Sydney": "sfc",
    "West Coast": "wcfc",
    "Western Bulldogs": "wbfc",
}

TEAM_CODE_TO_NAME: Dict[str, str] = {
    "AFC": "Adelaide",
    "BFC": "Brisbane",
    "CFC": "Carlton",
    "COFC": "Collingwood",
    "EFC": "Essendon",
    "FRFC": "Fremantle",
    "GFC": "Geelong",
    "GCFC": "Gold Coast",
    "GWS": "GWS Giants",
    "HFC": "Hawthorn",
    "MFC": "Melbourne",
    "NMFC": "North Melbourne",
    "PAFC": "Port Adelaide",
    "RFC": "Richmond",
    "SKFC": "St Kilda",
    "SFC": "Sydney",
    "WCFC": "West Coast",
    "WBFC": "Western Bulldogs",
}

TEAM_COLOURS: Dict[str, str] = {
    "Adelaide": "#002B5C",
    "Brisbane": "#7C003E",
    "Carlton": "#031A28",
    "Collingwood": "#000000",
    "Essendon": "#D50032",
    "Fremantle": "#2F0055",
    "Geelong": "#001F3D",
    "Gold Coast": "#E2001A",
    "GWS": "#F37A20",
    "GWS Giants": "#F37A20",
    "Hawthorn": "#4D2004",
    "Melbourne": "#0F1131",
    "North Melbourne": "#0055A4",
    "Port Adelaide": "#01A0E1",
    "Richmond": "#FFCC00",
    "St Kilda": "#E00034",
    "Sydney": "#E00034",
    "West Coast": "#003087",
    "Western Bulldogs": "#0055A4",
}

# All 18 AFL teams (normalized names)
ALL_TEAMS: List[str] = [
    "Adelaide", "Brisbane", "Carlton", "Collingwood", "Essendon",
    "Fremantle", "Geelong", "Gold Coast", "GWS Giants",
    "Hawthorn", "Melbourne", "North Melbourne", "Port Adelaide",
    "Richmond", "St Kilda", "Sydney", "West Coast", "Western Bulldogs"
]

# ============================================================================
# POSITION MAPPINGS
# ============================================================================
DEPTH_POSITIONS: List[str] = [
    "Key Defender",
    "Gen. Defender",
    "Midfielder",
    "Mid-Forward",
    "Wing",
    "Gen. Forward",
    "Ruck",
    "Key Forward",
]

POSITION_ABBREV_TO_FULL: Dict[str, str] = {
    "R": "Ruck",
    "M": "Midfielder",
    "MF": "Mid-Forward",
    "GD": "Gen. Defender",
    "W": "Wing",
    "GF": "Gen. Forward",
    "KF": "Key Forward",
    "KD": "Key Defender",
}

POSITION_COLOURS: Dict[str, Tuple[str, str]] = {
    "Key Defender": ("#ff0000", "white"),
    "Gen. Defender": ("#ff9900", "white"),
    "Midfielder": ("#00aa00", "white"),
    "Mid-Forward": ("#00aa00", "white"),
    "Wing": ("#ffff00", "black"),
    "Gen. Forward": ("#ffff00", "black"),
    "Ruck": ("#0099ff", "white"),
    "Key Forward": ("#0099ff", "white"),
}

# ============================================================================
# AGE BANDS
# ============================================================================
AGE_BANDS: List[str] = [
    "Under 22",
    "22 to 26 Year Old",
    "26 to 30 Year Old",
    "30+ Year Old",
]

# Alternate age band format used in some pages
AGE_BANDS_ALT: List[str] = ["<22", "22-25", "26-29", "30+"]

# ============================================================================
# METRIC CONFIGURATION
# ============================================================================
METRIC_ORDER: List[str] = [
    "Team Rating",
    "Ball Winning Ranking",
    "Ball Movement Ranking",
    "Scoring Ranking",
    "Defence Ranking",
    "Pressure Ranking",
]

# Rating column candidates in per-season sheets
RATING_COL_CANDIDATES: List[str] = [
    "RatingPoints_Avg",
    "RatingPoints_Ave",
    "RatingPoint_Ave",
    "RatingPoint_Avg",
]

# Trait columns for player analysis
TRAIT_COLUMNS: List[str] = [
    "Rating",
    "Ball Winning",
    "Ball Use",
    "Aerial",
    "Defence",
]

# ============================================================================
# UI CONFIGURATION
# ============================================================================
class UIConfig:
    """UI-related constants for consistent styling."""
    
    # Font stack
    FONT_FAMILY: str = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
    
    # Color thresholds (percentile-based)
    PERCENTILE_ELITE: float = 0.85      # Top 15%
    PERCENTILE_GOOD: float = 0.60       # 60-85%
    PERCENTILE_AVERAGE: float = 0.35    # 35-60%
    # Below 35% = below average
    
    # Rank thresholds (for 18 teams)
    RANK_ELITE: int = 4       # 1st-4th
    RANK_GOOD: int = 9        # 5th-9th
    RANK_AVERAGE: int = 14    # 10th-14th
    # 15th-18th = below average
    
    # Standard colors
    COLOR_ELITE: str = "#008000"          # Dark Green
    COLOR_GOOD: str = "#90EE90"           # Light Green
    COLOR_AVERAGE: str = "#FFA500"        # Orange
    COLOR_BELOW_AVERAGE: str = "#FF0000"  # Red
    
    # Text colors for backgrounds
    TEXT_ON_DARK: str = "#FFFFFF"
    TEXT_ON_LIGHT: str = "#000000"
    
    # Card/Table styling
    BORDER_RADIUS: str = "12px"
    BOX_SHADOW: str = "0 8px 32px rgba(0,0,0,0.4)"
    TRANSITION: str = "all 0.3s ease"


# ============================================================================
# COLOR FUNCTIONS
# ============================================================================
def get_rating_color(
    value: float,
    all_values,
    scheme: str = "percentile"
) -> Tuple[str, str]:
    """
    Unified color function for all rating displays.
    
    Args:
        value: The rating value to color
        all_values: Series or list of all values for percentile calculation
        scheme: "percentile" or "rank"
        
    Returns:
        Tuple of (background_color, text_color)
    """
    import pandas as pd
    
    if pd.isna(value):
        return "#666666", "#FFFFFF"
    
    try:
        series = pd.Series(all_values).dropna()
        if series.empty:
            return "#666666", "#FFFFFF"
        
        percentile = (series <= value).mean()
        
        if scheme == "percentile":
            if percentile >= UIConfig.PERCENTILE_ELITE:
                return UIConfig.COLOR_ELITE, UIConfig.TEXT_ON_DARK
            elif percentile >= UIConfig.PERCENTILE_GOOD:
                return UIConfig.COLOR_GOOD, UIConfig.TEXT_ON_LIGHT
            elif percentile >= UIConfig.PERCENTILE_AVERAGE:
                return UIConfig.COLOR_AVERAGE, UIConfig.TEXT_ON_DARK
            else:
                return UIConfig.COLOR_BELOW_AVERAGE, UIConfig.TEXT_ON_DARK
        
        elif scheme == "rank":
            # Convert percentile to rank (1-18)
            rank = int((1 - percentile) * 18) + 1
            if rank <= UIConfig.RANK_ELITE:
                return UIConfig.COLOR_ELITE, UIConfig.TEXT_ON_DARK
            elif rank <= UIConfig.RANK_GOOD:
                return UIConfig.COLOR_GOOD, UIConfig.TEXT_ON_LIGHT
            elif rank <= UIConfig.RANK_AVERAGE:
                return UIConfig.COLOR_AVERAGE, UIConfig.TEXT_ON_DARK
            else:
                return UIConfig.COLOR_BELOW_AVERAGE, UIConfig.TEXT_ON_DARK
        
        # Default fallback
        return "#666666", "#FFFFFF"
        
    except Exception:
        return "#666666", "#FFFFFF"


def get_rank_color(rank: int, total: int = 18) -> Tuple[str, str]:
    """
    Get color based on ranking position.
    
    Args:
        rank: The rank (1 = best)
        total: Total number of items being ranked (default 18 for AFL teams)
        
    Returns:
        Tuple of (background_color, text_color)
    """
    if rank is None or total is None or total == 0:
        return "#666666", "#FFFFFF"
    
    # Calculate which quartile
    if rank <= 4:
        return UIConfig.COLOR_ELITE, UIConfig.TEXT_ON_DARK
    elif rank <= 9:
        return UIConfig.COLOR_GOOD, UIConfig.TEXT_ON_LIGHT
    elif rank <= 14:
        return UIConfig.COLOR_AVERAGE, UIConfig.TEXT_ON_DARK
    else:
        return UIConfig.COLOR_BELOW_AVERAGE, UIConfig.TEXT_ON_DARK


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def get_ordinal(n: int) -> str:
    """Convert number to ordinal string (1st, 2nd, 3rd, etc.)"""
    if n is None:
        return "N/A"
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def safe_float(x) -> float:
    """Safely convert a value to float, returning None on failure."""
    if x is None:
        return None
    if isinstance(x, float) and (x != x):  # NaN check
        return None
    try:
        return float(str(x).replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def normalize_team_name(team: str) -> str:
    """Normalize team name to standard format."""
    if not team:
        return team
    
    team = str(team).strip()
    
    # Handle common variations
    mappings = {
        "GWS": "GWS Giants",
        "Greater Western Sydney": "GWS Giants",
        "Sydney Swans": "Sydney",
        "Brisbane Lions": "Brisbane",
        "Adelaide Crows": "Adelaide",
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
        "West Coast Eagles": "West Coast",
    }
    
    return mappings.get(team, team)


def safe_int(x):
    """Safely convert value to integer, returns None on failure."""
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None
