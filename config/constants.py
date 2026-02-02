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
CURRENT_SEASON: int = 2026
AVAILABLE_SEASONS: List[int] = [2026, 2025, 2024, 2023]
DEFAULT_SEASON: int = 2026

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
# METRIC TOOLTIPS - Explanations for key metrics
# ============================================================================
METRIC_TOOLTIPS: Dict[str, str] = {
    # Team Metrics
    "Ball Winning Ranking": "Measures a team's ability to win contested possessions, clearances, and ground balls. Higher = better at winning the ball.",
    "Ball Movement Ranking": "Evaluates efficiency in moving the ball from defense to attack through kicking, handballing, and chain plays.",
    "Scoring Ranking": "Assesses attacking efficiency including goals per inside 50, accuracy, and expected score performance.",
    "Defence Ranking": "Measures defensive effectiveness including scores conceded, defensive pressure, and opposition scoring efficiency.",
    "Pressure Ranking": "Evaluates tackling pressure, forward 50 tackles, pressure acts, and 1%ers defensive efforts.",
    "Team Rating": "Overall composite rating combining all game phases. Higher = stronger overall team performance.",
    
    # Player Metrics  
    "Rating": "Overall player rating based on performance across all measured attributes. Scale typically 0-100.",
    "Ball Winning": "Player's ability to win contested possessions, clearances, and ground balls.",
    "Ball Use": "Efficiency with disposals including kick/handball accuracy and decision making.",
    "Aerial": "Marking ability including contested marks, intercept marks, and aerial duels won.",
    "Defence": "Defensive actions including tackles, spoils, intercepts, and one-percenters.",
    
    # Age/Position Metrics
    "Age Band": "Player age groupings for list composition analysis. Elite lists typically balance across bands.",
    "Depth Position": "Primary positional role for depth chart analysis.",
    "RatingPoints_Avg": "Average rating points accumulated per game. Higher = more consistent impact.",
    
    # Comparison Metrics
    "League Avg": "Average value across all 18 AFL teams for comparison.",
    "Top 4 Avg": "Average value for current top 4 teams - benchmark for elite performance.",
    "Diff vs League": "Difference compared to league average. Positive = above average.",
    "Diff vs Top 4": "Difference compared to top 4 average. Positive = exceeding elite benchmark.",
    "Rank": "Position among 18 teams (1st = best, 18th = worst).",
}


def get_tooltip_html(metric: str) -> str:
    """Get HTML attribute for tooltip on a metric."""
    tooltip_text = METRIC_TOOLTIPS.get(metric, "")
    if tooltip_text:
        return f' data-tooltip="{tooltip_text}"'
    return ""


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

/* ============================================
   EXPORT BUTTONS
   ============================================ */

.fe-export-buttons {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-bottom: 8px;
}

.fe-export-btn {
    background: linear-gradient(135deg, #2a2a3e 0%, #3a3a4e 100%);
    color: #FFFFFF;
    border: 1px solid rgba(255,255,255,0.2);
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 0.85em;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.fe-export-btn:hover {
    background: linear-gradient(135deg, #3a3a4e 0%, #4a4a5e 100%);
    border-color: #FFD700;
    color: #FFD700;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

/* ============================================
   LOADING SKELETONS
   ============================================ */

@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}

.fe-skeleton-container {
    padding: 20px;
}

.fe-skeleton {
    background: linear-gradient(90deg, #2a2a3e 25%, #3a3a4e 50%, #2a2a3e 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 8px;
    margin-bottom: 12px;
}

.fe-skeleton-header {
    height: 48px;
    width: 100%;
}

.fe-skeleton-row {
    height: 40px;
    width: 100%;
}

.fe-skeleton-card {
    height: 120px;
    width: 100%;
}

/* ============================================
   TOOLTIPS
   ============================================ */

.fe-tooltip {
    position: fixed;
    background: linear-gradient(135deg, #1a1a2e 0%, #2a2a3e 100%);
    color: #FFFFFF;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 0.85em;
    font-weight: 500;
    max-width: 280px;
    z-index: 10000;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    border: 1px solid rgba(255,215,0,0.3);
    pointer-events: none;
    animation: tooltipFade 0.2s ease;
}

@keyframes tooltipFade {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

.fe-tooltip::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: #2a2a3e;
}

[data-tooltip] {
    cursor: help;
    border-bottom: 1px dotted rgba(255,215,0,0.5);
}

/* ============================================
   THEME TOGGLE BUTTON
   ============================================ */

.fe-theme-toggle {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: linear-gradient(135deg, #2a2a3e 0%, #3a3a4e 100%);
    color: #FFFFFF;
    border: 1px solid rgba(255,255,255,0.2);
    padding: 12px 20px;
    border-radius: 25px;
    font-size: 0.9em;
    font-weight: 600;
    cursor: pointer;
    z-index: 9999;
    transition: all 0.3s ease;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
}

.fe-theme-toggle:hover {
    background: linear-gradient(135deg, #3a3a4e 0%, #4a4a5e 100%);
    border-color: #FFD700;
    color: #FFD700;
    transform: scale(1.05);
}

/* ============================================
   LIGHT MODE THEME
   ============================================ */

/* Apply light mode to body and Streamlit app container */
.fe-light-mode,
.fe-light-mode .stApp,
body.fe-light-mode {
    background: linear-gradient(135deg, #f5f5f5 0%, #e8e8e8 100%) !important;
}

/* Light mode for main content area */
.fe-light-mode .main .block-container,
.fe-light-mode [data-testid="stAppViewContainer"] {
    background: transparent !important;
}

/* Light mode text colors */
.fe-light-mode .stMarkdown,
.fe-light-mode .stText,
.fe-light-mode p,
.fe-light-mode span,
.fe-light-mode label,
.fe-light-mode h1, .fe-light-mode h2, .fe-light-mode h3 {
    color: #333333 !important;
}

/* Light mode sidebar */
.fe-light-mode [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ffffff 0%, #f0f0f0 100%) !important;
}

.fe-light-mode [data-testid="stSidebar"] .stRadio label,
.fe-light-mode [data-testid="stSidebar"] .stSelectbox label {
    color: #333333 !important;
}

/* Light mode tables */
.fe-light-mode .fe-table {
    background: #ffffff !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}

.fe-light-mode .fe-table thead th {
    background: linear-gradient(135deg, #333333 0%, #444444 100%);
}

.fe-light-mode .fe-table tbody td {
    color: #333333;
    border-bottom-color: rgba(0,0,0,0.08);
}

.fe-light-mode .fe-table tbody td:first-child {
    color: #1a1a1a;
}

.fe-light-mode .fe-table tbody tr:nth-child(even) {
    background: rgba(0,0,0,0.03);
}

.fe-light-mode .fe-table tbody tr:hover {
    background: rgba(255,215,0,0.1) !important;
}

/* Light mode buttons */
.fe-light-mode .fe-export-btn,
.fe-light-mode .fe-theme-toggle {
    background: linear-gradient(135deg, #333333 0%, #444444 100%);
}

/* Light mode shortcuts hint */
.fe-light-mode .fe-shortcuts-hint {
    background: rgba(0,0,0,0.05) !important;
    color: #333333 !important;
    border-color: rgba(0,0,0,0.15) !important;
}

.fe-light-mode .fe-shortcuts-hint kbd {
    background: #ffffff !important;
    color: #333333 !important;
    border-color: rgba(0,0,0,0.2) !important;
}

/* Light mode inputs and widgets */
.fe-light-mode .stTextInput input,
.fe-light-mode .stSelectbox select,
.fe-light-mode .stMultiSelect > div {
    background: #ffffff !important;
    color: #333333 !important;
    border-color: rgba(0,0,0,0.2) !important;
}

/* ============================================
   PRINT STYLES
   ============================================ */

@media print {
    /* Hide non-essential elements */
    .stSidebar,
    .stButton,
    .fe-export-buttons,
    .fe-theme-toggle,
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    header,
    footer {
        display: none !important;
    }
    
    /* Full width content */
    .main .block-container {
        max-width: 100% !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    
    /* Clean table styling for print */
    .fe-table {
        box-shadow: none !important;
        border: 1px solid #ddd !important;
        page-break-inside: avoid;
    }
    
    .fe-table thead th {
        background: #333 !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }
    
    .fe-table tbody tr:nth-child(even) {
        background: #f5f5f5 !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }
    
    /* Ensure color-coded cells print properly */
    .cell-elite, .cell-good, .cell-average, .cell-below {
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }
    
    /* Page breaks */
    h1, h2, h3 {
        page-break-after: avoid;
    }
    
    .fe-table {
        page-break-inside: avoid;
    }
    
    /* Print header */
    @page {
        margin: 1cm;
        @top-center {
            content: "FutureEdge AFL Dashboard";
        }
        @bottom-center {
            content: counter(page);
        }
    }
}

/* ============================================
   KEYBOARD SHORTCUT HINT
   ============================================ */

.fe-shortcuts-hint {
    position: fixed;
    bottom: 70px;
    right: 20px;
    background: linear-gradient(135deg, #2a2a3e 0%, #3a3a4e 100%);
    color: rgba(255,255,255,0.7);
    padding: 12px 16px;
    border-radius: 8px;
    font-size: 0.75em;
    z-index: 9998;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    border: 1px solid rgba(255,255,255,0.1);
    line-height: 1.6;
}

.fe-shortcuts-hint kbd {
    background: rgba(255,255,255,0.15);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: monospace;
    margin: 0 2px;
}
</style>

<!-- Sortable Table JavaScript - Works with Streamlit -->
<script>
(function() {
    // Core sort function
    window.feSortTable = function(tableId, colIndex) {
        const table = document.getElementById(tableId) || document.querySelector('.fe-table.fe-sortable');
        if (!table) return;
        
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        
        const header = table.querySelectorAll('thead th')[colIndex];
        if (!header) return;
        
        const rows = Array.from(tbody.querySelectorAll('tr'));
        if (rows.length === 0) return;
        
        // Determine sort direction
        const isAsc = header.classList.contains('sort-asc');
        
        // Remove sort classes from all headers
        table.querySelectorAll('thead th').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc');
        });
        
        // Toggle direction
        const direction = isAsc ? 'desc' : 'asc';
        header.classList.add('sort-' + direction);
        
        // Sort the rows
        rows.sort((a, b) => {
            const aCell = a.cells[colIndex];
            const bCell = b.cells[colIndex];
            
            if (!aCell || !bCell) return 0;
            
            let aVal = aCell.textContent.trim();
            let bVal = bCell.textContent.trim();
            
            // Remove ordinal suffixes, percentages, plus signs
            aVal = aVal.replace(/(st|nd|rd|th)$/i, '').replace(/[%+]/g, '');
            bVal = bVal.replace(/(st|nd|rd|th)$/i, '').replace(/[%+]/g, '');
            
            const aNum = parseFloat(aVal);
            const bNum = parseFloat(bVal);
            
            let cmp;
            if (!isNaN(aNum) && !isNaN(bNum)) {
                cmp = aNum - bNum;
            } else {
                cmp = aVal.localeCompare(bVal, undefined, {numeric: true, sensitivity: 'base'});
            }
            
            return direction === 'asc' ? cmp : -cmp;
        });
        
        // Re-append sorted rows
        rows.forEach(row => tbody.appendChild(row));
    };
    
    // Initialize sortable tables
    function initSort() {
        document.querySelectorAll('.fe-table.fe-sortable').forEach((table, tableIndex) => {
            if (table.dataset.feSort) return;
            table.dataset.feSort = '1';
            
            // Give table a unique ID if it doesn't have one
            if (!table.id) {
                table.id = 'fe-table-' + tableIndex + '-' + Date.now();
            }
            
            const headers = table.querySelectorAll('thead th');
            headers.forEach((th, colIndex) => {
                th.style.cursor = 'pointer';
                th.onclick = function() {
                    window.feSortTable(table.id, colIndex);
                };
            });
        });
    }
    
    // Run initialization multiple times to catch dynamically loaded content
    initSort();
    setTimeout(initSort, 100);
    setTimeout(initSort, 500);
    setTimeout(initSort, 1000);
    setTimeout(initSort, 2000);
    setTimeout(initSort, 3000);
    
    // Use MutationObserver to catch new tables
    const observer = new MutationObserver(function(mutations) {
        initSort();
    });
    
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
})();

// ============================================
// KEYBOARD SHORTCUTS
// ============================================
document.addEventListener('keydown', function(e) {
    // Only trigger if not in an input field
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
    
    const shortcuts = {
        '1': 0,  // Home
        '2': 1,  // Club Overview
        '3': 2,  // Player Search
        '4': 3,  // Player Profile
        '5': 4,  // Depth Chart
        '6': 5,  // Team List Summary
        '7': 6,  // Draft Guide
        '8': 7,  // Individual Development Plan
        '9': 8,  // Game Model Scorecard
        '0': 9,  // Club Comparison
    };
    
    // Number keys for navigation (no modifiers)
    if (e.key in shortcuts && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        const sidebar = document.querySelector('[data-testid="stSidebar"]');
        if (sidebar) {
            // Try radio buttons first (st.radio)
            const radioButtons = sidebar.querySelectorAll('input[type="radio"]');
            const targetIndex = shortcuts[e.key];
            if (radioButtons.length > targetIndex) {
                radioButtons[targetIndex].click();
                return;
            }
            
            // Fallback: try navigation links
            const navLinks = sidebar.querySelectorAll('a[data-testid="stSidebarNavLink"]');
            if (navLinks.length > targetIndex) {
                navLinks[targetIndex].click();
            }
        }
    }
    
    // Ctrl+P or Cmd+P for print
    if ((e.ctrlKey || e.metaKey) && e.key === 'p') {
        e.preventDefault();
        window.print();
    }
    
    // Ctrl+D or Cmd+D for theme toggle
    if ((e.ctrlKey || e.metaKey) && e.key === 'd') {
        e.preventDefault();
        toggleTheme();
    }
});

// ============================================
// THEME TOGGLE (Dark/Light)
// ============================================
function toggleTheme() {
    const body = document.body;
    const isLight = body.classList.toggle('fe-light-mode');
    localStorage.setItem('fe-theme', isLight ? 'light' : 'dark');
    
    // Update ALL theme buttons
    document.querySelectorAll('.fe-theme-toggle').forEach(btn => {
        btn.textContent = isLight ? '🌙 Dark Mode' : '☀️ Light Mode';
    });
    
    // Also update Streamlit's main app container
    const stApp = document.querySelector('.stApp');
    if (stApp) {
        if (isLight) {
            stApp.classList.add('fe-light-mode');
        } else {
            stApp.classList.remove('fe-light-mode');
        }
    }
}

// Attach theme toggle click handler (works even with Streamlit's sanitization)
function initThemeToggle() {
    document.querySelectorAll('.fe-theme-toggle').forEach(btn => {
        // Remove any existing listeners
        btn.replaceWith(btn.cloneNode(true));
    });
    document.querySelectorAll('.fe-theme-toggle').forEach(btn => {
        btn.addEventListener('click', toggleTheme);
        btn.style.cursor = 'pointer';
    });
}

// Load saved theme preference and init toggle
(function() {
    const saved = localStorage.getItem('fe-theme');
    if (saved === 'light') {
        document.body.classList.add('fe-light-mode');
        const stApp = document.querySelector('.stApp');
        if (stApp) stApp.classList.add('fe-light-mode');
    }
    
    // Update button text based on saved preference
    setTimeout(() => {
        const isLight = saved === 'light';
        document.querySelectorAll('.fe-theme-toggle').forEach(btn => {
            btn.textContent = isLight ? '🌙 Dark Mode' : '☀️ Light Mode';
        });
        initThemeToggle();
    }, 500);
})();

// Re-attach when Streamlit re-renders
const themeObserver = new MutationObserver(() => {
    initThemeToggle();
});
themeObserver.observe(document.body, { childList: true, subtree: true });

// ============================================
// EXPORT TABLE TO CSV
// ============================================
function exportTableToCSV(tableSelector, filename) {
    const table = document.querySelector(tableSelector);
    if (!table) {
        alert('No table found to export');
        return;
    }
    
    let csv = [];
    const rows = table.querySelectorAll('tr');
    
    rows.forEach(row => {
        const cols = row.querySelectorAll('th, td');
        const rowData = [];
        cols.forEach(col => {
            // Clean the text content
            let text = col.textContent.trim().replace(/"/g, '""');
            rowData.push('"' + text + '"');
        });
        csv.push(rowData.join(','));
    });
    
    // Create download link
    const blob = new Blob([csv.join('\\n')], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename || 'table_export.csv';
    link.click();
}

// Add export buttons to tables
function addExportButtons() {
    const tables = document.querySelectorAll('.fe-table');
    tables.forEach((table, index) => {
        if (table.dataset.exportInit) return;
        table.dataset.exportInit = 'true';
        
        // Create export button container
        const btnContainer = document.createElement('div');
        btnContainer.className = 'fe-export-buttons';
        btnContainer.innerHTML = `
            <button class="fe-export-btn" onclick="exportTableToCSV('.fe-table:nth-of-type(${index + 1})', 'afl_data_${index + 1}.csv')">
                📥 Export CSV
            </button>
        `;
        
        // Insert before table
        table.parentNode.insertBefore(btnContainer, table);
    });
}

setTimeout(addExportButtons, 1000);
setTimeout(addExportButtons, 2500);

// ============================================
// LOADING SKELETONS
// ============================================
function showLoadingSkeleton(container) {
    container.innerHTML = `
        <div class="fe-skeleton-container">
            <div class="fe-skeleton fe-skeleton-header"></div>
            <div class="fe-skeleton fe-skeleton-row"></div>
            <div class="fe-skeleton fe-skeleton-row"></div>
            <div class="fe-skeleton fe-skeleton-row"></div>
            <div class="fe-skeleton fe-skeleton-row"></div>
        </div>
    `;
}

// ============================================
// TOOLTIPS
// ============================================
function initTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(el => {
        if (el.dataset.tooltipInit) return;
        el.dataset.tooltipInit = 'true';
        
        el.addEventListener('mouseenter', function(e) {
            const tooltip = document.createElement('div');
            tooltip.className = 'fe-tooltip';
            tooltip.textContent = this.dataset.tooltip;
            document.body.appendChild(tooltip);
            
            const rect = this.getBoundingClientRect();
            tooltip.style.left = rect.left + (rect.width / 2) - (tooltip.offsetWidth / 2) + 'px';
            tooltip.style.top = rect.top - tooltip.offsetHeight - 8 + 'px';
            
            this._tooltip = tooltip;
        });
        
        el.addEventListener('mouseleave', function() {
            if (this._tooltip) {
                this._tooltip.remove();
                this._tooltip = null;
            }
        });
    });
}

setTimeout(initTooltips, 500);
setTimeout(initTooltips, 1500);
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
