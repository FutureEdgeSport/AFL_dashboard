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
# UNIFIED TABLE STYLES
# ============================================================================
UNIFIED_TABLE_CSS = """
<style>
/* ============================================
   UNIFIED TABLE SYSTEM - FutureEdge AFL Dashboard
   ============================================ */

/* Smooth fade-in animation for tables */
@keyframes tableSlideIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Base table styling - applied to all .fe-table variants */
.fe-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    margin: 20px 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    animation: tableSlideIn 0.4s ease-out;
}

/* Header styling */
.fe-table thead th {
    background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%);
    color: #FFFFFF;
    padding: 16px 12px;
    text-align: center;
    font-weight: 800;
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    border-bottom: 2px solid rgba(255,255,255,0.1);
    border-right: 1px solid rgba(255,255,255,0.08);
    white-space: nowrap;
}

.fe-table thead th:first-child {
    text-align: left;
    padding-left: 20px;
}

.fe-table thead th:last-child {
    border-right: none;
}

/* Cell styling */
.fe-table tbody td {
    padding: 14px 12px;
    text-align: center;
    font-weight: 600;
    font-size: 0.9em;
    color: #E0E0E0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    border-right: 1px solid rgba(255,255,255,0.04);
    transition: all 0.2s ease;
}

.fe-table tbody td:first-child {
    text-align: left;
    padding-left: 20px;
    font-weight: 700;
    color: #FFFFFF;
}

.fe-table tbody td:last-child {
    border-right: none;
}

/* Row hover effect - professional highlight */
.fe-table tbody tr {
    transition: all 0.2s ease;
    position: relative;
}

.fe-table tbody tr:hover {
    background: rgba(255,215,0,0.08) !important;
    box-shadow: inset 4px 0 0 #FFD700;
}

.fe-table tbody tr:hover td {
    color: #FFFFFF;
}

/* Alternating row colors */
.fe-table tbody tr:nth-child(even) {
    background: rgba(0,0,0,0.15);
}

.fe-table tbody tr:nth-child(even):hover {
    background: rgba(255,215,0,0.08) !important;
}

/* ============================================
   TABLE VARIANTS
   ============================================ */

/* Compact table - less padding */
.fe-table-compact thead th {
    padding: 12px 8px;
    font-size: 0.8em;
}

.fe-table-compact tbody td {
    padding: 10px 8px;
    font-size: 0.85em;
}

/* Wide table - more padding */
.fe-table-wide thead th {
    padding: 18px 16px;
    font-size: 0.9em;
}

.fe-table-wide tbody td {
    padding: 16px;
    font-size: 0.95em;
}

/* Striped emphasis - stronger alternating */
.fe-table-striped tbody tr:nth-child(even) {
    background: rgba(0,0,0,0.25);
}

/* Bordered - visible cell borders */
.fe-table-bordered tbody td {
    border-right: 1px solid rgba(255,255,255,0.1);
    border-bottom: 1px solid rgba(255,255,255,0.1);
}

/* Light theme - white background for contrast with colored cells */
.fe-table-light {
    background: #ffffff !important;
}

.fe-table-light thead th {
    background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%);
    color: #FFFFFF;
}

.fe-table-light tbody td {
    color: #333333;
    border-bottom: 1px solid rgba(0,0,0,0.06);
    border-right: 1px solid rgba(0,0,0,0.04);
}

.fe-table-light tbody td:first-child {
    background: #fafafa !important;
    border-right: 2px solid rgba(0,0,0,0.08);
    color: #1a1a1a;
}

.fe-table-light tbody tr:nth-child(even) {
    background: #f8f8f8;
}

.fe-table-light tbody tr:hover {
    background: #f0f0f0;
}

.fe-table-light tbody tr:nth-child(even):hover {
    background: #f0f0f0;
}

/* ============================================
   SPECIAL COLUMN STYLES
   ============================================ */

/* Rank column - centered with badge style */
.fe-table .col-rank {
    font-weight: 900;
    font-size: 0.95em;
    min-width: 50px;
}

/* Rating column - for colored values */
.fe-table .col-rating {
    font-weight: 800;
    border-radius: 6px;
    min-width: 70px;
}

/* Player name column */
.fe-table .col-player {
    font-weight: 700;
    color: #FFFFFF !important;
    text-align: left !important;
}

/* Team column */
.fe-table .col-team {
    font-weight: 600;
    text-align: left !important;
}

/* Number/stat columns */
.fe-table .col-stat {
    font-variant-numeric: tabular-nums;
    font-weight: 700;
}

/* ============================================
   COLOR-CODED CELLS
   ============================================ */

.fe-table .cell-elite {
    background: #008000 !important;
    color: #FFFFFF !important;
    font-weight: 800;
}

.fe-table .cell-good {
    background: #90EE90 !important;
    color: #000000 !important;
    font-weight: 800;
}

.fe-table .cell-average {
    background: #FFA500 !important;
    color: #000000 !important;
    font-weight: 800;
}

.fe-table .cell-below {
    background: #FF0000 !important;
    color: #FFFFFF !important;
    font-weight: 800;
}

/* ============================================
   RESPONSIVE ADJUSTMENTS
   ============================================ */

@media (max-width: 768px) {
    .fe-table thead th,
    .fe-table tbody td {
        padding: 10px 6px;
        font-size: 0.8em;
    }
    
    .fe-table thead th:first-child,
    .fe-table tbody td:first-child {
        padding-left: 12px;
    }
}

/* ============================================
   SORTABLE TABLE HEADERS
   ============================================ */

/* Sortable header styling */
.fe-table.fe-sortable thead th {
    cursor: pointer;
    position: relative;
    padding-right: 28px;
    user-select: none;
    transition: background 0.2s ease, color 0.2s ease;
}

.fe-table.fe-sortable thead th:hover {
    background: linear-gradient(135deg, #2a2a3e 0%, #3a3a4e 100%);
    color: #FFD700;
}

/* Sort indicator arrows */
.fe-table.fe-sortable thead th::after {
    content: '⇅';
    position: absolute;
    right: 8px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 0.75em;
    opacity: 0.4;
    transition: opacity 0.2s ease;
}

.fe-table.fe-sortable thead th:hover::after {
    opacity: 0.8;
}

/* Active sort states */
.fe-table.fe-sortable thead th.sort-asc::after {
    content: '▲';
    opacity: 1;
    color: #FFD700;
}

.fe-table.fe-sortable thead th.sort-desc::after {
    content: '▼';
    opacity: 1;
    color: #FFD700;
}

/* Light theme sortable adjustments */
.fe-table-light.fe-sortable thead th:hover {
    background: linear-gradient(135deg, #2a2a2a 0%, #3a3a3a 100%);
}
</style>

<!-- Sortable Table JavaScript -->
<script>
document.addEventListener('DOMContentLoaded', function() {
    initSortableTables();
});

// Re-initialize on Streamlit reruns
if (typeof Streamlit !== 'undefined') {
    document.addEventListener('streamlit:render', function() {
        setTimeout(initSortableTables, 100);
    });
}

// Also run after a short delay (for Streamlit dynamic content)
setTimeout(initSortableTables, 500);
setTimeout(initSortableTables, 1500);

function initSortableTables() {
    const tables = document.querySelectorAll('.fe-table.fe-sortable');
    
    tables.forEach(table => {
        // Skip if already initialized
        if (table.dataset.sortInit) return;
        table.dataset.sortInit = 'true';
        
        const headers = table.querySelectorAll('thead th');
        
        headers.forEach((header, colIndex) => {
            header.addEventListener('click', function() {
                sortTable(table, colIndex, this);
            });
        });
    });
}

function sortTable(table, colIndex, header) {
    const tbody = table.querySelector('tbody');
    if (!tbody) return;
    
    const rows = Array.from(tbody.querySelectorAll('tr'));
    if (rows.length === 0) return;
    
    // Determine sort direction
    const isAsc = header.classList.contains('sort-asc');
    const isDesc = header.classList.contains('sort-desc');
    
    // Remove sort classes from all headers
    table.querySelectorAll('thead th').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
    });
    
    // Set new sort direction
    let direction;
    if (!isAsc && !isDesc) {
        direction = 'asc';
        header.classList.add('sort-asc');
    } else if (isAsc) {
        direction = 'desc';
        header.classList.add('sort-desc');
    } else {
        direction = 'asc';
        header.classList.add('sort-asc');
    }
    
    // Sort the rows
    rows.sort((a, b) => {
        const aCell = a.cells[colIndex];
        const bCell = b.cells[colIndex];
        
        if (!aCell || !bCell) return 0;
        
        let aVal = aCell.textContent.trim();
        let bVal = bCell.textContent.trim();
        
        // Remove ordinal suffixes (1st, 2nd, 3rd, etc.)
        aVal = aVal.replace(/(st|nd|rd|th)$/i, '');
        bVal = bVal.replace(/(st|nd|rd|th)$/i, '');
        
        // Remove percentage signs and plus signs
        aVal = aVal.replace(/[%+]/g, '');
        bVal = bVal.replace(/[%+]/g, '');
        
        // Try to parse as numbers
        const aNum = parseFloat(aVal);
        const bNum = parseFloat(bVal);
        
        let comparison;
        if (!isNaN(aNum) && !isNaN(bNum)) {
            comparison = aNum - bNum;
        } else {
            comparison = aVal.localeCompare(bVal, undefined, {numeric: true, sensitivity: 'base'});
        }
        
        return direction === 'asc' ? comparison : -comparison;
    });
    
    // Re-append rows in sorted order
    rows.forEach(row => tbody.appendChild(row));
    
    // Re-apply zebra striping
    rows.forEach((row, index) => {
        row.style.background = '';
    });
}
</script>
"""


def get_unified_table_css() -> str:
    """Return the unified table CSS for injection into the app."""
    return UNIFIED_TABLE_CSS


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
