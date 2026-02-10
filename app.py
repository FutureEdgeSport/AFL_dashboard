from pathlib import Path
import os
import warnings
import math
import string
import textwrap
import base64
from collections import defaultdict
from typing import Optional, Any, Tuple, List, Dict

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

# Import centralized configuration
from config.constants import (
    CURRENT_SEASON, AVAILABLE_SEASONS, DEFAULT_SEASON,
    TEAM_FILE, PLAYER_FILE, TRAITS_FILE, LADDERS_FILE, MASTER_FILE,
    LOGO_FOLDER, PLAYER_PHOTO_FOLDER,
    TEAM_CODE_MAP, TEAM_CODE_TO_NAME, TEAM_COLOURS, ALL_TEAMS,
    DEPTH_POSITIONS, POSITION_ABBREV_TO_FULL, POSITION_COLOURS,
    AGE_BANDS, AGE_BANDS_ALT,
    METRIC_ORDER, RATING_COL_CANDIDATES, TRAIT_COLUMNS,
    UIConfig, get_rating_color, get_rank_color, get_ordinal, safe_float, safe_int, normalize_team_name,
    get_unified_table_css, METRIC_TOOLTIPS, get_tooltip_html
)

# Import data pipeline for computed ratings (migration from Excel formulas)
from data_pipeline.compute_ratings import (
    get_player_seasons as dp_get_player_seasons,
    get_team_seasons as dp_get_team_seasons,
    load_team_ladders_computed,
    compute_player_summary_from_seasons,
    parse_table_with_detected_header,
    compare_to_excel_snapshot,
)
from data_pipeline.compute_player_summary import (
    compute_player_summary as dp_compute_player_summary,
    load_all_season_data as dp_load_all_season_data,
)
from data_pipeline.compute_list_ladder import (
    compute_list_ladder_l2,
    compute_list_ladder_career,
    compute_age_profile_2yr,
    compute_age_profile_1yr,
)

# Import unified data loader (master workbook with fallback)
try:
    from data_loader import (
        master_workbook_available,
        load_player_summary_data,
        load_player_stats_for_season,
        load_full_squad_data,
        load_wings_data,
        load_player_contracts_data,
        load_player_draft_data,
        load_team_summary_for_season as dl_load_team_summary,
        load_team_full_stats,
        load_ladder_positions,
        load_traits_for_season,
        load_player_registry as dl_load_player_registry,
        load_champion_data_ids,
        load_wheelo_player_data,
        load_wheelo_team_data,
        get_data_source_info,
        get_player_excel_file,
        get_team_excel_file,
        get_traits_excel_file,
    )
    DATA_LOADER_AVAILABLE = True
except ImportError:
    DATA_LOADER_AVAILABLE = False
    def master_workbook_available(): return False

# Import Historical Data Module (consolidated 2012-2025 data)
try:
    from data_pipeline.historical_data import (
        load_player_stats_historical,
        load_traits_historical,
        load_team_stats_historical,
        load_player_registry,
        load_all_player_stats_historical,
        load_all_traits_historical,
        load_all_team_stats_historical,
        get_player_dob,
        get_player_draft_info,
        get_player_contract_expiry,
        get_player_career_stats,
        get_player_career_traits,
        get_team_history,
        get_available_seasons as historical_get_available_seasons,
        historical_workbook_available,
        is_historical_season,
        clear_historical_cache,
    )
    HISTORICAL_DATA_AVAILABLE = True
except ImportError:
    HISTORICAL_DATA_AVAILABLE = False
    # Create stub functions so code doesn't break
    def historical_workbook_available(): return False
    def is_historical_season(s): return False
    def load_player_registry(): return pd.DataFrame()
    def get_player_dob(n): return None
    def get_player_draft_info(n): return {}
    def get_player_contract_expiry(n): return None

# Import Traits API integration (with graceful fallback if not available)
try:
    from traits_api import load_traits_cache, load_dob_cache
    TRAITS_API_AVAILABLE = True
except ImportError:
    TRAITS_API_AVAILABLE = False
    load_traits_cache = None
    load_dob_cache = None

# ---------------- STREAMLIT CONFIG ----------------
st.set_page_config(
    page_title="FutureEdge AFL Dashboard",
    page_icon="🏉",
    layout="wide",
)

# Inject unified table CSS globally
st.markdown(get_unified_table_css(), unsafe_allow_html=True)

# ============================================================================
# ENHANCED SESSION STATE FOR UX FEATURES
# ============================================================================
# Initialize session state for favorites
if "favorite_teams" not in st.session_state:
    st.session_state.favorite_teams = set()
if "favorite_players" not in st.session_state:
    st.session_state.favorite_players = set()  # Format: "Player Name|Team"

# Initialize session state for recent activity
if "recent_views" not in st.session_state:
    st.session_state.recent_views = []  # List of {"type": "team/player", "name": ..., "team": ..., "page": ...}

# Initialize session state for comparison history
if "comparison_history" not in st.session_state:
    st.session_state.comparison_history = []  # List of {"type": "team/best23", "team1": ..., "team2": ...}

def add_to_recent_views(view_type: str, name: str, team: str = None, page: str = None):
    """Add an item to recent views, keeping last 5 unique items."""
    item = {"type": view_type, "name": name, "team": team, "page": page}
    # Remove existing if same item
    st.session_state.recent_views = [v for v in st.session_state.recent_views 
                                      if not (v["type"] == view_type and v["name"] == name)]
    # Add to front
    st.session_state.recent_views.insert(0, item)
    # Keep only last 5
    st.session_state.recent_views = st.session_state.recent_views[:5]

def add_to_comparison_history(comp_type: str, team1: str, team2: str):
    """Add a comparison to history, keeping last 5."""
    item = {"type": comp_type, "team1": team1, "team2": team2}
    # Remove existing if same comparison
    st.session_state.comparison_history = [c for c in st.session_state.comparison_history 
                                            if not (c["team1"] == team1 and c["team2"] == team2)]
    st.session_state.comparison_history.insert(0, item)
    st.session_state.comparison_history = st.session_state.comparison_history[:5]

def toggle_favorite_team(team: str):
    """Toggle a team as favorite."""
    if team in st.session_state.favorite_teams:
        st.session_state.favorite_teams.discard(team)
    else:
        st.session_state.favorite_teams.add(team)

def toggle_favorite_player(player: str, team: str):
    """Toggle a player as favorite."""
    key = f"{player}|{team}"
    if key in st.session_state.favorite_players:
        st.session_state.favorite_players.discard(key)
    else:
        st.session_state.favorite_players.add(key)

def get_trend_indicator(current_val: float, prev_val: float = None) -> str:
    """Get trend arrow indicator based on value change."""
    if prev_val is None or current_val is None:
        return ""
    diff = current_val - prev_val
    if diff > 0.5:
        return '<span style="color: #00D26A; font-weight: bold;">↑</span>'
    elif diff < -0.5:
        return '<span style="color: #FF4B4B; font-weight: bold;">↓</span>'
    else:
        return '<span style="color: #888;">→</span>'

# ============================================================================
# UNIFIED CARD CSS
# ============================================================================
CARD_CSS = """
<style>
/* Unified Card Design */
.fe-card {
    background: linear-gradient(135deg, rgba(30, 30, 46, 0.95) 0%, rgba(42, 42, 62, 0.95) 100%);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 20px;
    margin: 10px 0;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.fe-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
}
.fe-card-header {
    font-size: 1.2em;
    font-weight: 700;
    margin-bottom: 12px;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 10px;
}
.fe-card-content {
    color: rgba(255, 255, 255, 0.85);
}
.fe-card-footer {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    font-size: 0.85em;
    color: rgba(255, 255, 255, 0.6);
}
/* Favorite star button */
.fe-star {
    cursor: pointer;
    font-size: 1.2em;
    transition: transform 0.15s ease;
}
.fe-star:hover {
    transform: scale(1.2);
}
.fe-star-active {
    color: #FFD700;
}
.fe-star-inactive {
    color: rgba(255, 255, 255, 0.3);
}
/* Breadcrumb styling */
.fe-breadcrumb {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 0.9em;
}
.fe-breadcrumb a {
    color: rgba(255, 255, 255, 0.7);
    text-decoration: none;
    transition: color 0.15s ease;
}
.fe-breadcrumb a:hover {
    color: #00D26A;
}
.fe-breadcrumb-separator {
    color: rgba(255, 255, 255, 0.3);
}
.fe-breadcrumb-current {
    color: #fff;
    font-weight: 600;
}
/* Sidebar enhancements */
.fe-sidebar-section {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    padding: 12px;
    margin: 8px 0;
}
.fe-sidebar-title {
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: rgba(255, 255, 255, 0.5);
    margin-bottom: 8px;
}
.fe-sidebar-item {
    padding: 6px 10px;
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s ease;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.9em;
}
.fe-sidebar-item:hover {
    background: rgba(255, 255, 255, 0.1);
}
/* Export button styling */
.fe-export-btn {
    background: linear-gradient(135deg, #00D26A 0%, #00A854 100%);
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.fe-export-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 210, 106, 0.4);
}
</style>
"""

st.markdown(CARD_CSS, unsafe_allow_html=True)

# Add theme toggle button and keyboard shortcuts hint
# Note: onclick is stripped by Streamlit, so JS attaches the listener
st.markdown('''
<button class="fe-theme-toggle">☀️ Light Mode</button>
<div class="fe-shortcuts-hint">
    <strong>Keyboard Shortcuts:</strong><br>
    <kbd>1</kbd>-<kbd>0</kbd> Navigate pages<br>
    <kbd>Ctrl</kbd>+<kbd>P</kbd> Print report<br>
    <kbd>Ctrl</kbd>+<kbd>D</kbd> Toggle theme<br>
    <kbd>?</kbd> Show all shortcuts
</div>
''', unsafe_allow_html=True)

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

BASE_DIR = Path(__file__).resolve().parent


# ============================================================================
# BREADCRUMB HELPER
# ============================================================================
def render_breadcrumb(items: list):
    """
    Render a breadcrumb navigation bar.
    
    Args:
        items: List of tuples (label, page_name) where page_name is None for current page
        Example: [("Home", "Home"), ("Team Breakdown", "Team Breakdown"), ("Adelaide", None)]
    """
    html_parts = []
    for i, (label, page_name) in enumerate(items):
        if page_name is None:
            # Current page (no link)
            html_parts.append(f'<span class="fe-breadcrumb-current">{label}</span>')
        else:
            # Clickable link (using JavaScript to trigger Streamlit)
            html_parts.append(f'<span class="fe-breadcrumb-link">{label}</span>')
        
        # Add separator except for last item
        if i < len(items) - 1:
            html_parts.append('<span class="fe-breadcrumb-separator">›</span>')
    
    st.markdown(f'<div class="fe-breadcrumb">{"".join(html_parts)}</div>', unsafe_allow_html=True)


# ============================================================================
# EXPORT HELPER FUNCTION
# ============================================================================
def render_export_button(element_id: str, filename: str = "export"):
    """
    Render an export button that triggers print dialog for the current view.
    The print dialog allows saving to PDF which can then be converted to image.
    
    For a true PNG export, we use html2canvas via JavaScript.
    """
    export_html = f"""
    <div style="margin: 20px 0; text-align: center;">
        <button onclick="window.print();" class="fe-export-btn" style="margin-right: 10px;">
            🖨️ Print / Save as PDF
        </button>
        <button onclick="
            const el = document.querySelector('section.main');
            if (el) {{
                html2canvas(el, {{
                    backgroundColor: '#0e1117',
                    scale: 2
                }}).then(canvas => {{
                    const link = document.createElement('a');
                    link.download = '{filename}.png';
                    link.href = canvas.toDataURL('image/png');
                    link.click();
                }});
            }}
        " class="fe-export-btn">
            📸 Export as PNG
        </button>
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    """
    st.markdown(export_html, unsafe_allow_html=True)


# ============================================================================
# UNIFIED HELPER FUNCTIONS
# ============================================================================
def render_html(container, html_str: str):
    """Render HTML safely without code block artifacts."""
    container.markdown(textwrap.dedent(html_str).strip(), unsafe_allow_html=True)


def render_sortable_table(html_table: str, height: int = None):
    """Render an HTML table with working JavaScript sorting.
    
    Uses st.components.v1.html() which properly executes JavaScript.
    The table HTML should use class='fe-table fe-sortable' for styling.
    """
    # Calculate height based on content if not provided
    row_count = html_table.count('<tr>') - 1  # Subtract header row
    if height is None:
        height = min(max(200, row_count * 45 + 80), 800)  # Min 200, max 800
    
    # Full HTML document with embedded CSS and JS
    full_html = f'''
    <!DOCTYPE html>
    <html>
    <head>
    <style>
    body {{
        margin: 0;
        padding: 0;
        background: transparent;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    .fe-table {{
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        font-size: 14px;
    }}
    .fe-table thead th {{
        background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%);
        color: #FFFFFF;
        padding: 14px 10px;
        text-align: center;
        font-weight: 800;
        font-size: 0.85em;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 2px solid rgba(255,255,255,0.1);
        cursor: pointer;
        position: relative;
        user-select: none;
        transition: background 0.2s ease;
    }}
    .fe-table thead th:hover {{
        background: linear-gradient(135deg, #2a2a3e 0%, #3a3a4e 100%);
        color: #FFD700;
    }}
    .fe-table thead th::after {{
        content: ' ⇅';
        opacity: 0.4;
        font-size: 0.8em;
    }}
    .fe-table thead th.sort-asc::after {{
        content: ' ▲';
        opacity: 1;
        color: #FFD700;
    }}
    .fe-table thead th.sort-desc::after {{
        content: ' ▼';
        opacity: 1;
        color: #FFD700;
    }}
    .fe-table tbody td {{
        padding: 12px 10px;
        text-align: center;
        font-weight: 600;
        color: #E0E0E0;
        border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .fe-table tbody td:first-child {{
        text-align: left;
        padding-left: 16px;
        font-weight: 700;
        color: #FFFFFF;
    }}
    .fe-table tbody tr {{
        transition: all 0.2s ease;
    }}
    .fe-table tbody tr:hover {{
        background: rgba(255,215,0,0.1) !important;
    }}
    .fe-table tbody tr:nth-child(even) {{
        background: rgba(0,0,0,0.15);
    }}
    .fe-table-light {{
        background: #ffffff !important;
    }}
    .fe-table-light tbody td {{
        color: #333333;
    }}
    .fe-table-light tbody td:first-child {{
        color: #1a1a1a;
        background: #fafafa;
    }}
    .fe-table-light tbody tr:nth-child(even) {{
        background: #f5f5f5;
    }}
    .fe-table-light tbody tr:hover {{
        background: #fffacd !important;
    }}
    .rank-badge {{
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 800;
        font-size: 0.85em;
    }}
    </style>
    </head>
    <body>
    {html_table}
    <script>
    (function() {{
        const table = document.querySelector('.fe-table');
        if (!table) return;
        
        const headers = table.querySelectorAll('thead th');
        
        headers.forEach((th, colIndex) => {{
            th.addEventListener('click', function() {{
                sortTable(colIndex, this);
            }});
        }});
        
        function sortTable(colIndex, header) {{
            const tbody = table.querySelector('tbody');
            if (!tbody) return;
            
            const rows = Array.from(tbody.querySelectorAll('tr'));
            if (rows.length === 0) return;
            
            const isAsc = header.classList.contains('sort-asc');
            
            // Remove sort classes from all headers
            headers.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
            
            // Toggle direction
            const direction = isAsc ? 'desc' : 'asc';
            header.classList.add('sort-' + direction);
            
            // Sort rows
            rows.sort((a, b) => {{
                const aCell = a.cells[colIndex];
                const bCell = b.cells[colIndex];
                if (!aCell || !bCell) return 0;
                
                let aVal = aCell.textContent.trim();
                let bVal = bCell.textContent.trim();
                
                // Clean values
                aVal = aVal.replace(/(st|nd|rd|th)$/i, '').replace(/[%+,]/g, '');
                bVal = bVal.replace(/(st|nd|rd|th)$/i, '').replace(/[%+,]/g, '');
                
                const aNum = parseFloat(aVal);
                const bNum = parseFloat(bVal);
                
                let cmp;
                if (!isNaN(aNum) && !isNaN(bNum)) {{
                    cmp = aNum - bNum;
                }} else {{
                    cmp = aVal.localeCompare(bVal, undefined, {{numeric: true}});
                }}
                
                return direction === 'asc' ? cmp : -cmp;
            }});
            
            rows.forEach(row => tbody.appendChild(row));
        }}
    }})();
    </script>
    </body>
    </html>
    '''
    
    components.html(full_html, height=height, scrolling=True)


def render_page_header(title: str, subtitle: str = None, icon: str = "📊"):
    """Render consistent page header across all pages."""
    subtitle_html = f'<p style="text-align: center; color: #CCCCCC; margin: 10px 0 0 0; font-size: 1.2em; font-weight: 300;">{subtitle}</p>' if subtitle else ''
    st.markdown(f'''
    <div style="background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%);
                padding: 40px 20px;
                border-radius: 15px;
                margin-bottom: 30px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.3);">
        <h1 style="text-align: center; color: #FFFFFF; margin: 0;
                   font-size: 2.8em; font-weight: 900;
                   text-shadow: 2px 2px 4px rgba(0,0,0,0.5);">
            {icon} {title.upper()}
        </h1>
        {subtitle_html}
    </div>
    ''', unsafe_allow_html=True)


def render_footer():
    """Render professional footer on all pages."""
    st.markdown('''
    <div style="text-align: center;
                color: rgba(255,255,255,0.4);
                padding: 40px 20px;
                margin-top: 60px;
                border-top: 1px solid rgba(255,255,255,0.1);">
        <p style="margin: 0 0 8px 0; font-weight: 600;">
            AFL Analytics Dashboard | Powered by FutureEdge Sport
        </p>
        <p style="margin: 0; font-size: 0.85em;">
            Data accuracy verified as of latest AFL.com.au update
        </p>
    </div>
    ''', unsafe_allow_html=True)


def render_info_box(content: str, box_type: str = "info"):
    """Render consistent info/warning/success boxes."""
    colors = {
        "info": ("rgba(100,149,237,0.1)", "#6495ED", "rgba(100,149,237,0.3)"),
        "warning": ("rgba(255,165,0,0.1)", "#FFA500", "rgba(255,165,0,0.3)"),
        "success": ("rgba(0,128,0,0.1)", "#008000", "rgba(0,128,0,0.3)"),
        "error": ("rgba(255,0,0,0.1)", "#FF0000", "rgba(255,0,0,0.3)")
    }
    bg, border, accent = colors.get(box_type, colors["info"])
    st.markdown(f'''
    <div style="background: {bg};
                padding: 20px;
                border-radius: 10px;
                border-left: 4px solid {border};
                margin-bottom: 20px;">
        <p style="color: #DDDDDD; margin: 0; line-height: 1.6;">{content}</p>
    </div>
    ''', unsafe_allow_html=True)


def render_empty_state(message: str, suggestion: str = None):
    """Render consistent empty state when no data is available."""
    suggestion_html = f'<p style="color: rgba(255,255,255,0.6);">{suggestion}</p>' if suggestion else ''
    st.markdown(f'''
    <div style="text-align: center;
                padding: 60px 20px;
                background: rgba(255,255,255,0.02);
                border-radius: 16px;
                border: 2px dashed rgba(255,255,255,0.1);">
        <div style="font-size: 48px; margin-bottom: 16px;">📭</div>
        <h3 style="color: #FFFFFF; margin-bottom: 12px;">{message}</h3>
        {suggestion_html}
    </div>
    ''', unsafe_allow_html=True)


def safe_load_file(file_path: Path, description: str) -> bool:
    """Check if a required file exists and show error if not."""
    if not file_path.exists():
        st.error(f"❌ Missing required file: {file_path.name}")
        render_info_box(
            f"<strong>File Not Found</strong><br>"
            f"Please ensure <code>{file_path.name}</code> is in the dashboard folder.<br>"
            f"Required for: {description}",
            "error"
        )
        return False
    return True


# -------------------------
# Global season defaults (using config)
# -------------------------
TEAM_SEASONS = AVAILABLE_SEASONS  # Use config value

def get_default_season() -> int:
    return CURRENT_SEASON

if "selected_season" not in st.session_state:
    st.session_state["selected_season"] = get_default_season()

if "primary_season" not in st.session_state:
    st.session_state["primary_season"] = st.session_state["selected_season"]


# NOTE: TEAM_CODE_MAP, TEAM_COLOURS, METRIC_ORDER, DEPTH_POSITIONS, AGE_BANDS, 
# POSITION_COLOURS are now imported from config.constants


# -------------------------
# Name key helper (kept in case you still use it elsewhere)
# -------------------------
def make_name_key(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = name.lower().strip()
    name = name.translate(str.maketrans("", "", string.punctuation))
    name = " ".join(name.split())
    return name


def match_player_name_to_traits(full_name: str, traits_df: pd.DataFrame, team_name: str = None) -> pd.DataFrame:
    """
    Match a full player name (e.g., 'Chad Warner') to the abbreviated format in traits (e.g., 'Ch. Warner').
    Returns matching rows from traits_df.
    """
    if traits_df is None or traits_df.empty or "Player_Full" not in traits_df.columns:
        return pd.DataFrame()
    
    # First try exact match
    exact_match = traits_df[traits_df["Player_Full"] == full_name]
    if not exact_match.empty:
        return exact_match
    
    # Parse the full name
    parts = full_name.strip().split()
    if len(parts) < 2:
        return pd.DataFrame()
    
    first_name = parts[0]
    last_name = parts[-1]
    
    # Try matching by last name and first initial
    first_initial = first_name[0].upper() + "."
    
    # Build possible abbreviated patterns
    # Pattern 1: "F. Lastname" (e.g., "C. Warner" for "Chad Warner")
    # Pattern 2: "Fi. Lastname" (e.g., "Ch. Warner" for "Chad Warner") 
    # Pattern 3: First few letters + ". Lastname"
    patterns = [
        f"{first_initial} {last_name}",  # C. Warner
        f"{first_name[:2]}. {last_name}",  # Ch. Warner
        f"{first_name[:3]}. {last_name}",  # Cha. Warner
    ]
    
    # Also handle middle names if present
    if len(parts) > 2:
        middle_parts = " ".join(parts[1:-1])
        patterns.append(f"{first_initial} {middle_parts} {last_name}")
    
    # Filter by team if provided (use Team_Full column)
    search_df = traits_df.copy()
    if team_name and "Team_Full" in search_df.columns:
        team_filtered = search_df[search_df["Team_Full"] == team_name]
        if not team_filtered.empty:
            search_df = team_filtered
    
    # Try each pattern
    for pattern in patterns:
        matches = search_df[search_df["Player_Full"].str.strip() == pattern]
        if not matches.empty:
            return matches
    
    # Fallback: match by last name only within the team
    last_name_matches = search_df[search_df["Player_Full"].str.contains(last_name, case=False, na=False)]
    if len(last_name_matches) == 1:
        return last_name_matches
    
    # If multiple last name matches, try to narrow by first initial
    if not last_name_matches.empty:
        initial_matches = last_name_matches[
            last_name_matches["Player_Full"].str.strip().str.startswith(first_initial[0], na=False)
        ]
        if len(initial_matches) == 1:
            return initial_matches
    
    return pd.DataFrame()


# ============================================================================
# DATA PIPELINE CONFIGURATION
# ============================================================================
# Feature flag for using Python-computed ratings vs Excel formulas
# Set to True to use computed ratings (future default), False to use Excel
USE_COMPUTED_RATINGS = True  # ✅ ENABLED - Using Python-computed data from CSV files

# Feature flag for using consolidated historical workbook
# Set to True to read historical data (<=2025) from AFL_Historical_2012_2025.xlsx
# Set to False to use original Excel files (legacy behavior)
USE_HISTORICAL_WORKBOOK = True  # ✅ ENABLED - Using consolidated historical data

def get_data_source_info() -> dict:
    """Return information about current data source configuration."""
    using_master = DATA_LOADER_AVAILABLE and master_workbook_available()
    return {
        "mode": "computed" if USE_COMPUTED_RATINGS else "excel",
        "description": "Python-computed from raw data" if USE_COMPUTED_RATINGS else "Excel formulas (legacy)",
        "historical_mode": "consolidated" if (USE_HISTORICAL_WORKBOOK and HISTORICAL_DATA_AVAILABLE and historical_workbook_available()) else "individual_files",
        "using_master_workbook": using_master,
        "master_file": MASTER_FILE if using_master else None,
        "team_file": TEAM_FILE,
        "player_file": PLAYER_FILE,
        "traits_file": TRAITS_FILE,
    }


# ---------------- FC/FIFA STYLE RATING CONVERSION ----------------
def convert_trait_to_fc_rating(value, min_orig=1.0, max_orig=4.0, min_fc=50, max_fc=99):
    """
    Convert a trait rating from original scale (1-4) to FC/FIFA style (50-99).
    Maintains the shape of the data curve using linear interpolation.
    
    Args:
        value: The original trait value (1-4 scale)
        min_orig: Minimum value in original scale (default 1.0)
        max_orig: Maximum value in original scale (default 4.0)
        min_fc: Minimum value in FC scale (default 50)
        max_fc: Maximum value in FC scale (default 99)
    
    Returns:
        Converted value in FC scale (50-99) as integer, or None if invalid
    """
    try:
        val = float(value)
        if pd.isna(val):
            return None
        # Clamp to original range
        val = max(min_orig, min(max_orig, val))
        # Linear interpolation: (val - min_orig) / (max_orig - min_orig) = (result - min_fc) / (max_fc - min_fc)
        normalized = (val - min_orig) / (max_orig - min_orig)
        fc_value = min_fc + normalized * (max_fc - min_fc)
        return int(round(fc_value))
    except (ValueError, TypeError):
        return None


def convert_df_traits_to_fc(df, trait_columns=None):
    """
    Convert all trait columns in a DataFrame from 1-4 scale to FC/FIFA scale (50-99).
    
    Args:
        df: DataFrame containing trait data
        trait_columns: List of column names to convert. If None, uses default trait columns.
    
    Returns:
        DataFrame with converted trait values
    """
    if df is None or df.empty:
        return df
    
    if trait_columns is None:
        trait_columns = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    
    df_converted = df.copy()
    for col in trait_columns:
        if col in df_converted.columns:
            df_converted[col] = df_converted[col].apply(convert_trait_to_fc_rating)
    
    return df_converted


def get_fc_rating_label(value):
    """Get tier label for FC-style rating (50-99 scale) - 5 tier system."""
    try:
        val = int(value) if value is not None else 0
    except (ValueError, TypeError):
        return ""
    
    # 5-tier system with equal 20% bands (50-99 scale = 49 point range)
    # Elite: 90-99 (top 20%)
    # Good: 80-89 (20-40%)
    # Average: 70-79 (40-60%)
    # Below Average: 60-69 (60-80%)
    # Poor: 50-59 (bottom 20%)
    if val >= 90:
        return "Elite"
    elif val >= 80:
        return "Good"
    elif val >= 70:
        return "Average"
    elif val >= 60:
        return "Below Average"
    else:
        return "Poor"


def format_trait_display(value, fc_mode=False):
    """Format trait value for display based on current mode."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        if fc_mode:
            fc_val = convert_trait_to_fc_rating(value)
            return str(fc_val) if fc_val is not None else "—"
        else:
            return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return "—"


# ---------------- DATA LOADERS – TEAM LADDERS ----------------
def _normalise_ladder_df(raw: pd.DataFrame) -> pd.DataFrame:
    header_idx_candidates = raw.index[
        raw.apply(
            lambda row: row.astype(str).str.strip().str.lower().eq("team").any(),
            axis=1,
        )
    ]
    if len(header_idx_candidates) == 0:
        raise ValueError("Could not find a header row containing 'Team' in this sheet.")
    header_idx = header_idx_candidates[0]

    header = raw.iloc[header_idx]
    df = raw.iloc[header_idx + 1 :].copy()
    df.columns = header

    new_cols = []
    for c in df.columns:
        s = str(c).strip()
        new_cols.append("Rank" if s == "#" else c)
    df.columns = new_cols

    df = df[df["Team"].notna()].copy()
    df["Team"] = df["Team"].replace({
        "GWS": "GWS Giants",
        "Greater Western Sydney": "GWS Giants"
    })
    bad_labels = ["Total", "Totals", "Average", "Averages", "League", "Overall"]
    df = df[~df["Team"].isin(bad_labels)].copy()

    norm = pd.DataFrame()
    norm["Team"] = df["Team"].copy()

    cols = list(df.columns)
    i = 0
    while i < len(cols):
        col = cols[i]
        if col in ["Team", "Rank"]:
            i += 1
            continue

        metric_col = col
        metric_values = df[metric_col]

        rank_series = None
        rank_col_name = None
        if i + 1 < len(cols):
            next_col = cols[i + 1]
            if str(next_col).strip().lower() == "rank":
                rank_series = df.iloc[:, i + 1]
                rank_col_name = f"{metric_col} Rank"

        norm[metric_col] = metric_values
        if rank_series is not None:
            norm[rank_col_name] = rank_series
            i += 2
        else:
            i += 1

    for col in norm.columns:
        if col != "Team":
            norm[col] = pd.to_numeric(norm[col], errors="coerce")

    norm = norm.drop_duplicates(subset=["Team"], keep="first").reset_index(drop=True)
    return norm


@st.cache_data(show_spinner=False)
def load_team_ladders_from_excel(season: int, last10: bool = False) -> pd.DataFrame:
    """Load team ladder data from Excel sheets (legacy method with formulas)."""
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        sheet_name = f"{season} Ladders (L10)" if last10 else f"{season} Ladders"
        raw = xl.parse(sheet_name)
        return _normalise_ladder_df(raw)
    except FileNotFoundError:
        st.error(f"❌ Team ratings file not found: {TEAM_FILE}")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Could not load {season} ladder data: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_team_ladders_computed_wrapper(season: int, last10: bool = False) -> pd.DataFrame:
    """
    Load team ladder data from computed CSV files (sophisticated Z-score based ratings).
    
    NEW METHODOLOGY (v2.0):
    - Uses Z-score normalization for proper metric standardization
    - Applies weighted metrics for each pillar
    - Maps to 50-99 scale (like FC ratings) using sigmoid transformation
    - Ratings: 50-59 = Poor, 60-69 = Below Avg, 70-79 = Average, 80-89 = Good, 90-99 = Elite
    """
    try:
        # Determine the data file based on season and block
        block = "L10" if last10 else "Season"
        
        # First try to load from computed CSV files (new sophisticated system)
        # Use block-specific file if available
        if last10:
            computed_path = Path(__file__).parent / "data" / "computed" / f"team_summary_{season}_L10.csv"
        else:
            computed_path = Path(__file__).parent / "data" / "computed" / f"team_summary_{season}.csv"
        
        if computed_path.exists():
            df = pd.read_csv(computed_path)
            
            # Normalize team names using standard function
            if "Team" in df.columns:
                df["Team"] = df["Team"].apply(lambda x: normalize_team_name(str(x)) if pd.notna(x) else x)
            
            # Create Team Rating from Overall Rating
            if "Overall Rating" in df.columns:
                df["Team Rating"] = df["Overall Rating"]
                df["Team Rating Rank"] = df["Overall Rank"] if "Overall Rank" in df.columns else \
                                         df["Overall Rating"].rank(ascending=False, method='min').astype(int)
            
            return df
        
        # Fallback to Excel Ladders sheets (which have the ranking data formatted correctly)
        # Use load_team_ladders_from_excel which handles the Ladders sheets properly
        return load_team_ladders_from_excel(season, last10)
    except FileNotFoundError:
        st.error(f"❌ Team ratings file not found: {TEAM_FILE}")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Could not compute {season} ladder data: {e}")
        return pd.DataFrame()


def load_team_ladders(season: int, last10: bool = False) -> pd.DataFrame:
    """
    Load team ladder data - automatically chooses data source based on USE_COMPUTED_RATINGS flag.
    
    When USE_COMPUTED_RATINGS is True: Uses Python-computed values from raw data
    When USE_COMPUTED_RATINGS is False: Uses Excel formulas (current default)
    """
    if USE_COMPUTED_RATINGS:
        return load_team_ladders_computed_wrapper(season, last10)
    else:
        return load_team_ladders_from_excel(season, last10)


@st.cache_data(show_spinner=False)
def load_afl_ladder_positions() -> pd.DataFrame:
    """Load historical AFL ladder positions - uses master workbook with fallback."""
    # Try master workbook first
    if DATA_LOADER_AVAILABLE and master_workbook_available():
        df = load_ladder_positions()
        if not df.empty:
            return df
    
    # Fallback to legacy method
    try:
        df = pd.read_excel("afl_ladders_2011_2025.xlsx")
        team_name_mapping = {
            "Adelaide Crows": "Adelaide",
            "Brisbane Lions": "Brisbane",
            "Carlton Blues": "Carlton",
            "Collingwood Magpies": "Collingwood",
            "Essendon Bombers": "Essendon",
            "Fremantle Dockers": "Fremantle",
            "Geelong Cats": "Geelong",
            "Gold Coast Suns": "Gold Coast",
            "GWS Giants": "GWS Giants",
            "GWS": "GWS Giants",
            "Greater Western Sydney": "GWS Giants",
            "Hawthorn Hawks": "Hawthorn",
            "Melbourne Demons": "Melbourne",
            "North Melbourne Kangaroos": "North Melbourne",
            "Port Adelaide Power": "Port Adelaide",
            "Richmond Tigers": "Richmond",
            "St Kilda Saints": "St Kilda",
            "Sydney Swans": "Sydney",
            "West Coast Eagles": "West Coast",
            "Western Bulldogs": "Western Bulldogs",
        }
        df["Team"] = df["Team"].replace(team_name_mapping)
        return df
    except Exception as e:
        st.warning(f"Could not load ladder positions: {e}")
        return pd.DataFrame()


def get_ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------- DATA LOADERS – TEAM SUMMARY ----------------
@st.cache_data(show_spinner=False)
def load_team_summary_for_year(season: int) -> pd.DataFrame:
    """Load team summary for a season - uses master workbook with fallback."""
    # Try new data loader first (master workbook)
    if DATA_LOADER_AVAILABLE and master_workbook_available():
        df = dl_load_team_summary(season)
        if not df.empty:
            return df
    
    # Fallback to legacy method
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        year_sheet = f"{season} Summary"
        df = xl.parse(year_sheet)
        df.columns = df.columns.astype(str)
        return df
    except Exception:
        return pd.DataFrame()


# ---------------- DATA LOADERS – PLAYERS ----------------
@st.cache_data(show_spinner=False)
def _load_player_summary_excel() -> pd.DataFrame:
    """Load player summary data - uses master workbook with fallback to legacy Excel."""
    # Try new data loader first (master workbook)
    if DATA_LOADER_AVAILABLE and master_workbook_available():
        df = load_player_summary_data()
        if not df.empty:
            return df
    
    # Fallback to legacy method
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        df = xl.parse("Summary")
        df.columns = df.columns.astype(str).str.strip()
        return df
    except FileNotFoundError:
        st.error(f"❌ Player ratings file not found: {PLAYER_FILE}")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Could not load player summary: {e}")
        return pd.DataFrame()


def _load_player_summary_computed() -> pd.DataFrame:
    """
    Load player summary from computed CSV data.
    Uses data_pipeline.compute_player_summary module.
    """
    try:
        from pathlib import Path
        csv_path = Path(__file__).parent / "data" / "computed" / "player_summary.csv"
        
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            df.columns = df.columns.astype(str).str.strip()
            
            # Ensure column compatibility with Excel version
            # Rename '2025 Rating' to '2025' if needed (to match Excel column name)
            if '2025 Rating' in df.columns and '2025' not in df.columns:
                df = df.rename(columns={'2025 Rating': '2025_Rating_Current'})
            
            return df
        else:
            # Fall back to computing on-the-fly
            df = dp_compute_player_summary(current_season=CURRENT_SEASON)
            return df
            
    except Exception as e:
        st.warning(f"⚠️ Could not load computed player summary: {e}")
        # Fall back to Excel
        return _load_player_summary_excel()


def load_player_summary() -> pd.DataFrame:
    """
    Load player summary data - uses computed or Excel based on feature flag.
    
    When USE_COMPUTED_RATINGS=True: Loads from data/computed/player_summary.csv
    When USE_COMPUTED_RATINGS=False: Loads from AFL Player Ratings.xlsx Summary sheet (or master workbook)
    """
    if USE_COMPUTED_RATINGS:
        return _load_player_summary_computed()
    else:
        return _load_player_summary_excel()


@st.cache_data(show_spinner=False)
def get_player_seasons() -> list[int]:
    """Get available player seasons with error handling."""
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        seasons = []
        for s in xl.sheet_names:
            if str(s).isdigit():
                seasons.append(int(s))
        return sorted(seasons, reverse=True)
    except Exception:
        return AVAILABLE_SEASONS  # Fall back to config default


@st.cache_data(show_spinner=False)
def get_traits_seasons() -> list[int]:
    """Get available trait seasons from the traits Excel file (2021-2025)."""
    try:
        xl = pd.ExcelFile(TRAITS_FILE)
        seasons = []
        for s in xl.sheet_names:
            if str(s).isdigit():
                seasons.append(int(s))
        return sorted(seasons, reverse=True)
    except Exception:
        return [2025, 2024, 2023, 2022, 2021]  # Known available seasons


def _normalise_rating_column(df: pd.DataFrame) -> pd.DataFrame:
    for cand in RATING_COL_CANDIDATES:
        if cand in df.columns:
            if cand != "RatingPoints_Avg":
                df = df.rename(columns={cand: "RatingPoints_Avg"})
            break
    return df


@st.cache_data(show_spinner=False)
def load_players(season: int) -> pd.DataFrame:
    """
    Player Ratings loader - uses master workbook with fallback to legacy files.
    This should NOT enforce traits columns.
    Falls back to previous season if requested season is empty/missing.
    """
    def _load_season_from_master(s: int) -> pd.DataFrame:
        """Try loading from master workbook first."""
        if not DATA_LOADER_AVAILABLE or not master_workbook_available():
            return pd.DataFrame()
        
        df = load_player_stats_for_season(s)
        if df.empty:
            return df
        
        df = _normalise_rating_column(df)
        cols = [
            "Player", "Team", "Age", "Age_Decimal", "Position", "Matches",
            "RatingPoints_Avg", "CoachesVotes_Avg", "TimeOnGround",
            "Height", "Height_cm", "Jumper", "Jersey", "Number", "Guernsey", "No",
        ]
        existing = [c for c in cols if c in df.columns]
        if not existing or "Player" not in existing:
            return pd.DataFrame()
        df = df[existing].copy()
        
        if "Player" in df.columns:
            df["Player"] = df["Player"].astype(str).str.strip()
        if "Team" in df.columns:
            df["Team"] = df["Team"].astype(str).str.strip().replace({"GWS": "GWS Giants"})
        if "Position" in df.columns:
            df["Position"] = df["Position"].astype(str).str.strip()
        
        return df
    
    def _load_season_legacy(s: int) -> pd.DataFrame:
        """Fallback to legacy Excel file."""
        try:
            xl = pd.ExcelFile(PLAYER_FILE)
            if str(s) not in xl.sheet_names:
                return pd.DataFrame()
            df = xl.parse(str(s))
            df.columns = df.columns.astype(str).str.strip()
            df = _normalise_rating_column(df)

            cols = [
                "Player", "Team", "Age", "Age_Decimal", "Position", "Matches",
                "RatingPoints_Avg", "CoachesVotes_Avg", "TimeOnGround",
                "Height", "Height_cm", "Jumper", "Jersey", "Number", "Guernsey", "No",
            ]
            existing = [c for c in cols if c in df.columns]
            if not existing or "Player" not in existing:
                return pd.DataFrame()
            df = df[existing].copy()

            if "Player" in df.columns:
                df["Player"] = df["Player"].astype(str).str.strip()
            if "Team" in df.columns:
                df["Team"] = df["Team"].astype(str).str.strip().replace({"GWS": "GWS Giants"})
            if "Position" in df.columns:
                df["Position"] = df["Position"].astype(str).str.strip()

            return df
        except FileNotFoundError:
            return pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    
    def _load_season(s: int) -> pd.DataFrame:
        """Load season data - try master first, then fallback."""
        df = _load_season_from_master(s)
        if not df.empty:
            return df
        return _load_season_legacy(s)
    
    # Try requested season first
    df = _load_season(season)
    
    # If empty and season is 2026, fall back to 2025
    if df.empty and season == 2026:
        df = _load_season(2025)
        if not df.empty:
            st.info("ℹ️ 2026 data not yet available. Showing 2025 season data.")
    
    if df.empty:
        st.warning(f"⚠️ Could not load player data for {season}")
    
    return df


@st.cache_data(show_spinner=False)
def load_full_squad(season: int) -> pd.DataFrame:
    """
    Load full squad list including players who didn't play.
    Uses master workbook with fallback to legacy files.
    """
    # Try master workbook first
    if DATA_LOADER_AVAILABLE and master_workbook_available():
        df = load_full_squad_data(season)
        if not df.empty:
            df = _normalise_rating_column(df)
            # Map column names
            col_map = {"Matches_Current": "Matches", "JumperNumber": "Jumper"}
            df = df.rename(columns=col_map)
            
            # If missing RatingPoints_Avg, merge from stats
            if "RatingPoints_Avg" not in df.columns:
                stats_df = load_player_stats_for_season(season)
                if not stats_df.empty:
                    stats_df = _normalise_rating_column(stats_df)
                    if "Player" in stats_df.columns and "RatingPoints_Avg" in stats_df.columns:
                        ratings_cols = ["Player", "RatingPoints_Avg"]
                        if "CoachesVotes_Avg" in stats_df.columns:
                            ratings_cols.append("CoachesVotes_Avg")
                        if "TimeOnGround" in stats_df.columns:
                            ratings_cols.append("TimeOnGround")
                        ratings_df = stats_df[ratings_cols].copy()
                        ratings_df["Player"] = ratings_df["Player"].astype(str).str.strip()
                        df["Player"] = df["Player"].astype(str).str.strip()
                        df = df.merge(ratings_df, on="Player", how="left")
            
            cols = [
                "Player", "Team", "Age", "Age_Decimal", "Position", "Matches",
                "RatingPoints_Avg", "CoachesVotes_Avg", "TimeOnGround",
                "Height", "Height_cm", "Jumper", "Jersey", "Number", "Guernsey", "No",
            ]
            existing = [c for c in cols if c in df.columns]
            df = df[existing].copy()
            
            if "Player" in df.columns:
                df["Player"] = df["Player"].astype(str).str.strip()
            if "Team" in df.columns:
                df["Team"] = df["Team"].astype(str).str.strip().replace({"GWS": "GWS Giants"})
            if "Position" in df.columns:
                df["Position"] = df["Position"].astype(str).str.strip()
            
            return df
    
    # Fallback to legacy method
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        
        # Check if full squad sheet exists for this season
        squad_sheet = f"{season} AFL Squads"
        if squad_sheet in xl.sheet_names:
            df = xl.parse(squad_sheet)
            df.columns = df.columns.astype(str).str.strip()
            
            # Map columns from squad sheet to expected columns
            col_map = {"Matches_Current": "Matches", "JumperNumber": "Jumper"}
            df = df.rename(columns=col_map)
            
            # The squad sheet doesn't have RatingPoints_Avg, so we need to merge with the season data
            season_df = xl.parse(str(season))
            season_df.columns = season_df.columns.astype(str).str.strip()
            season_df = _normalise_rating_column(season_df)
            
            # Get ratings columns from season sheet
            if "Player" in season_df.columns and "RatingPoints_Avg" in season_df.columns:
                ratings_cols = ["Player", "RatingPoints_Avg"]
                if "CoachesVotes_Avg" in season_df.columns:
                    ratings_cols.append("CoachesVotes_Avg")
                if "TimeOnGround" in season_df.columns:
                    ratings_cols.append("TimeOnGround")
                
                ratings_df = season_df[ratings_cols].copy()
                ratings_df["Player"] = ratings_df["Player"].astype(str).str.strip()
                
                # Merge ratings into squad
                df["Player"] = df["Player"].astype(str).str.strip()
                df = df.merge(ratings_df, on="Player", how="left")
        else:
            # Fall back to regular season sheet
            df = xl.parse(str(season))
            df.columns = df.columns.astype(str).str.strip()
            df = _normalise_rating_column(df)
        
        cols = [
            "Player", "Team", "Age", "Age_Decimal", "Position", "Matches",
            "RatingPoints_Avg", "CoachesVotes_Avg", "TimeOnGround",
            "Height", "Height_cm", "Jumper", "Jersey", "Number", "Guernsey", "No",
        ]
        existing = [c for c in cols if c in df.columns]
        df = df[existing].copy()

        # clean key columns
        if "Player" in df.columns:
            df["Player"] = df["Player"].astype(str).str.strip()
        if "Team" in df.columns:
            df["Team"] = df["Team"].astype(str).str.strip().replace({"GWS": "GWS Giants"})
        if "Position" in df.columns:
            df["Position"] = df["Position"].astype(str).str.strip()

        return df
    except FileNotFoundError:
        st.error(f"❌ Player ratings file not found: {PLAYER_FILE}")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Could not load full squad data for {season}: {e}")
        return pd.DataFrame()


# ---------------- DATA LOADERS – TRAITS (ENRICHED source of truth) ----------------

def _load_traits_api_cache() -> dict:
    """
    Load cached Traits API data. Returns empty dict if not available.
    """
    if not TRAITS_API_AVAILABLE:
        return {}
    try:
        cache = load_traits_cache()
        return cache.get('players', {})
    except Exception:
        return {}


def _enhance_traits_with_api(df: pd.DataFrame, api_cache: dict) -> pd.DataFrame:
    """
    Enhance Excel traits data with API data where available.
    API data is considered more current/accurate when available.
    Falls back to Excel data for any missing values.
    
    Args:
        df: DataFrame from Excel with traits data
        api_cache: Dict of player_name -> traits dict from API
        
    Returns:
        Enhanced DataFrame with API data merged in
    """
    if not api_cache:
        return df
    
    # Map API trait column names to Excel column names
    API_TO_EXCEL = {
        'Overall_Rating': 'Rating',
        'Ball Winning_Rating': 'Ball Winning',
        'Ball Use_Rating': 'Ball Use',
        'Aerial_Rating': 'Aerial',
        'Defence_Rating': 'Defence',
        # Sub-metrics
        'Ball Winning_Stoppage': 'Stoppage',
        'Ball Winning_Contest': 'Contest',
        'Ball Winning_Power': 'Power',
        'Ball Winning_Receives': 'Receives',
        'Ball Use_Handballing': 'Handballing',
        'Ball Use_Kicking': 'Kicking',
        'Ball Use_Goal Kicking': 'Goal Kicking',
        'Ball Use_Connecting': 'Connecting',
        'Aerial_Marking': 'Marking',
        'Aerial_Contested': 'Contested',
        'Aerial_Moks': 'Moks',
        'Aerial_Ruck': 'Ruck',
        'Defence_Pressure': 'Pressure',
        'Defence_Tackling': 'Tackling',
        'Defence_Intercepting': 'Intercepting',
        'Defence_Neutralise': 'Neutralise',
    }
    
    updated_count = 0
    
    for idx, row in df.iterrows():
        player_name = row.get('Player_Full') or row.get('Player', '')
        
        # Try to find in API cache
        api_data = api_cache.get(player_name)
        if not api_data:
            continue
        
        # Update each trait column from API if available
        for api_col, excel_col in API_TO_EXCEL.items():
            if excel_col in df.columns and api_col in api_data:
                api_val = api_data[api_col]
                if api_val is not None and not pd.isna(api_val):
                    df.at[idx, excel_col] = api_val
        
        updated_count += 1
    
    return df


@st.cache_data(show_spinner=False)
def load_traits(season: int = CURRENT_SEASON) -> pd.DataFrame:
    """
    Load ENRICHED traits for a season.
    
    Enhanced with Traits API data where available:
    - Loads Excel as baseline (source of truth for structure/all players)
    - Overlays API data for players where available (more current ratings)
    - Falls back to Excel for any players not in API cache

    Assumes ENRICHED is the source of truth:
    - does NOT use player_registry / player_uid
    - guarantees: Player_Full, Team_Full, Position_Full, Season exist
    
    Falls back to 2025 if requested season (e.g., 2026) doesn't exist yet.
    """
    TEAM_CODE_TO_NAME = {
        "AFC": "Adelaide","BFC": "Brisbane","CFC": "Carlton","COFC": "Collingwood","EFC": "Essendon",
        "FRFC": "Fremantle","GFC": "Geelong","GCFC": "Gold Coast","GWS": "GWS Giants","HFC": "Hawthorn",
        "MFC": "Melbourne","NMFC": "North Melbourne","PAFC": "Port Adelaide","RFC": "Richmond","SKFC": "St Kilda",
        "SFC": "Sydney","SYFC": "Sydney","WCFC": "West Coast","WBFC": "Western Bulldogs",
    }

    POSITION_ABBREV_TO_FULL = {
        "R": "Ruck",
        "M": "Midfielder",
        "MF": "Mid-Forward",
        "GD": "Gen. Defender",
        "W": "Wing",
        "GF": "Gen. Forward",
        "KF": "Key Forward",
        "KD": "Key Defender",
    }

    def _process_traits_df(df: pd.DataFrame, actual_season: int) -> pd.DataFrame:
        """Process and normalize traits dataframe."""
        df.columns = [str(c).strip() for c in df.columns]
        
        # Season
        if "Season" not in df.columns:
            df["Season"] = season
        df["Season"] = pd.to_numeric(df["Season"], errors="coerce").fillna(season).astype(int)

        # Team_Full - ALWAYS apply mapping to fix any team codes (e.g., SYFC -> Sydney)
        if "Team" in df.columns:
            team_mapped = (
                df["Team"].astype(str).str.strip()
                .map(TEAM_CODE_TO_NAME)
                .fillna(df["Team"].astype(str).str.strip())
            )
            if "Team_Full" in df.columns:
                existing_full = df["Team_Full"].astype(str).str.strip()
                df["Team_Full"] = existing_full.apply(
                    lambda x: TEAM_CODE_TO_NAME.get(x, x) if x in TEAM_CODE_TO_NAME else x
                )
            else:
                df["Team_Full"] = team_mapped
        elif "Team_Full" not in df.columns:
            df["Team_Full"] = ""
        df["Team_Full"] = df["Team_Full"].astype(str).str.strip()

        # Player_Full
        if "Player_Full" not in df.columns:
            if "Player" in df.columns:
                df["Player_Full"] = df["Player"].astype(str).str.strip()
            else:
                return pd.DataFrame()
        df["Player_Full"] = df["Player_Full"].astype(str).str.strip()
        
        # Fix Sydney player names by matching surnames with player summary
        try:
            sydney_mask = df["Team_Full"] == "Sydney"
            if sydney_mask.any():
                player_summary_path = "data/computed/player_summary.csv"
                if os.path.exists(player_summary_path):
                    player_summary = pd.read_csv(player_summary_path)
                    sydney_players = player_summary[player_summary["Team"] == "Sydney"]["Player"].tolist()
                    
                    def extract_surname(name):
                        parts = str(name).strip().split()
                        return parts[-1] if len(parts) >= 2 else name
                    
                    surname_to_full = {extract_surname(n): n for n in sydney_players}
                    
                    def fix_sydney_name(row):
                        if row["Team_Full"] == "Sydney":
                            surname = extract_surname(row["Player_Full"])
                            return surname_to_full.get(surname, row["Player_Full"])
                        return row["Player_Full"]
                    
                    df["Player_Full"] = df.apply(fix_sydney_name, axis=1)
        except Exception:
            pass

        # Position_Full
        if "Position" in df.columns:
            pos_abbrev = df["Position"].astype(str).str.strip()
            df["Position_Full"] = pos_abbrev.map(POSITION_ABBREV_TO_FULL).fillna(pos_abbrev)
        elif "Position_Full" not in df.columns:
            df["Position_Full"] = ""
        df["Position_Full"] = df["Position_Full"].astype(str).str.strip()

        # clean obvious junk strings
        for c in ["Player_Full", "Team_Full", "Position_Full"]:
            df[c] = df[c].replace({"nan": "", "None": ""})

        # Enhance with Traits API data for recent seasons
        if actual_season >= 2025:
            api_cache = _load_traits_api_cache()
            if api_cache:
                df = _enhance_traits_with_api(df, api_cache)

        return df

    try:
        # Try master workbook first
        if DATA_LOADER_AVAILABLE and master_workbook_available():
            df = load_traits_for_season(season)
            if not df.empty:
                return _process_traits_df(df, season)
        
        # Fallback to legacy method
        xl = pd.ExcelFile("2025 Traits ENRICHED.xlsx")
        available_sheets = xl.sheet_names
        actual_season = season
        
        # If requested season doesn't exist, fall back to most recent available
        if str(season) not in available_sheets:
            numeric_sheets = [int(s) for s in available_sheets if s.isdigit()]
            if numeric_sheets:
                actual_season = max(numeric_sheets)
            else:
                st.error(f"No valid season sheets found in traits file")
                return pd.DataFrame()
        
        df = pd.read_excel(xl, sheet_name=str(actual_season))
        return _process_traits_df(df, actual_season)

    except Exception as e:
        st.error(f"Error loading ENRICHED traits for {season}: {e}")
        return pd.DataFrame()


# ============================================================================
# HISTORICAL DATA ACCESS HELPERS
# ============================================================================
# These functions provide access to consolidated historical data (2012-2025)
# from the single source of truth workbook, while falling back to original
# data sources if the workbook is unavailable or the feature is disabled.

def get_enriched_player_data(player_name: str) -> dict:
    """
    Get enriched player data including DOB, draft info, and contract expiry.
    Uses historical workbook if available, otherwise returns empty dict.
    
    This function ADDS data - it doesn't change any existing functionality.
    """
    if not (USE_HISTORICAL_WORKBOOK and HISTORICAL_DATA_AVAILABLE and historical_workbook_available()):
        return {}
    
    result = {}
    
    # Get DOB
    dob = get_player_dob(player_name)
    if dob:
        result['DOB'] = dob
    
    # Get draft info
    draft_info = get_player_draft_info(player_name)
    if draft_info:
        result.update(draft_info)
    
    # Get contract expiry
    contract_expiry = get_player_contract_expiry(player_name)
    if contract_expiry:
        result['Contract_Expiry'] = contract_expiry
    
    return result


def get_enriched_player_career(player_name: str) -> pd.DataFrame:
    """
    Get full career history for a player from historical workbook.
    Includes all seasons from 2012-2025 where the player has stats.
    
    Returns empty DataFrame if workbook unavailable or player not found.
    """
    if not (USE_HISTORICAL_WORKBOOK and HISTORICAL_DATA_AVAILABLE and historical_workbook_available()):
        return pd.DataFrame()
    
    return get_player_career_stats(player_name)


def get_team_historical_data(team_name: str) -> pd.DataFrame:
    """
    Get all historical team stats from consolidated workbook.
    
    Returns empty DataFrame if workbook unavailable.
    """
    if not (USE_HISTORICAL_WORKBOOK and HISTORICAL_DATA_AVAILABLE and historical_workbook_available()):
        return pd.DataFrame()
    
    return get_team_history(team_name)


def get_all_player_registry_data() -> pd.DataFrame:
    """
    Get the full player registry with DOB, draft, contract info.
    
    Returns empty DataFrame if workbook unavailable.
    """
    if not (USE_HISTORICAL_WORKBOOK and HISTORICAL_DATA_AVAILABLE and historical_workbook_available()):
        return pd.DataFrame()
    
    return load_player_registry()


# ---------------- ATTRIBUTE STRUCTURE HELPERS (TEAM SUMMARY) ----------------
def _extract_attribute_structure(summary_df: pd.DataFrame, attribute_name: str):
    """
    Reads group header row and stat row to find columns for one attribute group.
    Returns list of dicts:
      { "stat_name": ..., "value_col": int, "rank_col": int | None }
    """
    if summary_df is None or summary_df.empty:
        return []

    # These indices assume your TEAM summary workbook layout
    header_row = summary_df.iloc[1]  # group header row
    stat_row = summary_df.iloc[2]    # stat labels row

    start_idx_list = [i for i, val in enumerate(header_row) if str(val).strip() == attribute_name]
    if not start_idx_list:
        return []

    start = start_idx_list[0]
    group_starts = [i for i, val in enumerate(header_row) if pd.notna(val) and i > start]
    end = group_starts[0] if group_starts else summary_df.shape[1]

    blocks = []
    col = start
    while col < end:
        label = stat_row.iloc[col]
        if pd.isna(label):
            col += 1
            continue

        label_str = str(label).strip()
        if label_str in ["Team", "#", "", "Rank"]:
            col += 1
            continue

        value_col = col
        rank_col = None
        if col + 1 < end and str(stat_row.iloc[col + 1]).strip() in ["#", "Rank"]:
            rank_col = col + 1
            col += 2
        else:
            col += 1

        blocks.append({"stat_name": label_str, "value_col": value_col, "rank_col": rank_col})

    return blocks


def get_attribute_stat_distribution(
    summary_df: pd.DataFrame,
    attribute_name: str,
    stat_name: str,
    block: str = "Season",  # "Season" or "Last10"
) -> pd.DataFrame:
    blocks = _extract_attribute_structure(summary_df, attribute_name)
    if not blocks:
        return pd.DataFrame(columns=["Team", "Value", "Rank"])

    block_info = next((b for b in blocks if b["stat_name"] == stat_name), None)
    if block_info is None:
        return pd.DataFrame(columns=["Team", "Value", "Rank"])

    value_col = block_info["value_col"]
    rank_col = block_info["rank_col"]

    team_series = summary_df.iloc[:, 0]
    team_aliases = set(TEAM_CODE_MAP.keys()) | {"Greater Western Sydney"}

    team_row_indices = [i for i, val in team_series.items() if str(val).strip() in team_aliases]
    if not team_row_indices:
        return pd.DataFrame(columns=["Team", "Value", "Rank"])

    team_row_indices = sorted(team_row_indices)
    total_rows = len(team_row_indices)

    # If file has Season + L10 blocks stacked, split in half
    if total_rows > 18:
        chunk_size = total_rows // 2
        season_indices = team_row_indices[:chunk_size]
        last10_indices = team_row_indices[-chunk_size:]
    else:
        season_indices = team_row_indices
        last10_indices = team_row_indices

    chosen_indices = last10_indices if block.lower().startswith("last") else season_indices

    records = []
    for idx in chosen_indices:
        team_raw = str(team_series.iloc[idx]).strip()
        team = "GWS Giants" if team_raw in ["GWS", "Greater Western Sydney", "GWS Giants"] else team_raw
        val = summary_df.iloc[idx, value_col]
        rank = summary_df.iloc[idx, rank_col] if rank_col is not None else None
        records.append({"Team": team, "Value": val, "Rank": rank})

    df_out = pd.DataFrame(records)
    if df_out.empty:
        return df_out

    df_out["Value"] = pd.to_numeric(df_out["Value"], errors="coerce")
    df_out["Rank"] = pd.to_numeric(df_out["Rank"], errors="coerce").astype("Int64")
    return df_out


# ---------------- IMAGE HELPERS ----------------
def get_team_logo_path(team_name: str):
    if not isinstance(team_name, str):
        return None
    code = TEAM_CODE_MAP.get(team_name)
    if not code:
        return None
    for ext in (".png", ".jpg", ".jpeg"):
        path = str(BASE_DIR / LOGO_FOLDER / (code + ext))
        if os.path.exists(path):
            return path
    return None


@st.cache_data
def load_player_name_mapping():
    """Load player photo guide and create mapping from various name formats to full names."""
    try:
        guide_df = pd.read_csv(str(BASE_DIR / "player_photo_guide.csv"))
        name_map = {}
        team_player_map = {}  # Map of (team, initial.surname) -> full_name
        
        # Team name normalization
        def normalize_team(team):
            team = str(team).strip().lower()
            if 'sydney' in team or team in ['syfc', 'sfc']:
                return 'sydney'
            if 'gws' in team or 'giants' in team or 'greater western sydney' in team:
                return 'gws'
            if 'bulldogs' in team or team in ['wbfc']:
                return 'western bulldogs'
            return team.replace(' ', '').replace('fc', '')
        
        for _, row in guide_df.iterrows():
            full_name = str(row["Player"]).strip()
            team = normalize_team(row.get("Team", ""))
            
            # Map full name to itself
            name_map[full_name] = full_name
            name_map[full_name.lower()] = full_name
            
            # Create initial + surname mapping (e.g., "J. Dawson" -> "Jordan Dawson")
            # Also handles multi-part surnames like "Tom De Koning" -> "T. De Koning"
            parts = full_name.split()
            if len(parts) >= 2:
                first_name = parts[0]
                surname = " ".join(parts[1:])  # Handle multi-part surnames
                initial_surname = f"{first_name[0]}. {surname}"
                name_map[initial_surname] = full_name
                name_map[initial_surname.lower()] = full_name
                
                # Create team-specific mapping for more accurate matching
                team_key = f"{team}_{initial_surname.lower()}"
                team_player_map[team_key] = full_name
        
        # Store team map as attribute for use in get_player_photo_path
        name_map['__team_player_map__'] = team_player_map
        return name_map
    except Exception:
        return {}


def resolve_player_full_name(abbreviated_name: str, team_name: str | None = None) -> str:
    """Resolve abbreviated player names (e.g., 'T. De Koning') to full names (e.g., 'Tom De Koning')."""
    if not isinstance(abbreviated_name, str):
        return abbreviated_name
    
    name_map = load_player_name_mapping()
    team_player_map = name_map.get('__team_player_map__', {})
    
    # Normalize team name for lookup
    def normalize_team(team):
        team = str(team).strip().lower()
        if 'sydney' in team or team in ['syfc', 'sfc']:
            return 'sydney'
        if 'gws' in team or 'giants' in team:
            return 'gws'
        if 'bulldogs' in team or team in ['wbfc']:
            return 'western bulldogs'
        return team.replace(' ', '').replace('fc', '')
    
    # Try team-aware lookup first
    if team_name and team_player_map:
        norm_team = normalize_team(team_name)
        team_key = f"{norm_team}_{abbreviated_name.strip().lower()}"
        if team_key in team_player_map:
            return team_player_map[team_key]
    
    # Fall back to regular name mapping
    resolved = name_map.get(abbreviated_name.strip(), name_map.get(abbreviated_name.strip().lower(), abbreviated_name.strip()))
    return resolved


def get_player_photo_path(player_name: str, team_name: str | None = None) -> str | None:
    if not isinstance(player_name, str):
        return None
    
    # Try to normalize the name using the mapping
    name_map = load_player_name_mapping()
    team_player_map = name_map.get('__team_player_map__', {})
    
    # Try team-aware lookup first if team provided
    normalized_name = player_name.strip()
    if team_name and team_player_map:
        def normalize_team(team):
            team = str(team).strip().lower()
            if 'sydney' in team or team in ['syfc', 'sfc']:
                return 'sydney'
            if 'gws' in team or 'giants' in team:
                return 'gws'
            if 'bulldogs' in team or team in ['wbfc']:
                return 'western bulldogs'
            return team.replace(' ', '').replace('fc', '')
        
        norm_team = normalize_team(team_name)
        team_key = f"{norm_team}_{player_name.strip().lower()}"
        if team_key in team_player_map:
            normalized_name = team_player_map[team_key]
    
    # Fall back to regular name mapping
    if normalized_name == player_name.strip():
        normalized_name = name_map.get(player_name.strip(), name_map.get(player_name.strip().lower(), player_name.strip()))
    
    base = normalized_name.lower().replace(" ", "_")
    for ext in (".png", ".jpg", ".jpeg"):
        path = str(BASE_DIR / PLAYER_PHOTO_FOLDER / (base + ext))
        if os.path.exists(path):
            return path
    return None


def _resize_image(path: str, size: int):
    try:
        img = Image.open(path).convert("RGBA")
        img = img.resize((size, size))
        return img
    except Exception:
        return None


def display_logo(team_name: str, container, size: int = 80):
    path = get_team_logo_path(team_name)
    if not path:
        return
    img = _resize_image(path, size)
    if img is not None:
        container.image(img)
    else:
        try:
            container.image(path, width=size)
        except Exception:
            return


def display_player_photo(player_name: str, container, size: int = 160, use_container_width: bool = False, team_name: str | None = None):
    path = get_player_photo_path(player_name, team_name)
    if not path:
        # Show placeholder when photo not found
        container.markdown(f"<div style='width:{size}px;height:{size}px;background:#333;display:flex;align-items:center;justify-content:center;border-radius:8px;'><span style='font-size:48px;opacity:0.3;'>👤</span></div>", unsafe_allow_html=True)
        return
    try:
        # Streamlit 1.53.0 uses the modern 'width' parameter
        if use_container_width:
            container.image(path, width="stretch")
        else:
            img = _resize_image(path, size)
            if img is not None:
                container.image(img, width=size)
            else:
                container.image(path, width=size)
    except Exception as e:
        container.error(f"Error loading photo: {str(e)}")
        return



# ---------------- RATING COLOUR HELPERS ----------------
def rating_colour_for_value(v: float, values: pd.Series) -> tuple[str, str]:
    """Return colour based on percentile - 5 tier system.
    
    5-Tier System (equal 20% bands):
        - Elite: Top 20% (80-100%) - Dark Green
        - Good: 60-80% - Light Green
        - Average: 40-60% - Gold
        - Below Average: 20-40% - Orange
        - Poor: Bottom 20% (0-20%) - Red
    """
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if len(vals) == 0 or pd.isna(v):
        return "#333333", "white"

    perc = (vals <= v).mean()
    if perc >= 0.80:
        return "#008000", "white"   # Elite - Dark Green
    elif perc >= 0.60:
        return "#90EE90", "black"   # Good - Light Green
    elif perc >= 0.40:
        return "#FFD700", "black"   # Average - Gold
    elif perc >= 0.20:
        return "#FFA500", "white"   # Below Average - Orange
    else:
        return "#FF0000", "white"   # Poor - Red


# ---------------- PLAYER TRAITS HISTORY TABLE HELPERS ----------------
def _opacity_from_pct(pct: float) -> float:
    """Map percentile to opacity for visual intensity - 5 tier system."""
    if pd.isna(pct):
        return 0.20
    if pct >= 0.80:  # Elite
        return 1.0
    if pct >= 0.60:  # Good
        return 0.80
    if pct >= 0.40:  # Average
        return 0.60
    if pct >= 0.20:  # Below Average
        return 0.40
    return 0.20      # Poor


def build_player_traits_history_table(
    traits_df: pd.DataFrame,
    team_full_map: dict | None = None,
    position_full_map: dict | None = None,
):
    """
    Builds a history table for ONE player (traits_df is already filtered to that player).
    Returns: (display_df, html_string)
    """
    required = ["Player_Full", "Team_Full", "Season", "Position_Full", "Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    missing = [c for c in required if c not in traits_df.columns]
    if missing:
        raise KeyError(f"Traits DF missing required columns: {missing}")

    t = traits_df.copy()
    t["Season"] = pd.to_numeric(t["Season"], errors="coerce").astype("Int64")

    # Ensure team/pos are filled
    if team_full_map and "Team" in t.columns and "Team_Full" not in t.columns:
        t["Team_Full"] = t["Team"].map(team_full_map).fillna(t["Team"])
    if position_full_map and "Position" in t.columns and "Position_Full" not in t.columns:
        t["Position_Full"] = t["Position"].map(position_full_map).fillna(t["Position"])

    for c in ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
        t[c] = pd.to_numeric(t[c], errors="coerce")

    out = pd.DataFrame({
        "Player": t["Player_Full"],
        "Club": t["Team_Full"],
        "Season": t["Season"],
        "Position": t["Position_Full"],
        "Rating": t["Rating"],
        "Ball Winning": t["Ball Winning"],
        "Ball Use": t["Ball Use"],
        "Aerial": t["Aerial"],
        "Defence": t["Defence"],
    }).sort_values("Season", ascending=False).reset_index(drop=True)

    # Percentiles computed per season against that season’s competition requires full competition df.
    # Here we only colour by the player’s own value tiers (still looks great & avoids needing registry).
    base_colors = {
        "Rating": (0, 0, 0),
        "Ball Winning": (0, 102, 204),
        "Ball Use": (0, 153, 0),
        "Aerial": (255, 204, 0),
        "Defence": (204, 0, 0),
    }

    # Build simple “tier percentile” vs that player’s history range (min..max)
    pct_cols = {}
    for metric in ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
        vals = out[metric].dropna()
        if len(vals) <= 1:
            pct = pd.Series([np.nan] * len(out))
        else:
            pct = out[metric].rank(pct=True)
        pct_cols[metric] = pct

    def fmt2(x):
        try:
            return f"{float(x):.2f}"
        except Exception:
            return "—"

    display_cols = ["Player", "Club", "Season", "Position", "Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    headers = "".join([f"<th>{c}</th>" for c in display_cols])

    rows_html = []
    for i, r in out.iterrows():
        tds = []
        for c in display_cols:
            if c in base_colors:
                pct = pct_cols[c].iloc[i]
                a = _opacity_from_pct(pct)
                rr, gg, bb = base_colors[c]
                bg = f"rgba({rr},{gg},{bb},{a})"
                text = "white" if (c == "Rating" and a >= 0.75) else ("#111111" if c == "Aerial" else "white")
                tds.append(
                    f"<td style='background-color:{bg} !important; color:{text} !important; font-weight:800; text-align:center;'>"
                    f"{fmt2(r.get(c))}</td>"
                )
            else:
                v = r.get(c, "—")
                tds.append(f"<td style='text-align:center;'>{v}</td>")
        rows_html.append("<tr>" + "".join(tds) + "</tr>")

    table_html = (
        "<table>"
        "<thead><tr>" + headers + "</tr></thead>"
        "<tbody>" + "".join(rows_html) + "</tbody>"
        "</table>"
    )

    return out[display_cols], table_html

# ---------------- TEAM SUMMARY: AVAILABLE YEARS ----------------
@st.cache_data(show_spinner=False)
def get_available_summary_years() -> list[int]:
    """
    Returns all years that have a '<YEAR> Summary' sheet in TEAM_FILE.
    Falls back to common years if workbook can't be read.
    """
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        years = []
        for sheet in xl.sheet_names:
            s = str(sheet).strip()
            if s.endswith(" Summary"):
                head = s.split()[0]
                if head.isdigit():
                    years.append(int(head))
        years = sorted(set(years), reverse=True)
        return years if years else sorted(set(TEAM_SEASONS), reverse=True)
    except Exception:
        return sorted(set(TEAM_SEASONS), reverse=True)


# ---------------- AFL LADDER HELPERS ----------------
@st.cache_data(show_spinner=False)
def get_ladder_position(team_name: str, season: int) -> tuple[str, int | None, str]:
    """
    Returns (position_str, position_int, color) for team/season from ladder file.
    """
    ladder_df = load_afl_ladder_positions()
    if ladder_df.empty:
        return "N/A", None, "#888888"

    team_data = ladder_df[(ladder_df["Team"] == team_name) & (ladder_df["Season"] == season)]
    if team_data.empty:
        return "N/A", None, "#888888"

    position = team_data["Position"].iloc[0]
    try:
        pos_int = int(position)
        # 5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)
        if pos_int <= 4:
            color = "#008000"   # Elite - Dark Green
        elif pos_int <= 7:
            color = "#90EE90"   # Good - Light Green
        elif pos_int <= 11:
            color = "#FFD700"   # Average - Gold
        elif pos_int <= 15:
            color = "#FFA500"   # Below Average - Orange
        else:
            color = "#FF0000"   # Poor - Red
        return get_ordinal_suffix(pos_int), pos_int, color
    except (ValueError, TypeError):
        return str(position), None, "#888888"


@st.cache_data(show_spinner=False)
def get_ladder_percentage(team_name: str, season: int) -> tuple[str, int | None, str]:
    """
    Returns (percentage_str, pct_rank, color) for team/season.
    Rank is computed within the season by numeric Percentage.
    """
    ladder_df = load_afl_ladder_positions()
    if ladder_df.empty:
        return "N/A", None, "#888888"

    team_data = ladder_df[(ladder_df["Team"] == team_name) & (ladder_df["Season"] == season)]
    if team_data.empty:
        return "N/A", None, "#888888"

    percentage = team_data["Percentage"].iloc[0]
    percentage_str = str(percentage).strip()

    def extract_pct(val):
        s = str(val).strip().replace("%", "")
        try:
            return float(s)
        except Exception:
            return np.nan

    season_data = ladder_df[ladder_df["Season"] == season].copy()
    season_data["pct_numeric"] = season_data["Percentage"].apply(extract_pct)
    season_data = season_data.dropna(subset=["pct_numeric"]).sort_values("pct_numeric", ascending=False).reset_index(drop=True)

    pct_rank = None
    for idx, row in season_data.iterrows():
        if row["Team"] == team_name:
            pct_rank = idx + 1
            break

    if pct_rank is not None:
        # 5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)
        if pct_rank <= 4:
            color = "#008000"   # Elite - Dark Green
        elif pct_rank <= 7:
            color = "#90EE90"   # Good - Light Green
        elif pct_rank <= 11:
            color = "#FFD700"   # Average - Gold
        elif pct_rank <= 15:
            color = "#FFA500"   # Below Average - Orange
        else:
            color = "#FF0000"   # Poor - Red
    else:
        color = "#888888"

    pct_val = extract_pct(percentage)
    if pd.isna(pct_val):
        return percentage_str if "%" in percentage_str else percentage_str + "%", pct_rank, color

    return f"{pct_val:.1f}%", pct_rank, color



# ---------------- DEPTH CHART HELPERS ----------------


def find_first_column(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def map_position_to_depth(pos_raw: str) -> str:
    if not isinstance(pos_raw, str):
        return "Midfielder"
    p = pos_raw.lower()

    # Check for Wing FIRST - it overrides all other positions
    if "wing" in p:
        return "Wing"
    
    if "ruck" in p or "ruc" in p:
        return "Ruck"
    if ("key" in p and ("def" in p or "back" in p)) or "kpd" in p:
        return "Key Defender"
    if ("key" in p and ("fwd" in p or "forward" in p)) or "kpf" in p:
        return "Key Forward"
    if "mid-f" in p or "hff" in p or ("half" in p and "forward" in p):
        return "Mid-Forward"
    if "mid" in p:
        return "Midfielder"
    if "def" in p or "back" in p or "hb" in p:
        return "Gen. Defender"
    if "fwd" in p or "forward" in p:
        return "Gen. Forward"
    return "Midfielder"


def map_age_to_band(age_val) -> str:
    try:
        a = float(age_val)
    except Exception:
        return "Under 22"
    if a < 22:
        return "Under 22"
    elif a < 26:
        return "22 to 26 Year Old"
    elif a < 30:
        return "26 to 30 Year Old"
    else:
        return "30+ Year Old"


def get_rating_color_team_context(rating_value, df_team, rating_col):
    """Return colour based on percentile of rating_value within df_team[rating_col].
    
    5-Tier System (equal 20% bands):
        - Elite: Top 20% (80-100%)
        - Good: 60-80%
        - Average: 40-60%
        - Below Average: 20-40%
        - Poor: Bottom 20% (0-20%)
    """
    try:
        ratings = pd.to_numeric(df_team[rating_col], errors="coerce").dropna()
        if len(ratings) == 0 or pd.isna(rating_value):
            return "#333333", "white"

        percentile = (ratings <= rating_value).mean()

        if percentile >= 0.80:
            return "#008000", "white"   # Elite - Dark Green
        elif percentile >= 0.60:
            return "#90EE90", "black"   # Good - Light Green
        elif percentile >= 0.40:
            return "#FFD700", "black"   # Average - Gold
        elif percentile >= 0.20:
            return "#FFA500", "white"   # Below Average - Orange
        else:
            return "#FF0000", "white"   # Poor - Red
    except Exception:
        return "#333333", "white"


def build_depth_chart_html(df_team: pd.DataFrame, all_teams_df: pd.DataFrame = None, fc_mode: bool = False) -> str:
    """
    df_team is the Summary subset for one team, with:
    Player, Jumper, Age, Height, Position, RatingPoints_Avg.
    all_teams_df is the full Summary DataFrame for all teams (for ranking calculations).
    fc_mode: if True, display ratings in FIFA/FC style (50-99 scale).
    """
    # Remove duplicate columns if they exist
    if len(df_team.columns) != len(set(df_team.columns)):
        df_team = df_team.loc[:, ~df_team.columns.duplicated()]
    
    num_col = find_first_column(df_team, ["Jumper", "Jersey", "Number", "Guernsey", "No"])
    age_col = "Age"
    height_col = "Height"
    rating_col = "RatingPoints_Avg"
    pos_col = "Position"
    player_col = "Player"

    grid = {pos: {band: [] for band in AGE_BANDS} for pos in DEPTH_POSITIONS}
    
    # Track ratings for each cell to calculate averages
    ratings_grid = {pos: {band: [] for band in AGE_BANDS} for pos in DEPTH_POSITIONS}

    # Calculate weighted rating for sorting (Rating × Matches) - same as List Ladder
    # Look for matches column in df_team or fall back to raw rating
    matches_col_display = None
    for col_name in ['Matches', '2025 Matches', 'Total Matches']:
        if col_name in df_team.columns:
            matches_col_display = col_name
            break
    
    # Cap matches at 23 (regular season) to avoid over-rating players who played finals
    MAX_MATCHES_FOR_RATING = 23
    if matches_col_display:
        df_team = df_team.copy()
        capped_matches = pd.to_numeric(df_team[matches_col_display], errors="coerce").fillna(0).clip(upper=MAX_MATCHES_FOR_RATING)
        df_team["_Weighted_Sort"] = pd.to_numeric(df_team[rating_col], errors="coerce").fillna(0) * capped_matches
        df_sorted = df_team.sort_values("_Weighted_Sort", ascending=False, na_position='last')
    elif rating_col in df_team.columns:
        df_sorted = df_team.sort_values(rating_col, ascending=False, na_position='last')
    else:
        df_sorted = df_team.copy()

    for _, row in df_sorted.iterrows():
        player_name = row.get(player_col, "")
        if not isinstance(player_name, str) or not player_name.strip():
            continue

        num = row.get(num_col, "")
        age = row.get(age_col, "")
        height = row.get(height_col, "")
        rating = row.get(rating_col, "")

        depth_pos = map_position_to_depth(row.get(pos_col, ""))
        age_band = map_age_to_band(age)

        # Build player info with rating box positioned on the right side, top-aligned
        info_parts = []
        
        # Left side: jumper + name, age, height
        left_parts = []
        
        # Line 1: jumper + name
        line1_parts = []
        if pd.notna(num) and str(num).strip() != "":
            try:
                line1_parts.append(f"<span style='display:inline-block;background:linear-gradient(135deg,#2d2d2d 0%,#1a1a1a 100%);color:#fff;padding:3px 8px;border-radius:6px;margin-right:6px;font-weight:900;box-shadow:0 2px 6px rgba(0,0,0,0.3);'>{int(num)}</span>")
            except Exception:
                line1_parts.append(f"<span style='display:inline-block;background:linear-gradient(135deg,#2d2d2d 0%,#1a1a1a 100%);color:#fff;padding:3px 8px;border-radius:6px;margin-right:6px;font-weight:900;box-shadow:0 2px 6px rgba(0,0,0,0.3);'>{num}</span>")
        line1_parts.append(f"<span style='font-weight:900;color:#1a1a1a;'>{player_name}</span>")
        left_parts.append(f"<div style='font-size:1.05em;margin-bottom:4px;'>{' '.join(line1_parts)}</div>")
        
        # Line 2: age, height
        line2_parts = []
        if pd.notna(age) and str(age).strip() != "":
            try:
                line2_parts.append(f"{float(age):.1f}yrs")
            except Exception:
                line2_parts.append(f"{age}yrs")

        if pd.notna(height) and str(height).strip() != "":
            try:
                line2_parts.append(f"{float(height):.0f}cm")
            except Exception:
                line2_parts.append(f"{height}cm")
        
        if line2_parts:
            left_parts.append(f"<div style='font-size:0.9em;color:#666;font-weight:600;'>{', '.join(line2_parts)}</div>")
        
        left_html = "".join(left_parts)
        
        # Right side: rating box
        # Show rating if available, or "N/A" badge for players who didn't play (no 2025 games)
        rating_box_html = ""
        has_valid_rating = rating_col in df_team.columns and pd.notna(rating) and str(rating).strip() not in ("", "nan")
        
        if has_valid_rating:
            try:
                rating_float = float(rating)
                bg_color, text_color = get_rating_color_team_context(
                    rating_float, df_team, rating_col
                )
                
                # Format rating based on FC mode
                if fc_mode:
                    fc_val = convert_trait_to_fc_rating(rating_float)
                    rating_display = str(fc_val) if fc_val is not None else "—"
                else:
                    rating_display = f"{rating_float:.2f}"

                rating_box_html = f"<span style='display:inline-block;padding:8px 16px;border-radius:10px;background:{bg_color};color:{text_color};font-weight:900;font-size:1.5em;box-shadow:0 3px 10px rgba(0,0,0,0.3);border:2px solid rgba(255,255,255,0.2);min-width:50px;text-align:center;'>{rating_display}</span>"
            except Exception:
                rating_box_html = f"<span>{rating}</span>"
        else:
            # Player didn't play - show N/A badge in grey
            rating_box_html = f"<span style='display:inline-block;padding:8px 16px;border-radius:10px;background:#666666;color:#ffffff;font-weight:900;font-size:1.2em;box-shadow:0 3px 10px rgba(0,0,0,0.3);border:2px solid #444444;min-width:50px;text-align:center;'>N/A</span>"
        
        # Combine left and right with flexbox, top-aligned - ENHANCED PLAYER CARD
        if rating_box_html:
            player_html = f"<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 10px;background:linear-gradient(135deg,#f8f9fa 0%,#ffffff 100%);border-radius:8px;border-left:4px solid #2d2d2d;box-shadow:0 2px 6px rgba(0,0,0,0.08);transition:all 0.2s;margin:2px 0;'><div style='flex:1;'>{left_html}</div><div>{rating_box_html}</div></div>"
        else:
            player_html = f"<div style='padding:8px 10px;background:linear-gradient(135deg,#f8f9fa 0%,#ffffff 100%);border-radius:8px;border-left:4px solid #2d2d2d;box-shadow:0 2px 6px rgba(0,0,0,0.08);margin:2px 0;'>{left_html}</div>"

        if depth_pos in grid and age_band in grid[depth_pos]:
            grid[depth_pos][age_band].append(player_html)
            # Track rating for average calculation
            if pd.notna(rating) and str(rating).strip() != "":
                try:
                    ratings_grid[depth_pos][age_band].append(float(rating))
                except Exception:
                    pass

    # Calculate rankings if all_teams_df is provided
    age_band_rankings = {}
    position_rankings = {}
    
    if all_teams_df is not None and rating_col in all_teams_df.columns:
        # Debug: Check for duplicate columns
        if len(all_teams_df.columns) != len(set(all_teams_df.columns)):
            # Remove duplicate columns
            all_teams_df = all_teams_df.loc[:, ~all_teams_df.columns.duplicated()]
        
        # Load Wing players mapping (same as List Ladder) - critical for accurate position rankings
        wing_players_by_lastname_team = {}
        try:
            wings_file_path = BASE_DIR / "data" / "AFL_Historical_2012_2025.xlsx"
            wings_df = pd.read_excel(wings_file_path, sheet_name="Wings")
            for _, wrow in wings_df.iterrows():
                wplayer_name = wrow.get("Player", "")
                wteam = wrow.get("Team", "")
                if pd.notna(wplayer_name) and pd.notna(wteam):
                    name_parts = str(wplayer_name).strip().split()
                    if len(name_parts) >= 1:
                        last_name = name_parts[-1].lower()
                        team_str = str(wteam).strip().lower()
                        wing_players_by_lastname_team[(last_name, team_str)] = "Wing"
        except Exception:
            pass  # Continue without Wing mapping if file not available
        
        # Load Summary positions mapping (same as List Ladder) - for accurate position lookup
        summary_positions = {}
        try:
            summary_xl = pd.ExcelFile(PLAYER_FILE)
            summary_for_pos = summary_xl.parse("Summary")
            summary_for_pos.columns = summary_for_pos.columns.astype(str).str.strip()
            for _, srow in summary_for_pos.iterrows():
                sp_name = srow.get("Player", "")
                sp_position = srow.get("Position", "")
                if pd.notna(sp_name) and pd.notna(sp_position):
                    summary_positions[str(sp_name).strip()] = str(sp_position).strip()
        except Exception:
            pass  # Continue without Summary positions if loading fails
        
        # Function to get corrected depth position (matches List Ladder logic EXACTLY)
        def get_corrected_depth_position(player_name, team_name, fallback_position):
            player_key = str(player_name).strip() if pd.notna(player_name) else ""
            team_key = str(team_name).strip().lower() if pd.notna(team_name) else ""
            
            # First check if player is a Wing (by last name + team match)
            if player_key:
                name_parts = player_key.split()
                if len(name_parts) >= 2:
                    last_name = name_parts[-1].lower()
                    if (last_name, team_key) in wing_players_by_lastname_team:
                        return "Wing"
            
            # Then check Summary tab positions (same as List Ladder)
            if player_key in summary_positions:
                summary_pos = summary_positions[player_key]
                return map_position_to_depth(summary_pos)
            
            # Otherwise use the position from player data
            return map_position_to_depth(fallback_position)
        
        # Find matches column (could be 'Total Matches', '2025 Matches', or 'Matches')
        matches_col = None
        for col_name in ['2025 Matches', 'Total Matches', 'Matches']:
            if col_name in all_teams_df.columns:
                matches_col = col_name
                break
        
        # Calculate weighted rating: Rating × Matches (rewards sustained performance)
        # Cap matches at 23 (regular season) to avoid over-rating players who played finals
        MAX_MATCHES_FOR_RATING = 23
        if matches_col and matches_col in all_teams_df.columns:
            all_teams_df = all_teams_df.copy()
            all_teams_df["_Matches"] = pd.to_numeric(all_teams_df[matches_col], errors="coerce").fillna(0).clip(upper=MAX_MATCHES_FOR_RATING)
            all_teams_df["_Weighted_Rating"] = pd.to_numeric(all_teams_df[rating_col], errors="coerce").fillna(0) * all_teams_df["_Matches"]
            all_weighted = all_teams_df["_Weighted_Rating"].dropna()
        else:
            # Fallback to raw ratings if no matches column
            all_teams_df = all_teams_df.copy()
            all_teams_df["_Weighted_Rating"] = pd.to_numeric(all_teams_df[rating_col], errors="coerce").fillna(0)
            all_weighted = all_teams_df["_Weighted_Rating"].dropna()
        
        def get_rating_points(weighted_val, all_weighted_clean):
            """Convert weighted rating (Rating × Matches) to points based on percentile.
            
            4-Tier System (matches List Ladder):
                - Elite: Top 15% = 3 points
                - Good: Top 40% = 1 point
                - Average: Top 65% = 0.5 points
                - Poor: Bottom 35% = 0 points
            """
            if pd.isna(weighted_val) or weighted_val == 0:
                return 0
            
            percentile = (all_weighted_clean <= weighted_val).mean()
            
            if percentile >= 0.85:
                return 3    # Elite - top 15%
            elif percentile >= 0.60:
                return 1    # Good - top 40%
            elif percentile >= 0.35:
                return 0.5  # Average - top 65%
            else:
                return 0    # Poor - bottom 35%
        
        # Get unique teams
        teams = all_teams_df["Team"].dropna().unique()
        
        # Calculate age band rankings (column rankings) - TOTAL POINTS using weighted rating
        age_band_points = {team: {band: 0 for band in AGE_BANDS} for team in teams}
        
        for team in teams:
            team_df = all_teams_df[all_teams_df["Team"] == team]
            for _, row in team_df.iterrows():
                player_age = row.get(age_col, None)
                weighted_rating = row.get("_Weighted_Rating", None)
                
                if pd.notna(player_age) and pd.notna(weighted_rating):
                    age_band = map_age_to_band(player_age)
                    try:
                        points = get_rating_points(float(weighted_rating), all_weighted)
                        age_band_points[team][age_band] += points
                    except Exception:
                        pass
        
        # Rank teams for each age band based on TOTAL POINTS
        # Use pandas rank with method='min' for consistency (tied teams get same rank)
        for band in AGE_BANDS:
            pts_series = pd.Series({team: age_band_points[team][band] for team in teams})
            ranks = pts_series.rank(ascending=False, method='min').astype(int)
            
            selected_team_name = df_team["Team"].iloc[0]
            if selected_team_name in ranks.index:
                age_band_rankings[band] = (ranks[selected_team_name], len(teams), pts_series[selected_team_name])
        
        # Calculate position rankings (row rankings) - TOTAL POINTS using weighted rating
        position_points = {team: {pos: 0 for pos in DEPTH_POSITIONS} for team in teams}
        
        for team in teams:
            team_df = all_teams_df[all_teams_df["Team"] == team]
            for _, row in team_df.iterrows():
                player_pos_raw = row.get(pos_col, None)
                player_name = row.get(player_col, None)
                weighted_rating = row.get("_Weighted_Rating", None)
                
                if pd.notna(player_pos_raw) and pd.notna(weighted_rating):
                    # Use corrected depth position (with Wing mapping) - matches List Ladder
                    depth_pos = get_corrected_depth_position(player_name, team, player_pos_raw)
                    try:
                        points = get_rating_points(float(weighted_rating), all_weighted)
                        position_points[team][depth_pos] += points
                    except Exception:
                        pass
        
        # Rank teams for each position based on TOTAL POINTS
        # Use pandas rank with method='min' to match List Ladder exactly (tied teams get same rank)
        for pos in DEPTH_POSITIONS:
            # Build a Series of points for all teams
            pts_series = pd.Series({team: position_points[team][pos] for team in teams})
            # Use rank with method='min' - same as List Ladder
            ranks = pts_series.rank(ascending=False, method='min').astype(int)
            
            selected_team_name = df_team["Team"].iloc[0]
            if selected_team_name in ranks.index:
                position_rankings[pos] = (ranks[selected_team_name], len(teams), pts_series[selected_team_name])

    # Helper function to get ordinal suffix
    def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    
    # Helper function to get ranking color - 5 tier system
    def get_ranking_color(rank, total=18):
        """5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)"""
        if rank <= 4:
            return "#008000"   # Elite - Dark Green
        elif rank <= 7:
            return "#90EE90"   # Good - Light Green
        elif rank <= 11:
            return "#FFD700"   # Average - Gold
        elif rank <= 15:
            return "#FFA500"   # Below Average - Orange
        else:
            return "#FF0000"   # Poor - Red

    # build HTML table with rankings - PROFESSIONAL BROADCAST STYLE
    html = []
    html.append("<table style='width:100%;border-collapse:separate;border-spacing:0;font-size:0.85em;box-shadow:0 8px 24px rgba(0,0,0,0.4);border-radius:12px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,\"Helvetica Neue\",Arial,sans-serif;'>")
    
    # Header row with column names and rankings
    html.append("<tr>")
    html.append("<th style='background:linear-gradient(135deg,#1a1a1a 0%,#2d2d2d 100%);color:#FFFFFF;padding:16px 12px;border-right:2px solid #444;font-weight:900;font-size:1.05em;letter-spacing:0.05em;text-transform:uppercase;text-shadow:2px 2px 4px rgba(0,0,0,0.5);'>Position</th>")
    
    for band in AGE_BANDS:
        # Get ranking info for this age band
        ranking_html = ""
        if band in age_band_rankings:
            rank, total, avg = age_band_rankings[band]
            ordinal = get_ordinal(rank)
            color = get_ranking_color(rank, total)
            # Use black text on light backgrounds (Light Green and Gold)
            text_color = "black" if color in ("#90EE90", "#FFD700") else "white"
            ranking_html = f"<div style='margin-top:10px;'><span style='display:inline-block;background-color:{color};color:{text_color};padding:10px 20px;border-radius:10px;font-weight:900;font-size:1.3em;box-shadow:0 4px 12px rgba(0,0,0,0.3);border:2px solid rgba(255,255,255,0.2);'>{ordinal}</span></div>"
        
        html.append(f"<th style='background:linear-gradient(135deg,#7CB342 0%,#9CCC65 100%);color:#1a1a1a;padding:16px 12px;border-right:2px solid #5a8f2f;text-align:center;vertical-align:top;font-weight:900;font-size:1.05em;letter-spacing:0.05em;text-transform:uppercase;text-shadow:1px 1px 2px rgba(255,255,255,0.3);'><div>{band}</div>{ranking_html}</th>")
    html.append("</tr>")

    for pos in DEPTH_POSITIONS:
        bg, fg = POSITION_COLOURS.get(pos, ("#dddddd", "black"))
        html.append("<tr>")
        
        # Position cell with ranking
        pos_cell_html = f"<div style='font-size:1.1em;font-weight:900;letter-spacing:0.03em;'>{pos}</div>"
        if pos in position_rankings:
            rank, total, avg = position_rankings[pos]
            ordinal = get_ordinal(rank)
            color = get_ranking_color(rank, total)
            # Use black text on light backgrounds (Light Green and Gold)
            text_color = "black" if color in ("#90EE90", "#FFD700") else "white"
            pos_cell_html += f"<div style='margin-top:10px;'><span style='display:inline-block;background-color:{color};color:{text_color};padding:10px 20px;border-radius:10px;font-weight:900;font-size:1.3em;box-shadow:0 4px 12px rgba(0,0,0,0.3);border:2px solid rgba(255,255,255,0.2);'>{ordinal}</span></div>"
        
        html.append(f"<td style='background:{bg};color:{fg};padding:16px 12px;border-right:2px solid #444;border-top:2px solid #444;font-weight:900;vertical-align:top;text-align:center;'>{pos_cell_html}</td>")
        
        for band in AGE_BANDS:
            players = grid[pos][band]
            if players:
                sep = "<div style='margin:8px 0;height:1px;background:linear-gradient(90deg,transparent 0%,#ddd 50%,transparent 100%);'></div>"
                cell_html = sep.join(players)
            else:
                cell_html = ""
            html.append(f"<td style='background:#FFFFFF;color:#1a1a1a;padding:12px;border-right:2px solid #e0e0e0;border-top:2px solid #e0e0e0;vertical-align:top;'>{cell_html}</td>")
        html.append("</tr>")

    html.append("</table>")
    return "".join(html)


# ============ PLAYER PERFORMANCE PREDICTION ============


def predict_player_trajectory(
    player_name: str,
    position: str,
    current_age: float,
    current_rating: float,
    historical_ratings: list,
    all_players_df: pd.DataFrame,
    current_season: int = CURRENT_SEASON,
    projection_years: int = 5,
    confidence_band: float = 0.15,
) -> pd.DataFrame:
    """
    Predict player performance trajectory for next N years based on:
    1. Historical rating trend for this player
    2. Position-based age-performance curve from all players
    3. Current rating percentile
    
    Returns DataFrame with Year, Predicted_Rating, Upper_Band, Lower_Band
    """
    
    # Ensure current_age is numeric
    current_age = float(current_age) if pd.notna(current_age) else 25.0
    current_rating = float(current_rating) if pd.notna(current_rating) else 50.0
    
    # Step 1: Build age-performance curve for this position
    # Get all historical data for this position
    if position and isinstance(position, str):
        # Normalize position to match depth chart logic
        normalized_pos = map_position_to_depth(position)
        position_players = all_players_df[
            all_players_df["Position"].apply(lambda p: map_position_to_depth(p) if pd.notna(p) else "") == normalized_pos
        ].copy()
    else:
        # Fallback: use all players
        position_players = all_players_df.copy()
    
    if position_players.empty:
        position_players = all_players_df.copy()
    
    # Ensure Age and RatingPoints_Avg are numeric
    position_players["Age"] = pd.to_numeric(position_players["Age"], errors="coerce")
    position_players["RatingPoints_Avg"] = pd.to_numeric(
        position_players["RatingPoints_Avg"], errors="coerce"
    )
    position_players = position_players.dropna(subset=["Age", "RatingPoints_Avg"])
    
    if position_players.empty:
        # No data available, return flat line at current rating
        years = list(range(current_season, current_season + projection_years + 1))
        data = {
            "Year": years,
            "Predicted_Rating": [current_rating] * len(years),
            "Upper_Band": [current_rating * (1 + confidence_band)] * len(years),
            "Lower_Band": [current_rating * (1 - confidence_band)] * len(years),
        }
        return pd.DataFrame(data)
    
    # Step 2: Calculate position-age trend using polynomial fit (degree 2)
    # Group by age and get median rating
    age_stats = (
        position_players.groupby(pd.cut(position_players["Age"], bins=20))
        .agg({"RatingPoints_Avg": ["median", "count"]})
        .reset_index()
    )
    age_stats.columns = ["Age_Bin", "Median_Rating", "Count"]
    
    # Extract midpoint of age bins
    age_stats["Age"] = age_stats["Age_Bin"].apply(lambda x: x.mid if pd.notna(x) else None)
    age_stats = age_stats.dropna(subset=["Age", "Median_Rating"])
    age_stats = age_stats[age_stats["Count"] >= 3]  # Only use bins with 3+ players
    
    if len(age_stats) < 2:
        # Not enough data for curve fitting, use flat prediction
        years = list(range(current_season, current_season + projection_years + 1))
        data = {
            "Year": years,
            "Predicted_Rating": [current_rating] * len(years),
            "Upper_Band": [current_rating * (1 + confidence_band)] * len(years),
            "Lower_Band": [current_rating * (1 - confidence_band)] * len(years),
        }
        return pd.DataFrame(data)
    
    # Fit polynomial curve (degree 2)
    try:
        import numpy as np
        coeffs = np.polyfit(age_stats["Age"], age_stats["Median_Rating"], 2)
        poly = np.poly1d(coeffs)
        
        # Step 3: Calculate trajectory adjustment
        # If player has historical data, calculate trend
        if len(historical_ratings) >= 2:
            # Simple linear trend over last few seasons
            trend = (historical_ratings[-1] - historical_ratings[0]) / (len(historical_ratings) - 1)
        else:
            trend = 0
        
        # Define universal peak age and performance shape for each position
        # Players follow a similar curve, just starting at different points
        peak_age_map = {
            "Midfielder": 28,
            "Wing": 27,
            "Ruck": 29,
            "Key Forward": 29,
            "Gen. Forward": 28,
            "Mid-Forward": 28,
            "Key Defender": 29,
            "Gen. Defender": 28,
        }
        normalized_pos = map_position_to_depth(position) if position else "Midfielder"
        peak_age = peak_age_map.get(normalized_pos, 28)
        
        # Step 4: Calculate trajectory using universal curve shape
        years = []
        predictions = []
        upper_bands = []
        lower_bands = []
        
        for year_offset in range(projection_years + 1):
            future_age = current_age + year_offset
            future_year = current_season + year_offset
            
            # For year 0 (current), use actual rating
            if year_offset == 0:
                predicted_rating = current_rating
            else:
                # Universal performance curve shape based on age relative to peak
                # This creates a realistic rise → peak → decline pattern for all players
                
                if future_age < peak_age:
                    # Pre-peak: gradual rise toward peak
                    # Distance to peak: how many years until peak
                    years_to_peak = peak_age - future_age
                    max_years_to_peak = peak_age - 20  # Assume players start rising around age 20
                    
                    # Calculate rise factor (0 at age 20, 1 at peak age)
                    # Using a smooth curve that accelerates initially then slows
                    progress_to_peak = (peak_age - future_age) / max_years_to_peak
                    progress_to_peak = max(0, min(progress_to_peak, 1))  # Clamp between 0-1
                    
                    # S-curve for smoother rise: starts slow, accelerates, slows near peak
                    rise_multiplier = 1.0 + (0.025 * (max_years_to_peak - years_to_peak))
                    
                    predicted_rating = current_rating * rise_multiplier
                
                elif future_age == peak_age:
                    # At peak: maintain current trajectory slightly boosted
                    predicted_rating = current_rating * 1.02
                
                else:
                    # Post-peak: gradual decline
                    years_past_peak = future_age - peak_age
                    
                    # Decline accelerates over time
                    # Year 1 past peak: -2%
                    # Year 2 past peak: -4.5%
                    # Year 3 past peak: -7.2%
                    # etc.
                    decline_multiplier = 1.0 - (0.02 * years_past_peak) - (0.005 * (years_past_peak ** 2))
                    decline_multiplier = max(decline_multiplier, 0.65)  # Floor at 65% of peak
                    
                    predicted_rating = current_rating * decline_multiplier
            
            # Ensure prediction stays reasonable (> 0)
            predicted_rating = max(predicted_rating, 5.0)
            
            # Calculate confidence bands that widen over time
            # Base confidence band increases with projection distance
            dynamic_confidence = confidence_band * (1 + 0.05 * year_offset)  # +5% uncertainty per year
            # Older players have higher uncertainty
            if future_age > 30:
                dynamic_confidence *= 1.2
            
            upper = predicted_rating * (1 + dynamic_confidence)
            lower = predicted_rating * (1 - dynamic_confidence)
            
            years.append(future_year)
            predictions.append(predicted_rating)
            upper_bands.append(upper)
            lower_bands.append(lower)
        
        data = {
            "Year": years,
            "Predicted_Rating": predictions,
            "Upper_Band": upper_bands,
            "Lower_Band": lower_bands,
        }
        return pd.DataFrame(data)
    
    except Exception as e:
        # Fallback if fitting fails
        years = list(range(current_season, current_season + projection_years + 1))
        data = {
            "Year": years,
            "Predicted_Rating": [current_rating] * len(years),
            "Upper_Band": [current_rating * (1 + confidence_band)] * len(years),
            "Lower_Band": [current_rating * (1 - confidence_band)] * len(years),
        }
        return pd.DataFrame(data)
    


# ---------------- PAGE NAV ----------------

# Define page groups for organized navigation
PAGE_GROUPS = {
    "Home": ["Home"],
    "Team": ["Overview", "Team Breakdown", "Team Compare", "Game Day Playground", "Game Model Scorecard"],
    "Player": ["Player Profile", "Player Traits", "IDP", "Club List", "Custom Player Comparison"],
    "List Management": ["Depth Chart", "Team Age Breakdown", "List Ladder", "Team List Summary", "Best 23", "List Breakdown - Traits", "Contract Status"],
}

# Flat list of all pages for compatibility
PAGES = []
for group_pages in PAGE_GROUPS.values():
    PAGES.extend(group_pages)

# Initialize session state for page navigation
if "selected_page" not in st.session_state:
    st.session_state.selected_page = "Home"
if "page_override" not in st.session_state:
    st.session_state.page_override = False

def render_grouped_navigation():
    """Render grouped sidebar navigation with styled sections."""
    selected = st.session_state.selected_page
    
    # CSS to make the logo sticky at top of sidebar with proper masking
    st.markdown("""
    <style>
    /* Fixed logo container at top of sidebar - solid background to hide scrolling content */
    .fixed-logo-container {
        position: fixed;
        top: 0;
        left: 0;
        width: 300px;
        z-index: 9999;
        background: rgb(14, 17, 23);
        padding: 70px 15px 15px 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
    }
    .fixed-logo-container img {
        width: 100%;
        max-width: 250px;
        display: block;
        margin: 0 auto;
    }
    .fixed-logo-container hr {
        margin: 12px 0 0 0;
        border: none;
        border-top: 1px solid rgba(255,255,255,0.2);
    }
    /* Add padding to sidebar content to account for fixed logo */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        padding-top: 200px !important;
    }
    /* Ensure sidebar scrolls properly and content is clipped */
    [data-testid="stSidebar"] > div:first-child {
        overflow-y: auto;
        padding-top: 0;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Future Edge Logo - fixed at top of sidebar using HTML
    logo_path = os.path.join(os.path.dirname(__file__), "team_logos", "Logo Transparent.png")
    if os.path.exists(logo_path):
        import base64
        with open(logo_path, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode()
        st.sidebar.markdown(f"""
        <div class="fixed-logo-container">
            <img src="data:image/png;base64,{logo_base64}" alt="FutureEdge Logo">
            <hr>
        </div>
        """, unsafe_allow_html=True)
    
    # Custom CSS for navigation groups
    st.sidebar.markdown("""
    <style>
    .nav-group-header {
        font-size: 0.75em;
        font-weight: 700;
        color: rgba(255,255,255,0.5);
        text-transform: uppercase;
        letter-spacing: 0.1em;
        padding: 12px 0 6px 8px;
        margin-top: 8px;
        border-top: 1px solid rgba(255,255,255,0.1);
    }
    .nav-group-header:first-child {
        border-top: none;
        margin-top: 0;
    }
    </style>
    """, unsafe_allow_html=True)
    
    new_page = selected
    
    # --- Player Search (at top of sidebar, after logo) ---
    st.sidebar.markdown("🔍 **Player Search**")
    
    @st.cache_data(show_spinner=False)
    def get_all_players_for_search(season: int):
        """Get all players for search functionality."""
        try:
            players = load_players(season)
            if players.empty:
                return []
            player_list = []
            for _, row in players.iterrows():
                player = row.get("Player", "")
                team = row.get("Team", "")
                if player and team:
                    player_list.append({"player": player, "team": team, "display": f"{player} ({team})"})
            return player_list
        except:
            return []

    all_players_search = get_all_players_for_search(CURRENT_SEASON)
    
    search_query = st.sidebar.text_input("Search for a player...", key="global_player_search", placeholder="Type player name...")
    
    if search_query and len(search_query) >= 2:
        matches = [p for p in all_players_search if search_query.lower() in p["player"].lower()][:5]
        if matches:
            for match in matches:
                col1, col2 = st.sidebar.columns([4, 1])
                with col1:
                    if st.button(f"🏃 {match['player']}", key=f"search_{match['player']}_{match['team']}", use_container_width=True):
                        st.session_state.selected_player_search = match['player']
                        st.session_state.selected_team_search = match['team']
                        st.session_state.default_team = match['team']
                        st.session_state.selected_page = "Player Profile"
                        st.session_state.page_override = True
                        add_to_recent_views("player", match['player'], match['team'], "Player Profile")
                        st.rerun()
                with col2:
                    player_key = f"{match['player']}|{match['team']}"
                    is_fav = player_key in st.session_state.favorite_players
                    star_label = "⭐" if is_fav else "☆"
                    if st.button(star_label, key=f"fav_search_{match['player']}_{match['team']}"):
                        toggle_favorite_player(match['player'], match['team'])
                        st.rerun()
        else:
            st.sidebar.caption("No players found")
    
    st.sidebar.markdown("---")
    
    # Render Home button after Player Search
    home_selected = "Home" == selected
    if st.sidebar.button(
        "🏠 Home",
        key="nav_Home",
        use_container_width=True,
        type="primary" if home_selected else "secondary"
    ):
        new_page = "Home"
        st.session_state.selected_page = "Home"
        st.rerun()
    
    # Render remaining groups (skip Home since we already rendered it)
    for group_name, pages in PAGE_GROUPS.items():
        if group_name == "Home":
            continue  # Already rendered above
            
        st.sidebar.markdown(f"<div class='nav-group-header'>📁 {group_name}</div>", unsafe_allow_html=True)
        
        for page_name in pages:
            icons = {
                "Home": "🏠",
                "Overview": "📊",
                "Team Breakdown": "📈",
                "Team Compare": "⚖️",
                "Club List": "📋",
                "Game Day Playground": "🎮",
                "Game Model Scorecard": "🎯",
                "Player Profile": "👤",
                "Player Traits": "🎯",
                "IDP": "🏈",
                "Custom Player Comparison": "🧬",
                "Depth Chart": "📋",
                "Team Age Breakdown": "📅",
                "List Ladder": "🪜",
                "Team List Summary": "📝",
                "Best 23": "🏆",
                "List Breakdown - Traits": "📊",
                "Contract Status": "📝",
            }
            icon = icons.get(page_name, "📄")
            
            is_selected = page_name == selected
            button_type = "primary" if is_selected else "secondary"
            
            if st.sidebar.button(
                f"{icon} {page_name}",
                key=f"nav_{page_name}",
                use_container_width=True,
                type=button_type
            ):
                new_page = page_name
                st.session_state.selected_page = page_name
                st.rerun()
    
    return new_page

# Check if there's a page override from a button click
if st.session_state.page_override:
    page = st.session_state.selected_page
    render_grouped_navigation()
    # Clear the override flag for next rerun
    st.session_state.page_override = False
else:
    # Normal sidebar navigation
    page = render_grouped_navigation()
    # Update session state with the current page selection
    st.session_state.selected_page = page

# ================= SIDEBAR ENHANCEMENTS =================

# --- Favorites Section ---
if st.session_state.favorite_teams or st.session_state.favorite_players:
    st.sidebar.markdown("---")
    st.sidebar.markdown("⭐ **Favorites**")
    
    # Favorite Teams
    if st.session_state.favorite_teams:
        for team in sorted(st.session_state.favorite_teams):
            col1, col2 = st.sidebar.columns([4, 1])
            with col1:
                if st.button(f"🏟️ {team}", key=f"fav_team_{team}", use_container_width=True):
                    st.session_state.default_team = team
                    st.session_state.selected_page = "Team Breakdown"
                    st.session_state.page_override = True
                    add_to_recent_views("team", team, team, "Team Breakdown")
                    st.rerun()
            with col2:
                if st.button("✕", key=f"unfav_team_{team}"):
                    toggle_favorite_team(team)
                    st.rerun()
    
    # Favorite Players
    if st.session_state.favorite_players:
        for player_key in sorted(st.session_state.favorite_players):
            parts = player_key.split("|")
            if len(parts) == 2:
                player, team = parts
                col1, col2 = st.sidebar.columns([4, 1])
                with col1:
                    if st.button(f"🏃 {player}", key=f"fav_player_{player_key}", use_container_width=True):
                        st.session_state.selected_player_search = player
                        st.session_state.selected_team_search = team
                        st.session_state.default_team = team
                        st.session_state.selected_page = "Player Profile"
                        st.session_state.page_override = True
                        add_to_recent_views("player", player, team, "Player Profile")
                        st.rerun()
                with col2:
                    if st.button("✕", key=f"unfav_player_{player_key}"):
                        toggle_favorite_player(player, team)
                        st.rerun()

# --- Recent Activity Section ---
if st.session_state.recent_views:
    st.sidebar.markdown("---")
    st.sidebar.markdown("🕐 **Recent**")
    for item in st.session_state.recent_views[:5]:
        icon = "🏟️" if item["type"] == "team" else "🏃"
        label = item["name"]
        if st.sidebar.button(f"{icon} {label}", key=f"recent_{item['type']}_{item['name']}_{item.get('team', '')}", use_container_width=True):
            if item["type"] == "team":
                st.session_state.default_team = item["name"]
                st.session_state.selected_page = item.get("page", "Team Breakdown")
            else:
                st.session_state.selected_player_search = item["name"]
                st.session_state.selected_team_search = item.get("team", "")
                st.session_state.default_team = item.get("team", "")
                st.session_state.selected_page = item.get("page", "Player Profile")
            st.session_state.page_override = True
            st.rerun()

# --- Comparison History ---
if st.session_state.comparison_history:
    st.sidebar.markdown("---")
    st.sidebar.markdown("🔄 **Recent Comparisons**")
    for comp in st.session_state.comparison_history[:3]:
        label = f"{comp['team1']} vs {comp['team2']}"
        page_target = "Team Compare" if comp["type"] == "team" else "Best 23"
        if st.sidebar.button(f"⚔️ {label}", key=f"comp_{comp['team1']}_{comp['team2']}", use_container_width=True):
            st.session_state.default_team = comp['team1']
            st.session_state.selected_page = page_target
            st.session_state.page_override = True
            st.rerun()


# ================= CUSTOM STYLING =================

# Add CSS to give all team logos a white glow/shadow effect so dark logos pop
st.markdown(
    """
    <style>
    /* Apply drop-shadow to all images */
    div[data-testid="stImage"] img {
        filter: drop-shadow(0 0 4px rgba(255, 255, 255, 0.4));
    }
    
    /* Remove shadow from the first image (FutureEdge logo) on home page */
    div[data-testid="column"]:nth-child(2) > div:first-child div[data-testid="stImage"] img {
        filter: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ================= HOME =================

if page == "Home":
    # Reduce top padding on home page
    st.markdown("<style>.block-container { padding-top: 1rem !important; }</style>", unsafe_allow_html=True)
    
    # Display centered logo using HTML/CSS (st.image doesn't center properly)
    logo_path = "team_logos/Logo Transparent.png"
    
    if os.path.exists(logo_path):
        import base64
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        st.markdown(f"""
            <div style='display: flex; justify-content: center; margin-bottom: 0px;'>
                <img src='data:image/png;base64,{logo_b64}' style='width: 320px; filter: drop-shadow(0 0 20px rgba(255,255,255,0.4)) drop-shadow(0 4px 12px rgba(0,0,0,0.5));'>
            </div>
        """, unsafe_allow_html=True)
    else:
        # Fallback if logo not found - show placeholder
        st.markdown(
            "<div style='text-align: center; font-size: 100px; color: #999;'>🏉</div>",
            unsafe_allow_html=True
        )
    
    # Heading - reduced margin to bring closer to logo
    st.markdown(
        """
        <h1 style='text-align: center; font-size: 2.5em; margin-top: 5px; margin-bottom: 5px;'>
            AFL Dashboards
        </h1>
        """,
        unsafe_allow_html=True
    )
    
    # Team selection instruction - reduced margins
    st.markdown(
        """
        <h3 style='text-align: center; color: #FFFFFF; margin-top: 10px; margin-bottom: 15px;'>
            Select Your Team
        </h3>
        """,
        unsafe_allow_html=True
    )
    
    # List of all 18 AFL teams in alphabetical order
    all_teams = [
        "Adelaide", "Brisbane", "Carlton", "Collingwood", "Essendon", 
        "Fremantle", "Geelong", "Gold Coast", "GWS Giants",
        "Hawthorn", "Melbourne", "North Melbourne", "Port Adelaide", 
        "Richmond", "St Kilda", "Sydney", "West Coast", "Western Bulldogs"
    ]
    
    # First row of 9 teams
    row1_cols = st.columns(9)
    for idx, team in enumerate(all_teams[:9]):
        with row1_cols[idx]:
            team_code = TEAM_CODE_MAP.get(team, team.lower().replace(" ", ""))
            team_logo_path = f"{LOGO_FOLDER}/{team_code}.png"
            
            if os.path.exists(team_logo_path):
                try:
                    # Display logo centered
                    img = Image.open(team_logo_path)
                    # Resize image to fixed dimensions for consistency
                    img_resized = img.resize((120, 120), Image.Resampling.LANCZOS)
                    # Center the image using columns
                    _, img_col, _ = st.columns([0.1, 0.8, 0.1])
                    with img_col:
                        st.image(img_resized, use_container_width=True)
                    
                    # Add small spacer before button
                    st.markdown('<div style="height: 5px;"></div>', unsafe_allow_html=True)
                    # Create clickable button
                    if st.button("Select", key=f"home_team_{team}_{idx}", use_container_width=True, help=f"Select {team}"):
                        # Set default team in session state
                        st.session_state.default_team = team
                        st.session_state.selected_page = "Team Breakdown"
                        st.session_state.page_override = True
                        st.rerun()
                except Exception:
                    st.markdown(f"<div style='text-align: center; font-size: 0.7em;'>{team}</div>", unsafe_allow_html=True)
    
    # Second row of 9 teams
    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
    row2_cols = st.columns(9)
    for idx, team in enumerate(all_teams[9:]):
        with row2_cols[idx]:
            team_code = TEAM_CODE_MAP.get(team, team.lower().replace(" ", ""))
            team_logo_path = f"{LOGO_FOLDER}/{team_code}.png"
            
            if os.path.exists(team_logo_path):
                try:
                    # Display logo centered
                    img = Image.open(team_logo_path)
                    # Resize image to fixed dimensions for consistency
                    img_resized = img.resize((120, 120), Image.Resampling.LANCZOS)
                    # Center the image using columns
                    _, img_col, _ = st.columns([0.1, 0.8, 0.1])
                    with img_col:
                        st.image(img_resized, use_container_width=True)
                    
                    # Add small spacer before button
                    st.markdown('<div style="height: 5px;"></div>', unsafe_allow_html=True)
                    # Create clickable button
                    if st.button("Select", key=f"home_team_{team}_{idx+9}", use_container_width=True, help=f"Select {team}"):
                        # Set default team in session state
                        st.session_state.default_team = team
                        st.session_state.selected_page = "Team Breakdown"
                        st.session_state.page_override = True
                        st.rerun()
                except Exception:
                    st.markdown(f"<div style='text-align: center; font-size: 0.7em;'>{team}</div>", unsafe_allow_html=True)

import hashlib
import random
import pandas as pd
import streamlit as st

def _stable_seed(*parts) -> int:
    s = "||".join([str(p) for p in parts if p is not None])
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16)

def _mock_matchup_model(team_a: str, team_b: str):
    """
    Returns consistent mock ratings + component stats based on (team_a, team_b).
    """
    rng = random.Random(_stable_seed(team_a, team_b))

    # 4 game-type dimensions (0..100). >50 => right side, <=50 => left side
    game_type = {
        "Chaos vs Control": rng.randint(25, 75),
        "Stoppage vs Transition": rng.randint(25, 75),
        "Front Half vs Back Half": rng.randint(25, 75),
        "Shoot Out vs Slog": rng.randint(25, 75),
    }

    # 5 phases (0..100)
    phases = {
        "Ball Winning": rng.randint(45, 85),
        "Ball Use": rng.randint(40, 85),
        "Scoring": rng.randint(35, 85),
        "Defence": rng.randint(40, 85),
        "Pressure": rng.randint(45, 90),
    }

    # Component stats per phase (mock but shaped like football stats)
    stats = {
        "Ball Winning": [
            ("Contested Possessions", rng.randint(110, 170), "higher better"),
            ("Ground Ball Gets", rng.randint(45, 75), "higher better"),
            ("Clearances", rng.randint(30, 52), "higher better"),
            ("First Possession (stoppage) %", rng.randint(42, 62), "higher better"),
        ],
        "Ball Use": [
            ("Disposal Efficiency %", rng.randint(66, 79), "higher better"),
            ("Turnovers", rng.randint(45, 78), "lower better"),
            ("Metres Gained", rng.randint(4200, 6200), "higher better"),
            ("Inside 50 Efficiency %", rng.randint(41, 56), "higher better"),
        ],
        "Scoring": [
            ("Shots", rng.randint(22, 33), "higher better"),
            ("Shots per I50", round(rng.uniform(0.35, 0.55), 2), "higher better"),
            ("Goal Accuracy %", rng.randint(45, 62), "higher better"),
            ("Scores per 10 Entries", rng.randint(8, 13), "higher better"),
        ],
        "Defence": [
            ("Opposition I50s", rng.randint(45, 62), "lower better"),
            ("Intercept Marks", rng.randint(12, 20), "higher better"),
            ("Defensive One-on-one Win %", rng.randint(46, 63), "higher better"),
            ("Scores Conceded", rng.randint(70, 98), "lower better"),
        ],
        "Pressure": [
            ("Tackles", rng.randint(55, 82), "higher better"),
            ("Pressure Acts", rng.randint(170, 240), "higher better"),
            ("Forced Turnovers", rng.randint(18, 30), "higher better"),
            ("Time in Forward Half %", rng.randint(45, 58), "higher better"),
        ],
    }

    return game_type, phases, stats

# ---------------------------------------
# GLOBAL: TEAMS LIST (available to all pages)
# ---------------------------------------
try:
    _summary = load_player_summary()
    _seasons = get_player_seasons()
    _season = 2025 if 2025 in _seasons else (_seasons[0] if _seasons else None)

    if _season is not None:
        _ratings = load_players(_season)

        # Reuse your find_col helper if you have it; otherwise assume columns exist
        s_name = find_col(_summary, ["player"]) or find_col(_summary, ["name"])
        s_pos  = find_col(_summary, ["position"])
        s_num  = find_col(_summary, ["jumper"]) or find_col(_summary, ["guernsey"])

        r_name = find_col(_ratings, ["player"]) or find_col(_ratings, ["name"])
        r_val  = find_col(_ratings, ["rating"])

        if all([s_name, s_pos, r_name, r_val]) and "Team" in _summary.columns and "Team" in _ratings.columns:
            _summary = _summary.rename(columns={s_name: "Player", s_pos: "Position"})
            _ratings = _ratings.rename(columns={r_name: "Player", r_val: "Rating"})
            _summary["Jumper"] = _summary[s_num] if s_num else ""

            def _make_key(df):
                return (
                    df["Team"].astype(str).str.lower().str.strip()
                    + "||"
                    + df["Player"].astype(str).str.lower().str.strip()
                )

            _summary["__k"] = _make_key(_summary)
            _ratings["__k"] = _make_key(_ratings)

            _merged_all = _summary.merge(_ratings[["__k", "Rating"]], on="__k", how="left")
            _merged_all["Rating"] = pd.to_numeric(_merged_all["Rating"], errors="coerce")
            _merged_all = _merged_all.dropna(subset=["Rating"])

            teams = sorted(_merged_all["Team"].dropna().unique())
        else:
            teams = []
    else:
        teams = []
except Exception:
    teams = []



def _logo_img(team_name: str, width=220):
    """
    Uses your existing get_team_logo_path(team) if present.
    Falls back to a text badge if missing.
    """
    try:
        fn = globals().get("get_team_logo_path", None)
        if callable(fn):
            p = fn(team_name)
            if isinstance(p, str) and p:
                st.markdown(f"<style>.logo-glow img {{ filter: drop-shadow(0 0 20px rgba(255,255,255,0.4)) drop-shadow(0 4px 12px rgba(0,0,0,0.5)); }}</style><div class='logo-glow'>", unsafe_allow_html=True)
                st.image(p, width=width)
                st.markdown("</div>", unsafe_allow_html=True)
                return
    except Exception:
        pass

    st.markdown(
        f"""
        <div style="width:{width}px;height:{int(width*0.55)}px;
             border-radius:18px;background:rgba(255,255,255,0.06);
             display:flex;align-items:center;justify-content:center;
             font-weight:900;">
          {team_name}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _pill(label: str, active: bool):
    bg = "rgba(0,180,90,0.55)" if active else "rgba(255,255,255,0.08)"
    bd = "1px solid rgba(255,255,255,0.08)" if active else "1px solid rgba(255,255,255,0.06)"
    return f"""
    <div style="
        padding:10px 14px;
        border-radius:999px;
        background:{bg};
        border:{bd};
        font-weight:900;
        text-align:center;
        min-width:180px;
        display:inline-flex;
        justify-content:center;
        align-items:center;
        ">
      {label}
    </div>
    """

def _phase_card(title: str, rating: int, stats_rows):
    # rating bar
    bar = f"""
    <div style="background:rgba(255,255,255,0.06);border-radius:999px;height:14px;overflow:hidden;">
      <div style="height:14px;width:{max(0,min(100,int(rating)))}%;
           background:rgba(0,180,90,0.60);"></div>
    </div>
    """

    st.markdown(
        f"""
        <div style="padding:16px 16px 14px 16px;border-radius:18px;
             background:rgba(255,255,255,0.03);
             border:1px solid rgba(255,255,255,0.06);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
            <div style="font-size:18px;font-weight:900;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">{title}</div>
            <div style="font-size:18px;font-weight:900;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">{rating}/100</div>
          </div>
          <div style="margin-top:10px;">{bar}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander(f"Show inputs for {title}", expanded=False):
        df = pd.DataFrame(stats_rows, columns=["Stat", "Value", "Direction"])
        st.dataframe(df, width="stretch", hide_index=True)


def render_game_day_playground(teams: list[str]):
    st.markdown("""<div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);padding: 40px 20px;border-radius: 16px;box-shadow: 0 8px 24px rgba(0,0,0,0.4);margin-bottom: 32px;text-align: center;"><h1 style="color: #FFFFFF;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-weight: 900;font-size: 48px;margin: 0 0 12px 0;letter-spacing: 0.02em;text-shadow: 2px 2px 8px rgba(0,0,0,0.5);">🎮 Game Day Playground</h1><p style="color: rgba(255,255,255,0.8);font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-size: 16px;margin: 0;font-weight: 600;letter-spacing: 0.03em;">Select two teams + time window, explore game modes + zone health (all mock for now). Next: wire in real data.</p></div>""", unsafe_allow_html=True)

    # -------------------------------------------------
    # SAFETY: build teams if global list is empty
    # -------------------------------------------------
    if not teams:
        try:
            df = load_player_summary()
            if "Team" in df.columns:
                teams = sorted(df["Team"].dropna().unique())
        except Exception as e:
            st.error("Unable to load teams for Game Day Playground")
            st.exception(e)
            st.stop()

    if not teams:
        st.error("Teams list is empty — check load_player_summary() and Team column.")
        st.stop()

    # ===== Broadcast Styling Pack (drop-in) =====
    st.markdown("""
    <style>
    /* Page spacing + broadcast background */
    section.main > div { padding-top: 0.5rem; }
    .gdp-card{
    padding:20px;
    border-radius:16px;
    background: linear-gradient(145deg, rgba(20,20,30,0.95), rgba(30,30,45,0.95));
    border:1px solid rgba(255,255,255,0.15);
    box-shadow:0 8px 24px rgba(0,0,0,0.5);
    backdrop-filter: blur(8px);
    transition: all 0.3s ease;
    }
    .gdp-card:hover{
    box-shadow:0 12px 32px rgba(0,0,0,0.6);
    transform: translateY(-2px);
    }

    .gdp-title{ font-size:22px; font-weight:900; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; letter-spacing:0.03em; }
    .gdp-sub{ opacity:0.8; font-size:13px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-weight:600; }
    .gdp-pill{
    padding:12px 20px;
    border-radius:20px;
    font-weight:900;
    font-size:14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    letter-spacing:0.05em;
    text-align:center;
    min-width:190px;
    background:rgba(255,255,255,0.08);
    border:1px solid rgba(255,255,255,0.12);
    box-shadow:0 4px 12px rgba(0,0,0,0.4);
    transition: all 0.3s ease;
    }
    .gdp-pill:hover{
    transform: translateY(-2px);
    box-shadow:0 6px 16px rgba(0,0,0,0.5);
    }
    .gdp-pill-active{
    box-shadow:0 8px 20px rgba(0,0,0,0.5);
    border:1px solid rgba(255,255,255,0.2);
    }
    .gdp-bar-bg{
    height:10px;
    border-radius:8px;
    background:rgba(255,255,255,0.15);
    overflow:hidden;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);
    }
    .gdp-bar-fill{
    height:10px;
    border-radius:8px;
    transition: width 0.4s ease;
    box-shadow:0 0 16px currentColor;
    }
    .gdp-dot{ font-weight:900; font-size:18px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
    </style>
    """, unsafe_allow_html=True)

    def _gdp_colour(score: float) -> str:
        """Get color for GDP score - 5 tier system (0-100 scale)."""
        # 5-tier: Elite (80+), Good (60-80), Average (40-60), Below Avg (20-40), Poor (<20)
        if score >= 80: return "#008000"   # Elite - Dark Green
        if score >= 60: return "#90EE90"   # Good - Light Green
        if score >= 40: return "#FFD700"   # Average - Gold
        if score >= 20: return "#FFA500"   # Below Average - Orange
        return "#FF0000"                    # Poor - Red

    def _gdp_zone_tile(label: str, rating: int, subtitle: str = "") -> str:
        col = _gdp_colour(rating)
        sub = f"<div class='gdp-sub' style='margin-top:4px;'>{subtitle}</div>" if subtitle else ""
        return (
            "<div class='gdp-card' style='padding:20px 24px; position:relative; overflow:hidden;'>"
            f"<div style='position:absolute;left:0;top:0;bottom:0;width:6px;background:{col};"
            f"box-shadow:0 0 24px {col};'></div>"
            "<div style='display:flex;justify-content:space-between;align-items:baseline;gap:12px;'>"
                "<div style='padding-left:12px;'>"
                f"<div class='gdp-title' style='font-size:17px;color:rgba(255,255,255,0.95);font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;'>{label}</div>"
                f"{sub}"
                "</div>"
                f"<div class='gdp-title' style='font-size:20px;color:{col};font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;'>{rating}</div>"
            "</div>"
            "<div style='margin-top:14px;' class='gdp-bar-bg'>"
                f"<div class='gdp-bar-fill' style='width:{rating}%;background:{col};box-shadow:0 0 20px {col};'></div>"
            "</div>"
            "</div>"
        )



    def _game_mode_pill(label: str, opacity: float, on: bool):
        # same green, but "off" is basically dark/grey
        if not on:
            return f"""
            <div style="
                padding:16px 24px;border-radius:20px;
                font-weight:900;font-size:14px;text-align:center;
                background:rgba(255,255,255,0.06);
                border:1px solid rgba(255,255,255,0.08);
                color:rgba(255,255,255,0.6);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                letter-spacing:0.05em;
                box-shadow:0 4px 12px rgba(0,0,0,0.3);
            ">{label}</div>
            """
        return f"""
        <div style="
            padding:16px 24px;border-radius:20px;
            font-weight:900;font-size:14px;text-align:center;
            background:rgba(63,185,132,{opacity});
            border:1px solid rgba(63,185,132,{min(1.0, opacity + 0.2)});
            color:#ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            letter-spacing:0.05em;
            box-shadow:0 0 20px rgba(63,185,132,{min(0.7, opacity)}), 0 4px 12px rgba(0,0,0,0.4);
        ">{label}</div>
        """



    def _gdp_phase_card(title: str, rating: int, stats_rows):
        col = _gdp_colour(rating)
        st.markdown(
            f"""
            <div class="gdp-card" style="padding:20px 24px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div class="gdp-title" style="font-size:18px;">{title}</div>
                <div class="gdp-title" style="color:{col};font-size:20px;">{rating}/100</div>
            </div>
            <div style="margin-top:16px;" class="gdp-bar-bg">
                <div class="gdp-bar-fill" style="width:{rating}%;background:{col};box-shadow:0 0 20px {col};"></div>
            </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("Show contributing stats", expanded=False):
            # quick “good/bad” dot flag (mock-friendly)
            rows = []
            for stat, val, direction in stats_rows:
                try:
                    v = float(val)
                except Exception:
                    v = 60.0
                dot = _gdp_colour(v if direction == "higher better" else (100 - min(v, 100)))
                rows.append({
                    "Stat": stat,
                    "Value": val,
                    "Flag": f"<span class='gdp-dot' style='color:{dot};'>●</span>"
                })
            st.markdown(pd.DataFrame(rows).to_html(escape=False, index=False), unsafe_allow_html=True)
    # ===== End pack =====


    # Keep fonts consistent with Streamlit theme
    st.markdown(
            """
            <style>
            .gdp-muted{opacity:0.7;font-size:12px;font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;}
            .gdp-h2{font-size:18px;font-weight:900;margin:0;font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;}
            </style>
            """,
            unsafe_allow_html=True,
        )

    # --- Team selection
    st.markdown("<div style='margin-top:24px;margin-bottom:24px;'></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2.2, 0.6, 2.2], vertical_alignment="center")
    with c1:
        gdp_default_idx = 0
        if "default_team" in st.session_state and st.session_state.default_team in teams:
            gdp_default_idx = teams.index(st.session_state.default_team)
        team_a = st.selectbox("Team A", teams, index=gdp_default_idx, key="gdp_team_a")
    with c2:
        st.markdown("<div style='text-align:center;font-weight:900;font-size:32px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.05em;text-shadow:2px 2px 6px rgba(0,0,0,0.4);'>VS</div>", unsafe_allow_html=True)
    with c3:
        team_b = st.selectbox("Team B", [t for t in teams if t != team_a], key="gdp_team_b")

    # --- Logo row: logo vs logo
    # --- Centered logo lock-up
    st.markdown("<div style='margin-top:16px;margin-bottom:32px;'></div>", unsafe_allow_html=True)
    c = st.columns([3, 2, 1, 2, 3])

    with c[1]:
        st.markdown("<div style='display:flex;justify-content:flex-end;filter:drop-shadow(0 8px 16px rgba(0,0,0,0.5));'>", unsafe_allow_html=True)
        _logo_img(team_a, width=260)
        st.markdown("</div>", unsafe_allow_html=True)

    with c[2]:
        st.markdown(
            "<div style='text-align:center;font-weight:900;font-size:28px;opacity:0.9;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.05em;text-shadow:2px 2px 6px rgba(0,0,0,0.4);'>VS</div>",
            unsafe_allow_html=True
        )

    with c[3]:
        st.markdown("<div style='display:flex;justify-content:flex-start;filter:drop-shadow(0 8px 16px rgba(0,0,0,0.5));'>", unsafe_allow_html=True)
        _logo_img(team_b, width=260)
        st.markdown("</div>", unsafe_allow_html=True)




    st.markdown("<div style='margin:32px 0;border-top:1px solid rgba(255,255,255,0.15);'></div>", unsafe_allow_html=True)

    # --- Time-slice filter (under logos)
    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;font-weight:900;font-size:18px;margin-bottom:16px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.05em;'>⏱️ Time Filter</div>", unsafe_allow_html=True)

    time_options = ["Q1", "Q2", "Q3", "Q4", "Last 10 min"]
    

    # --- Time filter (single widget, single key)
    time_filter = st.radio(
        "Time Filter",
        ["Q1", "Q2", "Q3", "Q4", "Last 10 min"],
        horizontal=True,
        key="gdp_time_filter",
        label_visibility="collapsed",
)



# use time_filter directly below




    game_type, phases, stats = _mock_matchup_model(team_a, team_b)

        # =====================================================
        # What type of game are we in?
        # =====================================================
    st.markdown("<div style='margin:40px 0 24px 0;'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;'>🎯 What type of game are we in?</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:24px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Green fill indicates how strongly the game is trending toward each mode. Full opacity = strong, light opacity = slight.</div>", unsafe_allow_html=True)

    dims = [
        ("Chaos", "Control", "Chaos vs Control"),
        ("Stoppage", "Transition", "Stoppage vs Transition"),
        ("Front Half", "Back Half", "Front Half vs Back Half"),
        ("Shoot Out", "Slog", "Shoot Out vs Slog"),
    ]

    for left, right, key in dims:
        v = int(game_type[key])  # 0–100

        # winner side (ONLY one)
        left_wins = v < 50
        right_wins = not left_wins

        # strength based on distance from 50
        dist = abs(v - 50)  # 0..50
        if dist >= 20:
            strength_opacity = 1.0     # strong
        elif dist >= 8:
            strength_opacity = 0.30    # slight
        else:
            strength_opacity = 0.18    # very slight / near neutral

        row = st.columns([2.4, 0.4, 2.4, 0.8])

        with row[0]:
            st.markdown(
                _game_mode_pill(left, strength_opacity, on=left_wins),
                unsafe_allow_html=True
            )
        with row[1]:
            st.markdown("<div style='text-align:center;opacity:0.5;font-weight:900;font-size:20px;'>↔</div>", unsafe_allow_html=True)
        with row[2]:
            st.markdown(
                _game_mode_pill(right, strength_opacity, on=right_wins),
                unsafe_allow_html=True
            )
        with row[3]:
            st.markdown(
                f"<div class='gdp-muted' style='text-align:right;font-weight:700;'>Index: <b>{v}</b></div>",
                unsafe_allow_html=True,
            )


    st.markdown("<div style='margin:40px 0;border-top:1px solid rgba(255,255,255,0.15);'></div>", unsafe_allow_html=True)

    # =====================================================
    # Momentum Meter
    # =====================================================
    st.markdown("<div style='text-align:center;font-weight:900;font-size:26px;margin-bottom:8px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;text-shadow:2px 2px 6px rgba(0,0,0,0.4);'>⚡ Momentum Meter</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.75);font-size:14px;margin-bottom:28px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Rolling last 10 minutes — aggregated across all 5 phases</div>", unsafe_allow_html=True)

    # Calculate momentum based on all 5 phases
    rng = random.Random(_stable_seed(team_a, team_b))
    
    team_a_scores = []
    team_b_scores = []
    
    for phase_name, phase_score in phases.items():
        if rng.random() > 0.5:
            team_a_scores.append(phase_score)
            team_b_scores.append(100 - phase_score + rng.randint(-10, 10))
        else:
            team_b_scores.append(phase_score)
            team_a_scores.append(100 - phase_score + rng.randint(-10, 10))
    
    team_a_momentum_raw = sum(team_a_scores) / len(team_a_scores)
    team_b_momentum_raw = sum(team_b_scores) / len(team_b_scores)
    
    total_momentum = team_a_momentum_raw + team_b_momentum_raw
    if total_momentum > 0:
        team_a_pct = (team_a_momentum_raw / total_momentum) * 100
    else:
        team_a_pct = 50
    
    team_b_pct = 100 - team_a_pct
    momentum_diff = abs(team_a_pct - 50)
    
    if momentum_diff >= 25:
        momentum_status = "DOMINANT"
        status_color = "#00FF41"
    elif momentum_diff >= 15:
        momentum_status = "STRONG"
        status_color = "#FFD700"
    elif momentum_diff >= 8:
        momentum_status = "BUILDING"
        status_color = "#FF6B35"
    else:
        momentum_status = "NEUTRAL"
        status_color = "#888888"
    
    # Build complete momentum meter as pure HTML
    phase_labels = ["Ball Win", "Ball Use", "Scoring", "Defence", "Pressure"]
    phase_indicators_html = ""
    
    for i, label in enumerate(phase_labels):
        if i < len(team_a_scores):
            p_a = team_a_scores[i]
            p_b = team_b_scores[i]
            phase_leader = "A" if p_a > p_b else "B"
            phase_color = "#FF6B35" if phase_leader == "A" else "#4A90E2"
            phase_strength = abs(p_a - p_b) / max(p_a + p_b, 1) * 100
            dot_opacity = 0.3 + (phase_strength / 100 * 0.7)
            
            phase_indicators_html += "<div style='display:flex;flex-direction:column;align-items:center;gap:6px;'>"
            phase_indicators_html += "<div style='width:12px;height:12px;border-radius:50%;background:" + phase_color + ";opacity:" + str(dot_opacity) + ";box-shadow:0 0 12px " + phase_color + ";'></div>"
            phase_indicators_html += "<div style='font-size:11px;font-weight:700;color:rgba(255,255,255,0.6);text-transform:uppercase;text-align:center;'>" + label + "</div>"
            phase_indicators_html += "</div>"
    
    # Build the complete HTML string using concatenation
    momentum_html = "<div style='background:linear-gradient(145deg, rgba(15,15,25,0.98), rgba(25,25,40,0.98));padding:32px 28px;border-radius:20px;border:2px solid rgba(255,255,255,0.12);box-shadow:0 12px 32px rgba(0,0,0,0.6);'>"
    
    momentum_html += "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;'>"
    momentum_html += "<div style='font-weight:900;font-size:20px;'>" + team_a + "</div>"
    momentum_html += "<div style='background:rgba(255,255,255,0.08);padding:8px 20px;border-radius:20px;font-weight:900;font-size:13px;text-transform:uppercase;letter-spacing:0.1em;color:" + status_color + ";text-align:center;'>" + momentum_status + "</div>"
    momentum_html += "<div style='font-weight:900;font-size:20px;'>" + team_b + "</div>"
    momentum_html += "</div>"
    
    momentum_html += "<div style='position:relative;height:48px;background:rgba(255,255,255,0.06);border-radius:24px;overflow:hidden;border:2px solid rgba(255,255,255,0.1);margin-bottom:20px;'>"
    momentum_html += "<div style='position:absolute;left:0;top:0;bottom:0;width:" + str(team_a_pct) + "%;background:linear-gradient(90deg, #FF6B35 0%, #F7931E 100%);'></div>"
    momentum_html += "<div style='position:absolute;right:0;top:0;bottom:0;width:" + str(team_b_pct) + "%;background:linear-gradient(270deg, #4A90E2 0%, #357ABD 100%);'></div>"
    momentum_html += "<div style='position:absolute;left:50%;top:0;bottom:0;width:3px;background:rgba(255,255,255,0.5);transform:translateX(-50%);'></div>"
    momentum_html += "<div style='position:absolute;left:12px;top:50%;transform:translateY(-50%);font-weight:900;font-size:18px;color:#FFFFFF;text-shadow:2px 2px 6px rgba(0,0,0,0.8);'>" + str(int(team_a_pct)) + "%</div>"
    momentum_html += "<div style='position:absolute;right:12px;top:50%;transform:translateY(-50%);font-weight:900;font-size:18px;color:#FFFFFF;text-shadow:2px 2px 6px rgba(0,0,0,0.8);'>" + str(int(team_b_pct)) + "%</div>"
    momentum_html += "</div>"
    
    momentum_html += "<div style='display:flex;justify-content:center;gap:16px;'>"
    momentum_html += phase_indicators_html
    momentum_html += "</div>"
    
    momentum_html += "</div>"
    
    st.markdown(momentum_html, unsafe_allow_html=True)

    st.markdown("<div style='margin:40px 0;border-top:1px solid rgba(255,255,255,0.15);'></div>", unsafe_allow_html=True)

    st.markdown("<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;'>🏟️ Ground health check</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:24px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Each zone shows an overall health score (0–100). Expand a zone to see which phases are driving it (mock).</div>", unsafe_allow_html=True)

    # Stable mock zone + phase ratings tied to matchup
    rng = random.Random(_stable_seed(team_a, team_b, "zones_v2"))

    zone_names = ["Defensive 50", "Defensive Mid", "Centre Bounce", "Attacking Mid", "Forward 50"]
    phase_names = ["Ball Winning", "Ball Use", "Scoring", "Defence", "Pressure"]

    # Build mock phase ratings per zone (these are what you’ll later compute from real data)
    zone_phase = {}
    for z in zone_names:
        zone_phase[z] = {p: rng.randint(40, 92) for p in phase_names}

    # Give each zone a single overall rating = average of its phase ratings
    zone_overall = {z: int(round(sum(zone_phase[z].values()) / len(phase_names), 0)) for z in zone_names}

    # Render zone tiles in a row
    zcols = st.columns(5, gap="large")

    for i, z in enumerate(zone_names):
        with zcols[i]:
            # headline tile
            st.markdown(_gdp_zone_tile(z, zone_overall[z], subtitle="Overall zone health"), unsafe_allow_html=True)

            # expand -> show phase breakdown
            with st.expander(f"Explain {z}", expanded=False):
                # phase mini-cards (clean + readable)
                for p in phase_names:
                    r = int(zone_phase[z][p])
                    col = _gdp_colour(r)
                    st.markdown(
                        f"""
                        <div class="gdp-card" style="padding:16px 20px;margin-bottom:12px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;">
                            <div style="font-weight:900;font-size:14px;letter-spacing:0.05em;text-transform:uppercase;opacity:0.9;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            {p}
                            </div>
                            <div style="font-weight:900;font-size:18px;color:{col};font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">{r}/100</div>
                        </div>
                        <div class="gdp-bar-bg" style="margin-top:8px;">
                            <div class="gdp-bar-fill" style="width:{r}%;background:{col};box-shadow:0 0 16px {col};"></div>
                        </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                st.caption("Mock: in v1 this is arbitrary. In v2, each phase score is computed from your real KPI bundle for that zone.")


        # =====================================================
        # 5 phases of the game
        # =====================================================
    st.markdown("<div style='margin:40px 0 24px 0;'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;'>📊 5 phases of the game</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:24px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Each phase has a rating (0–100). Expand each card to see the stats feeding the score (mock inputs).</div>", unsafe_allow_html=True)



    st.markdown("<div style='margin:40px 0;border-top:1px solid rgba(255,255,255,0.15);'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.6);font-size:13px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Mock page only. Next step is wiring this to your existing match + player/team metric tables.</div>", unsafe_allow_html=True)

# 5 cards in a single row (5 columns)
    pkeys = list(phases.keys())
    cols = st.columns(5, gap="large")

    for i, k in enumerate(pkeys):
        with cols[i]:
            _gdp_phase_card(k, int(phases[k]), stats[k])

    # =====================================================
    # 5 KEY IMPACT AREAS
    # =====================================================
    st.markdown("<div style='margin:48px 0 32px 0;'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;'>🎯 5 Key Impact Areas</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:32px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Focus on these zone-phase combinations to maximize performance (hypothetical analysis)</div>", unsafe_allow_html=True)

    # Generate 5 key impact areas (zone + phase combinations)
    # Use stable seed for consistent mock data
    impact_rng = random.Random(_stable_seed(team_a, team_b, "impact_areas"))
    
    # Define all possible zone-phase combinations
    all_zones = ["Defensive 50", "Defensive Mid", "Centre Bounce", "Attacking Mid", "Forward 50"]
    all_phases = ["Ball Winning", "Ball Use", "Scoring", "Defence", "Pressure"]
    
    # Create weighted impact combinations (some are more logical than others)
    impact_combinations = [
        ("Defensive 50", "Defence", "High impact: Protecting the defensive zone"),
        ("Defensive 50", "Ball Use", "Critical: Launching counter-attacks from defense"),
        ("Defensive Mid", "Ball Winning", "Essential: Winning clearances in defensive midfield"),
        ("Defensive Mid", "Pressure", "Key: Applying pressure to stop opposition transition"),
        ("Centre Bounce", "Ball Winning", "Crucial: Dominating center clearances"),
        ("Centre Bounce", "Pressure", "Important: First pressure at stoppages"),
        ("Attacking Mid", "Ball Use", "Vital: Quality delivery into forward 50"),
        ("Attacking Mid", "Ball Winning", "Critical: Winning ball in attacking territory"),
        ("Forward 50", "Scoring", "Essential: Converting opportunities"),
        ("Forward 50", "Pressure", "Important: Locking ball in forward zone"),
        ("Forward 50", "Ball Use", "Key: Smart ball movement inside 50"),
        ("Defensive 50", "Pressure", "Critical: Preventing opposition scores"),
    ]
    
    # Randomly select 5 impact areas with scores
    selected_impacts = impact_rng.sample(impact_combinations, 5)
    
    # Generate impact scores and recommendations
    impact_areas = []
    for zone, phase, reasoning in selected_impacts:
        # Get the score from our existing zone_phase data
        impact_score = zone_phase.get(zone, {}).get(phase, impact_rng.randint(45, 90))
        
        # Determine if this is strength or weakness
        if impact_score >= 75:
            status = "STRENGTH"
            status_color = "#00CC00"
            icon = "✅"
            action = "Maintain"
        elif impact_score >= 60:
            status = "MODERATE"
            status_color = "#F4A261"
            icon = "⚠️"
            action = "Improve"
        else:
            status = "WEAKNESS"
            status_color = "#FF4444"
            icon = "🔴"
            action = "Prioritize"
        
        impact_areas.append({
            "zone": zone,
            "phase": phase,
            "score": impact_score,
            "reasoning": reasoning,
            "status": status,
            "status_color": status_color,
            "icon": icon,
            "action": action
        })
    
    # Sort by score (weaknesses first for priority focus)
    impact_areas.sort(key=lambda x: x["score"])
    
    # Display impact areas in cards
    for idx, area in enumerate(impact_areas, 1):
        zone = area["zone"]
        phase = area["phase"]
        score = area["score"]
        reasoning = area["reasoning"]
        status = area["status"]
        status_color = area["status_color"]
        icon = area["icon"]
        action = area["action"]
        
        # Determine gradient color based on score
        card_color = _gdp_colour(score)
        
        st.markdown(
            f"""
            <div class="gdp-card" style="padding:24px 28px;margin-bottom:20px;border-left:6px solid {status_color};position:relative;overflow:hidden;">
                <div style="position:absolute;top:0;right:0;bottom:0;width:180px;background:linear-gradient(90deg, transparent 0%, {card_color}15 100%);"></div>
                <div style="display:flex;justify-content:space-between;align-items:flex-start;position:relative;">
                    <div style="flex:1;">
                        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
                            <span style="font-size:28px;">{icon}</span>
                            <div>
                                <div style="font-weight:900;font-size:20px;color:#FFFFFF;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;letter-spacing:0.02em;">
                                    #{idx} · {zone} – {phase}
                                </div>
                                <div style="font-size:13px;color:rgba(255,255,255,0.7);margin-top:4px;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-weight:600;">
                                    {reasoning}
                                </div>
                            </div>
                        </div>
                        <div style="display:flex;gap:16px;align-items:center;margin-top:16px;">
                            <div style="background:{status_color}25;border:1px solid {status_color};padding:8px 16px;border-radius:8px;">
                                <span style="font-size:11px;font-weight:900;color:{status_color};letter-spacing:0.1em;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                                    {status}
                                </span>
                            </div>
                            <div style="background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);padding:8px 16px;border-radius:8px;">
                                <span style="font-size:11px;font-weight:900;color:rgba(255,255,255,0.9);letter-spacing:0.1em;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                                    ACTION: {action.upper()}
                                </span>
                            </div>
                        </div>
                    </div>
                    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;margin-left:24px;">
                        <div style="font-weight:900;font-size:48px;color:{card_color};font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;line-height:1;text-shadow:0 2px 8px {card_color}50;">
                            {score}
                        </div>
                        <div style="font-size:11px;color:rgba(255,255,255,0.6);font-weight:700;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            IMPACT SCORE
                        </div>
                        <div class="gdp-bar-bg" style="width:120px;margin-top:8px;">
                            <div class="gdp-bar-fill" style="width:{score}%;background:{card_color};box-shadow:0 0 16px {card_color};"></div>
                        </div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    # Summary card
    avg_impact_score = sum(area["score"] for area in impact_areas) / len(impact_areas)
    weaknesses_count = sum(1 for area in impact_areas if area["status"] == "WEAKNESS")
    strengths_count = sum(1 for area in impact_areas if area["status"] == "STRENGTH")
    
    summary_color = _gdp_colour(avg_impact_score)
    
    st.markdown(
        f"""
        <div class="gdp-card" style="padding:24px 28px;margin-top:32px;background:linear-gradient(135deg, rgba(20,20,30,0.98) 0%, rgba(30,30,45,0.98) 100%);border:2px solid {summary_color}40;">
            <div style="text-align:center;">
                <div style="font-weight:900;font-size:18px;color:rgba(255,255,255,0.9);margin-bottom:16px;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;letter-spacing:0.05em;">
                    📊 IMPACT AREAS SUMMARY
                </div>
                <div style="display:flex;justify-content:center;gap:32px;margin-top:20px;">
                    <div>
                        <div style="font-size:32px;font-weight:900;color:{summary_color};font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            {avg_impact_score:.0f}
                        </div>
                        <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:4px;font-weight:700;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            AVG SCORE
                        </div>
                    </div>
                    <div>
                        <div style="font-size:32px;font-weight:900;color:#00CC00;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            {strengths_count}
                        </div>
                        <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:4px;font-weight:700;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            STRENGTHS
                        </div>
                    </div>
                    <div>
                        <div style="font-size:32px;font-weight:900;color:#FF4444;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            {weaknesses_count}
                        </div>
                        <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:4px;font-weight:700;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                            PRIORITIES
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.markdown("<div style='margin:24px 0;'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.5);font-size:12px;font-style:italic;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;'>Note: All impact areas and scores are hypothetical for demonstration purposes</div>", unsafe_allow_html=True)
    
    # =====================================================
    # COACHES BOX DASHBOARD - Single Screen Consolidated View
    # =====================================================
    st.markdown("<div style='margin:60px 0 20px 0;border-top:3px solid rgba(255,215,0,0.4);'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style='text-align:center;margin-bottom:24px;'>
        <div style='font-weight:900;font-size:32px;color:#FFD700;font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;letter-spacing:0.05em;text-shadow:2px 2px 8px rgba(0,0,0,0.5);'>
            📺 COACHES BOX DASHBOARD
        </div>
        <div style='color:rgba(255,255,255,0.7);font-size:13px;margin-top:8px;font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;font-weight:600;'>
            Game Day Monitor View — All Key Data on One Screen
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Build the consolidated dashboard HTML
    # Top row: Team logos with VS, Game Type indicators, Momentum
    
    # Get team logo paths
    team_a_code = TEAM_CODE_MAP.get(team_a, team_a.lower().replace(" ", ""))
    team_b_code = TEAM_CODE_MAP.get(team_b, team_b.lower().replace(" ", ""))
    team_a_logo = f"{LOGO_FOLDER}/{team_a_code}.png"
    team_b_logo = f"{LOGO_FOLDER}/{team_b_code}.png"
    
    # Encode logos to base64 for embedding
    def get_logo_b64(path):
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except:
            return ""
    
    logo_a_b64 = get_logo_b64(team_a_logo)
    logo_b_b64 = get_logo_b64(team_b_logo)
    
    # Game mode values
    game_modes_html = ""
    for left, right, key in dims:
        v = int(game_type[key])
        winner = left if v < 50 else right
        dist = abs(v - 50)
        strength = "STRONG" if dist >= 20 else ("SLIGHT" if dist >= 8 else "EVEN")
        mode_color = "#3FB984" if dist >= 8 else "#888888"
        game_modes_html += f"""
        <div style='display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.08);'>
            <span style='font-size:10px;color:rgba(255,255,255,0.6);width:80px;'>{left}/{right[0:4]}</span>
            <span style='font-size:11px;font-weight:800;color:{mode_color};'>{winner}</span>
        </div>
        """
    
    # Zone health mini-bars
    zones_html = ""
    for z in zone_names:
        score = zone_overall[z]
        col = _gdp_colour(score)
        short_name = z.replace("Defensive ", "D").replace("Attacking ", "A").replace("Centre Bounce", "CB").replace("Forward ", "F").replace("Mid", "M")
        zones_html += f"""
        <div style='flex:1;text-align:center;padding:4px;'>
            <div style='font-size:9px;color:rgba(255,255,255,0.5);margin-bottom:2px;font-weight:700;'>{short_name}</div>
            <div style='font-size:14px;font-weight:900;color:{col};'>{score}</div>
            <div style='height:4px;background:rgba(255,255,255,0.1);border-radius:2px;margin-top:2px;'>
                <div style='height:4px;width:{score}%;background:{col};border-radius:2px;'></div>
            </div>
        </div>
        """
    
    # Phase ratings mini-cards
    phases_html = ""
    for k in pkeys:
        score = int(phases[k])
        col = _gdp_colour(score)
        short_phase = k.replace("Ball Winning", "WIN").replace("Ball Use", "USE").replace("Scoring", "SCORE").replace("Defence", "DEF").replace("Pressure", "PRESS")
        phases_html += f"""
        <div style='flex:1;text-align:center;padding:6px 4px;background:rgba(255,255,255,0.03);border-radius:6px;margin:0 2px;'>
            <div style='font-size:8px;color:rgba(255,255,255,0.5);margin-bottom:2px;font-weight:700;letter-spacing:0.05em;'>{short_phase}</div>
            <div style='font-size:16px;font-weight:900;color:{col};'>{score}</div>
        </div>
        """
    
    # Top 3 impact areas (sorted by priority - lowest scores first)
    top_impacts_html = ""
    for i, area in enumerate(impact_areas[:3], 1):
        score = area["score"]
        col = _gdp_colour(score)
        zone_short = area["zone"].replace("Defensive ", "D").replace("Attacking ", "A").replace("Centre Bounce", "CB").replace("Forward ", "F").replace("Mid", "M")
        phase_short = area["phase"].replace("Ball Winning", "WIN").replace("Ball Use", "USE").replace("Scoring", "SCORE").replace("Defence", "DEF").replace("Pressure", "PRESS")
        top_impacts_html += f"""
        <div style='display:flex;justify-content:space-between;align-items:center;padding:6px 8px;background:rgba(255,255,255,0.03);border-radius:6px;margin-bottom:4px;border-left:3px solid {area["status_color"]};'>
            <span style='font-size:10px;color:rgba(255,255,255,0.8);font-weight:700;'>{zone_short} • {phase_short}</span>
            <span style='font-size:12px;font-weight:900;color:{col};'>{score}</span>
        </div>
        """
    
    # Build the complete consolidated dashboard
    dashboard_html = f"""
    <div style='
        background: linear-gradient(145deg, rgba(10,10,18,0.98), rgba(20,20,35,0.98));
        border: 2px solid rgba(255,215,0,0.3);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 12px 40px rgba(0,0,0,0.6);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    '>
        <!-- ROW 1: Teams + Game Type + Momentum -->
        <div style='display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:12px;margin-bottom:12px;'>
            
            <!-- Team Matchup -->
            <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:12px;display:flex;align-items:center;justify-content:center;gap:12px;'>
                <div style='text-align:center;'>
                    <img src='data:image/png;base64,{logo_a_b64}' style='width:50px;height:50px;object-fit:contain;filter:drop-shadow(0 4px 8px rgba(0,0,0,0.5));'/>
                    <div style='font-size:10px;font-weight:800;color:#FFFFFF;margin-top:4px;'>{team_a[:12]}</div>
                </div>
                <div style='font-size:18px;font-weight:900;color:rgba(255,255,255,0.4);'>VS</div>
                <div style='text-align:center;'>
                    <img src='data:image/png;base64,{logo_b_b64}' style='width:50px;height:50px;object-fit:contain;filter:drop-shadow(0 4px 8px rgba(0,0,0,0.5));'/>
                    <div style='font-size:10px;font-weight:800;color:#FFFFFF;margin-top:4px;'>{team_b[:12]}</div>
                </div>
            </div>
            
            <!-- Game Type -->
            <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'>
                <div style='font-size:10px;font-weight:800;color:#FFD700;margin-bottom:6px;letter-spacing:0.1em;text-align:center;'>GAME TYPE</div>
                {game_modes_html}
            </div>
            
            <!-- Momentum -->
            <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'>
                <div style='font-size:10px;font-weight:800;color:#FFD700;margin-bottom:8px;letter-spacing:0.1em;text-align:center;'>MOMENTUM</div>
                <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'>
                    <span style='font-size:11px;font-weight:800;color:#FF6B35;'>{team_a[:8]}</span>
                    <span style='font-size:10px;font-weight:900;color:{status_color};padding:2px 8px;background:rgba(255,255,255,0.08);border-radius:8px;'>{momentum_status}</span>
                    <span style='font-size:11px;font-weight:800;color:#4A90E2;'>{team_b[:8]}</span>
                </div>
                <div style='position:relative;height:20px;background:rgba(255,255,255,0.06);border-radius:10px;overflow:hidden;'>
                    <div style='position:absolute;left:0;top:0;bottom:0;width:{team_a_pct}%;background:linear-gradient(90deg, #FF6B35 0%, #F7931E 100%);'></div>
                    <div style='position:absolute;right:0;top:0;bottom:0;width:{team_b_pct}%;background:linear-gradient(270deg, #4A90E2 0%, #357ABD 100%);'></div>
                    <div style='position:absolute;left:50%;top:0;bottom:0;width:2px;background:rgba(255,255,255,0.4);transform:translateX(-50%);'></div>
                    <span style='position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:11px;font-weight:900;color:#FFF;'>{int(team_a_pct)}%</span>
                    <span style='position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:11px;font-weight:900;color:#FFF;'>{int(team_b_pct)}%</span>
                </div>
            </div>
        </div>
        
        <!-- ROW 2: Zone Health -->
        <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;margin-bottom:12px;'>
            <div style='font-size:10px;font-weight:800;color:#FFD700;margin-bottom:8px;letter-spacing:0.1em;text-align:center;'>ZONE HEALTH</div>
            <div style='display:flex;justify-content:space-between;gap:4px;'>
                {zones_html}
            </div>
        </div>
        
        <!-- ROW 3: 5 Phases + Impact Areas -->
        <div style='display:grid;grid-template-columns:2fr 1fr;gap:12px;'>
            
            <!-- 5 Phases -->
            <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'>
                <div style='font-size:10px;font-weight:800;color:#FFD700;margin-bottom:8px;letter-spacing:0.1em;text-align:center;'>5 PHASES</div>
                <div style='display:flex;justify-content:space-between;'>
                    {phases_html}
                </div>
            </div>
            
            <!-- Top 3 Impact Areas -->
            <div style='background:rgba(255,255,255,0.03);border-radius:10px;padding:10px 12px;'>
                <div style='font-size:10px;font-weight:800;color:#FFD700;margin-bottom:8px;letter-spacing:0.1em;text-align:center;'>TOP 3 PRIORITIES</div>
                {top_impacts_html}
            </div>
        </div>
        
        <!-- Footer -->
        <div style='text-align:center;margin-top:12px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.08);'>
            <span style='font-size:9px;color:rgba(255,255,255,0.4);font-weight:600;'>FUTUREEDGE SPORT • GAME DAY MONITOR • {time_filter}</span>
        </div>
    </div>
    """
    
    # Use components.html for complex HTML with embedded images
    import streamlit.components.v1 as components
    components.html(dashboard_html, height=320, scrolling=False)
    
    st.markdown("<div style='margin:20px 0;'></div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.5);font-size:11px;font-style:italic;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;'>💡 This consolidated view is designed to fit on a single monitor in the coaches box during game day</div>", unsafe_allow_html=True)
    
    # Professional footer
    render_footer()


# ================= OVERVIEW =================
if page == "Overview":
    import textwrap
    import pandas as pd
    import streamlit as st

    render_page_header("FutureEdge AFL Dashboard", "Overview & Performance Analysis", "🏉")

    # ----------------------------
    # Helpers (using global get_ordinal from config)
    # ----------------------------
    def safe_int_str(x):
        try:
            return f"{int(round(float(x)))}"
        except Exception:
            return str(x)

    def darken_color(hex_color: str, factor: float = 0.6) -> str:
        """factor 0-1: lower = darker."""
        try:
            hex_color = str(hex_color).lstrip("#")
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            r = max(0, min(255, int(r * factor)))
            g = max(0, min(255, int(g * factor)))
            b = max(0, min(255, int(b * factor)))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#111111"

    def find_rank_col(df: pd.DataFrame, metric_col: str):
        """
        Your data sometimes uses:
        - 'Ball Winning Ranking Rank'
        - 'Ball Winning Rank'
        - 'Team Rating Rank'
        """
        candidates = [
            f"{metric_col} Rank",                           # "Ball Winning Ranking Rank"
            metric_col.replace(" Ranking", "") + " Rank",   # "Ball Winning Rank"
            metric_col.replace("Ranking", "").strip() + " Rank",
            metric_col + "Rank",
        ]
        for c in candidates:
            if c in df.columns:
                return c
        return None

    # ----------------------------
    # Year / window selection
    # ----------------------------
    available_years = get_available_summary_years()
    if not available_years:
        st.error("No summary years available.")
        st.stop()

    year_options = []
    for y in available_years:
        year_options.append(f"{y} - Season")
        if int(y) == 2025:
            year_options.append("2025 - Last 10 Games")

    # Primary period selector
    col_primary, col_compare_toggle = st.columns([3, 1])
    with col_primary:
        selected_option = st.selectbox(
            "Select Year & Data Window",
            year_options,
            index=0,
            help="Choose which year to view. Last 10 Games only available for 2025.",
        )
    with col_compare_toggle:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)  # Spacer to align
        compare_mode = st.checkbox("📊 Compare Periods", value=False, help="Compare two time periods side by side")

    if " - Last 10 Games" in selected_option:
        selected_season = 2025
        window = "Last 10 Games"
    else:
        selected_season = int(selected_option.split(" - ")[0])
        window = "Season"

    last10 = window == "Last 10 Games"
    period_label = f"{window} ({selected_season})"

    # Comparison period selector (if enabled)
    ladders2 = None
    period_label2 = None
    if compare_mode:
        # Filter out the primary selection from comparison options
        compare_options = [opt for opt in year_options if opt != selected_option]
        if compare_options:
            compare_option = st.selectbox(
                "Compare To",
                compare_options,
                index=0,
                help="Select the second period to compare against",
                key="overview_compare_period"
            )
            
            if " - Last 10 Games" in compare_option:
                compare_season = 2025
                compare_window = "Last 10 Games"
            else:
                compare_season = int(compare_option.split(" - ")[0])
                compare_window = "Season"
            
            compare_last10 = compare_window == "Last 10 Games"
            period_label2 = f"{compare_window} ({compare_season})"
            
            # Load comparison data
            try:
                ladders2 = load_team_ladders(compare_season, last10=compare_last10)
            except Exception as e:
                st.warning(f"Could not load comparison data for {period_label2}: {e}")
                ladders2 = None

    # ----------------------------
    # Load ladder
    # ----------------------------
    try:
        ladders = load_team_ladders(selected_season, last10=last10)
    except Exception as e:
        st.error(f"Error loading data for {selected_season} – {window}: {e}")
        st.stop()

    if ladders is None or ladders.empty:
        st.warning(f"No ladder data found for {period_label}.")
        st.stop()

    # Force consistent types
    ladders = ladders.copy()
    ladders["Team"] = ladders["Team"].astype(str)

    # ----------------------------
    # Team leaders cards (top4)
    # ----------------------------
    top4_colour_map = {
        "Team Rating": ("#000000", "white"),
        "Ball Winning Ranking": ("#0066CC", "white"),
        "Ball Movement Ranking": ("#009933", "white"),
        "Scoring Ranking": ("#FFEB3B", "black"),
        "Defence Ranking": ("#CC0000", "white"),
        "Pressure Ranking": ("#800080", "white"),
    }

    render_html(st, f"<hr><h2 style='text-align:center;color:#FFFFFF;margin-bottom:25px;'>🏆 Team Leaders – {period_label}</h2>")

    metric_configs = [
        {"label": "Team Rating", "metric_col": "Team Rating"},
        {"label": "Ball Winning Ranking", "metric_col": "Ball Winning Ranking"},
        {"label": "Ball Movement Ranking", "metric_col": "Ball Movement Ranking"},
        {"label": "Scoring Ranking", "metric_col": "Scoring Ranking"},
        {"label": "Defence Ranking", "metric_col": "Defence Ranking"},
        {"label": "Pressure Ranking", "metric_col": "Pressure Ranking"},
    ]

    def render_leader_column(container, cfg):
        metric_col = cfg["metric_col"]
        if metric_col not in ladders.columns:
            return

        df = ladders[["Team", metric_col]].copy()
        df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce")
        df = df.dropna(subset=[metric_col]).sort_values(metric_col, ascending=False).head(4)
        if df.empty:
            return

        bg, fg = top4_colour_map.get(metric_col, ("#333333", "white"))
        header_html = f"""
        <div style='background: linear-gradient(135deg, {bg} 0%, rgba(0,0,0,0.4) 100%);
                    border-left: 4px solid {bg}; padding: 12px; border-radius: 8px; margin-bottom: 15px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);'>
            <div style='font-size: 1.1em; font-weight: 900; color: {fg};'>{cfg["label"]}</div>
        </div>
        """
        render_html(container, header_html)

        leader_team = df.iloc[0]["Team"]
        logo_c1, logo_c2, logo_c3 = container.columns([0.5, 1, 0.5])
        with logo_c2:
            # IMPORTANT: pass the container, not st
            display_logo(leader_team, st, size=100)

        lines = []
        for j, (_, r) in enumerate(df.iterrows()):
            team = r["Team"]
            val_str = safe_int_str(r[metric_col])

            if j == 0:
                bg_gradient = f"linear-gradient(135deg, {bg} 0%, rgba(0,0,0,0.3) 100%)"
                border_style = f"border: 2px solid {bg}; box-shadow: 0 4px 6px rgba(0,0,0,0.3);"
                font_size = "1.15em"
                font_weight = "900"
                padding = "12px 14px"
                prefix = f"👑 {team}"
                value_display = f"<span style='float: right; font-size: 1.2em;'>{val_str}</span>"
                color = fg
            else:
                bg_gradient = "linear-gradient(135deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0.05) 100%)"
                border_style = "border: 1px solid rgba(255,255,255,0.2);"
                font_size = "0.95em"
                font_weight = "700"
                padding = "10px 12px"
                prefix = f"{j+1}. {team}"
                value_display = f"<span style='float: right; color: rgba(255,255,255,0.8);'>{val_str}</span>"
                color = "white"

            lines.append(
                f"<div style='background:{bg_gradient};color:{color};border-radius:10px;padding:{padding};"
                f"margin-bottom:8px;{border_style}font-size:{font_size};font-weight:{font_weight};'>"
                f"{prefix}{value_display}</div>"
            )

        render_html(container, "".join(lines))

    cols_row1 = st.columns(3)
    for i in range(3):
        render_leader_column(cols_row1[i], metric_configs[i])

    render_html(st, "<div style='margin-top:30px;margin-bottom:30px;'><hr style='border:0;border-top:2px solid rgba(255,215,0,0.3);'></div>")

    cols_row2 = st.columns(3)
    for i in range(3, 6):
        render_leader_column(cols_row2[i - 3], metric_configs[i])

    # ----------------------------
    # Ladder table (robust)
    # ----------------------------
    render_html(st, f"<hr><h2 style='text-align:center;color:#FFFFFF;margin-top:30px;margin-bottom:25px;'>📊 Team Ladder – {period_label}</h2>")

    # Use your metric order for display
    # METRIC_ORDER should contain the metric value cols e.g.
    # ["Team Rating","Ball Winning Ranking","Ball Movement Ranking","Scoring Ranking","Defence Ranking","Pressure Ranking"]
    ladder_cols = ["Team"]
    for metric_col in METRIC_ORDER:
        if metric_col in ladders.columns:
            ladder_cols.append(metric_col)
            rc = find_rank_col(ladders, metric_col)
            if rc:
                ladder_cols.append(rc)

    # Clean + enforce existing
    ladder_cols = [c for c in dict.fromkeys(ladder_cols) if c in ladders.columns]
    if not ladder_cols:
        st.info("No ladder columns found to display.")
        st.stop()

    ladder_view = ladders[ladder_cols].copy()

    # Sort by Team Rating if available
    if "Team Rating" in ladder_view.columns:
        ladder_view["Team Rating"] = pd.to_numeric(ladder_view["Team Rating"], errors="coerce")
        ladder_view = ladder_view.sort_values("Team Rating", ascending=False, na_position="last")

    # Convert metric value columns to int (no decimals) but LEAVE rank cols alone
    for c in ladder_view.columns:
        if c == "Team":
            continue
        if c.endswith(" Rank") or c.endswith("Ranking Rank") or c.endswith("Rank"):
            # rank col: leave numeric-ish; ordinal later
            continue
        ladder_view[c] = pd.to_numeric(ladder_view[c], errors="coerce").round(0).astype("Int64")

    # Rename columns to show wrapped headers
    pretty_metric = {
        "Team Rating": "Team\nRating",
        "Ball Winning Ranking": "Ball Winning\nRanking",
        "Ball Movement Ranking": "Ball Movement\nRanking",
        "Scoring Ranking": "Scoring\nRanking",
        "Defence Ranking": "Defence\nRanking",
        "Pressure Ranking": "Pressure\nRanking",
    }

    rename_map = {"Team": "Team"}
    # metrics first
    for metric_col in METRIC_ORDER:
        if metric_col in ladder_view.columns:
            rename_map[metric_col] = pretty_metric.get(metric_col, metric_col.replace(" ", "\n", 1))

            rc = find_rank_col(ladder_view, metric_col)
            if rc and rc in ladder_view.columns:
                # rank pretty label aligned to metric
                pm = rename_map[metric_col]
                # "Team\nRating" -> "Team Rating\nRank"
                if pm == "Team\nRating":
                    rename_map[rc] = "Team Rating\nRank"
                else:
                    rename_map[rc] = pm.replace("\nRanking", "\nRank") + ("" if "\nRank" in pm else "")

    ladder_view = ladder_view.rename(columns=rename_map)

    # Convert rank columns to ordinal (only if they are rank columns)
    for c in ladder_view.columns:
        if c.endswith("\nRank") or c.endswith(" Rank") or c.endswith("\nRank"):
            ladder_view[c] = pd.to_numeric(ladder_view[c], errors="coerce").apply(get_ordinal)

    # Color maps (matching your palette)
    metric_colors = {
        "Team\nRating": ("#000000", "white"),
        "Ball Winning\nRanking": ("#0066CC", "white"),
        "Ball Movement\nRanking": ("#009933", "white"),
        "Scoring\nRanking": ("#FFEB3B", "black"),
        "Defence\nRanking": ("#CC0000", "white"),
        "Pressure\nRanking": ("#800080", "white"),
    }
    rank_header_colors = {
        "Team Rating\nRank": ("#404040", "white"),
    }

    # Precompute opacity ranks by metric value column
    column_rankings = {}
    for c in ladder_view.columns:
        if c == "Team":
            continue
        if c.endswith("\nRank"):
            continue
        # metric cols are Int64 now; rank by value (desc)
        s = pd.to_numeric(ladder_view[c], errors="coerce")
        if not s.isna().all():
            column_rankings[c] = s.rank(ascending=False, method="min")

    # Build HTML table using unified .fe-table-light CSS
    html = []
    html.append("<table class='fe-table fe-table-light fe-sortable'><thead><tr>")

    # headers
    for c in ladder_view.columns:
        if c == "Team":
            bg = "#1a1a1a"
            grad = f"linear-gradient(135deg,{bg} 0%,{darken_color(bg,0.5)} 100%)"
            html.append(f"<th style='background:{grad};color:#FFFFFF;'>{c}</th>")
            continue

        if c in metric_colors:
            bg, fg = metric_colors[c]
            grad = f"linear-gradient(135deg,{bg} 0%,{darken_color(bg,0.6)} 100%)"
            html.append(f"<th style='background:{grad};color:{fg};'>{c}</th>")
            continue

        if c.endswith("\nRank"):
            # rank col header: tie it to parent metric header color if possible
            parent = c.replace("\nRank", "\nRanking")
            if parent == "Team\nRating":
                bg, fg = rank_header_colors.get("Team Rating\nRank", ("#404040", "white"))
            elif parent in metric_colors:
                bg, fg = metric_colors[parent]
                bg = darken_color(bg, 0.75)
            else:
                bg, fg = ("#404040", "white")
            grad = f"linear-gradient(135deg,{bg} 0%,{darken_color(bg,0.6)} 100%)"
            html.append(f"<th style='background:{grad};color:{fg};'>{c}</th>")
            continue

        bg = "#1a1a1a"
        grad = f"linear-gradient(135deg,{bg} 0%,{darken_color(bg,0.5)} 100%)"
        html.append(f"<th style='background:{grad};color:#FFFFFF;'>{c}</th>")

    html.append("</tr></thead><tbody>")

    # rows
    n_teams = max(1, ladder_view["Team"].nunique())
    denom = max(1, n_teams - 1)

    for ridx, row in ladder_view.iterrows():
        html.append("<tr>")
        for c in ladder_view.columns:
            v = row[c]

            if c == "Team":
                html.append(f"<td>{v}</td>")
                continue

            # metric value cell
            if c in metric_colors:
                bg, fg = metric_colors[c]
                opacity = 1.0
                if c in column_rankings:
                    r = column_rankings[c].loc[ridx]
                    if pd.notna(r):
                        opacity = 1.0 - (float(r) - 1.0) / denom * 0.7  # 1.0 -> 0.3
                r_, g_, b_ = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
                html.append(f"<td style='background:rgba({r_},{g_},{b_},{opacity:.3f});color:{fg};'>{v}</td>")
                continue

            # rank cell
            if c.endswith("\nRank"):
                parent = c.replace("\nRank", "\nRanking")
                if parent == "Team\nRating":
                    bg = "#404040"
                    fg = "white"
                    parent_metric = "Team\nRating"
                elif parent in metric_colors:
                    bg, fg = metric_colors[parent]
                    bg = darken_color(bg, 0.75)
                    parent_metric = parent
                else:
                    bg, fg = "#404040", "white"
                    parent_metric = parent

                opacity = 1.0
                if parent_metric in column_rankings:
                    r = column_rankings[parent_metric].loc[ridx]
                    if pd.notna(r):
                        opacity = 1.0 - (float(r) - 1.0) / denom * 0.7

                r_, g_, b_ = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
                html.append(f"<td style='background:rgba({r_},{g_},{b_},{opacity:.3f});color:{fg};'>{v}</td>")
                continue

            html.append(f"<td>{v}</td>")

        html.append("</tr>")

    html.append("</tbody></table>")

    # Use render_sortable_table for working JavaScript sorting
    render_sortable_table("\n".join(html))

    st.caption(f"Teams shown: {ladder_view['Team'].nunique()} (should be 18)")

    # ----------------------------
    # Period Comparison Table (if compare mode enabled)
    # ----------------------------
    if compare_mode and ladders2 is not None and not ladders2.empty:
        render_html(st, f"<hr><h2 style='text-align:center;color:#FFFFFF;margin-top:40px;margin-bottom:25px;'>📈 Period Comparison – {period_label} vs {period_label2}</h2>")
        render_html(st, f"<p style='text-align:center;color:#888;margin-bottom:20px;'>Changes shown as: {period_label} minus {period_label2}. Ranked by biggest positive change (1st) to biggest negative change (18th).</p>")
        
        # Make sure ladders2 has consistent team names
        ladders2 = ladders2.copy()
        ladders2["Team"] = ladders2["Team"].astype(str)
        
        # Metrics to compare (value columns only, not rank columns)
        compare_metrics = ["Team Rating", "Ball Winning Ranking", "Ball Movement Ranking", "Scoring Ranking", "Defence Ranking", "Pressure Ranking"]
        
        # Build comparison dataframe
        comparison_data = []
        for team in ladders["Team"].unique():
            team_data = {"Team": team}
            team_row1 = ladders[ladders["Team"] == team]
            team_row2 = ladders2[ladders2["Team"] == team]
            
            if team_row1.empty or team_row2.empty:
                continue
            
            for metric in compare_metrics:
                if metric in ladders.columns and metric in ladders2.columns:
                    val1 = pd.to_numeric(team_row1[metric].iloc[0], errors="coerce")
                    val2 = pd.to_numeric(team_row2[metric].iloc[0], errors="coerce")
                    if pd.notna(val1) and pd.notna(val2):
                        change = val1 - val2
                        team_data[f"{metric}"] = round(change, 1)
                    else:
                        team_data[f"{metric}"] = None
            comparison_data.append(team_data)
        
        if comparison_data:
            comparison_df = pd.DataFrame(comparison_data)
            
            # Calculate change rankings for each metric (biggest positive = rank 1)
            change_rankings = {}
            for metric in compare_metrics:
                if metric in comparison_df.columns:
                    change_rankings[metric] = comparison_df[metric].rank(ascending=False, method="min", na_option="bottom")
            
            # Build HTML comparison table
            comp_html = []
            comp_html.append("<table class='fe-table fe-table-light fe-sortable'><thead><tr>")
            
            # Headers
            comp_html.append("<th style='background:linear-gradient(135deg,#1a1a1a 0%,#0a0a0a 100%);color:#FFFFFF;'>Team</th>")
            
            metric_colors_comp = {
                "Team Rating": ("#000000", "white"),
                "Ball Winning Ranking": ("#0066CC", "white"),
                "Ball Movement Ranking": ("#009933", "white"),
                "Scoring Ranking": ("#FFEB3B", "black"),
                "Defence Ranking": ("#CC0000", "white"),
                "Pressure Ranking": ("#800080", "white"),
            }
            
            pretty_headers = {
                "Team Rating": "Team Rating\nΔ",
                "Ball Winning Ranking": "Ball Winning\nΔ",
                "Ball Movement Ranking": "Ball Movement\nΔ",
                "Scoring Ranking": "Scoring\nΔ",
                "Defence Ranking": "Defence\nΔ",
                "Pressure Ranking": "Pressure\nΔ",
            }
            
            for metric in compare_metrics:
                if metric in comparison_df.columns:
                    bg, fg = metric_colors_comp.get(metric, ("#404040", "white"))
                    grad = f"linear-gradient(135deg,{bg} 0%,{darken_color(bg, 0.6)} 100%)"
                    header_text = pretty_headers.get(metric, metric + "\nΔ")
                    comp_html.append(f"<th style='background:{grad};color:{fg};'>{header_text}</th>")
                    # Add rank column header
                    rank_bg = darken_color(bg, 0.75) if bg != "#000000" else "#404040"
                    rank_grad = f"linear-gradient(135deg,{rank_bg} 0%,{darken_color(rank_bg, 0.6)} 100%)"
                    comp_html.append(f"<th style='background:{rank_grad};color:white;'>Rank</th>")
            
            comp_html.append("</tr></thead><tbody>")
            
            # Sort by Team Rating change (descending) if available
            if "Team Rating" in comparison_df.columns:
                comparison_df = comparison_df.sort_values("Team Rating", ascending=False, na_position="last")
            
            # Data rows
            n_teams_comp = max(1, len(comparison_df))
            denom_comp = max(1, n_teams_comp - 1)
            
            for ridx, row in comparison_df.iterrows():
                comp_html.append("<tr>")
                comp_html.append(f"<td>{row['Team']}</td>")
                
                for metric in compare_metrics:
                    if metric in comparison_df.columns:
                        val = row[metric]
                        bg, fg = metric_colors_comp.get(metric, ("#404040", "white"))
                        
                        # Color based on positive/negative change
                        if pd.notna(val):
                            if val > 0:
                                # Positive change: green tint with dark green text
                                cell_bg = "rgba(0, 153, 51, 0.3)"
                                cell_color = "#006622"  # Dark green for readability
                                display_val = f"+{val:.0f}"
                            elif val < 0:
                                # Negative change: red tint with dark red text
                                cell_bg = "rgba(204, 0, 0, 0.3)"
                                cell_color = "#990000"  # Dark red for readability
                                display_val = f"{val:.0f}"
                            else:
                                cell_bg = "rgba(128, 128, 128, 0.2)"
                                cell_color = "#555555"
                                display_val = "0"
                            
                            comp_html.append(f"<td style='background:{cell_bg};color:{cell_color};font-weight:bold;'>{display_val}</td>")
                            
                            # Rank cell
                            rank_val = change_rankings[metric].loc[ridx]
                            rank_bg = darken_color(bg, 0.75) if bg != "#000000" else "#404040"
                            
                            # Opacity based on rank
                            opacity = 1.0 - (float(rank_val) - 1.0) / denom_comp * 0.7 if pd.notna(rank_val) else 0.3
                            r_, g_, b_ = int(rank_bg[1:3], 16), int(rank_bg[3:5], 16), int(rank_bg[5:7], 16)
                            comp_html.append(f"<td style='background:rgba({r_},{g_},{b_},{opacity:.3f});color:white;'>{get_ordinal(int(rank_val))}</td>")
                        else:
                            comp_html.append("<td style='color:#666;'>N/A</td>")
                            comp_html.append("<td style='color:#666;'>—</td>")
                
                comp_html.append("</tr>")
            
            comp_html.append("</tbody></table>")
            
            render_sortable_table("\n".join(comp_html))
            
            st.caption(f"Comparison showing {len(comparison_df)} teams")
        else:
            st.info("No matching teams found between the two periods for comparison.")



# ================= TEAM BREAKDOWN =================

elif page == "Team Breakdown":
    render_page_header("Team Breakdown", "Detailed Team Performance Analysis", "📊")
    
    # Breadcrumb navigation
    render_breadcrumb([("Home", "Home"), ("Team Breakdown", None)])

    # Get available years for top-level selection
    available_years = get_available_summary_years()
    if not available_years:
        st.error("No summary years available.")
        st.stop()
    
    # Create options: years with Season, plus 2025 with Last 10 Games
    year_options = []
    for year in available_years:
        year_options.append(f"{year} - Season")
        if year == 2025:
            year_options.append("2025 - Last 10 Games")
    
    # Year and data window selection combined
    selected_option = st.selectbox(
        "Select Year & Data Window",
        year_options,
        index=0 if year_options else None,
        help="Choose which year to view. Last 10 Games only available for 2025.",
    )
    
    # Parse the selection
    if " - Last 10 Games" in selected_option:
        selected_year = 2025
        window = "Last 10 Games"
    else:
        selected_year = int(selected_option.split(" - ")[0])
        window = "Season"
    
    last10 = window == "Last 10 Games"
    period_label = f"{window} ({selected_year})"

    try:
        ladders = load_team_ladders(selected_year, last10=last10)
    except Exception as e:
        st.error(f"Error loading team data for {selected_year} – {window}: {e}")
        st.stop()

    if ladders.empty:
        st.warning(f"No ladder data found for {period_label}.")
        st.stop()

    st.caption(f"Showing: {period_label}")

    # Normalize team names in ladders DataFrame and dropdown
    ladders["Team"] = ladders["Team"].replace({

        "GWS": "GWS Giants",
        "Greater Western Sydney": "GWS Giants"
    })
    # Only check for canonical team names (one per team)
    canonical_teams = set([
        "Adelaide", "Brisbane", "Carlton", "Collingwood", "Essendon", "Fremantle", "Geelong", "Gold Coast",
        "GWS Giants", "Hawthorn", "Melbourne", "North Melbourne", "Port Adelaide", "Richmond", "St Kilda",
        "Sydney", "West Coast", "Western Bulldogs"
    ])
    missing_teams = canonical_teams - set(ladders["Team"].unique())




    if missing_teams:
        st.warning(f"Warning: Only {ladders['Team'].nunique()} teams found in data (expected 18). Data may be incomplete.")
        st.warning(f"Missing teams: {', '.join(sorted(missing_teams))}")
    team_list = sorted(ladders["Team"].unique())
    # Set default index based on session state
    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in team_list:
        default_idx = team_list.index(st.session_state.default_team)
    
    # Team selection with favorite star
    team_col1, team_col2 = st.columns([5, 1])
    with team_col1:
        team_name = st.selectbox("Select a team", team_list, index=default_idx)
    with team_col2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)  # Spacer to align
        is_fav = team_name in st.session_state.favorite_teams
        star_label = "⭐ Favorited" if is_fav else "☆ Favorite"
        if st.button(star_label, key="fav_team_breakdown"):
            toggle_favorite_team(team_name)
            st.rerun()
    
    # Track in recent views
    add_to_recent_views("team", team_name, team_name, "Team Breakdown")

    team_row = ladders[ladders["Team"] == team_name].iloc[0]
    
    # Display team logo with centered positioning
    st.markdown("---")
    st.markdown(f"<h2 style='text-align: center; color: #FFFFFF; margin-bottom: 20px;'>{team_name}</h2>", unsafe_allow_html=True)
    
    team_code = TEAM_CODE_MAP.get(team_name, team_name.lower().replace(" ", ""))
    team_logo_path = f"{LOGO_FOLDER}/{team_code}.png"
    
    # Get ladder position and percentage for this team and season with colors
    ladder_position_str, ladder_position_rank, position_color = get_ladder_position(team_name, selected_year)
    ladder_percentage_str, percentage_rank, percentage_color = get_ladder_percentage(team_name, selected_year)
    
    # Determine text color based on background color (5-tier system)
    def get_text_color(bg_color):
        # Light backgrounds need dark text
        if bg_color in ["#90EE90", "#FFD700"]:  # Light Green, Gold
            return "black"
        else:  # Dark colors: Dark Green, Orange, Red
            return "white"
    
    position_text_color = get_text_color(position_color)
    percentage_text_color = get_text_color(percentage_color)
    
    if os.path.exists(team_logo_path):
        try:
            img = Image.open(team_logo_path)
            # Create columns: left spacer, logo, ladder stats, right spacer
            logo_col1, logo_col2, logo_col3, logo_col4 = st.columns([1, 1, 1, 1])
            with logo_col2:
                st.image(img)
            with logo_col3:
                # Display ladder position and percentage to the right of logo, centered vertically with colored backgrounds
                st.markdown(
                    f"""
                    <div style="display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100%;">
                        <div style="margin-bottom: 30px; width: 100%;">
                            <p style="font-size: 12px; color: #888; margin: 0 0 5px 0; text-align: center;">Ladder Position</p>
                            <div style="background-color: {position_color}; padding: 10px 20px; border-radius: 8px; text-align: center;">
                                <p style="font-size: 48px; font-weight: bold; color: {position_text_color}; margin: 0;">{ladder_position_str}</p>
                            </div>
                        </div>
                        <div style="width: 100%;">
                            <p style="font-size: 12px; color: #888; margin: 0 0 5px 0; text-align: center;">Percentage</p>
                            <div style="background-color: {percentage_color}; padding: 10px 20px; border-radius: 8px; text-align: center;">
                                <p style="font-size: 48px; font-weight: bold; color: {percentage_text_color}; margin: 0;">{ladder_percentage_str}</p>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        except Exception as e:
            st.warning(f"Could not load {team_name} logo")
    else:
        st.info(f"Logo not found for {team_name}")

    # --- Team Ratings Snapshot ---
    st.markdown("---")
    st.markdown("<h2 style='text-align: center; color: #FFFFFF; margin-bottom: 20px;'>📊 Team Ratings Snapshot</h2>", unsafe_allow_html=True)

    # Prepare data for spider chart
    spider_metrics = []
    team_values = []
    top4_averages = []
    
    for metric_col in METRIC_ORDER:
        if metric_col not in ladders.columns:
            continue
        
        # Get team value
        rating_val = team_row[metric_col]
        try:
            team_val = float(rating_val)
        except Exception:
            continue
        
        # Calculate Top 4 average
        top4_vals = ladders.nlargest(4, metric_col)[metric_col]
        top4_avg = top4_vals.mean()
        
        spider_metrics.append(metric_col)
        team_values.append(team_val)
        top4_averages.append(top4_avg)
    
    # Create spider chart if we have data
    if spider_metrics and team_values:
        try:
            import plotly.graph_objects as go
            
            # Clean metric names for display
            clean_metrics = [m.replace(' Ranking', '').replace('Ranking', '').strip() for m in spider_metrics]
            
            # Close the polygon by appending first value to end
            team_values_closed = team_values + [team_values[0]]
            top4_averages_closed = top4_averages + [top4_averages[0]]
            clean_metrics_closed = clean_metrics + [clean_metrics[0]]
            
            # Create the radar chart
            fig = go.Figure()
            
            # Add Top 4 Average trace (bold yellow/gold)
            fig.add_trace(go.Scatterpolar(
                r=top4_averages_closed,
                theta=clean_metrics_closed,
                fill='toself',
                fillcolor='rgba(255, 215, 0, 0.1)',
                line=dict(color='#FFD700', width=4),
                name='Top 4 Average'
            ))
            
            # Add Selected Team trace (white)
            fig.add_trace(go.Scatterpolar(
                r=team_values_closed,
                theta=clean_metrics_closed,
                fill='toself',
                fillcolor='rgba(255, 255, 255, 0.1)',
                line=dict(color='white', width=3),
                name=team_name
            ))
            
            # Update layout
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 100],
                        showticklabels=True,
                        tickfont=dict(color='white', size=10),
                        gridcolor='gray'
                    ),
                    angularaxis=dict(
                        tickfont=dict(color='white', size=12, family='Arial Black'),
                        gridcolor='gray'
                    ),
                    bgcolor='rgba(0,0,0,0)'
                ),
                showlegend=True,
                legend=dict(
                    font=dict(color='white', size=12),
                    bgcolor='rgba(0,0,0,0.5)',
                    bordercolor='white',
                    borderwidth=1
                ),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=500
            )
            
            st.plotly_chart(fig, width="stretch")
            
        except ImportError:
            st.warning("Plotly not installed. Install with: `conda install -n afl plotly -y`")
    
    # Numeric values below chart with enhanced card styling
    st.markdown("---")
    st.markdown("<h3 style='color: #CCCCCC; margin-bottom: 15px;'>Key Performance Metrics</h3>", unsafe_allow_html=True)
    
    cols_row1 = st.columns(3)
    cols_row2 = st.columns(3)
    idx = 0

    for metric_col in METRIC_ORDER:
        if metric_col not in ladders.columns:
            continue

        rating_val = team_row[metric_col]
        try:
            rating_str = f"{float(rating_val):.1f}"
        except Exception:
            rating_str = str(rating_val)

        rank_col = f"{metric_col} Rank"
        rank_int = None
        if rank_col in team_row.index:
            try:
                rank_int = int(team_row[rank_col])
            except Exception:
                rank_int = None

        if isinstance(rank_int, int) and rank_int == 0:
            rank_int = 1

        if isinstance(rank_int, int):
            # 5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)
            if rank_int <= 4:
                color = "#008000"  # Elite - Dark Green
                bg_gradient = "linear-gradient(135deg, rgba(0,128,0,0.2) 0%, rgba(0,128,0,0.1) 100%)"
                border_color = "#00AA00"
            elif rank_int <= 7:
                color = "#90EE90"  # Good - Light Green
                bg_gradient = "linear-gradient(135deg, rgba(144,238,144,0.2) 0%, rgba(144,238,144,0.1) 100%)"
                border_color = "#90EE90"
            elif rank_int <= 11:
                color = "#FFD700"  # Average - Gold
                bg_gradient = "linear-gradient(135deg, rgba(255,215,0,0.2) 0%, rgba(255,215,0,0.1) 100%)"
                border_color = "#FFD700"
            elif rank_int <= 15:
                color = "#FFA500"  # Below Average - Orange
                bg_gradient = "linear-gradient(135deg, rgba(255,165,0,0.2) 0%, rgba(255,165,0,0.1) 100%)"
                border_color = "#FFA500"
            else:
                color = "#FF0000"  # Poor - Red
                bg_gradient = "linear-gradient(135deg, rgba(255,0,0,0.2) 0%, rgba(255,0,0,0.1) 100%)"
                border_color = "#DD0000"
        else:
            color = "grey"
            bg_gradient = "linear-gradient(135deg, rgba(128,128,128,0.2) 0%, rgba(128,128,128,0.1) 100%)"
            border_color = "#888888"

        if rank_int is not None:
            try:
                r_int = int(rank_int)
                if 10 <= (r_int % 100) <= 20:
                    suf = "th"
                else:
                    suf = {1: "st", 2: "nd", 3: "rd"}.get(r_int % 10, "th")
                ord_snap = f"{r_int}{suf}"
            except Exception:
                ord_snap = str(rank_int)
            value_str = f"{rating_str}"
            rank_badge = f"<span style='background: {color}; padding: 2px 8px; border-radius: 12px; font-weight: bold;'>{ord_snap}</span>"
        else:
            value_str = rating_str
            rank_badge = ""

        target_col = cols_row1[idx] if idx < 3 else cols_row2[idx - 3]
        
        # Enhanced card HTML
        card_html = f"""
        <div style='background: {bg_gradient}; padding: 15px; border-radius: 10px; 
                    border-left: 4px solid {border_color}; margin-bottom: 10px;'>
            <div style='color: #AAAAAA; font-size: 0.9em; margin-bottom: 4px;'>{metric_col}</div>
            <div style='font-size: 2.0em; font-weight: 900; color: {color}; margin-bottom: 5px;'>{value_str}</div>
            <div>{rank_badge}</div>
        </div>
        """
        target_col.markdown(card_html, unsafe_allow_html=True)

        idx += 1

    # --- Attribute Detail – new design ---
    st.markdown("---")
    st.markdown("<h2 style='text-align: center; color: #FFFFFF; margin-bottom: 20px;'>📈 Detailed Attribute Analysis</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #AAAAAA; margin-bottom: 25px;'>Team Performance vs League Competition</p>", unsafe_allow_html=True)

    # Load summary data for the selected year
    summary_year = load_team_summary_for_year(selected_year)

    attribute_options = [
        "Ball Winning",
        "Ball Movement",
        "Scoring",
        "Defence",
        "Pressure",
        "Health Check",
        "Wheelo Ratings",
    ]
    selected_attribute = st.selectbox(
        "Select attribute group",
        attribute_options,
        help=f"Matches the groups in the {selected_year} Summary sheet.",
    )

    blocks = _extract_attribute_structure(summary_year, selected_attribute)
    if not blocks:
        st.info("No stats found for this attribute group.")
    else:
        stat_names = [b["stat_name"] for b in blocks]
        which_block = "Last10" if window == "Last 10 Games" else "Season"
        
        # Health Check shows 6 stats in 2 rows of 3, others show 4 stats in 1 row
        if selected_attribute == "Health Check":
            num_stats = min(6, len(stat_names))
            num_cols = 3  # 3 columns per row for Health Check
            stats_per_row = 3
        else:
            num_stats = min(4, len(stat_names))
            num_cols = 4
            stats_per_row = 4
        
        # Helper function to render a stat column
        def render_stat_column(stat_name, col_idx, total_cols):
            dist_df = get_attribute_stat_distribution(
                summary_year,
                selected_attribute,
                stat_name,
                block=which_block,
            )
            # add a subtle right border between columns for visual separation
            col_border = (
                "border-right:2px solid rgba(255,215,0,0.2);padding-right:12px;margin-right:8px;"
                if col_idx < total_cols - 1
                else ""
            )
            st.markdown(f"<div style='{col_border}'>", unsafe_allow_html=True)
            st.markdown(f"<h3 style='color: #FFFFFF; font-size: 1.2em; margin-bottom: 15px;'>{stat_name}</h3>", unsafe_allow_html=True)
            if dist_df.empty:
                st.info("No data found for this stat across teams.")
            else:
                dist_df = dist_df.copy()
                dist_df["Value"] = pd.to_numeric(dist_df["Value"], errors="coerce")
                dist_df["Rank"] = pd.to_numeric(dist_df["Rank"], errors="coerce")
                dist_df = dist_df.dropna(subset=["Team", "Value"]).reset_index(drop=True)
                expected_team_count = 18
                actual_team_count = dist_df["Team"].nunique()
                if "Rank" not in dist_df.columns or dist_df["Rank"].isna().all():
                    dist_df = dist_df.sort_values("Value", ascending=False)
                    dist_df["Rank"] = range(1, len(dist_df) + 1)
                else:
                    dist_df = dist_df.sort_values("Rank", ascending=True)
                dist_df["Rank"] = dist_df["Rank"].round(0).astype("Int64")
                sel_row = dist_df[dist_df["Team"] == team_name]
                if sel_row.empty:
                    st.warning(f"{team_name} has no data for this stat.")
                else:
                    sel = sel_row.iloc[0]
                    val = sel["Value"]
                    rank = int(sel["Rank"])
                    canonical_teams = set([
                        "Adelaide", "Brisbane", "Carlton", "Collingwood", "Essendon", "Fremantle", "Geelong", "Gold Coast",
                        "GWS Giants", "Hawthorn", "Melbourne", "North Melbourne", "Port Adelaide", "Richmond", "St Kilda",
                        "Sydney", "West Coast", "Western Bulldogs"
                    ])
                    missing_teams = canonical_teams - set(dist_df["Team"].unique())
                    if actual_team_count != expected_team_count:
                        n_teams = actual_team_count
                        rank_str = f"{rank} / {n_teams}"
                        st.warning(f"Warning: Only {actual_team_count} teams found in data (expected 18). Data may be incomplete.")
                        if missing_teams:
                            st.warning(f"Missing teams: {', '.join(sorted(missing_teams))}")
                    else:
                        n_teams = expected_team_count
                        rank_str = f"{rank} / {n_teams}"
                    try:
                        val_str = f"{float(val):.1f}"
                    except Exception:
                        val_str = str(val)
                    if rank <= 4:
                        main_color = "#008000"  # Elite - Dark Green
                        bg_gradient = "linear-gradient(135deg, rgba(0,128,0,0.3) 0%, rgba(0,128,0,0.1) 100%)"
                        border_color = "#00AA00"
                    elif rank <= 7:
                        main_color = "#90EE90"  # Good - Light Green
                        bg_gradient = "linear-gradient(135deg, rgba(144,238,144,0.3) 0%, rgba(144,238,144,0.1) 100%)"
                        border_color = "#90EE90"
                    elif rank <= 11:
                        main_color = "#FFD700"  # Average - Gold
                        bg_gradient = "linear-gradient(135deg, rgba(255,215,0,0.3) 0%, rgba(255,215,0,0.1) 100%)"
                        border_color = "#FFD700"
                    elif rank <= 15:
                        main_color = "#FFA500"  # Below Average - Orange
                        bg_gradient = "linear-gradient(135deg, rgba(255,165,0,0.3) 0%, rgba(255,165,0,0.1) 100%)"
                        border_color = "#FFA500"
                    else:
                        main_color = "#FF0000"  # Poor - Red
                        bg_gradient = "linear-gradient(135deg, rgba(255,0,0,0.3) 0%, rgba(255,0,0,0.1) 100%)"
                        border_color = "#DD0000"
                    # compute ordinal (1st, 2nd, 3rd, 4th...)
                    try:
                        r_int = int(rank)
                        if 10 <= (r_int % 100) <= 20:
                            suf = "th"
                        else:
                            suf = {1: "st", 2: "nd", 3: "rd"}.get(r_int % 10, "th")
                        ord_str = f"{r_int}{suf}"
                    except Exception:
                        ord_str = str(rank)
                    # Enhanced card with gradient background
                    card_html = f"""
                    <div style='background: {bg_gradient}; padding: 15px; border-radius: 10px; 
                                border-left: 4px solid {border_color}; margin-bottom: 10px;'>
                        <div style='color: #AAAAAA; font-size: 0.9em; margin-bottom: 4px;'>{stat_name}</div>
                        <div style='font-size: 1.8em; font-weight: 900; color: {main_color};'>{val_str}</div>
                        <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 4px;'>Rank: {ord_str}</div>
                    </div>
                    """
                    st.markdown(card_html, unsafe_allow_html=True)
                # Top 4 by Rank
                st.markdown("<h4 style='color: #FFFFFF; margin-top: 20px; margin-bottom: 10px;'>🏆 Top 4 Teams</h4>", unsafe_allow_html=True)
                top4 = (
                    dist_df.dropna(subset=["Rank"])
                    .sort_values("Rank", ascending=True)
                    .head(4)
                )
                if top4.empty:
                    st.info("No ranked teams found for this stat.")
                else:
                    lines = []
                    for _, row in top4.iterrows():
                        t = row["Team"]
                        val = row["Value"]
                        r = int(row["Rank"])
                        try:
                            val_str = f"{float(val):.1f}"
                        except Exception:
                            val_str = str(val)
                        if t == team_name:
                            bg_color = "rgba(0,200,0,0.2)"
                            border = "2px solid #00CC00"
                            size = "1.0em"
                            weight = "900"
                            color = "#00FF00"
                        elif r == 1:
                            bg_color = "rgba(255,215,0,0.15)"
                            border = "2px solid #FFD700"
                            size = "1.0em"
                            weight = "800"
                            color = "#FFD700"
                        else:
                            bg_color = "rgba(255,255,255,0.05)"
                            border = "1px solid #555555"
                            size = "0.95em"
                            weight = "700"
                            color = "#CCCCCC"
                        line_html = (
                            f"<div style='background: {bg_color}; border: {border}; "
                            f"border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; "
                            f"font-size: {size}; font-weight: {weight}; color: {color};'>"
                            f"{r}. {t} <span style='float: right; font-weight: bold;'>{val_str}</span></div>"
                        )
                        lines.append(line_html)
                    st.markdown("".join(lines), unsafe_allow_html=True)
                    
                    # Professional Averages Section
                    st.markdown("<hr style='border:0;border-top:1px solid rgba(255,255,255,0.1);margin:20px 0 16px 0;'>", unsafe_allow_html=True)
                    
                    # Calculate both averages
                    top4_avg = top4["Value"].dropna().mean() if not top4.empty and top4["Value"].notna().any() else None
                    league_avg = dist_df["Value"].dropna().mean() if "Value" in dist_df.columns and dist_df["Value"].notna().any() else None
                    
                    avg_html = """
                    <div style='display: flex; gap: 12px;'>
                        <div style='flex: 1; background: linear-gradient(135deg, rgba(255,215,0,0.15) 0%, rgba(255,215,0,0.05) 100%); 
                                    border: 1px solid rgba(255,215,0,0.3); border-radius: 10px; padding: 14px; text-align: center;'>
                            <div style='color: #FFD700; font-size: 0.75em; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;'>🏆 Top 4 Avg</div>
                            <div style='font-size: 1.6em; font-weight: 900; color: #FFD700;'>""" + (f"{top4_avg:.1f}" if top4_avg is not None else "–") + """</div>
                        </div>
                        <div style='flex: 1; background: linear-gradient(135deg, rgba(100,149,237,0.15) 0%, rgba(100,149,237,0.05) 100%); 
                                    border: 1px solid rgba(100,149,237,0.3); border-radius: 10px; padding: 14px; text-align: center;'>
                            <div style='color: #6495ED; font-size: 0.75em; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;'>📊 League Avg</div>
                            <div style='font-size: 1.6em; font-weight: 900; color: #6495ED;'>""" + (f"{league_avg:.1f}" if league_avg is not None else "–") + """</div>
                        </div>
                    </div>
                    """
                    st.markdown(avg_html, unsafe_allow_html=True)
            # close the bordered div
            st.markdown("</div>", unsafe_allow_html=True)
        
        # First row of stats
        stat_cols = st.columns(num_cols)
        for idx in range(min(stats_per_row, len(stat_names))):
            with stat_cols[idx]:
                render_stat_column(stat_names[idx], idx, num_cols)
        
        # Second row for Health Check (stats 4-6)
        if selected_attribute == "Health Check" and len(stat_names) > 3:
            st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
            stat_cols_row2 = st.columns(num_cols)
            for idx in range(3, min(6, len(stat_names))):
                with stat_cols_row2[idx - 3]:
                    render_stat_column(stat_names[idx], idx - 3, num_cols)


# ================= TEAM COMPARE =================

elif page == "Team Compare":
    render_page_header("Team Compare", "Head-to-Head Team Analysis", "⚖️")
    
    # Breadcrumb navigation
    render_breadcrumb([("Home", "Home"), ("Team Compare", None)])
    
    # Using global get_ordinal from config

    # Get available years for top-level selection (same as Team Breakdown)
    available_years = get_available_summary_years()
    if not available_years:
        st.error("No summary years available.")
        st.stop()
    
    # Create options: years with Season, plus 2025 with Last 10 Games
    year_options = []
    for year in available_years:
        year_options.append(f"{year} - Season")
        if year == 2025:
            year_options.append("2025 - Last 10 Games")
    
    # Helper function to parse year/window selection and load data
    def load_team_data_for_selection(selected_option):
        """Parse selection and load ladder data."""
        if " - Last 10 Games" in selected_option:
            sel_year = 2025
            sel_window = "Last 10 Games"
        else:
            sel_year = int(selected_option.split(" - ")[0])
            sel_window = "Season"
        
        sel_last10 = sel_window == "Last 10 Games"
        sel_label = f"{sel_window} ({sel_year})"
        
        try:
            sel_ladders = load_team_ladders(sel_year, last10=sel_last10)
            # Normalize team names
            sel_ladders["Team"] = sel_ladders["Team"].replace({
                "GWS": "GWS Giants",
                "Greater Western Sydney": "GWS Giants"
            })
            return sel_ladders, sel_label, sel_year, sel_window
        except Exception as e:
            return None, sel_label, sel_year, sel_window
    
    # Team selection with individual time filters
    st.markdown("### Select Teams to Compare")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Team 1 (Base)")
        # Time filter for Team 1
        selected_option1 = st.selectbox(
            "Year & Data Window",
            year_options,
            index=0 if year_options else None,
            help="Choose which year/window for Team 1",
            key="team_compare_period1"
        )
        
        # Load data for Team 1's selection
        ladders1, period_label1, year1, window1 = load_team_data_for_selection(selected_option1)
        
        if ladders1 is None or ladders1.empty:
            st.error(f"No data for {period_label1}")
            st.stop()
        
        team_list1 = sorted(ladders1["Team"].unique())
        
        # Team selector for Team 1
        default_idx1 = 0
        if "default_team" in st.session_state and st.session_state.default_team in team_list1:
            default_idx1 = team_list1.index(st.session_state.default_team)
        team1 = st.selectbox("Select Team", team_list1, index=default_idx1, key="team_compare_team1")
        
        st.caption(f"📅 {period_label1}")
    
    with col2:
        st.markdown("#### Team 2 (Comparison)")
        # Time filter for Team 2
        selected_option2 = st.selectbox(
            "Year & Data Window",
            year_options,
            index=0 if year_options else None,
            help="Choose which year/window for Team 2",
            key="team_compare_period2"
        )
        
        # Load data for Team 2's selection
        ladders2, period_label2, year2, window2 = load_team_data_for_selection(selected_option2)
        
        if ladders2 is None or ladders2.empty:
            st.error(f"No data for {period_label2}")
            st.stop()
        
        team_list2 = sorted(ladders2["Team"].unique())
        
        # Team selector for Team 2
        default_idx2 = 1 if len(team_list2) > 1 else 0
        team2 = st.selectbox("Select Team", team_list2, index=default_idx2, key="team_compare_team2")
        
        st.caption(f"📅 {period_label2}")
    
    # Track comparison in history (only if different teams or different periods)
    if team1 != team2 or period_label1 != period_label2:
        add_to_comparison_history("team", f"{team1} ({period_label1})", f"{team2} ({period_label2})")
    
    # Check if same team AND same period (invalid comparison)
    if team1 == team2 and period_label1 == period_label2:
        st.warning("Please select different teams or different time periods to compare.")
        st.stop()
    
    # Build comparison description
    if period_label1 == period_label2:
        comparison_desc = f"Comparing: {period_label1}"
    else:
        comparison_desc = f"Comparing: {team1} ({period_label1}) vs {team2} ({period_label2})"
    
    # Display team logos with reflection effect
    st.markdown("---")
    logo_col1, logo_col2 = st.columns(2)
    
    with logo_col1:
        # Show team name with period if different periods
        if period_label1 != period_label2:
            st.markdown(f"<h3 style='text-align: center;'>{team1}<br><span style='font-size: 14px; color: rgba(255,255,255,0.6);'>{period_label1}</span></h3>", unsafe_allow_html=True)
        else:
            st.markdown(f"<h3 style='text-align: center;'>{team1}</h3>", unsafe_allow_html=True)
        team1_code = TEAM_CODE_MAP.get(team1, team1.lower().replace(" ", ""))
        team1_logo_path = f"{LOGO_FOLDER}/{team1_code}.png"
        if os.path.exists(team1_logo_path):
            try:
                img1 = Image.open(team1_logo_path)
                # Center the image using columns
                inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
                with inner_col2:
                    st.image(img1, width=300)
            except Exception as e:
                st.warning(f"Could not load {team1} logo")
        else:
            st.info(f"Logo not found for {team1}")
    
    with logo_col2:
        # Show team name with period if different periods
        if period_label1 != period_label2:
            st.markdown(f"<h3 style='text-align: center;'>{team2}<br><span style='font-size: 14px; color: rgba(255,255,255,0.6);'>{period_label2}</span></h3>", unsafe_allow_html=True)
        else:
            st.markdown(f"<h3 style='text-align: center;'>{team2}</h3>", unsafe_allow_html=True)
        team2_code = TEAM_CODE_MAP.get(team2, team2.lower().replace(" ", ""))
        team2_logo_path = f"{LOGO_FOLDER}/{team2_code}.png"
        if os.path.exists(team2_logo_path):
            try:
                img2 = Image.open(team2_logo_path)
                # Center the image using columns
                inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
                with inner_col2:
                    st.image(img2, width=300)
            except Exception as e:
                st.warning(f"Could not load {team2} logo")
        else:
            st.info(f"Logo not found for {team2}")
    
    # Get team rows from their respective ladder data
    team1_row = ladders1[ladders1["Team"] == team1].iloc[0]
    team2_row = ladders2[ladders2["Team"] == team2].iloc[0]
    
    # For similarity calculation, we need to use the combined/intersecting columns
    # Find common columns between both ladder datasets
    common_cols = set(ladders1.columns) & set(ladders2.columns)
    
    # ========== SIMILARITY SCORE CALCULATION ==========
    # Calculate similarity score between the two teams based on all available metrics
    similarity_metrics = []
    for col in common_cols:
        if col == "Team" or col not in team1_row.index or col not in team2_row.index:
            continue
        try:
            val1 = float(team1_row[col])
            val2 = float(team2_row[col])
            # Skip if either value is NaN
            if pd.isna(val1) or pd.isna(val2):
                continue
            # For cross-period comparison, use a combined range for normalization
            # Get min/max from both datasets
            col_min = min(ladders1[col].min(), ladders2[col].min())
            col_max = max(ladders1[col].max(), ladders2[col].max())
            if col_max == col_min:
                continue
            # Normalize both values to 0-100 scale
            norm1 = ((val1 - col_min) / (col_max - col_min)) * 100
            norm2 = ((val2 - col_min) / (col_max - col_min)) * 100
            # Calculate absolute difference
            diff = abs(norm1 - norm2)
            # Convert to similarity (100 - difference)
            similarity = 100 - diff
            similarity_metrics.append(similarity)
        except:
            continue
    
    # Calculate overall similarity score
    if similarity_metrics:
        overall_similarity = sum(similarity_metrics) / len(similarity_metrics)
    else:
        overall_similarity = 0
    
    # Display similarity score between logos
    st.markdown(f"""
    <div style='text-align: center; margin: 30px 0;'>
        <div style='background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%); 
                    border-radius: 16px; padding: 24px; display: inline-block; min-width: 300px;
                    border: 2px solid rgba(255,255,255,0.2); box-shadow: 0 8px 24px rgba(0,0,0,0.3);'>
            <div style='font-size: 14px; font-weight: 700; color: rgba(255,255,255,0.6); 
                        text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 12px;'>
                Team Similarity Score
            </div>
            <div style='font-size: 56px; font-weight: 900; color: #ffffff; 
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        margin-bottom: 8px;'>
                {overall_similarity:.1f}%
            </div>
            <div style='font-size: 13px; color: rgba(255,255,255,0.5); font-style: italic;'>
                Based on {len(similarity_metrics)} comparable metrics
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ========== TEAM FAVOURED INDICATOR ==========
    st.markdown("---")
    
    # Define the 6 key pillars with their data columns
    # Note: Columns are named "Ranking" in the data but values are actually ratings (higher = better)
    pillar_config = {
        "Ball Winning": "Ball Winning Ranking",
        "Ball Movement": "Ball Movement Ranking",
        "Scoring": "Scoring Ranking",
        "Defence": "Defence Ranking",
        "Pressure": "Pressure Ranking",
        "Health Check": "Health Check Ranking"
    }
    
    # Check which pillars have data in BOTH ladder datasets (for cross-period comparison)
    available_pillars = {}
    for pillar_name, col_name in pillar_config.items():
        if col_name in ladders1.columns and col_name in ladders2.columns:
            try:
                t1_val = float(team1_row.get(col_name, 0))
                t2_val = float(team2_row.get(col_name, 0))
                if not pd.isna(t1_val) and not pd.isna(t2_val):
                    available_pillars[pillar_name] = col_name
            except:
                pass
    
    if available_pillars:
        st.markdown("""
        <div style='text-align: center; margin-bottom: 20px;'>
            <div style='font-size: 24px; font-weight: 900; color: #FFFFFF;
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        letter-spacing: 0.02em;'>
                ⚖️ Team Favoured Indicator
            </div>
            <div style='font-size: 14px; color: rgba(255,255,255,0.6); margin-top: 8px;'>
                Adjust pillar weightings to see which team is favoured (must sum to 100%)
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Initialize session state for pillar weights if not exists
        if "pillar_weights" not in st.session_state:
            # Default equal weights across available pillars
            num_pillars = len(available_pillars)
            default_weight = 100 // num_pillars
            remainder = 100 - (default_weight * num_pillars)
            st.session_state.pillar_weights = {}
            for i, pillar in enumerate(available_pillars.keys()):
                # Add remainder to first pillar to ensure sum is exactly 100
                st.session_state.pillar_weights[pillar] = default_weight + (remainder if i == 0 else 0)
        
        # Ensure all available pillars have weights
        for pillar in available_pillars.keys():
            if pillar not in st.session_state.pillar_weights:
                st.session_state.pillar_weights[pillar] = 0
        
        # Pillar weight sliders in an expander
        with st.expander("⚙️ Adjust Pillar Weightings", expanded=False):
            st.markdown("""
            <div style='font-size: 13px; color: rgba(255,255,255,0.7); margin-bottom: 16px; padding: 12px;
                        background: rgba(255,255,255,0.05); border-radius: 8px; border-left: 3px solid #FFD700;'>
                <strong>How it works:</strong> Each pillar's rating is compared between teams. Higher ratings are better. 
                Adjust the weights to prioritize what matters most to you. Weights must sum to 100%.
            </div>
            """, unsafe_allow_html=True)
            
            pillar_list = list(available_pillars.keys())
            
            # Quick preset buttons with tooltips showing values
            st.markdown("**Quick Presets:**")
            
            # Define presets with descriptions
            preset_definitions = {
                "equal": {"Ball Winning": 17, "Ball Movement": 17, "Scoring": 17, "Defence": 17, "Pressure": 16, "Health Check": 16},
                "offensive": {"Ball Winning": 15, "Ball Movement": 30, "Scoring": 35, "Defence": 5, "Pressure": 10, "Health Check": 5},
                "defensive": {"Ball Winning": 20, "Ball Movement": 10, "Scoring": 10, "Defence": 35, "Pressure": 20, "Health Check": 5},
                "balanced": {"Ball Winning": 20, "Ball Movement": 20, "Scoring": 20, "Defence": 20, "Pressure": 15, "Health Check": 5}
            }
            
            # Show preset descriptions
            st.caption("**Equal:** 17% each | **Offensive:** Scoring 35%, Movement 30% | **Defensive:** Defence 35%, Pressure 20% | **Balanced:** 20% on core pillars")
            
            preset_cols = st.columns(4)
            preset_clicked = None
            with preset_cols[0]:
                if st.button("Equal", key="preset_equal", use_container_width=True, help="17% Ball Win, 17% Movement, 17% Scoring, 17% Defence, 16% Pressure, 16% Health"):
                    preset_clicked = "equal"
            with preset_cols[1]:
                if st.button("Offensive", key="preset_offense", use_container_width=True, help="15% Ball Win, 30% Movement, 35% Scoring, 5% Defence, 10% Pressure, 5% Health"):
                    preset_clicked = "offensive"
            with preset_cols[2]:
                if st.button("Defensive", key="preset_defense", use_container_width=True, help="20% Ball Win, 10% Movement, 10% Scoring, 35% Defence, 20% Pressure, 5% Health"):
                    preset_clicked = "defensive"
            with preset_cols[3]:
                if st.button("Balanced", key="preset_balanced", use_container_width=True, help="20% Ball Win, 20% Movement, 20% Scoring, 20% Defence, 15% Pressure, 5% Health"):
                    preset_clicked = "balanced"
            
            # Apply preset BEFORE creating widgets
            if preset_clicked:
                presets = preset_definitions[preset_clicked]
                for p in pillar_list:
                    st.session_state.pillar_weights[p] = presets.get(p, 0)
                st.rerun()
            
            st.markdown("---")
            st.markdown("**Pillar Weights:**")
            
            # Create columns for number inputs (3 per row)
            weights = {}
            
            # First row of inputs
            cols1 = st.columns(3)
            for i, pillar in enumerate(pillar_list[:3]):
                with cols1[i]:
                    weights[pillar] = st.number_input(
                        f"{pillar}",
                        min_value=0,
                        max_value=100,
                        value=st.session_state.pillar_weights.get(pillar, 0),
                        step=1,
                        key=f"weight_{pillar}",
                        help=f"Weight for {pillar} ranking (0-100%)"
                    )
            
            # Second row of inputs (if more than 3 pillars)
            if len(pillar_list) > 3:
                cols2 = st.columns(3)
                for i, pillar in enumerate(pillar_list[3:6]):
                    with cols2[i]:
                        weights[pillar] = st.number_input(
                            f"{pillar}",
                            min_value=0,
                            max_value=100,
                            value=st.session_state.pillar_weights.get(pillar, 0),
                            step=1,
                            key=f"weight_{pillar}",
                            help=f"Weight for {pillar} ranking (0-100%)"
                        )
            
            # Update session state from current widget values
            st.session_state.pillar_weights = weights
            
            # Show current sum and validation
            total_weight = sum(weights.values())
            if total_weight == 100:
                st.success(f"✅ Weights sum to 100% - Ready!")
            elif total_weight < 100:
                st.warning(f"⚠️ Weights sum to {total_weight}% - Add {100 - total_weight}% more")
            else:
                st.error(f"❌ Weights sum to {total_weight}% - Remove {total_weight - 100}%")
        
        # Calculate weighted score for each team
        weights = st.session_state.pillar_weights
        total_weight = sum(weights.values())
        
        if total_weight == 100:
            # Calculate weighted ratings (higher rating = better)
            team1_weighted_score = 0
            team2_weighted_score = 0
            pillar_breakdown = []
            
            for pillar_name, col_name in available_pillars.items():
                weight = weights.get(pillar_name, 0)
                if weight == 0:
                    continue
                    
                try:
                    # Get ratings (higher = better, typically 0-100 scale)
                    t1_rating = float(team1_row.get(col_name, 50))
                    t2_rating = float(team2_row.get(col_name, 50))
                    
                    # Apply weight directly (ratings are already on a scale where higher = better)
                    # Normalize to 0-100 scale if not already
                    t1_weighted = (t1_rating / 100) * weight
                    t2_weighted = (t2_rating / 100) * weight
                    
                    team1_weighted_score += t1_weighted
                    team2_weighted_score += t2_weighted
                    
                    # Track breakdown (higher rating wins)
                    pillar_breakdown.append({
                        "pillar": pillar_name,
                        "weight": weight,
                        "t1_rating": t1_rating,
                        "t2_rating": t2_rating,
                        "t1_contribution": t1_weighted,
                        "t2_contribution": t2_weighted,
                        "winner": team1 if t1_rating > t2_rating else (team2 if t2_rating > t1_rating else "Tie")
                    })
                except:
                    continue
            
            # Calculate favour percentage (how much one team is favoured over another)
            total_possible = 100  # Maximum possible weighted score
            team1_pct = (team1_weighted_score / total_possible) * 100 if total_possible > 0 else 50
            team2_pct = (team2_weighted_score / total_possible) * 100 if total_possible > 0 else 50
            
            # Calculate relative favour on a -100 to +100 scale (negative = team1, positive = team2)
            # Then convert to 0-100 scale where 50 = even, 0 = team1 fully favoured, 100 = team2 fully favoured
            score_diff = team2_weighted_score - team1_weighted_score
            max_diff = total_possible  # Maximum possible difference
            
            # Normalize to 0-100 scale centered at 50
            favour_position = 50 + (score_diff / max_diff) * 50 if max_diff > 0 else 50
            favour_position = max(0, min(100, favour_position))  # Clamp to 0-100
            
            # Determine which team is favoured and by how much
            if favour_position < 45:
                favoured_team = team1
                favour_strength = 50 - favour_position
                favour_desc = "Strongly" if favour_strength > 15 else "Moderately" if favour_strength > 8 else "Slightly"
            elif favour_position > 55:
                favoured_team = team2
                favour_strength = favour_position - 50
                favour_desc = "Strongly" if favour_strength > 15 else "Moderately" if favour_strength > 8 else "Slightly"
            else:
                favoured_team = None
                favour_strength = abs(50 - favour_position)
                favour_desc = "Even"
            
            # Get team colors for the gradient
            team1_color = "#6496FF"  # Blue
            team2_color = "#FF6464"  # Red
            
            # Build verdict text
            if favoured_team:
                verdict_text = f"{favour_desc} Favours {favoured_team}"
            else:
                verdict_text = "Too Close to Call"
            
            # Create the continuum display using separate st.markdown calls for reliability
            st.markdown(f"""
            <div style="margin: 20px 0; padding: 24px; background: linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.03) 100%);
                        border-radius: 16px; border: 1px solid rgba(255,255,255,0.1);">
                <div style="display: flex; justify-content: space-between; margin-bottom: 16px;">
                    <div style="font-size: 18px; font-weight: 700; color: {team1_color};">{team1}</div>
                    <div style="font-size: 18px; font-weight: 700; color: {team2_color};">{team2}</div>
                </div>
                <div style="position: relative; height: 40px; background: linear-gradient(to right, {team1_color}, #333333 50%, {team2_color});
                            border-radius: 20px; margin-bottom: 8px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.3);">
                    <div style="position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; 
                                background: rgba(255,255,255,0.3); transform: translateX(-50%);"></div>
                    <div style="position: absolute; left: {favour_position:.1f}%; top: 50%; transform: translate(-50%, -50%);
                                width: 24px; height: 24px; background: #FFD700; border-radius: 50%; 
                                border: 3px solid #FFFFFF; box-shadow: 0 0 12px rgba(255,215,0,0.8), 0 2px 8px rgba(0,0,0,0.4);"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 12px; color: rgba(255,255,255,0.5);">
                    <span>← Favours {team1}</span>
                    <span>EVEN</span>
                    <span>Favours {team2} →</span>
                </div>
                <div style="text-align: center; margin-top: 20px; padding: 16px; 
                            background: rgba(255,215,0,0.1); border-radius: 12px; border: 1px solid rgba(255,215,0,0.3);">
                    <div style="font-size: 14px; color: rgba(255,255,255,0.6); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">
                        Weighted Verdict
                    </div>
                    <div style="font-size: 24px; font-weight: 900; color: #FFD700;">
                        {verdict_text}
                    </div>
                    <div style="font-size: 13px; color: rgba(255,255,255,0.5); margin-top: 8px;">
                        Based on weighted pillar ratings
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Pillar breakdown table in expander
            with st.expander("📊 View Pillar Breakdown", expanded=False):
                if pillar_breakdown:
                    breakdown_data = []
                    for pb in pillar_breakdown:
                        winner_icon = "🏆" if pb["winner"] != "Tie" else "🤝"
                        breakdown_data.append({
                            "Pillar": pb["pillar"],
                            "Weight": f"{pb['weight']}%",
                            f"{team1} Rating": f"{pb['t1_rating']:.1f}",
                            f"{team2} Rating": f"{pb['t2_rating']:.1f}",
                            "Pillar Winner": f"{winner_icon} {pb['winner']}"
                        })
                    
                    breakdown_df = pd.DataFrame(breakdown_data)
                    st.dataframe(breakdown_df, use_container_width=True, hide_index=True)
                    
                    # Summary stats
                    team1_wins = sum(1 for pb in pillar_breakdown if pb["winner"] == team1)
                    team2_wins = sum(1 for pb in pillar_breakdown if pb["winner"] == team2)
                    ties = sum(1 for pb in pillar_breakdown if pb["winner"] == "Tie")
                    
                    st.markdown(f"""
                    <div style="display: flex; justify-content: center; gap: 40px; margin-top: 16px;">
                        <div style="text-align: center;">
                            <div style="font-size: 28px; font-weight: 900; color: {team1_color};">{team1_wins}</div>
                            <div style="font-size: 12px; color: rgba(255,255,255,0.6);">{team1} Pillar Wins</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="font-size: 28px; font-weight: 900; color: rgba(255,255,255,0.5);">{ties}</div>
                            <div style="font-size: 12px; color: rgba(255,255,255,0.6);">Ties</div>
                        </div>
                        <div style="text-align: center;">
                            <div style="font-size: 28px; font-weight: 900; color: {team2_color};">{team2_wins}</div>
                            <div style="font-size: 12px; color: rgba(255,255,255,0.6);">{team2} Pillar Wins</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("⚠️ Adjust the pillar weights above to sum to exactly 100% to see the Team Favoured indicator.")
    
    # ========== RADAR CHARTS AND COLUMN CHART SECTION ==========
    st.markdown("---")
    st.subheader("Visual Comparison")
    
    # Prepare data for charts
    spider_metrics = []
    team1_values = []
    team2_values = []
    top4_averages = []
    
    for metric_col in METRIC_ORDER:
        if metric_col not in ladders.columns:
            continue
        
        # Get team values
        try:
            team1_val = float(team1_row[metric_col])
            team2_val = float(team2_row[metric_col])
        except Exception:
            continue
        
        # Calculate Top 4 average
        top4_vals = ladders.nlargest(4, metric_col)[metric_col]
        top4_avg = top4_vals.mean()
        
        spider_metrics.append(metric_col)
        team1_values.append(team1_val)
        team2_values.append(team2_val)
        top4_averages.append(top4_avg)
    
    # Clean metric names for display (outside try block so it's always available)
    clean_metrics = [m.replace(' Ranking', '').replace('Ranking', '').strip() for m in spider_metrics]
    
    if spider_metrics and team1_values and team2_values:
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            
            # Close the polygon by appending first value to end
            team1_values_closed = team1_values + [team1_values[0]]
            team2_values_closed = team2_values + [team2_values[0]]
            top4_averages_closed = top4_averages + [top4_averages[0]]
            clean_metrics_closed = clean_metrics + [clean_metrics[0]]
            
            # Create subplots: 2 radars + 1 column chart
            fig = make_subplots(
                rows=1, cols=3,
                specs=[[{'type': 'polar'}, {'type': 'polar'}, {'type': 'xy'}]],
                horizontal_spacing=0.15
            )
            
            # === RADAR 1: TEAM 1 ===
            fig.add_trace(
                go.Scatterpolar(
                    r=top4_averages_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor='rgba(255, 215, 0, 0.1)',
                    line=dict(color='#FFD700', width=3),
                    name='Top 4 Avg',
                    legendgroup='averages',
                    showlegend=True
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatterpolar(
                    r=team1_values_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor='rgba(100, 150, 255, 0.2)',
                    line=dict(color='#6496FF', width=3),
                    name=team1,
                    legendgroup='teams',
                    showlegend=True
                ),
                row=1, col=1
            )
            
            # === RADAR 2: TEAM 2 ===
            fig.add_trace(
                go.Scatterpolar(
                    r=top4_averages_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor='rgba(255, 215, 0, 0.1)',
                    line=dict(color='#FFD700', width=3),
                    name='Top 4 Avg',
                    legendgroup='averages',
                    showlegend=False
                ),
                row=1, col=2
            )
            
            fig.add_trace(
                go.Scatterpolar(
                    r=team2_values_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor='rgba(255, 100, 100, 0.2)',
                    line=dict(color='#FF6464', width=3),
                    name=team2,
                    legendgroup='teams',
                    showlegend=True
                ),
                row=1, col=2
            )
            
            # === COLUMN CHART: SIDE BY SIDE COMPARISON ===
            x_positions = clean_metrics
            fig.add_trace(
                go.Bar(
                    x=x_positions,
                    y=team1_values,
                    name=team1,
                    marker=dict(color='#6496FF'),
                    legendgroup='teams',
                    showlegend=False
                ),
                row=1, col=3
            )
            
            fig.add_trace(
                go.Bar(
                    x=x_positions,
                    y=team2_values,
                    name=team2,
                    marker=dict(color='#FF6464'),
                    legendgroup='teams',
                    showlegend=False
                ),
                row=1, col=3
            )
            
            # Update polar axes
            fig.update_polars(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    showticklabels=True,
                    tickfont=dict(color='white', size=9),
                    gridcolor='gray'
                ),
                angularaxis=dict(
                    tickfont=dict(color='white', size=11, family='Arial Black'),
                    gridcolor='gray'
                ),
                bgcolor='rgba(0,0,0,0)',
                row=1, col=1
            )
            
            fig.update_polars(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    showticklabels=True,
                    tickfont=dict(color='white', size=9),
                    gridcolor='gray'
                ),
                angularaxis=dict(
                    tickfont=dict(color='white', size=11, family='Arial Black'),
                    gridcolor='gray'
                ),
                bgcolor='rgba(0,0,0,0)',
                row=1, col=2
            )
            
            # Update column chart axes
            fig.update_xaxes(title_text="", tickfont=dict(color='white', size=10), row=1, col=3)
            fig.update_yaxes(title_text="Rating", tickfont=dict(color='white', size=10), row=1, col=3)
            
            # Update layout
            fig.update_layout(
                title_text=f"<b>{team1} vs {team2}</b> – Radar Charts & Comparison ({period_label})",
                title_font_size=18,
                showlegend=True,
                legend=dict(
                    font=dict(color='white', size=11),
                    bgcolor='rgba(0,0,0,0.5)',
                    bordercolor='white',
                    borderwidth=1,
                    x=1.02,
                    y=1
                ),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=550,
                font=dict(color='white')
            )
            
            st.plotly_chart(fig, width="stretch")
            
        except ImportError:
            st.warning("Plotly not installed. Install with: `conda install -n afl plotly -y`")
    
    # ========== STRENGTH/WEAKNESS ANALYSIS (Team 1 vs Team 2) ==========
    st.markdown("---")
    st.subheader(f"Strengths & Weaknesses Analysis: {team1} vs {team2}")
    
    # Helper function for ordinal rank format
    def format_rank(rank_val):
        """Convert rank number to ordinal format like (2nd), (1st), (3rd), etc."""
        if pd.isna(rank_val):
            return "N/A"
        try:
            r = int(rank_val)
            if 10 <= (r % 100) <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(r % 10, "th")
            return f"({r}{suffix})"
        except:
            return str(rank_val)
    
    # Load summary data for attributes
    try:
        summary_year = load_team_summary_for_year(selected_year)
    except Exception:
        summary_year = None
    
    # Get ranking for each metric (lower rank = better)
    metric_analysis = []
    for i, metric_col in enumerate(spider_metrics):
        team1_val = team1_values[i]
        team2_val = team2_values[i]
        top4_avg = top4_averages[i]
        
        # Get rankings for both teams using the {metric_col} Rank pattern
        rank_col = f"{metric_col} Rank"
        team1_rank = team1_row.get(rank_col, np.nan)
        team2_rank = team2_row.get(rank_col, np.nan)
        
        try:
            team1_rank = float(team1_rank) if not pd.isna(team1_rank) else np.nan
            team2_rank = float(team2_rank) if not pd.isna(team2_rank) else np.nan
        except (ValueError, TypeError):
            pass
        
        # Convert 0 ranks to 1 (same as Team Breakdown does)
        if team1_rank == 0:
            team1_rank = 1
        if team2_rank == 0:
            team2_rank = 1
        
        metric_analysis.append({
            "metric": clean_metrics[i],
            "team1_val": team1_val,
            "team2_val": team2_val,
            "team1_rank": team1_rank,
            "team2_rank": team2_rank,
        })
    
    # Separate strengths and weaknesses based on rankings
    metric_df = pd.DataFrame(metric_analysis)
    
    # Strengths: Team 1 has BETTER ranking (lower number) than Team 2
    team1_strengths = metric_df[
        (metric_df["team1_rank"].notna()) & 
        (metric_df["team2_rank"].notna()) & 
        (metric_df["team1_rank"] < metric_df["team2_rank"])
    ].sort_values("team1_rank", ascending=True)[["metric", "team1_val", "team2_val", "team1_rank", "team2_rank"]].reset_index(drop=True)
    
    # Weaknesses: Team 2 has BETTER ranking (lower number) than Team 1
    team1_weaknesses = metric_df[
        (metric_df["team1_rank"].notna()) & 
        (metric_df["team2_rank"].notna()) & 
        (metric_df["team1_rank"] > metric_df["team2_rank"])
    ].sort_values("team2_rank", ascending=True)[["metric", "team1_val", "team2_val", "team1_rank", "team2_rank"]].reset_index(drop=True)
    
    # Display Team 1 analysis with enhanced styling
    st.markdown("---")
    st.subheader(f"📊 Strengths & Weaknesses Analysis: {team1} vs {team2}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"<h3 style='color: #00CC00;'>🟢 {team1} – Strengths</h3>", unsafe_allow_html=True)
        if len(team1_strengths) > 0:
            for idx, row in team1_strengths.iterrows():
                metric = row["metric"]
                t1_val = row["team1_val"]
                t2_val = row["team2_val"]
                t1_rank = row["team1_rank"]
                t2_rank = row["team2_rank"]
                t1_rank_str = format_rank(t1_rank)
                t2_rank_str = format_rank(t2_rank)
                
                # Calculate rank difference for visual indicator
                rank_diff = int(t2_rank - t1_rank)
                
                st.markdown(
                    f"""
                    <div style='background: linear-gradient(90deg, rgba(0,204,0,0.1) 0%, rgba(0,204,0,0.05) 100%); 
                                border-left: 4px solid #00CC00; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                        <div style='font-weight: bold; color: #00CC00;'>{idx + 1}. {metric}</div>
                        <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                            {team1}: <span style='font-weight: bold; color: #00FF00;'>{t1_val:.1f}</span> {t1_rank_str} 
                            <span style='color: #888;'>vs</span> 
                            {team2}: <span style='font-weight: bold;'>{t2_val:.1f}</span> {t2_rank_str}
                        </div>
                        <div style='font-size: 0.85em; color: #00DD00; margin-top: 4px;'>
                            +{rank_diff} positions ahead
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.info("No statistics where Team 1 ranks higher")
    
    with col2:
        st.markdown(f"<h3 style='color: #FF4444;'>🔴 {team1} – Weaknesses</h3>", unsafe_allow_html=True)
        if len(team1_weaknesses) > 0:
            for idx, row in team1_weaknesses.iterrows():
                metric = row["metric"]
                t1_val = row["team1_val"]
                t2_val = row["team2_val"]
                t1_rank = row["team1_rank"]
                t2_rank = row["team2_rank"]
                t1_rank_str = format_rank(t1_rank)
                t2_rank_str = format_rank(t2_rank)
                
                # Calculate rank difference for visual indicator
                rank_diff = int(t1_rank - t2_rank)
                
                st.markdown(
                    f"""
                    <div style='background: linear-gradient(90deg, rgba(255,68,68,0.1) 0%, rgba(255,68,68,0.05) 100%); 
                                border-left: 4px solid #FF4444; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                        <div style='font-weight: bold; color: #FF4444;'>{idx + 1}. {metric}</div>
                        <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                            {team1}: <span style='font-weight: bold;'>{t1_val:.1f}</span> {t1_rank_str} 
                            <span style='color: #888;'>vs</span> 
                            {team2}: <span style='font-weight: bold; color: #FF6666;'>{t2_val:.1f}</span> {t2_rank_str}
                        </div>
                        <div style='font-size: 0.85em; color: #FF6666; margin-top: 4px;'>{rank_diff} positions behind</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.markdown("*No statistics where Team 2 ranks higher*")
    
    if summary_year is not None:
        # Attribute groups to analyze
        attribute_groups = [
            "Ball Winning",
            "Ball Movement",
            "Scoring",
            "Defence",
            "Pressure",
            "Health Check",
        ]
        
        # Get all stats from the 6 main metrics to exclude them (use spider_metrics which has the full names)
        main_metric_stats = set(spider_metrics)
        
        # Collect all attribute stats (excluding main metrics)
        all_attribute_stats = []
        which_block = "Last10" if window == "Last 10 Games" else "Season"
        
        for attribute_group in attribute_groups:
            try:
                blocks = _extract_attribute_structure(summary_year, attribute_group)
                if not blocks:
                    continue
            except Exception as e:
                print(f"Error processing attribute group: {e}")
                continue
            
            # Get stat names from blocks
            stat_names = [b["stat_name"] for b in blocks]
            # Add to all_attribute_stats (excluding main metrics)
            for stat_name in stat_names:
                if stat_name not in main_metric_stats:
                    all_attribute_stats.append((attribute_group, stat_name))
        
        if all_attribute_stats:
            # ========== ATTRIBUTE STATS BREAKDOWN (Team 1 vs Team 2) - SIDE BY SIDE ==========
            st.markdown("---")
            st.subheader(f"📊 Detailed Attribute Stats Breakdown: {team1} vs {team2}")
            
            st.markdown(f"""<div style='background: rgba(255,215,0,0.1); padding: 18px; border-radius: 10px; border-left: 5px solid #FFD700; margin-bottom: 25px;'><p style='color: #DDDDDD; margin: 0; font-size: 1.05em; line-height: 1.6;'><strong style='color: #FFFFFF; font-size: 1.2em;'>About This Section</strong><br><span style='color: #CCCCCC; font-size: 0.95em;'>Deep-dive comparison of specific attribute statistics across both teams. Stats are color-coded based on team rankings (green = elite, orange = average, red = needs work).</span></p></div>""", unsafe_allow_html=True)
            
            # Helper function for ordinal rank
            def get_ordinal_suffix(n):
                if 10 <= n % 100 <= 20:
                    suffix = "th"
                else:
                    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
                return suffix
            
            # Group stats by attribute for display
            for attribute_group in attribute_groups:
                # Get stats for this group
                group_stats = [(grp, stat) for grp, stat in all_attribute_stats if grp == attribute_group]
                if not group_stats:
                    continue
                
                st.markdown(f"### {attribute_group}")
                
                # Collect all stat comparisons for this group
                team1_strengths_attr = []
                team1_weaknesses_attr = []
                
                for grp, stat_name in group_stats:
                    dist_df = get_attribute_stat_distribution(
                        summary_year,
                        attribute_group,
                        stat_name,
                        block=which_block,
                    )
                    
                    if dist_df.empty:
                        continue
                    
                    dist_df = dist_df.copy()
                    dist_df["Value"] = pd.to_numeric(dist_df["Value"], errors="coerce")
                    dist_df["Rank"] = pd.to_numeric(dist_df["Rank"], errors="coerce")
                    dist_df = dist_df.dropna(subset=["Team", "Value"]).reset_index(drop=True)
                    
                    if "Rank" not in dist_df.columns or dist_df["Rank"].isna().all():
                        dist_df = dist_df.sort_values("Value", ascending=False)
                        dist_df["Rank"] = range(1, len(dist_df) + 1)
                    else:
                        dist_df = dist_df.sort_values("Rank", ascending=True)
                    dist_df["Rank"] = dist_df["Rank"].round(0).astype("Int64")
                    
                    # Get Team 1 and Team 2 data
                    team1_row_stat = dist_df[dist_df["Team"] == team1]
                    team2_row_stat = dist_df[dist_df["Team"] == team2]
                    
                    if not team1_row_stat.empty and not team2_row_stat.empty:
                        t1_val = team1_row_stat.iloc[0]["Value"]
                        t1_rank = int(team1_row_stat.iloc[0]["Rank"])
                        t2_val = team2_row_stat.iloc[0]["Value"]
                        t2_rank = int(team2_row_stat.iloc[0]["Rank"])
                        
                        # Determine if this is a strength or weakness for team1
                        if t1_rank < t2_rank:
                            team1_strengths_attr.append({
                                "stat": stat_name,
                                "t1_val": t1_val,
                                "t1_rank": t1_rank,
                                "t2_val": t2_val,
                                "t2_rank": t2_rank
                            })
                        elif t1_rank > t2_rank:
                            team1_weaknesses_attr.append({
                                "stat": stat_name,
                                "t1_val": t1_val,
                                "t1_rank": t1_rank,
                                "t2_val": t2_val,
                                "t2_rank": t2_rank
                            })
                
                # Display side-by-side: Strengths | Weaknesses
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown(f"<h4 style='color: #00CC00;'>🟢 {team1} – Strengths</h4>", unsafe_allow_html=True)
                    if len(team1_strengths_attr) > 0:
                        for idx, item in enumerate(team1_strengths_attr):
                            stat = item["stat"]
                            t1_val = item["t1_val"]
                            t1_rank = item["t1_rank"]
                            t2_val = item["t2_val"]
                            t2_rank = item["t2_rank"]
                            
                            rank_diff = int(t2_rank - t1_rank)
                            t1_ord = f"{t1_rank}{get_ordinal_suffix(t1_rank)}"
                            t2_ord = f"{t2_rank}{get_ordinal_suffix(t2_rank)}"
                            
                            try:
                                t1_val_str = f"{float(t1_val):.1f}"
                                t2_val_str = f"{float(t2_val):.1f}"
                            except:
                                t1_val_str = str(t1_val)
                                t2_val_str = str(t2_val)
                            
                            st.markdown(
                                f"""
                                <div style='background: linear-gradient(90deg, rgba(0,204,0,0.1) 0%, rgba(0,204,0,0.05) 100%); 
                                            border-left: 4px solid #00CC00; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                                    <div style='font-weight: bold; color: #00CC00;'>{idx + 1}. {stat}</div>
                                    <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                        {team1}: <span style='font-weight: bold; color: #00FF00;'>{t1_val_str}</span> ({t1_ord}) 
                                        <span style='color: #888;'>vs</span> 
                                        {team2}: <span style='font-weight: bold;'>{t2_val_str}</span> ({t2_ord})
                                    </div>
                                    <div style='font-size: 0.85em; color: #00DD00; margin-top: 4px;'>
                                        +{rank_diff} positions ahead
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                    else:
                        st.info(f"No {attribute_group} stats where {team1} ranks higher")
                
                with col2:
                    st.markdown(f"<h4 style='color: #FF4444;'>🔴 {team1} – Weaknesses</h4>", unsafe_allow_html=True)
                    if len(team1_weaknesses_attr) > 0:
                        for idx, item in enumerate(team1_weaknesses_attr):
                            stat = item["stat"]
                            t1_val = item["t1_val"]
                            t1_rank = item["t1_rank"]
                            t2_val = item["t2_val"]
                            t2_rank = item["t2_rank"]
                            
                            rank_diff = int(t1_rank - t2_rank)
                            t1_ord = f"{t1_rank}{get_ordinal_suffix(t1_rank)}"
                            t2_ord = f"{t2_rank}{get_ordinal_suffix(t2_rank)}"
                            
                            try:
                                t1_val_str = f"{float(t1_val):.1f}"
                                t2_val_str = f"{float(t2_val):.1f}"
                            except:
                                t1_val_str = str(t1_val)
                                t2_val_str = str(t2_val)
                            
                            st.markdown(
                                f"""
                                <div style='background: linear-gradient(90deg, rgba(255,68,68,0.1) 0%, rgba(255,68,68,0.05) 100%); 
                                            border-left: 4px solid #FF4444; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                                    <div style='font-weight: bold; color: #FF4444;'>{idx + 1}. {stat}</div>
                                    <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                        {team1}: <span style='font-weight: bold;'>{t1_val_str}</span> ({t1_ord}) 
                                        <span style='color: #888;'>vs</span> 
                                        {team2}: <span style='font-weight: bold; color: #FF6666;'>{t2_val_str}</span> ({t2_ord})
                                    </div>
                                    <div style='font-size: 0.85em; color: #FF6666; margin-top: 4px;'>{rank_diff} positions behind</div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                    else:
                        st.info(f"No {attribute_group} stats where {team2} ranks higher")
    
    # Export section
    st.markdown("---")
    render_export_button("team-compare", f"TeamCompare_{team1}_vs_{team2}")

# ================= CLUB LIST =================
elif page == "Club List":
    render_page_header("Club List", "Complete Team Roster", "📋")

    # ---------- Season selector ----------
    seasons = sorted(get_player_seasons(), reverse=True)
    if not seasons:
        st.error("No player seasons found.")
        st.stop()

    default_season_idx = seasons.index(2025) if 2025 in seasons else 0
    season = st.selectbox(
        "Select Season",
        seasons,
        index=default_season_idx,
        key="club_list_season",
    )

    # ---------- Load data ----------
    try:
        # Use full squad loader to include players who didn't play
        df = load_full_squad(int(season))
    except Exception as e:
        st.error(f"Failed to load player data for {season}: {e}")
        st.stop()

    if df is None or df.empty:
        st.warning(f"No player data available for {season}.")
        st.stop()

    df = df.copy()

    # ---------- Validate required columns ----------
    required = ["Player", "Team", "Position", "RatingPoints_Avg"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Club List can’t run for {season}. Missing column(s): {', '.join(missing)}")
        st.stop()

    # ---------- Clean + numeric (SAFE) ----------
    df["Player"] = df["Player"].astype(str).str.strip()
    df["Team"] = df["Team"].astype(str).str.strip()
    df["Position"] = df["Position"].astype(str).str.strip()

    df["RatingPoints_Avg"] = pd.to_numeric(df["RatingPoints_Avg"], errors="coerce")

    if "Age" in df.columns:
        df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
    else:
        df["Age"] = np.nan

    if "Matches" in df.columns:
        df["Matches"] = pd.to_numeric(df["Matches"], errors="coerce")
    else:
        df["Matches"] = np.nan

    # New columns: Coaches Votes and Time on Ground
    if "CoachesVotes_Avg" in df.columns:
        df["CoachesVotes_Avg"] = pd.to_numeric(df["CoachesVotes_Avg"], errors="coerce")
    else:
        df["CoachesVotes_Avg"] = np.nan

    if "TimeOnGround" in df.columns:
        df["TimeOnGround"] = pd.to_numeric(df["TimeOnGround"], errors="coerce")
    else:
        df["TimeOnGround"] = np.nan

    # Fill missing ratings with 0 (keep all players including those who didn't play)
    df["RatingPoints_Avg"] = df["RatingPoints_Avg"].fillna(0)
    df["Matches"] = df["Matches"].fillna(0)

    # ---------- Team selector (pre-load from Home) ----------
    teams = sorted([t for t in df["Team"].dropna().unique().tolist() if str(t).strip() != ""])
    if not teams:
        st.warning(f"No teams found in data for {season}.")
        st.stop()

    default_team = st.session_state.get("default_team")
    default_selection = [default_team] if default_team in teams else [teams[0]]

    selected_teams = st.multiselect(
     "Select Team(s)",
     teams,
     default=default_selection,
        key="club_list_teams",
    )

# Keep Home pre-load behaviour (store first selected team as default_team)
    if selected_teams:
        st.session_state.default_team = selected_teams[0]
    else:
        st.session_state.default_team = default_selection[0]

    # ---------- Rating Type Selector ----------
    rating_type_col1, rating_type_col2, rating_type_col3 = st.columns([2, 2, 4])
    with rating_type_col1:
        rating_type = st.selectbox(
            "Rating Type",
            ["Rating", "Trait Rating"],
            index=0,
            key="club_list_rating_type",
            help="Select 'Rating' for Wheelo ratings or 'Trait Rating' for trait-based ratings"
        )
    
    # FC Mode toggle (only show when Trait Rating is selected)
    fc_mode = False
    if rating_type == "Trait Rating":
        with rating_type_col2:
            fc_mode = st.toggle("⚽ FC Rating Mode", key="club_list_fc_mode", help="Convert trait ratings to FIFA/FC style 50-99 scale")
    
    # ---------- Load Traits Data (if Trait Rating selected) ----------
    traits_df = None
    if rating_type == "Trait Rating":
        try:
            traits_df = load_traits(int(season))
            if traits_df is not None and not traits_df.empty:
                # Ensure numeric Rating column
                traits_df["Rating"] = pd.to_numeric(traits_df["Rating"], errors="coerce")
                traits_df["Player_Full"] = traits_df["Player_Full"].astype(str).str.strip()
                traits_df["Team_Full"] = traits_df["Team_Full"].astype(str).str.strip()
        except Exception as e:
            st.warning(f"Could not load traits data: {e}. Falling back to standard ratings.")
            traits_df = None

    # ---------- TPP (Total Player Payments) Input ----------
    tpp_col1, tpp_col2 = st.columns([2, 6])
    with tpp_col1:
        tpp_value = st.number_input(
            "TPP (Total Player Payments $)",
            min_value=0,
            max_value=50_000_000,
            value=18_000_000,
            step=100_000,
            format="%d",
            key="club_list_tpp",
            help="Enter the Total Player Payments cap for the selected season (e.g. $18,000,000)"
        )

    # ---------- Toggle ----------
    if "club_list_full" not in st.session_state:
        st.session_state.club_list_full = False

    c1, c2, _ = st.columns([1, 1, 6])
    with c1:
        if st.button("Show full list", width="stretch"):
            st.session_state.club_list_full = True
    with c2:
        if st.button("Top 5 only", width="stretch"):
            st.session_state.club_list_full = False

    # ---------- Team slice ----------
    if not selected_teams:
        st.info("Select at least one team to display.")
        st.stop()

    team_df = df[df["Team"].isin(selected_teams)].copy()

    if team_df.empty:
        st.info("No players found for this team.")
        st.stop()

    # ---------- Merge Trait Ratings if selected ----------
    if rating_type == "Trait Rating" and traits_df is not None and not traits_df.empty:
        # Create a lookup from traits_df by Player_Full and Team_Full
        traits_lookup = traits_df[["Player_Full", "Team_Full", "Rating", "Position_Full"]].copy()
        traits_lookup = traits_lookup.rename(columns={"Rating": "TraitRating", "Player_Full": "Player", "Team_Full": "Team"})
        traits_lookup["Player"] = traits_lookup["Player"].astype(str).str.strip()
        traits_lookup["Team"] = traits_lookup["Team"].astype(str).str.strip()
        traits_lookup["TraitRating"] = pd.to_numeric(traits_lookup["TraitRating"], errors="coerce")
        
        # Deduplicate: keep only the highest rated entry for each Player+Team combination
        traits_lookup = traits_lookup.sort_values("TraitRating", ascending=False).drop_duplicates(
            subset=["Player", "Team"], keep="first"
        )
        
        # Merge trait ratings into team_df
        team_df = team_df.merge(
            traits_lookup[["Player", "Team", "TraitRating"]],
            on=["Player", "Team"],
            how="left"
        )
        team_df["TraitRating"] = team_df["TraitRating"].fillna(0)
        
        # Also merge into main df for season-wide rankings
        df = df.merge(
            traits_lookup[["Player", "Team", "TraitRating"]],
            on=["Player", "Team"],
            how="left"
        )
        df["TraitRating"] = df["TraitRating"].fillna(0)
        
        # Use TraitRating as the display rating
        display_rating_col = "TraitRating"
    else:
        display_rating_col = "RatingPoints_Avg"

    team_df = team_df.sort_values(display_rating_col, ascending=False).reset_index(drop=True)

    # Calculate Ratings Total (Matches * Rating)
    team_df["RatingsTotal"] = team_df["Matches"].fillna(0) * team_df[display_rating_col].fillna(0)

    # Calculate % of Team's Ratings for each team separately
    team_ratings_sum = team_df.groupby("Team")["RatingsTotal"].transform("sum")
    team_df["PctOfTeamRatings"] = (team_df["RatingsTotal"] / team_ratings_sum * 100).round(1)

    # Calculate TPP OUTPUT (% of Team * TPP value, minimum $92,000 per player)
    MIN_PLAYER_PAYMENT = 92_000
    team_df["TPP_Output"] = (team_df["PctOfTeamRatings"] / 100 * tpp_value).clip(lower=MIN_PLAYER_PAYMENT).round(0)

    # ---------- Rankings (season-wide) ----------
    season_df = df.sort_values(display_rating_col, ascending=False).reset_index(drop=True)

    season_df["CompRank"] = season_df[display_rating_col].rank(method="min", ascending=False).astype(int)

    season_df["DepthPos"] = season_df["Position"].apply(
        lambda x: map_position_to_depth(x) if pd.notna(x) and str(x).strip() != "" else "—"
    )

    season_df["PosRank"] = (
        season_df.groupby("DepthPos")[display_rating_col]
        .rank(method="min", ascending=False)
        .astype(int)
    )

    # Merge ranks by Player (within-season unique enough)
    rank_map = season_df.set_index("Player")[["CompRank", "PosRank", "DepthPos"]]
    team_df = team_df.join(rank_map, on="Player", rsuffix="_season")

    def ordinal(n):
        if pd.isna(n):
            return "—"
        n = int(n)
        if 10 <= n % 100 <= 20:
            return f"{n}th"
        return f"{n}{ {1:'st',2:'nd',3:'rd'}.get(n%10,'th') }"

    # ---------- Build output ----------
    # Use Age_Decimal if available, otherwise fall back to Age
    age_col = "Age_Decimal" if "Age_Decimal" in team_df.columns else "Age"
    
    # Determine which rating value to display
    rating_display_values = team_df[display_rating_col] if display_rating_col in team_df.columns else team_df["RatingPoints_Avg"]
    
    # Use 2 decimal places for Trait Rating (or integer for FC mode), 1 for standard Rating
    if rating_type == "Trait Rating" and fc_mode:
        rating_decimals = 0  # FC mode uses integers
    elif rating_type == "Trait Rating":
        rating_decimals = 2
    else:
        rating_decimals = 1
    
    # Convert ratings to FC mode if enabled
    if rating_type == "Trait Rating" and fc_mode:
        out_rating = rating_display_values.apply(convert_trait_to_fc_rating)
    else:
        out_rating = pd.to_numeric(rating_display_values, errors="coerce").round(rating_decimals)
    
    out = pd.DataFrame({
        "PLAYER": team_df["Player"].fillna("—"),
        "SEASON": int(season),
        "TEAM": team_df["Team"].fillna("—"),
        "POSITION": team_df["DepthPos"].fillna("—"),
        "AGE": pd.to_numeric(team_df[age_col], errors="coerce").round(2),
        "MATCHES": pd.to_numeric(team_df["Matches"], errors="coerce").fillna(0).astype(int),
        "RATING": out_rating,
        "COMP RANK": team_df["CompRank"].apply(ordinal),
        "POS RANK": team_df["PosRank"].apply(ordinal),
        "COACHES VOTES": pd.to_numeric(team_df["CoachesVotes_Avg"], errors="coerce").round(2),
        "TOG %": pd.to_numeric(team_df["TimeOnGround"], errors="coerce").round(1),
        "RATINGS TOTAL": pd.to_numeric(team_df["RatingsTotal"], errors="coerce").round(1),
        "% OF TEAM": pd.to_numeric(team_df["PctOfTeamRatings"], errors="coerce").round(1),
        "TPP OUTPUT": pd.to_numeric(team_df["TPP_Output"], errors="coerce").round(0),
    })


    if not st.session_state.club_list_full:
        out = out.head(5).copy()

    # ---------- Render using unified table system ----------
    # Use the appropriate rating column for color scaling
    league_ratings = season_df[display_rating_col].dropna() if display_rating_col in season_df.columns else season_df["RatingPoints_Avg"].dropna()
    
    # Convert league ratings to FC mode for proper color scaling
    if rating_type == "Trait Rating" and fc_mode:
        league_ratings = league_ratings.apply(convert_trait_to_fc_rating).dropna()
    
    # Dynamic column header based on rating type
    if rating_type == "Trait Rating" and fc_mode:
        rating_header = "FC RATING"
    elif rating_type == "Trait Rating":
        rating_header = "TRAIT RATING"
    else:
        rating_header = "RATING"

    html = f"""
<table class="fe-table fe-sortable">
<thead>
<tr>
<th>PLAYER</th>
<th>SEASON</th>
<th>TEAM</th>
<th>POSITION</th>
<th>AGE</th>
<th>MATCHES</th>
<th>{rating_header}</th>
<th>COMP RANK</th>
<th>POS RANK</th>
<th>COACHES VOTES</th>
<th>TOG %</th>
<th>RATINGS TOTAL</th>
<th>% OF TEAM</th>
<th>TPP OUTPUT</th>
</tr>
</thead>
<tbody>
"""

    for _, r in out.iterrows():
        rating_val = r["RATING"]
        bg, fg = rating_colour_for_value(rating_val, league_ratings)

        age_val = r["AGE"]
        age_str = "—" if pd.isna(age_val) else f"{float(age_val):.1f}"

        matches_val = r["MATCHES"]
        matches_str = "—" if pd.isna(matches_val) else f"{int(matches_val)}"

        # Use 2 decimal places for Trait Rating (or integer for FC mode), 1 for standard Rating
        if rating_type == "Trait Rating" and fc_mode:
            rating_str = "—" if pd.isna(rating_val) else f"{int(rating_val)}"
        elif rating_type == "Trait Rating":
            rating_str = "—" if pd.isna(rating_val) else f"{float(rating_val):.2f}"
        else:
            rating_str = "—" if pd.isna(rating_val) else f"{float(rating_val):.1f}"

        coaches_val = r["COACHES VOTES"]
        coaches_str = "—" if pd.isna(coaches_val) else f"{float(coaches_val):.2f}"

        tog_val = r["TOG %"]
        tog_str = "—" if pd.isna(tog_val) else f"{float(tog_val):.1f}%"

        ratings_total_val = r["RATINGS TOTAL"]
        ratings_total_str = "—" if pd.isna(ratings_total_val) else f"{float(ratings_total_val):.1f}"

        pct_team_val = r["% OF TEAM"]
        pct_team_str = "—" if pd.isna(pct_team_val) else f"{float(pct_team_val):.1f}%"

        tpp_output_val = r["TPP OUTPUT"]
        tpp_output_str = "—" if pd.isna(tpp_output_val) else f"${int(tpp_output_val):,}"

        html += f"""
<tr>
<td>{r['PLAYER']}</td>
<td>{r['SEASON']}</td>
<td>{r['TEAM']}</td>
<td>{r['POSITION']}</td>
<td>{age_str}</td>
<td>{matches_str}</td>
<td style="background-color:{bg}; color:{fg}; font-weight:900;">{rating_str}</td>
<td>{r['COMP RANK']}</td>
<td>{r['POS RANK']}</td>
<td>{coaches_str}</td>
<td>{tog_str}</td>
<td>{ratings_total_str}</td>
<td>{pct_team_str}</td>
<td>{tpp_output_str}</td>
</tr>
"""


    html += "</tbody></table>"

    # Use render_sortable_table for working JavaScript sorting
    render_sortable_table(html)
    
    # Professional footer
    render_footer()


# ================= PLAYER PROFILE =================
elif page == "Player Profile":
    import textwrap

    render_page_header("Player Profile", "Individual Player Analysis", "👤")
    
    # Breadcrumb navigation (will update with player name once selected)
    render_breadcrumb([("Home", "Home"), ("Player Profile", None)])

    # Using global helpers from config: get_ordinal, safe_float

    # -----------------------------------
    # Load ALL player data for all seasons
    # -----------------------------------
    all_players_all = []
    for s in get_player_seasons():
        df_s = load_players(s)
        if df_s is None or df_s.empty:
            continue
        df_s = df_s.copy()
        df_s["Season"] = s
        all_players_all.append(df_s)

    if not all_players_all:
        st.error("No player data found across seasons.")
        st.stop()

    players_full = pd.concat(all_players_all, ignore_index=True)
    players_full = _normalise_rating_column(players_full)

    # Ensure numeric season + rating
    players_full["Season"] = pd.to_numeric(players_full["Season"], errors="coerce")
    players_full["RatingPoints_Avg"] = pd.to_numeric(players_full["RatingPoints_Avg"], errors="coerce")

    # -----------------------------------
    # Season filter - default to 2025
    # -----------------------------------
    seasons_available = sorted(players_full["Season"].dropna().unique().tolist(), reverse=True)
    if not seasons_available:
        st.error("No valid seasons available.")
        st.stop()

    default_season_idx = seasons_available.index(2025) if 2025 in seasons_available else 0
    
    # Season and FC Mode controls in columns
    ctrl_col1, ctrl_col2 = st.columns([2, 1])
    with ctrl_col1:
        selected_season = st.selectbox("Select Season", seasons_available, index=default_season_idx, key="pp_season")
    with ctrl_col2:
        fc_mode = st.toggle("⚽ FC Rating Mode (50-99)", key="pp_fc_mode", help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")

    # Filter by selected season
    players_season = players_full[players_full["Season"] == selected_season].copy()

    # Team selection
    teams = sorted([t for t in players_season["Team"].dropna().unique().tolist() if str(t).strip() != ""])
    if not teams:
        st.warning("No teams found for this season.")
        st.stop()

    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        default_idx = teams.index(st.session_state.default_team)

    selected_team = st.selectbox("Select Team", teams, index=default_idx, key="pp_team")
    st.session_state["default_team"] = selected_team

    # Player selection with favorite star
    team_players = players_season[players_season["Team"] == selected_team].copy()
    player_names = sorted([p for p in team_players["Player"].dropna().unique().tolist() if str(p).strip() != ""])
    if not player_names:
        st.warning("No players found for this team.")
        st.stop()

    # Check if a player was searched for and pre-select them
    player_default_idx = 0
    if "selected_player_search" in st.session_state and st.session_state.selected_player_search:
        searched_player = st.session_state.selected_player_search
        if searched_player in player_names:
            player_default_idx = player_names.index(searched_player)
        # Clear the search state after using it
        st.session_state.selected_player_search = None

    player_col1, player_col2 = st.columns([5, 1])
    with player_col1:
        selected_player = st.selectbox("Select Player", player_names, index=player_default_idx, key="pp_player")
    with player_col2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        player_fav_key = f"{selected_player}|{selected_team}"
        is_player_fav = player_fav_key in st.session_state.favorite_players
        star_label = "⭐ Favorited" if is_player_fav else "☆ Favorite"
        if st.button(star_label, key="fav_player_profile"):
            toggle_favorite_player(selected_player, selected_team)
            st.rerun()
    
    # Track in recent views
    add_to_recent_views("player", selected_player, selected_team, "Player Profile")

    # Get all seasons for this player
    player_data_all = players_full[players_full["Player"] == selected_player].copy()
    if player_data_all.empty:
        st.info("No data found for this player.")
        st.stop()

    player_data_all["Season"] = pd.to_numeric(player_data_all["Season"], errors="coerce")
    player_data_all["RatingPoints_Avg"] = pd.to_numeric(player_data_all["RatingPoints_Avg"], errors="coerce")

    latest_record = player_data_all.sort_values("Season", ascending=False).iloc[0]

    # -----------------------------------
    # Layout: logo + photo + meta
    # -----------------------------------
    col_photo, col_meta = st.columns([1, 3])

    latest_team = str(latest_record.get("Team", "")).strip()
    if latest_team:
        _, logo_col, _ = col_photo.columns([1, 2, 1])
        display_logo(latest_team, logo_col, size=160)

    display_player_photo(selected_player, col_photo, use_container_width=True)

    # Summary meta
    summary_df = load_player_summary()
    if summary_df is None or summary_df.empty or "Player" not in summary_df.columns:
        summary_match = pd.DataFrame()
    else:
        summary_match = summary_df[summary_df["Player"] == selected_player]

    summary_row = summary_match.iloc[0] if not summary_match.empty else None

    latest_position = latest_record.get("Position", "")
    latest_matches = latest_record.get("Matches", None)

    age_summary = summary_row.get("Age") if summary_row is not None else None

    draft_year = None
    if summary_row is not None:
        draft_year = summary_row.get("Draft Year") if "Draft Year" in summary_row.index else summary_row.get("Draft")

    draft_no = summary_row.get("Draft #") if summary_row is not None else None
    height_summary = summary_row.get("Height") if summary_row is not None else None
    total_matches = summary_row.get("Total Matches") if summary_row is not None else None
    rating_pct_2025 = summary_row.get("2025 Rating %") if summary_row is not None else None
    cap_value_2025 = summary_row.get("2025 Cap Value") if summary_row is not None else None

    # Load Contract Expiry and FA Status from Footywire data
    contract_expiry = None
    fa_status = None
    footywire_path = Path(__file__).parent / "data" / "raw" / "player" / "footywire_2026_complete.csv"
    if footywire_path.exists():
        try:
            fw_df = pd.read_csv(footywire_path)
            fw_df["Player"] = fw_df["Player"].astype(str).str.strip()
            fw_df["Team"] = fw_df["Team"].astype(str).str.strip()
            fw_match = fw_df[(fw_df["Player"] == selected_player) & (fw_df["Team"] == latest_team)]
            if not fw_match.empty:
                contract_expiry = fw_match.iloc[0].get("Contract_Expiry")
                fa_status = fw_match.iloc[0].get("FA_Status")
        except Exception:
            pass

    # Header
    header_html = f"""
    <div style='background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
                border-left: 5px solid #FFFFFF; padding: 20px; border-radius: 12px; margin-bottom: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);'>
        <h2 style='color: #FFFFFF; margin: 0; font-size: 2.2em; font-weight: 900;'>{selected_player}</h2>
    </div>
    """
    render_html(col_meta, header_html)

    # TEAM / POSITION cards
    info_cards = []
    if latest_team:
        info_cards.append(f"""
        <div style='background: linear-gradient(135deg, #2a2a2a 0%, #404040 100%);
                    border-left: 4px solid #CCCCCC; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.85em; margin-bottom: 4px;'>TEAM</div>
            <div style='color: #FFFFFF; font-size: 1.3em; font-weight: 800;'>{latest_team}</div>
        </div>
        """)
    if latest_position:
        info_cards.append(f"""
        <div style='background: linear-gradient(135deg, rgba(180, 83, 9, 0.8) 0%, rgba(245, 158, 11, 0.6) 100%);
                    border-left: 4px solid #f59e0b; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.85em; margin-bottom: 4px;'>POSITION</div>
            <div style='color: #FFFFFF; font-size: 1.3em; font-weight: 800;'>{latest_position}</div>
        </div>
        """)
    if info_cards:
        render_html(col_meta, "".join(info_cards))

    # -----------------------------------
    # Player Stats Grid (2-column fixed)
    # -----------------------------------
    stats_grid = []

    # AGE
    age_val = safe_float(age_summary)
    if age_val is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>AGE</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{age_val:.1f}</div>
        </div>
        """)
    elif age_summary not in [None, ""]:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>AGE</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{age_summary}</div>
        </div>
        """)

    # 2025 RATING %
    if rating_pct_2025 not in [None, ""] and pd.notna(rating_pct_2025):
        try:
            rating_pct_val = float(rating_pct_2025)
            rating_pct_values = summary_df["2025 Rating %"].dropna() if summary_df is not None and "2025 Rating %" in summary_df.columns else pd.Series(dtype=float)
            pct_bg, pct_fg = rating_colour_for_value(rating_pct_val, rating_pct_values)

            if pct_bg == "#008000":
                pct_gradient = "rgba(0,128,0,0.3)"
            elif pct_bg == "#90EE90":
                pct_gradient = "rgba(144,238,144,0.3)"
            elif pct_bg == "#FFA500":
                pct_gradient = "rgba(255,165,0,0.3)"
            else:
                pct_gradient = "rgba(255,0,0,0.3)"

            stats_grid.append(f"""
            <div style='background: {pct_gradient}; padding: 10px; border-radius: 6px; text-align: center;
                        border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>2025 RATING %</div>
                <div style='color: {pct_fg}; font-size: 1.4em; font-weight: 700;'>{rating_pct_val:.1f}%</div>
            </div>
            """)
        except Exception:
            stats_grid.append(f"""
            <div style='background: rgba(0,0,0,0.3); padding: 10px; border-radius: 6px; text-align: center;
                        border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>2025 RATING %</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{rating_pct_2025}%</div>
            </div>
            """)

    # 2025 CAP VALUE
    if cap_value_2025 not in [None, ""] and pd.notna(cap_value_2025):
        try:
            cap_val = float(cap_value_2025)
            stats_grid.append(f"""
            <div style='background: rgba(100,100,100,0.2); padding: 10px; border-radius: 6px; text-align: center;
                        border: 1px solid rgba(100,100,100,0.5);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>2025 CAP VALUE</div>
                <div style='color: rgba(255, 255, 255, 0.95); font-size: 1.4em; font-weight: 700;'>${cap_val:,.0f}</div>
            </div>
            """)
        except Exception:
            stats_grid.append(f"""
            <div style='background: rgba(100,100,100,0.2); padding: 10px; border-radius: 6px; text-align: center;
                        border: 1px solid rgba(100,100,100,0.5);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>2025 CAP VALUE</div>
                <div style='color: rgba(255, 255, 255, 0.95); font-size: 1.4em; font-weight: 700;'>${cap_value_2025}</div>
            </div>
            """)

    # DRAFT #
    dn = safe_int(draft_no)
    if dn is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>DRAFT #</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{dn}</div>
        </div>
        """)
    elif draft_no not in [None, ""] and pd.notna(draft_no):
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>DRAFT #</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{draft_no}</div>
        </div>
        """)

    # DRAFT YEAR
    dy = safe_int(draft_year)
    if dy is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>DRAFT YEAR</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{dy}</div>
        </div>
        """)
    elif draft_year not in [None, ""] and pd.notna(draft_year):
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>DRAFT YEAR</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{draft_year}</div>
        </div>
        """)

    # HEIGHT
    hv = safe_float(height_summary)
    if hv is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>HEIGHT</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{hv:.0f}
                <span style='font-size: 0.7em; color: rgba(255,255,255,0.7);'>cm</span>
            </div>
        </div>
        """)
    elif height_summary not in [None, ""] and pd.notna(height_summary):
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>HEIGHT</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{height_summary}
                <span style='font-size: 0.7em; color: rgba(255,255,255,0.7);'>cm</span>
            </div>
        </div>
        """)

    # TOTAL MATCHES
    tm = safe_int(total_matches)
    if tm is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>TOTAL MATCHES</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{tm}</div>
        </div>
        """)

    # CONTRACT EXPIRY
    ce = safe_int(contract_expiry)
    if ce is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>CONTRACT EXPIRY</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{ce}</div>
        </div>
        """)
    elif contract_expiry not in [None, ""] and pd.notna(contract_expiry):
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>CONTRACT EXPIRY</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{contract_expiry}</div>
        </div>
        """)

    # FA STATUS
    if fa_status not in [None, ""] and pd.notna(fa_status):
        # Color coding for FA status
        fa_colors = {
            "Unrestricted Free Agent": ("rgba(255,68,68,0.3)", "#FF4444"),
            "Restricted Free Agent": ("rgba(255,165,0,0.3)", "#FFA500"),
            "Non-Free Agent": ("rgba(76,175,80,0.3)", "#4CAF50"),
            "Delisted Free Agent": ("rgba(255,102,102,0.3)", "#FF6666"),
        }
        fa_bg, fa_border = fa_colors.get(str(fa_status), ("rgba(136,136,136,0.3)", "#888888"))
        # Shorten label for display
        if "Unrestricted" in str(fa_status):
            fa_short = "UFA"
        elif "Restricted" in str(fa_status) and "Unrestricted" not in str(fa_status):
            fa_short = "RFA"
        elif "Non-Free" in str(fa_status):
            fa_short = "Non-FA"
        elif "Delisted" in str(fa_status):
            fa_short = "DFA"
        else:
            fa_short = str(fa_status)[:12]
        stats_grid.append(f"""
        <div style='background: {fa_bg}; padding: 10px; border-radius: 6px; text-align: center;
                    border: 1px solid {fa_border};'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>FA STATUS</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{fa_short}</div>
        </div>
        """)

    if stats_grid:
        grid_html = f"""
        <div style='display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 15px;'>
            {''.join([textwrap.dedent(x).strip() for x in stats_grid])}
        </div>
        """
        render_html(col_meta, grid_html)


    # -----------------------------------
    # Rating by Season bar chart
    # -----------------------------------
    st.markdown("---")
    st.markdown("<h3 style='color: #FFFFFF; margin-bottom: 15px;'>📊 Rating by Season</h3>", unsafe_allow_html=True)

    plot_df = player_data_all.dropna(subset=["RatingPoints_Avg"]).copy()
    if plot_df.empty:
        st.info("No rating data to chart.")
    else:
        all_ratings = players_full["RatingPoints_Avg"].dropna()

        def colour_for_value(v):
            perc = (all_ratings <= v).mean()
            if perc >= 0.85:
                return "darkgreen"
            elif perc >= 0.60:
                return "lightgreen"
            elif perc >= 0.35:
                return "orange"
            else:
                return "red"

        plot_df["Color"] = plot_df["RatingPoints_Avg"].apply(colour_for_value)

        chart = (
            alt.Chart(plot_df)
            .mark_bar()
            .encode(
                x=alt.X("Season:O", sort="ascending"),
                y=alt.Y("RatingPoints_Avg:Q", title="Rating (avg)"),
                color=alt.Color("Color:N", scale=None, legend=None),
                tooltip=["Season", alt.Tooltip("RatingPoints_Avg:Q", format=".1f")],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, width="stretch")

    # -----------------------------------
    # Performance Projection (Next 5 Years)
    # -----------------------------------
    st.markdown("---")
    st.markdown("<h3 style='color: #FFFFFF; margin-bottom: 15px;'>🔮 Performance Projection (Next 5 Years)</h3>", unsafe_allow_html=True)

    try:
        latest_rating_val = float(latest_record.get("RatingPoints_Avg", 50)) if pd.notna(latest_record.get("RatingPoints_Avg")) else 50
        latest_age_val = float(latest_record.get("Age", 25)) if pd.notna(latest_record.get("Age")) else 25

        historical_ratings = plot_df.sort_values("Season")["RatingPoints_Avg"].dropna().tolist() if not plot_df.empty else []

        prediction_df = predict_player_trajectory(
            player_name=selected_player,
            position=latest_position,
            current_age=latest_age_val,
            current_rating=latest_rating_val,
            historical_ratings=historical_ratings,
            all_players_df=players_full,
            current_season=CURRENT_SEASON,
            projection_years=5,
            confidence_band=0.15,
        )

        if prediction_df is not None and not prediction_df.empty:
            pred = prediction_df.copy()

            band = (
                alt.Chart(pred)
                .mark_area(opacity=0.2, color="steelblue")
                .encode(
                    x=alt.X("Year:O", title="Year"),
                    y="Lower_Band:Q",
                    y2="Upper_Band:Q",
                    tooltip=[
                        alt.Tooltip("Lower_Band:Q", format=".1f", title="Lower (−15%)"),
                        alt.Tooltip("Upper_Band:Q", format=".1f", title="Upper (+15%)"),
                    ],
                )
            )

            line = (
                alt.Chart(pred)
                .mark_line(point=True, color="steelblue", size=3)
                .encode(
                    x=alt.X("Year:O"),
                    y=alt.Y("Predicted_Rating:Q", title="Predicted Rating", scale=alt.Scale(zero=False)),
                    tooltip=["Year", alt.Tooltip("Predicted_Rating:Q", format=".1f")],
                )
            )

            hist_chart = None
            if not plot_df.empty:
                hist_chart = (
                    alt.Chart(plot_df.reset_index(drop=True))
                    .mark_circle(color="gray", size=100, opacity=0.6)
                    .encode(
                        x=alt.X("Season:O", title="Year"),
                        y=alt.Y("RatingPoints_Avg:Q", title="Rating"),
                        tooltip=["Season", alt.Tooltip("RatingPoints_Avg:Q", format=".1f", title="Historical Rating")],
                    )
                )

            combined = band + line
            if hist_chart is not None:
                combined = combined + hist_chart

            st.altair_chart(combined.properties(height=300).interactive(), width="stretch")

            with st.expander("📊 View Detailed Predictions", expanded=False):
                pred_table = pred.copy()
                for c in ["Predicted_Rating", "Upper_Band", "Lower_Band"]:
                    if c in pred_table.columns:
                        pred_table[c] = pd.to_numeric(pred_table[c], errors="coerce").round(1)
                st.dataframe(pred_table, hide_index=True, width="stretch")
        else:
            st.info("Unable to generate performance projection with available data.")
    except Exception as e:
        st.warning(f"Could not generate performance projection: {str(e)}")

    # -----------------------------------
    # Player Season Data (HTML table)
    # -----------------------------------
    st.markdown("---")
    st.markdown("<h3 style='color: #CCCCCC; margin-bottom: 15px;'>📋 Player Season Data</h3>", unsafe_allow_html=True)

    player_table = plot_df.copy()
    if player_table.empty:
        st.info("No season rows to show.")
    else:
        age_col = "Age_Decimal" if "Age_Decimal" in player_table.columns else ("Age" if "Age" in player_table.columns else None)
        if age_col:
            player_table[age_col] = pd.to_numeric(player_table[age_col], errors="coerce").round(1)

        player_table["RatingPoints_Avg"] = pd.to_numeric(player_table["RatingPoints_Avg"], errors="coerce").round(1)

        cols = [c for c in ["Season", "Team", "Position", age_col, "Matches", "RatingPoints_Avg"] if c and c in player_table.columns]
        player_table = player_table[cols].drop_duplicates().reset_index(drop=True)

        competition_ranks, positional_ranks = [], []
        for _, row in player_table.iterrows():
            season = row["Season"]
            position = row["Position"]
            rating = row["RatingPoints_Avg"]

            season_players = players_full[players_full["Season"] == season].copy()
            season_players["RatingPoints_Avg"] = pd.to_numeric(season_players["RatingPoints_Avg"], errors="coerce")

            comp_rank = (season_players["RatingPoints_Avg"] >= rating).sum()
            competition_ranks.append(get_ordinal(comp_rank))

            try:
                position_players = season_players[
                    season_players["Position"].apply(lambda p: map_position_to_depth(p) if pd.notna(p) else "") ==
                    (map_position_to_depth(position) if pd.notna(position) else "")
                ]
            except Exception:
                position_players = season_players[season_players["Position"].astype(str) == str(position)]

            pos_rank = (position_players["RatingPoints_Avg"] >= rating).sum()
            positional_ranks.append(get_ordinal(pos_rank))

        player_table["Competition_Rank"] = competition_ranks
        player_table["Positional_Rank"] = positional_ranks

        rename_map = {}
        if age_col and age_col in player_table.columns:
            rename_map[age_col] = "Age"
        rename_map["RatingPoints_Avg"] = "Rating"
        rename_map["Competition_Rank"] = "Comp Rank"
        rename_map["Positional_Rank"] = "Pos Rank"
        player_table = player_table.rename(columns=rename_map)

        cols2 = list(player_table.columns)
        cols2.remove("Comp Rank")
        cols2.remove("Pos Rank")
        player_table = player_table[["Comp Rank", "Pos Rank"] + cols2]

        # Uses unified .fe-table CSS
        html_season_table = """
        <table class='fe-table fe-table-striped fe-sortable'>
        <thead><tr>
        """
        for col in player_table.columns:
            html_season_table += f"<th>{col}</th>"
        html_season_table += "</tr></thead><tbody>"

        all_comp_ratings = players_full["RatingPoints_Avg"].dropna()

        for _, row in player_table.iterrows():
            html_season_table += "<tr>"
            for col in player_table.columns:
                if col == "Rating":
                    rating_val = row[col]
                    if pd.notna(rating_val):
                        bg_color, text_color = rating_colour_for_value(float(rating_val), all_comp_ratings)
                        html_season_table += f"<td style='background-color: {bg_color}; color: {text_color}; font-weight: 800;'>{float(rating_val):.1f}</td>"
                    else:
                        html_season_table += "<td>–</td>"
                else:
                    html_season_table += f"<td>{row[col]}</td>"
            html_season_table += "</tr>"

        html_season_table += "</tbody></table>"
        render_sortable_table(html_season_table)

    # -----------------------------------
    # Traits Snapshot (ENRICHED, selected season) - Professional Card Design
    # -----------------------------------
    st.markdown("<div style='margin-top: 40px;'></div>", unsafe_allow_html=True)

    try:
        traits_selected = load_traits(int(selected_season))
        if traits_selected is not None and not traits_selected.empty and "Player_Full" in traits_selected.columns:
            # Use smart matching function to handle abbreviated names
            t = match_player_name_to_traits(selected_player, traits_selected, latest_team)
            if not t.empty:
                row = t.iloc[0]
                
                # Get all ratings for percentile calculation
                all_ratings = pd.to_numeric(traits_selected["Rating"], errors="coerce").dropna()
                
                def get_trait_color_and_label(val, all_vals):
                    """Return color and label based on percentile ranking."""
                    try:
                        v = float(val)
                        percentile = (all_vals < v).sum() / len(all_vals) * 100
                        if percentile >= 75:
                            return "#00C853", "Elite"
                        elif percentile >= 50:
                            return "#FFC107", "Above Avg"
                        elif percentile >= 25:
                            return "#FF9800", "Below Avg"
                        else:
                            return "#F44336", "Poor"
                    except:
                        return "#9E9E9E", "—"
                
                # Header
                st.markdown("""
                <div style='display: flex; align-items: center; margin-bottom: 20px; margin-top: 20px;'>
                    <span style='font-size: 1.5em; margin-right: 12px;'>🎯</span>
                    <h3 style='color: #FFFFFF; margin: 0; font-size: 1.4em; font-weight: 700;'>Player Traits Analysis</h3>
                    <span style='margin-left: 12px; background: rgba(255,255,255,0.1); padding: 4px 12px; border-radius: 20px; font-size: 0.85em; color: rgba(255,255,255,0.7);'>ENRICHED</span>
                </div>
                """, unsafe_allow_html=True)
                
                # Use Streamlit columns for reliable rendering
                trait_cols = st.columns(5)
                metrics = [
                    ("Rating", "Rating", row.get("Rating")),
                    ("Ball Winning", "Ball Winning", row.get("Ball Winning")),
                    ("Ball Use", "Ball Use", row.get("Ball Use")),
                    ("Aerial", "Aerial", row.get("Aerial")),
                    ("Defence", "Defence", row.get("Defence")),
                ]
                
                for i, (label, col_name, val) in enumerate(metrics):
                    with trait_cols[i]:
                        v = safe_float(val)
                        all_trait_vals = pd.to_numeric(traits_selected[col_name], errors="coerce").dropna() if col_name in traits_selected.columns else all_ratings
                        color, tier_orig = get_trait_color_and_label(v, all_trait_vals) if v else ("#9E9E9E", "—")
                        
                        # Format based on FC mode
                        if fc_mode and v:
                            display_val = str(convert_trait_to_fc_rating(v))
                            tier = get_fc_rating_label(convert_trait_to_fc_rating(v))
                        else:
                            display_val = f"{v:.2f}" if v else "—"
                            tier = tier_orig
                        
                        st.markdown(f"""
                        <div style='background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(0,0,0,0.1) 100%);
                                    border: 1px solid rgba(255,255,255,0.1); border-left: 3px solid {color};
                                    border-radius: 10px; padding: 16px 10px; text-align: center;'>
                            <div style='font-size: 0.7em; color: rgba(255,255,255,0.5); text-transform: uppercase;
                                        letter-spacing: 1px; margin-bottom: 6px; font-weight: 600;'>{label}</div>
                            <div style='font-size: 1.8em; font-weight: 800; color: {color}; line-height: 1;'>{display_val}</div>
                            <div style='font-size: 0.65em; color: rgba(255,255,255,0.4); margin-top: 4px;'>{tier}</div>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.info("No ENRICHED traits row found for this player in the selected season.")
        else:
            st.info("Traits file not loaded / empty.")
    except Exception:
        st.info("Traits section unavailable (load_traits not ready).")

    # -----------------------------------
    # Full Player Traits section (2025) - big card UI
    # -----------------------------------
    try:
        def get_trait_label(value):
            try:
                val = float(value)
                if val > 3.0:
                    return "Elite"
                elif val >= 2.5:
                    return "Above Average"
                elif val >= 2.0:
                    return "Below Average"
                else:
                    return "Poor"
            except Exception:
                return ""

        traits_2025 = load_traits(CURRENT_SEASON)
        if traits_2025 is not None and not traits_2025.empty and "Player_Full" in traits_2025.columns:
            # Use smart matching function to handle abbreviated names
            player_traits_2025 = match_player_name_to_traits(selected_player, traits_2025, latest_team)

            if "Season" in player_traits_2025.columns:
                player_traits_2025["Season"] = pd.to_numeric(player_traits_2025["Season"], errors="coerce")
                player_traits_2025 = player_traits_2025[player_traits_2025["Season"] == CURRENT_SEASON]

            if not player_traits_2025.empty:
                player_trait = player_traits_2025.iloc[0]

                rating = player_trait.get("Rating", None)
                ball_winning = player_trait.get("Ball Winning", None)
                ball_use = player_trait.get("Ball Use", None)
                aerial = player_trait.get("Aerial", None)
                defence = player_trait.get("Defence", None)
                position = player_trait.get("Position_Full", player_trait.get("Position", latest_position))

                # ---------------------------
                # KPI CARDS (FIXED POSITION RANK)
                # ---------------------------

                all_traits_sorted = traits_2025.copy()

                # Ensure we only use 2025 rows if Season exists
                if "Season" in all_traits_sorted.columns:
                    all_traits_sorted["Season"] = pd.to_numeric(all_traits_sorted["Season"], errors="coerce")
                    all_traits_sorted = all_traits_sorted[all_traits_sorted["Season"] == 2025]

                # Ensure needed cols exist
                if "Player_Full" not in all_traits_sorted.columns and "Player" in all_traits_sorted.columns:
                    all_traits_sorted["Player_Full"] = all_traits_sorted["Player"]

                # Numeric Rating, overall sort
                all_traits_sorted["Rating"] = pd.to_numeric(all_traits_sorted["Rating"], errors="coerce")
                all_traits_sorted = (
                    all_traits_sorted
                    .dropna(subset=["Rating"])
                    .sort_values("Rating", ascending=False)
                    .reset_index(drop=True)
                )

                rv = safe_float(rating)
                overall_rank = None
                position_rank = None

                # ---- Overall rank (competition-wide) ----
                if rv is not None and not all_traits_sorted.empty:
                    try:
                        overall_rank = int(all_traits_sorted[all_traits_sorted["Player_Full"] == selected_player].index[0] + 1)
                    except Exception:
                        overall_rank = int((all_traits_sorted["Rating"] >= rv).sum())

                # ---- Position rank (WITHIN position group) ----
                pos_df = pd.DataFrame()
                pos_col = "Position_Full" if "Position_Full" in all_traits_sorted.columns else ("Position" if "Position" in all_traits_sorted.columns else None)

                if rv is not None and pos_col and position not in [None, ""] and not all_traits_sorted.empty:
                    pos_df = all_traits_sorted[all_traits_sorted[pos_col].astype(str) == str(position)].copy()

                    if not pos_df.empty:
                        # CRITICAL FIX: re-sort + reset_index INSIDE position group
                        pos_df["Rating"] = pd.to_numeric(pos_df["Rating"], errors="coerce")
                        pos_df = (
                            pos_df
                            .dropna(subset=["Rating"])
                            .sort_values("Rating", ascending=False)
                            .reset_index(drop=True)
                        )

                        try:
                            position_rank = int(pos_df[pos_df["Player_Full"] == selected_player].index[0] + 1)
                        except Exception:
                            position_rank = int((pos_df["Rating"] >= rv).sum())

                # ---------------------------
                # Render Professional KPI Dashboard
                # ---------------------------
                
                st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
                
                # Header
                st.markdown("""
                <div style='display: flex; align-items: center; justify-content: center; margin-bottom: 20px;'>
                    <span style='font-size: 1.5em; margin-right: 12px;'>⭐</span>
                    <h3 style='color: #FFFFFF; margin: 0; font-size: 1.4em; font-weight: 700;'>Performance Rankings</h3>
                    <span style='margin-left: 12px; background: rgba(255,215,0,0.2); padding: 4px 12px; border-radius: 20px; font-size: 0.85em; color: #FFD700;'>2025</span>
                </div>
                """, unsafe_allow_html=True)

                # Use Streamlit columns
                kpi_cols = st.columns(3)
                
                if rv is not None:
                    all_ratings_traits = pd.to_numeric(all_traits_sorted["Rating"], errors="coerce").dropna()
                    bg_color, _ = rating_colour_for_value(rv, all_ratings_traits)
                    
                    # Format based on FC mode
                    if fc_mode:
                        rating_display = str(convert_trait_to_fc_rating(rv))
                        rating_label = get_fc_rating_label(convert_trait_to_fc_rating(rv))
                    else:
                        rating_display = f"{rv:.2f}"
                        rating_label = get_trait_label(rv)
                    
                    # Determine tier color
                    if rv >= 3.0:
                        tier_color = "#00C853"
                    elif rv >= 2.5:
                        tier_color = "#8BC34A"
                    elif rv >= 2.0:
                        tier_color = "#FFC107"
                    else:
                        tier_color = "#F44336"
                    
                    with kpi_cols[0]:
                        st.markdown(f"""
                        <div style='background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(0,0,0,0.1) 100%);
                                    border: 1px solid rgba(255,255,255,0.1); border-top: 3px solid {tier_color};
                                    border-radius: 12px; padding: 20px 16px; text-align: center;'>
                            <div style='font-size: 0.75em; color: rgba(255,255,255,0.5); text-transform: uppercase;
                                        letter-spacing: 1.5px; margin-bottom: 10px; font-weight: 600;'>Overall Rating</div>
                            <div style='font-size: 2.8em; font-weight: 800; color: {tier_color}; line-height: 1;'>{rating_display}</div>
                            <div style='margin-top: 10px; display: inline-block; background: rgba(255,255,255,0.1);
                                        padding: 4px 12px; border-radius: 15px; font-size: 0.8em; color: {tier_color};
                                        font-weight: 600;'>{rating_label}</div>
                        </div>
                        """, unsafe_allow_html=True)

                if overall_rank:
                    with kpi_cols[1]:
                        st.markdown(f"""
                        <div style='background: linear-gradient(135deg, rgba(255,215,0,0.1) 0%, rgba(0,0,0,0.1) 100%);
                                    border: 1px solid rgba(255,255,255,0.1); border-top: 3px solid #FFD700;
                                    border-radius: 12px; padding: 20px 16px; text-align: center;'>
                            <div style='font-size: 0.75em; color: rgba(255,255,255,0.5); text-transform: uppercase;
                                        letter-spacing: 1.5px; margin-bottom: 10px; font-weight: 600;'>League Rank</div>
                            <div style='font-size: 2.8em; font-weight: 800; color: #FFD700; line-height: 1;'>{get_ordinal(overall_rank)}</div>
                            <div style='margin-top: 10px; font-size: 0.75em; color: rgba(255,255,255,0.5);'>
                                out of <span style='color: #FFD700; font-weight: 600;'>{len(all_traits_sorted)}</span> players
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                if position_rank and position:
                    with kpi_cols[2]:
                        st.markdown(f"""
                        <div style='background: linear-gradient(135deg, rgba(100,149,237,0.1) 0%, rgba(0,0,0,0.1) 100%);
                                    border: 1px solid rgba(255,255,255,0.1); border-top: 3px solid #6495ED;
                                    border-radius: 12px; padding: 20px 16px; text-align: center;'>
                            <div style='font-size: 0.75em; color: rgba(255,255,255,0.5); text-transform: uppercase;
                                        letter-spacing: 1.5px; margin-bottom: 10px; font-weight: 600;'>Position Rank</div>
                            <div style='font-size: 2.8em; font-weight: 800; color: #6495ED; line-height: 1;'>{get_ordinal(position_rank)}</div>
                            <div style='margin-top: 10px; display: inline-block; background: rgba(100,149,237,0.2);
                                        padding: 4px 12px; border-radius: 15px; font-size: 0.8em; color: #6495ED;
                                        font-weight: 600;'>{position}</div>
                        </div>
                        """, unsafe_allow_html=True)

                st.markdown("<div style='margin-top: 40px;'></div>", unsafe_allow_html=True)
                st.markdown("""
                <div style='display: flex; align-items: center; justify-content: center; margin-bottom: 24px;'>
                    <span style='font-size: 1.5em; margin-right: 12px;'>📊</span>
                    <h3 style='color: #FFFFFF; margin: 0; font-size: 1.4em; font-weight: 700;'>Trait Analysis</h3>
                </div>
                """, unsafe_allow_html=True)

                ball_winning_substats = {
                    "Stoppage": player_trait.get("Stoppage", ""),
                    "Contest": player_trait.get("Contest", ""),
                    "Power": player_trait.get("Power", ""),
                    "Receives": player_trait.get("Receives", "")
                }
                ball_use_substats = {
                    "Handballing": player_trait.get("Handballing", ""),
                    "Kicking": player_trait.get("Kicking", ""),
                    "Goal Kicking": player_trait.get("Goal Kicking", ""),
                    "Connecting": player_trait.get("Connecting", "")
                }
                aerial_substats = {
                    "Marking": player_trait.get("Marking", ""),
                    "Contested": player_trait.get("Contested", ""),
                    "Moks": player_trait.get("Moks", ""),
                    "Ruck": player_trait.get("Ruck", "")
                }
                defence_substats = {
                    "Pressure": player_trait.get("Pressure", ""),
                    "Tackling": player_trait.get("Tackling", ""),
                    "Intercepting": player_trait.get("Intercepting", ""),
                    "Neutralise": player_trait.get("Neutralise", "")
                }

                trait_data = [
                    ("Ball Winning", ball_winning, "#0066CC", ball_winning_substats),
                    ("Ball Use", ball_use, "#009933", ball_use_substats),
                    ("Aerial", aerial, "#FFEB3B", aerial_substats),
                    ("Defence", defence, "#CC0000", defence_substats),
                ]

                trait_cards = []
                for trait_name, trait_value, trait_color, substats in trait_data:
                    if trait_value not in [None, ""] and pd.notna(trait_value):
                        try:
                            trait_val = float(trait_value)
                            
                            # Format based on FC mode
                            if fc_mode:
                                trait_display = str(convert_trait_to_fc_rating(trait_val))
                                trait_label = get_fc_rating_label(convert_trait_to_fc_rating(trait_val))
                            else:
                                trait_display = f"{trait_val:.2f}"
                                trait_label = get_trait_label(trait_val)
                            
                            r, g, b = int(trait_color.lstrip('#')[:2], 16), int(trait_color.lstrip('#')[2:4], 16), int(trait_color.lstrip('#')[4:], 16)

                            substats_html = ""
                            for substat_name, substat_value in substats.items():
                                if substat_value not in [None, ""] and pd.notna(substat_value):
                                    try:
                                        substat_val = float(substat_value)
                                        
                                        # Format substats based on FC mode
                                        if fc_mode:
                                            substat_display = str(convert_trait_to_fc_rating(substat_val))
                                            substat_label = get_fc_rating_label(convert_trait_to_fc_rating(substat_val))
                                        else:
                                            substat_display = f"{substat_val:.2f}"
                                            substat_label = get_trait_label(substat_val)
                                        
                                        substats_html += textwrap.dedent(f"""
                                        <div style='background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-bottom: 6px;'>
                                            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>{substat_name}</div>
                                            <div style='color: #FFFFFF; font-size: 1.2em; font-weight: 800;'>
                                                {substat_display} <span style='font-size: 0.7em; font-weight: 600;'>{substat_label}</span>
                                            </div>
                                        </div>
                                        """).strip() + "\n"

                                    except Exception:
                                        pass

                            substats_html = textwrap.dedent(substats_html).strip()
                            


                            trait_cards.append(f"""
                            <div style='background: linear-gradient(135deg, rgba({r},{g},{b},0.3) 0%, rgba({r},{g},{b},0.1) 100%);
                                        border-left: 4px solid {trait_color}; padding: 20px; border-radius: 12px; margin-bottom: 15px;
                                        box-shadow: 0 4px 8px rgba(0,0,0,0.3);'>
                                <div style='color: rgba(255, 255, 255, 0.8); font-size: 0.9em; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px;'>{trait_name}</div>
                                <div style='color: #FFFFFF; font-size: 2.5em; font-weight: 900;'>{trait_display}</div>
                                <div style='color: rgba(255, 255, 255, 0.9); font-size: 0.95em; font-weight: 700; margin-top: 8px; margin-bottom: 15px;'>{trait_label}</div>
                                {substats_html}
                            </div>
                            """)
                        except Exception:
                            pass

                if trait_cards:
                    t1, t2 = st.columns(2)
                    for i, card in enumerate(trait_cards):
                        container = t1 if i % 2 == 0 else t2
                        render_html(container, card)

    except Exception:
        pass


# ================= PLAYER TRAITS =================
elif page == "Player Traits":
    render_page_header("Player Traits", "Skill Analysis & Trait Breakdown", "🎯")

    # -------------------------
    # Styling (table wrapper only)
    # -------------------------
    st.markdown(
        """
        <style>
        .traits-card-table table {
            width: 100%;
            border-collapse: separate !important;
            border-spacing: 0;
            border-radius: 16px;
            overflow: hidden;
            background: linear-gradient(135deg, rgba(22,22,22,0.98) 0%, rgba(48,48,48,0.75) 100%);
            box-shadow: 0 10px 28px rgba(0,0,0,0.45);
        }
        .traits-card-table th {
            background: rgba(255,255,255,0.08);
            color: #FFFFFF;
            font-weight: 800;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            padding: 14px 10px;
            text-align: center;
            border-bottom: 1px solid rgba(255,255,255,0.12);
        }
        .traits-card-table td {
            color: #EDEDED;
            font-size: 14px;
            font-weight: 600;
            padding: 12px 10px;
            text-align: center;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            background-clip: padding-box;
        }
        .traits-card-table td:nth-child(1),
        .traits-card-table td:nth-child(2),
        .traits-card-table td:nth-child(3) {
            text-align: left;
            font-weight: 700;
        }
        .traits-card-table tbody tr:hover {
            background: rgba(255,255,255,0.04);
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # -------------------------
    # Helpers
    # -------------------------
    import re
    import html

    def sanitize_text(x) -> str:
        """Remove any HTML tags/entities and return safe plain text."""
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        s = str(x)
        # Unescape entities (&lt;div&gt; -> <div>)
        s = html.unescape(s)
        # Strip tags if any snuck in
        s = re.sub(r"<[^>]+>", "", s)
        # Remove any leftover angle brackets
        s = s.replace("<", "").replace(">", "")
        return s.strip()

    def safe_float(x):
        """Convert to float safely. Returns None if not a clean number."""
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        # If there's any HTML-ish content, reject it
        sx = sanitize_text(x)
        sx = sx.replace("%", "").strip()
        # Allow numbers like 2, 2.5, -1.2
        try:
            return float(sx)
        except Exception:
            return None

    # Using global get_ordinal from config

    def get_trait_label(value):
        try:
            val = float(value)
        except Exception:
            return ""
        if val >= 3.0:
            return "Elite"
        elif val >= 2.5:
            return "Above Average"
        elif val >= 2.0:
            return "Below Average"
        else:
            return "Poor"

    # NOTE: rating_colour_for_value is defined globally at line ~715
    # (render_html is imported from top of file)

    # -------------------------
    # Season selection - use traits-specific seasons (2021-2025)
    # -------------------------
    seasons_available = sorted(get_traits_seasons(), reverse=True)
    if not seasons_available:
        seasons_available = [2025, 2024, 2023, 2022, 2021]

    # Season and FC Mode controls in columns
    ctrl_col1, ctrl_col2 = st.columns([2, 1])
    with ctrl_col1:
        primary_season = st.selectbox("Select Season", seasons_available, index=0, key="traits_primary_season")
    with ctrl_col2:
        fc_mode = st.toggle("⚽ FC Rating Mode (50-99)", key="traits_fc_mode", help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")

    # Default to all available seasons (2021-2025)
    default_history = seasons_available.copy()
    history_seasons = st.multiselect(
        "History Seasons (for table)",
        options=seasons_available,
        default=default_history if default_history else [primary_season],
        key="traits_history_seasons",
    )
    if not history_seasons:
        history_seasons = [primary_season]

    # -------------------------
    # Load PRIMARY traits (ENRICHED)
    # -------------------------
    traits_df = load_traits(int(primary_season))
    if traits_df is None or traits_df.empty:
        st.error("Could not load ENRICHED traits data.")
        st.stop()

    required_cols = ["Player_Full", "Team_Full", "Position_Full", "Season"]
    missing = [c for c in required_cols if c not in traits_df.columns]
    if missing:
        st.error(f"Traits file is missing required columns: {missing}. Make sure you are loading ENRICHED.")
        st.stop()

    traits_df = traits_df.copy()
    traits_df["Season"] = pd.to_numeric(traits_df["Season"], errors="coerce").fillna(int(primary_season)).astype(int)

    # -------------------------
    # Team + Player selection (Full-name world)
    # -------------------------
    teams = sorted([t for t in traits_df["Team_Full"].dropna().unique().tolist() if str(t).strip() != ""])
    if not teams:
        st.warning("No teams found in traits data for this season.")
        st.stop()

    default_team = st.session_state.get("default_team")
    team_idx = teams.index(default_team) if default_team in teams else 0
    selected_team_full = st.selectbox("Select Team", teams, index=team_idx, key="traits_team_select")

    team_traits = traits_df[traits_df["Team_Full"] == selected_team_full].copy()
    player_names = sorted(team_traits["Player_Full"].dropna().unique().tolist())
    if not player_names:
        st.warning("No players found for this team in traits.")
        st.stop()

    selected_player_full = st.selectbox("Select Player", player_names, key=f"traits_player_{primary_season}_{selected_team_full}")

    # Resolve player row (PRIMARY season)
    player_trait_df = team_traits[team_traits["Player_Full"] == selected_player_full].copy()
    if player_trait_df.empty:
        st.warning("Could not resolve selected player for this team/season.")
        st.stop()

    player_trait = player_trait_df.iloc[0]

    # Display fields (sanitised for safety)
    team_name_full = sanitize_text(player_trait.get("Team_Full", selected_team_full))
    position = sanitize_text(player_trait.get("Position_Full", ""))
    age = player_trait.get("Age", "")
    matches = player_trait.get("Total Appearances", player_trait.get("Matches", ""))
    rating = player_trait.get("Rating", "")

    # Trait values
    ball_winning = player_trait.get("Ball Winning", "")
    ball_use = player_trait.get("Ball Use", "")
    aerial = player_trait.get("Aerial", "")
    defence = player_trait.get("Defence", "")

    # -------------------------
    # Rankings (within PRIMARY season)
    # -------------------------
    all_traits_sorted = traits_df.copy()
    all_traits_sorted["Rating"] = pd.to_numeric(all_traits_sorted.get("Rating"), errors="coerce")
    all_traits_sorted = all_traits_sorted.dropna(subset=["Rating"]).sort_values("Rating", ascending=False).reset_index(drop=True)

    try:
        overall_rank = all_traits_sorted[all_traits_sorted["Player_Full"] == selected_player_full].index[0] + 1
    except Exception:
        overall_rank = None

    try:
        pos_df = traits_df.copy()
        pos_df = pos_df[pos_df["Position_Full"].astype(str) == str(position)]
        pos_df["Rating"] = pd.to_numeric(pos_df.get("Rating"), errors="coerce")
        pos_df = pos_df.dropna(subset=["Rating"]).sort_values("Rating", ascending=False).reset_index(drop=True)
        position_rank = pos_df[pos_df["Player_Full"] == selected_player_full].index[0] + 1
    except Exception:
        position_rank = None

   # -------------------------
    # Traits history (by season) — STYLED TABLE
    # -------------------------
    st.markdown("---")
    st.subheader("Traits history (by season)")

    # (render_html is imported from top of file)

    traits_history_parts = []
    for y in sorted([int(s) for s in history_seasons], reverse=True):
        df_y = load_traits(int(y))
        if df_y is None or df_y.empty:
            continue

        df_y = df_y.copy()
        if "Season" not in df_y.columns:
            df_y["Season"] = int(y)
        df_y["Season"] = pd.to_numeric(df_y["Season"], errors="coerce").fillna(int(y)).astype(int)

        # Keep your existing selector variable
        if "Player_Full" in df_y.columns:
            df_y = df_y[df_y["Player_Full"].astype(str) == str(selected_player_full)].copy()
        else:
            # fallback if ever a file is missing Player_Full
            player_col = "Player" if "Player" in df_y.columns else None
            if player_col:
                df_y = df_y[df_y[player_col].astype(str) == str(selected_player_full)].copy()
            else:
                continue

        if not df_y.empty:
            traits_history_parts.append(df_y)

    traits_history_df = pd.concat(traits_history_parts, ignore_index=True) if traits_history_parts else pd.DataFrame()

    if traits_history_df.empty:
        st.info("No historical traits data available for this player in the selected seasons.")
    else:
        cols_to_show = ["Season", "Team_Full", "Position_Full", "Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
        cols_to_show = [c for c in cols_to_show if c in traits_history_df.columns]
        view = traits_history_df[cols_to_show].copy()

        for c in ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
            if c in view.columns:
                view[c] = pd.to_numeric(view[c], errors="coerce")

        view = view.sort_values("Season", ascending=False).reset_index(drop=True)

        # Ratings distribution for conditional formatting (prefer current season, else fallback to view)
        try:
            t2025 = load_traits(CURRENT_SEASON)
            if t2025 is not None and not t2025.empty and "Rating" in t2025.columns:
                league_ratings = pd.to_numeric(t2025["Rating"], errors="coerce").dropna()
            else:
                league_ratings = pd.to_numeric(view["Rating"], errors="coerce").dropna() if "Rating" in view.columns else pd.Series(dtype=float)
        except Exception:
            league_ratings = pd.to_numeric(view["Rating"], errors="coerce").dropna() if "Rating" in view.columns else pd.Series(dtype=float)

        # ---- Styled HTML table (uses unified .fe-table CSS) ----
        traits_html = """
    <table class="fe-table fe-table-striped fe-sortable">
    <thead>
        <tr>
    """

        # Build header labels from view columns
        for c in view.columns:
            traits_html += f"<th>{str(c).replace('_', ' ')}</th>"
        traits_html += """
        </tr>
    </thead>
    <tbody>
    """

        def fmt_trait(x, is_fc=False):
            if pd.isna(x):
                return "—"
            if is_fc:
                fc_val = convert_trait_to_fc_rating(x)
                return str(fc_val) if fc_val is not None else "—"
            return f"{float(x):.2f}"

        for _, r in view.iterrows():
            traits_html += "<tr>"
            for c in view.columns:
                if c == "Rating":
                    v = r.get(c, np.nan)
                    if pd.notna(v) and len(league_ratings) > 0:
                        bg, fg = rating_colour_for_value(float(v), league_ratings)
                        traits_html += f"<td style='background-color:{bg}; color:{fg}; font-weight:900;'>{fmt_trait(v, fc_mode)}</td>"
                    else:
                        traits_html += "<td>—</td>"
                else:
                    # numeric trait formatting
                    if c in ["Ball Winning", "Ball Use", "Aerial", "Defence"]:
                        traits_html += f"<td>{fmt_trait(r.get(c, np.nan), fc_mode)}</td>"
                    else:
                        traits_html += f"<td>{r.get(c, '—')}</td>"
            traits_html += "</tr>"

        traits_html += """
    </tbody>
    </table>
    """

    # Use render_sortable_table for working JavaScript sorting
    render_sortable_table(traits_html)


    st.markdown("---")

    # -------------------------
    # Page layout (photo/logo + header cards)
    # -------------------------
    col_photo, col_info = st.columns([1, 3])

    if team_name_full:
        _, logo_col, _ = col_photo.columns([1, 2, 1])
        display_logo(team_name_full, logo_col, size=160)

    display_player_photo(selected_player_full, col_photo, use_container_width=True)

    header_html = f"""
    <div style='background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
                border-left: 5px solid #FFFFFF; padding: 20px; border-radius: 12px; margin-bottom: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);'>
        <h2 style='color: #FFFFFF; margin: 0; font-size: 2.2em; font-weight: 900;'>{sanitize_text(selected_player_full)}</h2>
    </div>
    """
    render_html(col_info, header_html)


    info_cards = []
    if team_name_full:
        info_cards.append(f"""
        <div style='background: linear-gradient(135deg, #2a2a2a 0%, #404040 100%);
                    border-left: 4px solid #CCCCCC; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.85em; margin-bottom: 4px;'>TEAM</div>
            <div style='color: #FFFFFF; font-size: 1.3em; font-weight: 800;'>{team_name_full}</div>
        </div>
        """)
    if position:
        info_cards.append(f"""
        <div style='background: linear-gradient(135deg, rgba(180, 83, 9, 0.8) 0%, rgba(245, 158, 11, 0.6) 100%);
                    border-left: 4px solid #f59e0b; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.85em; margin-bottom: 4px;'>POSITION</div>
            <div style='color: #FFFFFF; font-size: 1.3em; font-weight: 800;'>{position}</div>
        </div>
        """)
    if info_cards:
        if info_cards:
            render_html(col_info, "".join(info_cards))

    # Load Contract Expiry and FA Status from Footywire data
    contract_expiry_traits = None
    fa_status_traits = None
    footywire_path = Path(__file__).parent / "data" / "raw" / "player" / "footywire_2026_complete.csv"
    if footywire_path.exists():
        try:
            fw_df = pd.read_csv(footywire_path)
            fw_df["Player"] = fw_df["Player"].astype(str).str.strip()
            fw_df["Team"] = fw_df["Team"].astype(str).str.strip()
            fw_match = fw_df[(fw_df["Player"] == selected_player_full) & (fw_df["Team"] == team_name_full)]
            if not fw_match.empty:
                contract_expiry_traits = fw_match.iloc[0].get("Contract_Expiry")
                fa_status_traits = fw_match.iloc[0].get("FA_Status")
        except Exception:
            pass

    # Small stats grid
    stats_grid = []

    age_val = safe_float(age)
    if age_val is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>AGE</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{age_val:.1f}</div>
        </div>""")

    stats_grid.append(f"""
    <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
        <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>SEASON</div>
        <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{int(primary_season)}</div>
    </div>""")

    matches_val = safe_float(matches)
    if matches_val is not None:
        stats_grid.append(f"""
        <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>GAMES</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{int(matches_val)}</div>
        </div>""")

    # CONTRACT EXPIRY
    if contract_expiry_traits not in [None, ""] and pd.notna(contract_expiry_traits):
        try:
            ce_val = int(float(contract_expiry_traits))
            stats_grid.append(f"""
            <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>CONTRACT EXPIRY</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{ce_val}</div>
            </div>""")
        except Exception:
            stats_grid.append(f"""
            <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>CONTRACT EXPIRY</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{contract_expiry_traits}</div>
            </div>""")

    # FA STATUS
    if fa_status_traits not in [None, ""] and pd.notna(fa_status_traits):
        # Color coding for FA status
        fa_colors = {
            "Unrestricted Free Agent": ("rgba(255,68,68,0.3)", "#FF4444"),
            "Restricted Free Agent": ("rgba(255,165,0,0.3)", "#FFA500"),
            "Non-Free Agent": ("rgba(76,175,80,0.3)", "#4CAF50"),
            "Delisted Free Agent": ("rgba(255,102,102,0.3)", "#FF6666"),
        }
        fa_bg, fa_border = fa_colors.get(str(fa_status_traits), ("rgba(136,136,136,0.3)", "#888888"))
        # Shorten label for display
        if "Unrestricted" in str(fa_status_traits):
            fa_short = "UFA"
        elif "Restricted" in str(fa_status_traits) and "Unrestricted" not in str(fa_status_traits):
            fa_short = "RFA"
        elif "Non-Free" in str(fa_status_traits):
            fa_short = "Non-FA"
        elif "Delisted" in str(fa_status_traits):
            fa_short = "DFA"
        else:
            fa_short = str(fa_status_traits)[:12]
        stats_grid.append(f"""
        <div style='background: {fa_bg}; padding: 10px; border-radius: 6px; text-align: center; border: 1px solid {fa_border};'>
            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>FA STATUS</div>
            <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{fa_short}</div>
        </div>""")

    if stats_grid:
        grid_html = f"""
        <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-top: 20px;'>
            {''.join(stats_grid)}
        </div>
        """
        if stats_grid:
            grid_html = (
                "<div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-top: 20px;'>"
                + "".join(stats_grid) +
                "</div>"
            )
            render_html(col_info, grid_html)


    # -------------------------
    # Key metrics (rating + ranks)
    # -------------------------
    st.markdown("---")
    st.markdown("<h3 style='text-align: center; color: #FFFFFF; margin-top: 30px; margin-bottom: 25px;'>⭐ Key Performance Metrics</h3>", unsafe_allow_html=True)

    key_metrics = []

    rating_val = safe_float(rating)
    if rating_val is not None:
        all_ratings = pd.to_numeric(traits_df["Rating"], errors="coerce").dropna() if "Rating" in traits_df.columns else pd.Series(dtype=float)
        bg_color, _ = rating_colour_for_value(rating_val, all_ratings)
        
        # Format rating based on FC mode
        if fc_mode:
            rating_display = str(convert_trait_to_fc_rating(rating_val))
            rating_label = get_fc_rating_label(convert_trait_to_fc_rating(rating_val))
        else:
            rating_display = f"{rating_val:.2f}"
            rating_label = get_trait_label(rating_val)

        if bg_color == "#008000":
            rating_gradient = "rgba(0,128,0,0.3)"
            rating_text_color = "#FFFFFF"
        elif bg_color == "#90EE90":
            rating_gradient = "rgba(144,238,144,0.3)"
            rating_text_color = "#000000"
        elif bg_color == "#FFA500":
            rating_gradient = "rgba(255,165,0,0.3)"
            rating_text_color = "#000000"
        else:
            rating_gradient = "rgba(255,0,0,0.3)"
            rating_text_color = "#FFFFFF"

        key_metrics.append(f"""
        <div style='background: linear-gradient(135deg, {rating_gradient} 0%, rgba(0,0,0,0.2) 100%);
                    border-left: 5px solid {bg_color}; padding: 25px; border-radius: 12px; margin-bottom: 15px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.4); text-align: center;'>
            <div style='color: rgba(255, 255, 255, 0.8); font-size: 1.1em; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 700;'>RATING</div>
            <div style='color: {rating_text_color}; font-size: 4em; font-weight: 900; line-height: 1;'>{rating_display}</div>
            <div style='color: {rating_text_color}; font-size: 1.3em; font-weight: 700; margin-top: 12px;'>{rating_label}</div>
        </div>
        """)

    if overall_rank:
        key_metrics.append(f"""
        <div style='background: linear-gradient(135deg, rgba(255,215,0,0.25) 0%, rgba(255,215,0,0.05) 100%);
                    border-left: 5px solid #FFD700; padding: 25px; border-radius: 12px; margin-bottom: 15px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.4); text-align: center;'>
            <div style='color: rgba(255, 255, 255, 0.8); font-size: 1.1em; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 700;'>OVERALL RANK</div>
            <div style='color: #FFD700; font-size: 4em; font-weight: 900; line-height: 1;'>{get_ordinal(overall_rank)}</div>
            <div style='color: rgba(255,215,0,0.8); font-size: 1.1em; font-weight: 600; margin-top: 12px;'>Out of {len(all_traits_sorted)} Players</div>
        </div>
        """)

    if position_rank and position:
        key_metrics.append(f"""
        <div style='background: linear-gradient(135deg, rgba(100,149,237,0.25) 0%, rgba(100,149,237,0.05) 100%);
                    border-left: 5px solid #6495ED; padding: 25px; border-radius: 12px; margin-bottom: 15px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.4); text-align: center;'>
            <div style='color: rgba(255, 255, 255, 0.8); font-size: 1.1em; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 700;'>POSITION RANK</div>
            <div style='color: #6495ED; font-size: 4em; font-weight: 900; line-height: 1;'>{get_ordinal(position_rank)}</div>
            <div style='color: rgba(100,149,237,0.8); font-size: 1.1em; font-weight: 600; margin-top: 12px;'>{position}</div>
        </div>
        """)

    if key_metrics:
        col1, col2, col3 = st.columns(3)
        if len(key_metrics) > 0:
            col1.markdown(key_metrics[0], unsafe_allow_html=True)
        if len(key_metrics) > 1:
            col2.markdown(key_metrics[1], unsafe_allow_html=True)
        if len(key_metrics) > 2:
            col3.markdown(key_metrics[2], unsafe_allow_html=True)

    # -------------------------
    # Trait cards  ✅ FIXED: no HTML-as-code blocks
    # -------------------------
    import textwrap

    st.markdown("---")
    st.markdown(
        "<h3 style='text-align: center; color: #FFFFFF; margin-top: 30px; margin-bottom: 25px;'>📊 Trait Analysis</h3>",
        unsafe_allow_html=True
    )

    # (render_html is imported from top of file)

    ball_winning_substats = {
        "Stoppage": player_trait.get("Stoppage", ""),
        "Contest": player_trait.get("Contest", ""),
        "Power": player_trait.get("Power", ""),
        "Receives": player_trait.get("Receives", "")
    }
    ball_use_substats = {
        "Handballing": player_trait.get("Handballing", ""),
        "Kicking": player_trait.get("Kicking", ""),
        "Goal Kicking": player_trait.get("Goal Kicking", ""),
        "Connecting": player_trait.get("Connecting", "")
    }
    aerial_substats = {
        "Marking": player_trait.get("Marking", ""),
        "Contested": player_trait.get("Contested", ""),
        "Moks": player_trait.get("Moks", ""),   # keep as-is if that's your column name
        "Ruck": player_trait.get("Ruck", "")
    }
    defence_substats = {
        "Pressure": player_trait.get("Pressure", ""),
        "Tackling": player_trait.get("Tackling", ""),
        "Intercepting": player_trait.get("Intercepting", ""),
        "Neutralise": player_trait.get("Neutralise", "")
    }

    trait_data = [
        ("Ball Winning", ball_winning, "#0066CC", ball_winning_substats),
        ("Ball Use", ball_use, "#009933", ball_use_substats),
        ("Aerial", aerial, "#FFEB3B", aerial_substats),
        ("Defence", defence, "#CC0000", defence_substats),
    ]

    trait_cards = []

    for trait_name, trait_value, trait_color, substats in trait_data:
        trait_val = safe_float(trait_value)
        if trait_val is None:
            continue

        # Format based on FC mode
        if fc_mode:
            trait_display = str(convert_trait_to_fc_rating(trait_val))
            trait_label = get_fc_rating_label(convert_trait_to_fc_rating(trait_val))
        else:
            trait_display = f"{trait_val:.2f}"
            trait_label = get_trait_label(trait_val)

        r = int(trait_color.lstrip("#")[:2], 16)
        g = int(trait_color.lstrip("#")[2:4], 16)
        b = int(trait_color.lstrip("#")[4:], 16)

        # Build substats HTML with NO leading indentation (prevents markdown code-block behaviour)
        substats_html_parts = []
        for substat_name, substat_value in substats.items():
            sub_val = safe_float(substat_value)
            if sub_val is None:
                continue
            
            # Format substats based on FC mode
            if fc_mode:
                sub_display = str(convert_trait_to_fc_rating(sub_val))
                sub_label = get_fc_rating_label(convert_trait_to_fc_rating(sub_val))
            else:
                sub_display = f"{sub_val:.2f}"
                sub_label = get_trait_label(sub_val)

            substats_html_parts.append(
                f"<div style='background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-bottom: 6px;'>"
                f"  <div style='color: rgba(255,255,255,0.7); font-size: 0.75em; margin-bottom: 4px;'>{sanitize_text(substat_name)}</div>"
                f"  <div style='color: #FFFFFF; font-size: 1.2em; font-weight: 800;'>"
                f"    {sub_display} <span style='font-size: 0.7em; font-weight: 600;'> {sanitize_text(sub_label)}</span>"
                f"  </div>"
                f"</div>"
            )

        substats_html = "".join(substats_html_parts)

        card_html = f"""
        <div style='background: linear-gradient(135deg, rgba({r},{g},{b},0.3) 0%, rgba({r},{g},{b},0.1) 100%);
                    border-left: 4px solid {trait_color}; padding: 20px; border-radius: 12px; margin-bottom: 15px;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.3);'>
            <div style='color: rgba(255,255,255,0.8); font-size: 0.9em; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px;'>
                {sanitize_text(trait_name)}
            </div>
            <div style='color: #FFFFFF; font-size: 2.5em; font-weight: 900;'>{trait_display}</div>
            <div style='color: rgba(255,255,255,0.9); font-size: 0.95em; font-weight: 700; margin-top: 8px; margin-bottom: 15px;'>
                {sanitize_text(trait_label)}
            </div>
            {substats_html}
        </div>
        """
        trait_cards.append(card_html)

    if trait_cards:
        c1, c2 = st.columns(2)
        for i, card in enumerate(trait_cards):
            render_html(c1 if i % 2 == 0 else c2, card)
    else:
        st.info("No trait card values available for this player.")
    
    # Professional footer
    render_footer()


# ================= DEPTH CHART =================

elif page == "Depth Chart":
    render_page_header("Depth Chart", "Positional Player Rankings", "📋")

    # Depth Chart needs FULL roster data including Wings and players who didn't play
    # Always load from Excel Summary sheet (not computed CSV which only has players who played)
    summary_df = _load_player_summary_excel()
    if summary_df.empty:
        st.error("Could not load Summary sheet from AFL Player Ratings.")
        st.stop()
    
    # Load 2025 players data (same source as List Ladder) for ranking calculations
    players_2025_df = load_players(CURRENT_SEASON)

    # Normalize team names in dropdown to match logic
    teams = sorted([
        "GWS Giants" if t in ["GWS", "GWS Giants", "Greater Western Sydney"] else t
        for t in summary_df["Team"].dropna().unique()
    ])
    # Set default index based on session state
    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        default_idx = teams.index(st.session_state.default_team)
    selected_team = st.selectbox("Team", teams, index=default_idx)

    rating_options = {
        "2025 (current)": "2025",
        "Last 2 Seasons Average": "Last 2 Average",
        "Career": "Career",
    }
    rating_label = st.selectbox(
        "Which rating to use?",
        list(rating_options.keys()),
        index=0,
    )
    rating_col_name = rating_options[rating_label]

    df_team = summary_df[summary_df["Team"] == selected_team].copy()
    if df_team.empty:
        st.warning("No data for this team in Summary sheet.")
        st.stop()

    if rating_col_name not in df_team.columns:
        st.error(
            f"Column '{rating_col_name}' not found in Summary sheet. "
            "Check the exact header names in the Excel file."
        )
        st.stop()

    df_team["RatingPoints_Avg"] = pd.to_numeric(
        df_team[rating_col_name], errors="coerce"
    )
    
    # IMPORTANT: df_team (from Summary) is used for DISPLAY - shows ALL squad players
    # This includes players who didn't play in 2025 (they'll have NaN ratings but still appear)
    # Ensure all players appear even without ratings
    
    # For RANKING calculations: use 2025 players data (same as List Ladder) when "2025 (current)" selected
    # Players who didn't play (not in 2025 data) don't affect rankings
    if rating_col_name == "2025" and not players_2025_df.empty:
        # Use 2025 players data for ranking (same data source as List Ladder)
        # Only players who actually played in 2025 will affect rankings
        ranking_df = players_2025_df.copy()
        # Ensure it has RatingPoints_Avg and Matches
        if "RatingPoints_Avg" not in ranking_df.columns:
            ranking_df["RatingPoints_Avg"] = 0
        if "Matches" not in ranking_df.columns:
            ranking_df["Matches"] = 0
    else:
        # Use Summary data for other rating types (Last 2 Average, Career)
        ranking_df = summary_df.copy()
        ranking_df["RatingPoints_Avg"] = pd.to_numeric(
            ranking_df[rating_col_name], errors="coerce"
        )
        # Get matches from Summary - use '2025 Matches' or 'Total Matches'
        if '2025 Matches' in ranking_df.columns:
            ranking_df["Matches"] = pd.to_numeric(ranking_df['2025 Matches'], errors="coerce").fillna(0)
        elif 'Total Matches' in ranking_df.columns:
            ranking_df["Matches"] = pd.to_numeric(ranking_df['Total Matches'], errors="coerce").fillna(0)
        else:
            ranking_df["Matches"] = 0

    st.markdown(
        f"#### Squad Depth Grid – {selected_team} "
        f"({rating_label}, coloured by team percentile)"
    )

    html = build_depth_chart_html(df_team, ranking_df)
    st.markdown(html, unsafe_allow_html=True)
    
    # Professional footer
    render_footer()


# ================= TEAM AGE BREAKDOWN =================

elif page == "Team Age Breakdown":
    # Professional header
    st.markdown(f"""<div style='background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%); padding: 40px 20px; border-radius: 15px; margin-bottom: 30px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);'><h1 style='text-align: center; color: #FFFFFF; margin: 0; font-size: 2.8em; font-weight: 900; text-shadow: 2px 2px 4px rgba(0,0,0,0.5);'>📊 AFL TEAM AGE BREAKDOWN</h1><p style='text-align: center; color: #CCCCCC; margin: 10px 0 0 0; font-size: 1.2em; font-weight: 300;'>{CURRENT_SEASON} Season | Age Group Performance Analysis</p></div>""", unsafe_allow_html=True)

    selected_season = CURRENT_SEASON

    # Load player data for the selected season
    try:
        players_df = load_players(selected_season)
    except Exception as e:
        st.error(f"Error loading player data for {selected_season}: {e}")
        st.stop()

    if players_df.empty:
        st.warning(f"No player data found for {selected_season}.")
        st.stop()

    # Ensure required columns exist
    required_cols = ["Player", "Team", "Age", "Matches", "RatingPoints_Avg"]
    missing_cols = [c for c in required_cols if c not in players_df.columns]
    if missing_cols:
        st.error(f"Missing required columns: {', '.join(missing_cols)}")
        st.stop()

    # Convert to numeric
    players_df["Age"] = pd.to_numeric(players_df["Age"], errors="coerce")
    players_df["Matches"] = pd.to_numeric(players_df["Matches"], errors="coerce").fillna(0)
    players_df["RatingPoints_Avg"] = pd.to_numeric(players_df["RatingPoints_Avg"], errors="coerce").fillna(0)

    # Calculate Total Rating Points (RatingPoints_Avg * Matches)
    # Cap matches at 23 (regular season) to avoid over-rating players who played finals
    MAX_MATCHES_FOR_RATING = 23
    capped_matches = players_df["Matches"].clip(upper=MAX_MATCHES_FOR_RATING)
    players_df["Total_Rating_Points"] = players_df["RatingPoints_Avg"] * capped_matches

    # Map each player to an age band
    players_df["Age_Band"] = players_df["Age"].apply(map_age_to_band)

    # Group by Team and Age_Band, sum Total_Rating_Points
    age_contributions = (
        players_df.groupby(["Team", "Age_Band"])["Total_Rating_Points"]
        .sum()
        .reset_index()
    )

    # Calculate team totals
    team_totals = (
        players_df.groupby("Team")["Total_Rating_Points"]
        .sum()
        .reset_index()
        .rename(columns={"Total_Rating_Points": "Team_Total"})
    )

    # Merge to get percentages
    age_contributions = age_contributions.merge(team_totals, on="Team")
    age_contributions["Percentage"] = (
        (age_contributions["Total_Rating_Points"] / age_contributions["Team_Total"]) * 100
    ).round(1)

    # Pivot to get age bands as columns
    age_breakdown_table = age_contributions.pivot(
        index="Team",
        columns="Age_Band",
        values="Percentage"
    ).reset_index()

    # Ensure all age bands are present (fill missing with 0)
    for band in AGE_BANDS:
        if band not in age_breakdown_table.columns:
            age_breakdown_table[band] = 0.0

    # Reorder columns to match AGE_BANDS order
    column_order = ["Team"] + AGE_BANDS
    age_breakdown_table = age_breakdown_table[column_order]

    # Fill NaN with 0
    age_breakdown_table = age_breakdown_table.fillna(0)

    # Sort by team name
    age_breakdown_table = age_breakdown_table.sort_values("Team").reset_index(drop=True)
    
    # Helper function to get ordinal suffix
    def get_ordinal_suffix(n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    
    # Calculate rankings for each age band (highest % = best = rank 1)
    for band in AGE_BANDS:
        # Rank teams by percentage (descending - highest is best)
        age_breakdown_table[f"{band}_Rank"] = age_breakdown_table[band].rank(ascending=False, method='min').astype(int)
        # Format as "X.X% (Yth)"
        age_breakdown_table[f"{band}_Display"] = age_breakdown_table.apply(
            lambda row: f"{row[band]:.1f}% ({get_ordinal_suffix(row[f'{band}_Rank'])})", 
            axis=1
        )
    
    # Create display table with formatted values
    display_table = age_breakdown_table[["Team"] + [f"{band}_Display" for band in AGE_BANDS]].copy()
    # Rename columns to remove _Display suffix
    display_table.columns = ["Team"] + AGE_BANDS

    # Calculate league averages for each age band (from original numeric values)
    league_averages = {"Team": "League Average"}
    for band in AGE_BANDS:
        avg_val = age_breakdown_table[band].mean()
        league_averages[band] = f"{avg_val:.1f}%"
    
    # Add league averages row to the display table
    league_avg_df = pd.DataFrame([league_averages])
    age_breakdown_with_avg = pd.concat([display_table, league_avg_df], ignore_index=True)

    # Professional subtitle
    st.markdown("""<div style='background: rgba(50,50,50,0.3); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); margin-bottom: 25px;'><h4 style='color: #FFFFFF; margin-top: 0; font-size: 1.3em;'>Understanding the Table</h4><p style='color: #DDDDDD; line-height: 1.8; margin: 0;'><strong style='color: #FFFFFF;'>How to Read:</strong> Each age band column shows the percentage of total rating points contributed by players in that age group, along with the team's rank (1st-18th). Higher percentages in prime age bands (23-25, 26-28) typically indicate stronger current performance, while higher percentages in younger bands suggest future potential.</p></div>""", unsafe_allow_html=True)
    
    # Display the age breakdown table
    st.markdown("<h3 style='color: #CCCCCC; margin: 20px 0;'>📊 Team Age Breakdown Table</h3>", unsafe_allow_html=True)
    
    # Helper function to get rank color - 5 tier system
    def get_rank_color_age(rank_val):
        """5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)"""
        if rank_val <= 4:
            return "#008000", "white"   # Elite - Dark Green
        elif rank_val <= 7:
            return "#90EE90", "black"   # Good - Light Green
        elif rank_val <= 11:
            return "#FFD700", "black"   # Average - Gold
        elif rank_val <= 15:
            return "#FFA500", "white"   # Below Average - Orange
        else:
            return "#FF0000", "white"   # Poor - Red
    
    # Create HTML table using unified table system with custom league-avg row styling
    html_table = """<style>
.fe-table .league-avg-row {
    background: linear-gradient(135deg, #2d2d2d 0%, #1a1a1a 100%) !important;
    border-top: 3px solid #CCCCCC !important;
}
.fe-table .league-avg-row td {
    font-weight: 800 !important;
    color: #FFFFFF !important;
    font-size: 1.05em !important;
}
.fe-table .league-avg-row:hover {
    background: linear-gradient(135deg, #2d2d2d 0%, #1a1a1a 100%) !important;
}
.rank-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 800;
    font-size: 0.85em;
    margin-left: 4px;
}
</style>
<table class='fe-table fe-sortable'>
<thead>
<tr>
"""
    
    # Add column headers
    for col in age_breakdown_with_avg.columns:
        html_table += f"<th>{col}</th>"
    html_table += "</tr>\n</thead>\n<tbody>\n"
    
    # Add data rows with color-coded rank badges
    for idx, row in age_breakdown_with_avg.iterrows():
        # Check if this is the league average row
        is_league_avg = row["Team"] == "League Average"
        row_class = " class='league-avg-row'" if is_league_avg else ""
        html_table += f"<tr{row_class}>\n"
        
        for col_idx, col in enumerate(age_breakdown_with_avg.columns):
            if col_idx == 0:  # Team column
                html_table += f"<td>{row[col]}</td>\n"
            else:
                # Age band columns with color-coded rank badges
                if is_league_avg:
                    html_table += f"<td>{row[col]}</td>\n"
                else:
                    # Extract percentage and rank from display value
                    val_str = row[col]
                    if "(" in val_str and ")" in val_str:
                        pct_part = val_str.split("(")[0].strip()
                        rank_part = val_str.split("(")[1].split(")")[0]
                        
                        # Get corresponding rank value from original data
                        band_name = AGE_BANDS[col_idx - 1]
                        rank_val = int(age_breakdown_table.loc[age_breakdown_table["Team"] == row["Team"], f"{band_name}_Rank"].iloc[0])
                        bg_color, text_color = get_rank_color_age(rank_val)
                        
                        html_table += f"<td>{pct_part} <span class='rank-badge' style='background: {bg_color}; color: {text_color};'>({rank_part})</span></td>\n"
                    else:
                        html_table += f"<td>{val_str}</td>\n"
        html_table += "</tr>\n"
    
    html_table += "</tbody>\n</table>"
    render_sortable_table(html_table)
    
    # Professional footer
    render_footer()


# ================= LIST LADDER =================

elif page == "List Ladder":
    # Professional header
    st.markdown(f"""<div style='background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%); padding: 40px 20px; border-radius: 15px; margin-bottom: 30px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);'><h1 style='text-align: center; color: #FFFFFF; margin: 0; font-size: 2.8em; font-weight: 900; text-shadow: 2px 2px 4px rgba(0,0,0,0.5);'>📊 AFL LIST LADDER</h1><p style='text-align: center; color: #CCCCCC; margin: 10px 0 0 0; font-size: 1.2em; font-weight: 300;'>{CURRENT_SEASON} Season | Positional Depth Rankings</p></div>""", unsafe_allow_html=True)

    # Load player data
    try:
        players_df = load_players(CURRENT_SEASON)
    except Exception as e:
        st.error(f"Error loading player data: {e}")
        st.stop()

    if players_df.empty:
        st.warning(f"No player data found for {CURRENT_SEASON}.")
        st.stop()

    # Ensure required columns exist
    required_cols = ["Player", "Team", "Position", "RatingPoints_Avg", "Matches"]
    missing_cols = [c for c in required_cols if c not in players_df.columns]
    if missing_cols:
        st.error(f"Missing required columns: {', '.join(missing_cols)}")
        st.stop()

    # Fill missing Matches with 0
    if "Matches" in players_df.columns:
        players_df["Matches"] = players_df["Matches"].fillna(0)
    else:
        players_df["Matches"] = 0

    # Calculate weighted score: RatingPoints_Avg × Matches
    # This rewards players who maintain high ratings over many games
    # Cap matches at 23 (regular season) to avoid over-rating players who played finals
    # A player with 100 rating over 23 games = 2300 weighted score (max)
    MAX_MATCHES_FOR_RATING = 23
    capped_matches = players_df["Matches"].clip(upper=MAX_MATCHES_FOR_RATING)
    players_df["Weighted_Rating"] = players_df["RatingPoints_Avg"].fillna(0) * capped_matches
    
    # Get all weighted ratings for percentile calculation
    all_weighted = players_df["Weighted_Rating"].dropna()
    
    # Define get_rating_points function using weighted score
    def get_rating_points(weighted_val, all_weighted_clean):
        """Convert weighted rating (Rating × Matches) to points based on percentile."""
        if pd.isna(weighted_val) or weighted_val == 0:
            return 0
        
        percentile = (all_weighted_clean <= weighted_val).mean()
        
        if percentile >= 0.85:
            return 3  # dark green - top 15%
        elif percentile >= 0.60:
            return 1  # light green - top 40%
        elif percentile >= 0.35:
            return 0.5  # orange - top 65%
        else:
            return 0  # red - bottom group
    
    # Get unique teams
    teams = sorted(players_df["Team"].dropna().unique())
    
    # Load Summary tab to get correct positions (especially Wings)
    summary_df = load_player_summary()
    
    # Create a position mapping from Summary tab
    summary_positions = {}
    if "Player" in summary_df.columns and "Position" in summary_df.columns:
        for _, row in summary_df.iterrows():
            player_name = row.get("Player", "")
            position = row.get("Position", "")
            if pd.notna(player_name) and pd.notna(position):
                summary_positions[str(player_name).strip()] = str(position).strip()
    
    # Load Wing players from AFL_Historical Wings sheet (65 wing players across all teams)
    wing_players_by_lastname_team = {}
    try:
        wings_df = pd.read_excel("data/AFL_Historical_2012_2025.xlsx", sheet_name="Wings")
        for _, row in wings_df.iterrows():
            player_name = row.get("Player", "")
            team = row.get("Team", "")
            if pd.notna(player_name) and pd.notna(team):
                # Extract last name for matching (handles full names like "Errol Gulden")
                name_parts = str(player_name).strip().split()
                if len(name_parts) >= 1:
                    last_name = name_parts[-1].lower()
                    team_str = str(team).strip().lower()
                    key = (last_name, team_str)
                    wing_players_by_lastname_team[key] = "Wing"
    except Exception:
        pass  # If Wings sheet not available, continue without it
    
    # Map players to depth positions, using Traits for Wings, then Summary, then fallback
    def get_depth_position(player_name, team_name, fallback_position):
        player_key = str(player_name).strip() if pd.notna(player_name) else ""
        team_key = str(team_name).strip().lower() if pd.notna(team_name) else ""
        
        # First check if player is a Wing (by last name + team match from Traits)
        if player_key:
            name_parts = player_key.split()
            if len(name_parts) >= 2:
                last_name = name_parts[-1].lower()
                if (last_name, team_key) in wing_players_by_lastname_team:
                    return "Wing"
        
        # Then check Summary tab positions
        if player_key in summary_positions:
            summary_pos = summary_positions[player_key]
            return map_position_to_depth(summary_pos)
        
        # Otherwise use the position from player data
        return map_position_to_depth(fallback_position) if pd.notna(fallback_position) else "Midfielder"
    
    players_df["Depth_Position"] = players_df.apply(
        lambda row: get_depth_position(row.get("Player"), row.get("Team"), row.get("Position")), axis=1
    )
    
    # Calculate points for each player using weighted rating (Rating × Matches)
    players_df["Points"] = players_df["Weighted_Rating"].apply(
        lambda r: get_rating_points(r, all_weighted)
    )
    
    # Also keep all_ratings for color coding individual players (raw rating for display)
    all_ratings = players_df["RatingPoints_Avg"].dropna()
    
    # Build ladder table
    ladder_data = []
    
    for team in teams:
        team_players = players_df[players_df["Team"] == team]
        team_row = {"Team": team}
        total_points = 0
        
        for position in DEPTH_POSITIONS:
            pos_players = team_players[team_players["Depth_Position"] == position]
            pos_total = pos_players["Points"].sum()
            team_row[position] = pos_total
            total_points += pos_total
        
        team_row["Total Points"] = total_points
        ladder_data.append(team_row)
    
    # Create DataFrame
    ladder_df = pd.DataFrame(ladder_data)
    
    # Calculate rankings for each position
    for position in DEPTH_POSITIONS:
        ladder_df[f"{position}_Rank"] = ladder_df[position].rank(ascending=False, method='min').astype(int)
    
    # Sort by total points
    ladder_df = ladder_df.sort_values("Total Points", ascending=False).reset_index(drop=True)
    ladder_df["Rank"] = range(1, len(ladder_df) + 1)
    
    # Professional explanation with 5-tier ranking guide
    st.markdown("""<div style='background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,215,0,0.2); margin-bottom: 25px;'><h4 style='color: #FFFFFF; margin-top: 0; font-size: 1.3em;'>Ranking Guide (5-Tier System)</h4><div style='display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 20px;'><div style='text-align: center; padding: 12px; background: #008000; border-radius: 8px;'><strong style='color: white; font-size: 1em;'>1st - 4th</strong><br><span style='color: #CCCCCC; font-size: 0.85em;'>Elite</span></div><div style='text-align: center; padding: 12px; background: #90EE90; border-radius: 8px;'><strong style='color: black; font-size: 1em;'>5th - 7th</strong><br><span style='color: #333333; font-size: 0.85em;'>Good</span></div><div style='text-align: center; padding: 12px; background: #FFD700; border-radius: 8px;'><strong style='color: black; font-size: 1em;'>8th - 11th</strong><br><span style='color: #333333; font-size: 0.85em;'>Average</span></div><div style='text-align: center; padding: 12px; background: #FFA500; border-radius: 8px;'><strong style='color: white; font-size: 1em;'>12th - 15th</strong><br><span style='color: #EEEEEE; font-size: 0.85em;'>Below Avg</span></div><div style='text-align: center; padding: 12px; background: #FF0000; border-radius: 8px;'><strong style='color: white; font-size: 1em;'>16th - 18th</strong><br><span style='color: #EEEEEE; font-size: 0.85em;'>Poor</span></div></div><p style='color: #DDDDDD; line-height: 1.8; margin: 0;'><strong style='color: #FFFFFF;'>Scoring Formula:</strong> Rating Points × Matches Played. This rewards players who maintain high ratings over many games—a player with 100 rating over 22 games contributes significantly more than a 1-game wonder with the same rating. <strong style='color: #90EE90;'>Total Points</strong> shows overall list strength.</p></div>""", unsafe_allow_html=True)
    
    # Helper function to get ordinal suffix
    def get_ordinal_suffix(n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    
    # Helper function to get color based on rank - 5 tier system
    def get_rank_color(rank):
        """5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)"""
        if rank <= 4:
            return "#008000"   # Elite - Dark Green
        elif rank <= 7:
            return "#90EE90"   # Good - Light Green
        elif rank <= 11:
            return "#FFD700"   # Average - Gold
        elif rank <= 15:
            return "#FFA500"   # Below Average - Orange
        else:
            return "#FF0000"   # Poor - Red
    
    # Create display table with formatted cells
    display_data = []
    
    for _, row in ladder_df.iterrows():
        display_row = {
            "Rank": int(row["Rank"]),
            "Team": row["Team"]
        }
        
        for position in DEPTH_POSITIONS:
            rank = int(row[f"{position}_Rank"])
            points = row[position]
            display_row[position] = f"{points:.1f} ({get_ordinal_suffix(rank)})"
        
        display_row["Total Points"] = f"{row['Total Points']:.1f}"
        display_data.append(display_row)
    
    display_df = pd.DataFrame(display_data)
    
    # Display the main ladder table with professional HTML styling
    st.markdown("<h3 style='color: #FFFFFF; margin: 20px 0;'>📋 Positional Depth Rankings</h3>", unsafe_allow_html=True)
    
    # Create HTML table using unified table system with custom styling for total column
    html_table = """<style>
.fe-table td:first-child {
    text-align: center !important;
    font-weight: 800;
}
.fe-table td:nth-child(2) {
    text-align: left !important;
    padding-left: 20px !important;
}
.fe-table td:last-child {
    background: rgba(100,100,100,0.2);
    font-weight: 800;
    color: #FFFFFF;
}
.rank-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 800;
    font-size: 0.85em;
    margin-left: 4px;
}
</style>
<table class='fe-table fe-sortable'>
<thead>
<tr>
"""
    
    # Add column headers
    for col in display_df.columns:
        html_table += f"<th>{col}</th>"
    html_table += "</tr>\n</thead>\n<tbody>\n"
    
    # Add data rows with color-coded rank badges
    for row_idx, row in display_df.iterrows():
        html_table += "<tr>\n"
        for col_idx, col in enumerate(display_df.columns):
            if col in ["Rank", "Team", "Total Points"]:
                # No color coding for these columns
                html_table += f"<td>{row[col]}</td>\n"
            else:
                # Position columns - extract rank and color code
                val_str = row[col]
                if "(" in val_str and ")" in val_str:
                    pts_part = val_str.split("(")[0].strip()
                    rank_part = val_str.split("(")[1].split(")")[0]
                    
                    # Get rank value from ladder_df
                    rank_val = int(ladder_df.iloc[row_idx][f"{col}_Rank"])
                    bg_color = get_rank_color(rank_val)
                    
                    html_table += f"<td>{pts_part} <span class='rank-badge' style='background: {bg_color}; color: white;'>({rank_part})</span></td>\n"
                else:
                    html_table += f"<td>{val_str}</td>\n"
        html_table += "</tr>\n"
    
    html_table += "</tbody>\n</table>"
    render_sortable_table(html_table)
    
    # ---- Team Selector for Positional Breakdown ----
    st.markdown("---")
    st.markdown("""<div style='background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 50%, #3a3a3a 100%); padding: 35px 20px; border-radius: 15px; margin: 40px 0 30px 0; box-shadow: 0 8px 32px rgba(0,0,0,0.4);'><h2 style='text-align: center; color: #FFFFFF; margin: 0; font-size: 2.5em; font-weight: 900; text-shadow: 2px 2px 4px rgba(0,0,0,0.5);'>📋 TEAM PLAYER BREAKDOWN</h2><p style='text-align: center; color: #FFFFFF; margin: 12px 0 0 0; font-size: 1.15em; font-weight: 400; text-shadow: 1px 1px 3px rgba(0,0,0,0.5);'>Positional Depth Analysis by Player Contributions</p></div>""", unsafe_allow_html=True)
    
    # Team selector
    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        default_idx = teams.index(st.session_state.default_team)
    selected_team = st.selectbox("Select a team to view contributing players", teams, index=default_idx, key="list_ladder_team_select")
    
    # Professional explanation
    st.markdown("""<div style='background: rgba(50,50,50,0.25); padding: 18px; border-radius: 10px; border-left: 5px solid #FFFFFF; margin-bottom: 25px;'><p style='color: #DDDDDD; margin: 0; font-size: 1.05em; line-height: 1.6;'><strong style='color: #FFFFFF; font-size: 1.2em;'>Player Contribution Analysis</strong><br><span style='color: #CCCCCC; font-size: 0.95em;'>View all players by position with their individual rating and point contributions. Players are color-coded by percentile ranking across the entire competition.</span></p></div>""", unsafe_allow_html=True)
    
    if selected_team:
        # Get players for selected team
        team_players = players_df[players_df["Team"] == selected_team].copy()
        
        if team_players.empty:
            st.warning(f"No players found for {selected_team}")
        else:
            # Create display tables for each position
            positions_with_players = sorted([p for p in DEPTH_POSITIONS if any(team_players["Depth_Position"] == p)])
            
            if not positions_with_players:
                st.warning(f"No players found for {selected_team}")
            else:
                # Display tables in columns (2 per row)
                for i, position in enumerate(positions_with_players):
                    # Create new row every 2 positions
                    if i % 2 == 0:
                        cols = st.columns(2)
                    
                    col_idx = i % 2
                    
                    with cols[col_idx]:
                        # Get players for this position
                        pos_players = team_players[team_players["Depth_Position"] == position].copy()
                        
                        if pos_players.empty:
                            continue
                        
                        # Sort by rating points
                        pos_players = pos_players.sort_values("RatingPoints_Avg", ascending=False)
                        
                        # Create display table
                        player_table = pos_players[["Player", "RatingPoints_Avg", "Points"]].copy()
                        player_table["Rating"] = player_table["RatingPoints_Avg"].round(1)
                        player_table["Points"] = player_table["Points"].round(1)
                        player_table = player_table[["Player", "Rating", "Points"]]
                        
                        # Position header with gradient
                        st.markdown(f"""<div style='background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%); padding: 12px; border-radius: 8px 8px 0 0; margin-top: 15px;'><h4 style='margin: 0; color: #FFFFFF; text-align: center; font-weight: 900; font-size: 1.2em;'>{position}</h4></div>""", unsafe_allow_html=True)
                        
                        # Create HTML table with color coding (uses unified .fe-table CSS)
                        html_player_table = """<table class='fe-table fe-table-compact'>
<thead>
<tr>
<th>Player</th>
<th>Rating</th>
<th>Points</th>
</tr>
</thead>
<tbody>
"""
                        
                        # Add player rows with color coding
                        for idx, row in player_table.iterrows():
                            rating_val = pos_players.loc[idx, "RatingPoints_Avg"]
                            bg_color, text_color = rating_colour_for_value(rating_val, all_ratings)
                            
                            html_player_table += f"""<tr>
<td>{row['Player']}</td>
<td style='background-color: {bg_color}; color: {text_color}; font-weight: 800;'>{row['Rating']}</td>
<td style='font-weight: 600; color: #CCCCCC;'>{row['Points']}</td>
</tr>
"""
                        
                        html_player_table += """</tbody>
</table>
"""
                        
                        st.markdown(html_player_table, unsafe_allow_html=True)
    
    # Professional footer
    render_footer()


# ================= TEAM LIST SUMMARY =================

elif page == "Team List Summary":
    render_page_header("Team List Summary", "Complete Team Overview", "📊")
    
    # Team selection
    # Get teams from player data
    try:
        players_df = load_players(CURRENT_SEASON)
    except Exception as e:
        st.error(f"Error loading player data: {e}")
        st.stop()
    
    # Check if data loaded properly
    if players_df.empty or "Team" not in players_df.columns:
        st.error("❌ No player data available. Please check that player data exists for the current season.")
        st.stop()
    
    teams = sorted(players_df["Team"].dropna().unique())
    
    # Set default index based on session state
    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        default_idx = teams.index(st.session_state.default_team)
    
    selected_team = st.selectbox("Select Team", teams, index=default_idx, key="team_list_summary_team")
    
    st.markdown("---")
    
    # Display team logo
    team_code = TEAM_CODE_MAP.get(selected_team, selected_team.lower().replace(" ", ""))
    team_logo_path = f"{LOGO_FOLDER}/{team_code}.png"
    
    if os.path.exists(team_logo_path):
        col_logo, col_title = st.columns([1, 4])
        with col_logo:
            st.markdown("<style>.team-logo img { filter: drop-shadow(0 0 20px rgba(255,255,255,0.4)) drop-shadow(0 4px 12px rgba(0,0,0,0.5)); }</style><div class='team-logo'>", unsafe_allow_html=True)
            st.image(team_logo_path, width=120)
            st.markdown("</div>", unsafe_allow_html=True)
        with col_title:
            st.markdown(f"<h2 style='color: #FFFFFF; margin-top: 20px;'>{selected_team}</h2>", unsafe_allow_html=True)
            st.markdown(f"<p style='color: #CCCCCC; font-size: 1.1em;'>2025 Season List Analysis</p>", unsafe_allow_html=True)
    else:
        st.markdown(f"<h2 style='text-align: center; color: #FFFFFF;'>{selected_team}</h2>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ================= AGE BREAKDOWN SECTION =================
    st.markdown("<h2 style='color: #FFFFFF; margin: 30px 0 20px 0;'>👥 Age Breakdown</h2>", unsafe_allow_html=True)
    
    # Calculate age breakdown data (same logic as Team Age Breakdown page)
    required_cols = ["Player", "Team", "Age", "Matches", "RatingPoints_Avg"]
    missing_cols = [c for c in required_cols if c not in players_df.columns]
    if missing_cols:
        st.error(f"Missing required columns: {', '.join(missing_cols)}")
        st.stop()
    
    players_df["Age"] = pd.to_numeric(players_df["Age"], errors="coerce")
    players_df["Matches"] = pd.to_numeric(players_df["Matches"], errors="coerce")
    players_df["RatingPoints_Avg"] = pd.to_numeric(players_df["RatingPoints_Avg"], errors="coerce")
    
    # Filter to players with at least 1 match
    players_filtered = players_df[players_df["Matches"] >= 1].copy()
    
    AGE_BANDS = ["<22", "22-25", "26-29", "30+"]
    
    def assign_age_band(age):
        if pd.isna(age):
            return None
        if age < 22:
            return "<22"
        elif age < 26:
            return "22-25"
        elif age < 30:
            return "26-29"
        else:
            return "30+"
    
    players_filtered["Age_Band"] = players_filtered["Age"].apply(assign_age_band)
    
    # Calculate team stats
    team_players = players_filtered[players_filtered["Team"] == selected_team]
    
    team_stats = {}
    for band in AGE_BANDS:
        band_players = team_players[team_players["Age_Band"] == band]
        if len(band_players) > 0:
            avg_rating = band_players["RatingPoints_Avg"].mean()
            team_stats[band] = avg_rating
        else:
            team_stats[band] = 0
    
    # Calculate league averages and all teams for ranking
    all_teams = sorted(players_filtered["Team"].dropna().unique())
    league_avg_stats = {}
    team_rankings = {band: [] for band in AGE_BANDS}
    
    for band in AGE_BANDS:
        band_values = []
        for team in all_teams:
            team_band_players = players_filtered[
                (players_filtered["Team"] == team) & 
                (players_filtered["Age_Band"] == band)
            ]
            if len(team_band_players) > 0:
                avg_rating = team_band_players["RatingPoints_Avg"].mean()
                band_values.append(avg_rating)
                team_rankings[band].append((team, avg_rating))
        
        league_avg_stats[band] = np.mean(band_values) if band_values else 0
        team_rankings[band].sort(key=lambda x: x[1], reverse=True)
    
    # Get Top 4 teams based on total points (from List Ladder logic)
    # Using weighted formula: Rating × Matches
    ladder_data = []
    
    # Fill missing Matches with 0
    if "Matches" in players_filtered.columns:
        players_filtered["Matches"] = players_filtered["Matches"].fillna(0)
    else:
        players_filtered["Matches"] = 0
    
    # Calculate weighted rating
    # Cap matches at 23 (regular season) to avoid over-rating players who played finals
    MAX_MATCHES_FOR_RATING = 23
    capped_matches = players_filtered["Matches"].clip(upper=MAX_MATCHES_FOR_RATING)
    players_filtered["Weighted_Rating"] = players_filtered["RatingPoints_Avg"].fillna(0) * capped_matches
    all_weighted = players_filtered["Weighted_Rating"].dropna()
    
    def get_rating_points(weighted_val, all_weighted_clean):
        if pd.isna(weighted_val) or weighted_val == 0:
            return 0
        percentile = (all_weighted_clean <= weighted_val).mean()
        if percentile >= 0.85:
            return 3
        elif percentile >= 0.60:
            return 1
        elif percentile >= 0.35:
            return 0.5
        else:
            return 0
    
    # Load Summary tab to get correct positions (especially Wings)
    summary_df = load_player_summary()
    
    # Create a position mapping from Summary tab
    summary_positions = {}
    if "Player" in summary_df.columns and "Position" in summary_df.columns:
        for _, row in summary_df.iterrows():
            player_name = row.get("Player", "")
            position = row.get("Position", "")
            if pd.notna(player_name) and pd.notna(position):
                summary_positions[str(player_name).strip()] = str(position).strip()
    
    # Load Wing players from AFL_Historical Wings sheet (65 wing players across all teams)
    wing_players_by_lastname_team_2 = {}
    try:
        wings_df_2 = pd.read_excel("data/AFL_Historical_2012_2025.xlsx", sheet_name="Wings")
        for _, row in wings_df_2.iterrows():
            player_name = row.get("Player", "")
            team = row.get("Team", "")
            if pd.notna(player_name) and pd.notna(team):
                name_parts = str(player_name).strip().split()
                if len(name_parts) >= 1:
                    last_name = name_parts[-1].lower()
                    team_str = str(team).strip().lower()
                    key = (last_name, team_str)
                    wing_players_by_lastname_team_2[key] = "Wing"
    except Exception:
        pass
    
    # Map players to depth positions, using Traits for Wings, then Summary, then fallback
    def get_depth_position(player_name, team_name, fallback_position):
        player_key = str(player_name).strip() if pd.notna(player_name) else ""
        team_key = str(team_name).strip().lower() if pd.notna(team_name) else ""
        
        # First check if player is a Wing (by last name + team match from Traits)
        if player_key:
            name_parts = player_key.split()
            if len(name_parts) >= 2:
                last_name = name_parts[-1].lower()
                if (last_name, team_key) in wing_players_by_lastname_team_2:
                    return "Wing"
        
        # Then check Summary tab positions
        if player_key in summary_positions:
            summary_pos = summary_positions[player_key]
            return map_position_to_depth(summary_pos)
        
        # Otherwise use the position from player data
        return map_position_to_depth(fallback_position) if pd.notna(fallback_position) else "Midfielder"
    
    players_filtered["Depth_Position"] = players_filtered.apply(
        lambda row: get_depth_position(row.get("Player"), row.get("Team"), row.get("Position")), axis=1
    )
    players_filtered["Points"] = players_filtered["Weighted_Rating"].apply(
        lambda r: get_rating_points(r, all_weighted)
    )
    
    for team in all_teams:
        team_players_all = players_filtered[players_filtered["Team"] == team]
        total_points = team_players_all["Points"].sum()
        ladder_data.append({"Team": team, "Total Points": total_points})
    
    ladder_df = pd.DataFrame(ladder_data).sort_values("Total Points", ascending=False).reset_index(drop=True)
    top_4_teams = ladder_df.head(4)["Team"].tolist()
    
    # Calculate Top 4 averages for age bands
    top4_avg_stats = {}
    for band in AGE_BANDS:
        band_values = []
        for team in top_4_teams:
            team_band_players = players_filtered[
                (players_filtered["Team"] == team) & 
                (players_filtered["Age_Band"] == band)
            ]
            if len(team_band_players) > 0:
                avg_rating = team_band_players["RatingPoints_Avg"].mean()
                band_values.append(avg_rating)
        top4_avg_stats[band] = np.mean(band_values) if band_values else 0
    
    # Display age breakdown comparison
    st.markdown("""<div style='background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,215,0,0.2); margin-bottom: 25px;'>
<p style='color: #DDDDDD; line-height: 1.8; margin: 0;'>
<strong style='color: #FFFFFF;'>Age Group Performance:</strong> Comparing your team's average player rating in each age bracket against league averages and Top 4 teams.
</p>
</div>""", unsafe_allow_html=True)
    
    # Create comparison table
    comparison_rows = []
    for band in AGE_BANDS:
        team_val = team_stats[band]
        league_val = league_avg_stats[band]
        top4_val = top4_avg_stats[band]
        
        # Get team rank
        rank = next((i + 1 for i, (t, _) in enumerate(team_rankings[band]) if t == selected_team), 18)
        
        comparison_rows.append({
            "Age Band": band,
            f"{selected_team}": f"{team_val:.1f}",
            "League Avg": f"{league_val:.1f}",
            "Top 4 Avg": f"{top4_val:.1f}",
            "Diff vs League": f"{team_val - league_val:+.1f}",
            "Diff vs Top 4": f"{team_val - top4_val:+.1f}",
            "Rank": rank,
            "Team_Val": team_val,
            "League_Val": league_val,
            "Top4_Val": top4_val
        })
    
    # Helper function to get ordinal suffix
    def get_ordinal_suffix(n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    
    # Helper function for rank color - 5 tier system
    def get_rank_color_age(rank):
        """5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)"""
        if rank <= 4:
            return "#008000", "white"   # Elite - Dark Green
        elif rank <= 7:
            return "#90EE90", "black"   # Good - Light Green
        elif rank <= 11:
            return "#FFD700", "black"   # Average - Gold
        elif rank <= 15:
            return "#FFA500", "white"   # Below Average - Orange
        else:
            return "#FF0000", "white"   # Poor - Red
    
    # Create HTML table for age breakdown (uses unified .fe-table CSS)
    html_age_table = """<table class='fe-table fe-table-striped fe-sortable'>
<thead>
<tr>
<th data-tooltip="Player age groupings for list composition analysis">Age Band</th>
<th>""" + selected_team + """</th>
<th data-tooltip="Average value across all 18 AFL teams">League Avg</th>
<th data-tooltip="Average for current top 4 teams - elite benchmark">Top 4 Avg</th>
<th data-tooltip="Difference compared to league average. Positive = above average">Diff vs League</th>
<th data-tooltip="Difference compared to top 4. Positive = exceeding elite benchmark">Diff vs Top 4</th>
<th data-tooltip="Position among 18 teams (1st = best)">Rank</th>
</tr>
</thead>
<tbody>
"""
    
    for row in comparison_rows:
        rank = row["Rank"]
        bg_color, text_color = get_rank_color_age(rank)
        rank_display = get_ordinal_suffix(rank)
        
        # Color code differences
        diff_league = float(row["Diff vs League"].replace("+", ""))
        diff_top4 = float(row["Diff vs Top 4"].replace("+", ""))
        
        diff_league_color = "#90EE90" if diff_league > 0 else "#FF6666" if diff_league < 0 else "#CCCCCC"
        diff_top4_color = "#90EE90" if diff_top4 > 0 else "#FF6666" if diff_top4 < 0 else "#CCCCCC"
        
        html_age_table += f"""<tr>
<td style='font-weight: 700; color: #FFFFFF;'>{row['Age Band']}</td>
<td style='font-weight: 700; color: #FFFFFF;'>{row[selected_team]}</td>
<td>{row['League Avg']}</td>
<td>{row['Top 4 Avg']}</td>
<td style='color: {diff_league_color}; font-weight: 700;'>{row['Diff vs League']}</td>
<td style='color: {diff_top4_color}; font-weight: 700;'>{row['Diff vs Top 4']}</td>
<td><span class='rank-badge' style='background: {bg_color}; color: {text_color};'>{rank_display}</span></td>
</tr>
"""
    
    html_age_table += "</tbody>\n</table>"
    render_sortable_table(html_age_table)
    
    # Age breakdown analysis
    st.markdown("<h3 style='color: #FFFFFF; margin: 30px 0 15px 0;'>📈 Age Breakdown Analysis</h3>", unsafe_allow_html=True)
    
    analysis_points = []
    
    # Find strengths and weaknesses
    strengths = [row for row in comparison_rows if row["Rank"] <= 6]
    weaknesses = [row for row in comparison_rows if row["Rank"] >= 13]
    
    if strengths:
        strength_bands = ", ".join([row["Age Band"] for row in strengths])
        analysis_points.append(f"✅ <strong>Strong Age Groups:</strong> {strength_bands} - performing in top third of competition")
    
    if weaknesses:
        weakness_bands = ", ".join([row["Age Band"] for row in weaknesses])
        analysis_points.append(f"⚠️ <strong>Development Areas:</strong> {weakness_bands} - below competition standard")
    
    # Compare to Top 4
    above_top4 = [row for row in comparison_rows if float(row["Diff vs Top 4"].replace("+", "")) > 0]
    if above_top4:
        above_bands = ", ".join([row["Age Band"] for row in above_top4])
        analysis_points.append(f"⭐ <strong>Elite Performance:</strong> {above_bands} - exceeding Top 4 average")
    
    # Overall comparison
    avg_diff_league = np.mean([float(row["Diff vs League"].replace("+", "")) for row in comparison_rows])
    if avg_diff_league > 1.0:
        analysis_points.append(f"📊 <strong>Overall:</strong> Team is performing above league average across age groups (+{avg_diff_league:.1f} average)")
    elif avg_diff_league < -1.0:
        analysis_points.append(f"📊 <strong>Overall:</strong> Team is performing below league average across age groups ({avg_diff_league:.1f} average)")
    else:
        analysis_points.append(f"📊 <strong>Overall:</strong> Team is performing at league average across age groups")
    
    if analysis_points:
        analysis_html = "<div style='background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,215,0,0.2);'>"
        for point in analysis_points:
            analysis_html += f"<p style='color: #DDDDDD; line-height: 1.8; margin: 10px 0;'>{point}</p>"
        analysis_html += "</div>"
        st.markdown(analysis_html, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ================= POSITIONAL DEPTH SECTION =================
    st.markdown("<h2 style='color: #FFFFFF; margin: 30px 0 20px 0;'>⚡ Positional Depth</h2>", unsafe_allow_html=True)
    
    # Calculate positional depth using same positions as Depth Chart
    # DEPTH_POSITIONS is already defined at top of file: ["Key Defender", "Gen. Defender", "Midfielder", "Mid-Forward", "Wing", "Gen. Forward", "Ruck", "Key Forward"]
    
    # Build ladder for all teams
    position_ladder = []
    for team in all_teams:
        team_players_pos = players_filtered[players_filtered["Team"] == team]
        team_row = {"Team": team}
        total_points = 0
        
        for position in DEPTH_POSITIONS:
            pos_players = team_players_pos[team_players_pos["Depth_Position"] == position]
            pos_total = pos_players["Points"].sum()
            team_row[position] = pos_total
            total_points += pos_total
        
        team_row["Total Points"] = total_points
        position_ladder.append(team_row)
    
    position_ladder_df = pd.DataFrame(position_ladder)
    
    # Calculate rankings for each position
    for position in DEPTH_POSITIONS:
        position_ladder_df[f"{position}_Rank"] = position_ladder_df[position].rank(ascending=False, method='min').astype(int)
    
    position_ladder_df = position_ladder_df.sort_values("Total Points", ascending=False).reset_index(drop=True)
    
    # Get selected team's data
    team_pos_data = position_ladder_df[position_ladder_df["Team"] == selected_team].iloc[0]
    
    # Calculate league and Top 4 averages for positions
    league_pos_avg = {}
    top4_pos_avg = {}
    
    for position in DEPTH_POSITIONS:
        league_pos_avg[position] = position_ladder_df[position].mean()
        top4_pos_avg[position] = position_ladder_df[position_ladder_df["Team"].isin(top_4_teams)][position].mean()
    
    # Create comparison table for positions
    pos_comparison_rows = []
    for position in DEPTH_POSITIONS:
        team_val = team_pos_data[position]
        league_val = league_pos_avg[position]
        top4_val = top4_pos_avg[position]
        rank = int(team_pos_data[f"{position}_Rank"])
        
        pos_comparison_rows.append({
            "Position": position,
            f"{selected_team}": f"{team_val:.1f}",
            "League Avg": f"{league_val:.1f}",
            "Top 4 Avg": f"{top4_val:.1f}",
            "Diff vs League": f"{team_val - league_val:+.1f}",
            "Diff vs Top 4": f"{team_val - top4_val:+.1f}",
            "Rank": rank
        })
    
    st.markdown("""<div style='background: rgba(50,50,50,0.3); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); margin-bottom: 25px;'>
<p style='color: #DDDDDD; line-height: 1.8; margin: 0;'>
<strong style='color: #FFFFFF;'>Positional Strength:</strong> Total points accumulated by players in each position, comparing against league and Top 4 averages. Higher points indicate stronger depth.
</p>
</div>""", unsafe_allow_html=True)
    
    # Create HTML table for positional depth (uses unified .fe-table CSS)
    html_pos_table = """<table class='fe-table fe-table-striped fe-sortable'>
<thead>
<tr>
<th data-tooltip="Primary positional role for depth chart analysis">Position</th>
<th>""" + selected_team + """</th>
<th data-tooltip="Average value across all 18 AFL teams">League Avg</th>
<th data-tooltip="Average for current top 4 teams - elite benchmark">Top 4 Avg</th>
<th data-tooltip="Difference compared to league average. Positive = above average">Diff vs League</th>
<th data-tooltip="Difference compared to top 4. Positive = exceeding elite benchmark">Diff vs Top 4</th>
<th data-tooltip="Position among 18 teams (1st = best)">Rank</th>
</tr>
</thead>
<tbody>
"""
    
    for row in pos_comparison_rows:
        rank = row["Rank"]
        bg_color, text_color = get_rank_color_age(rank)
        rank_display = get_ordinal_suffix(rank)
        
        diff_league = float(row["Diff vs League"].replace("+", ""))
        diff_top4 = float(row["Diff vs Top 4"].replace("+", ""))
        
        diff_league_color = "#90EE90" if diff_league > 0 else "#FF6666" if diff_league < 0 else "#CCCCCC"
        diff_top4_color = "#90EE90" if diff_top4 > 0 else "#FF6666" if diff_top4 < 0 else "#CCCCCC"
        
        html_pos_table += f"""<tr>
<td style='font-weight: 700; color: #FFFFFF;'>{row['Position']}</td>
<td style='font-weight: 700; color: #FFFFFF;'>{row[selected_team]}</td>
<td>{row['League Avg']}</td>
<td>{row['Top 4 Avg']}</td>
<td style='color: {diff_league_color}; font-weight: 700;'>{row['Diff vs League']}</td>
<td style='color: {diff_top4_color}; font-weight: 700;'>{row['Diff vs Top 4']}</td>
<td><span class='rank-badge' style='background: {bg_color}; color: {text_color};'>{rank_display}</span></td>
</tr>
"""
    
    html_pos_table += "</tbody>\n</table>"
    render_sortable_table(html_pos_table)
    
    # Positional depth analysis
    st.markdown("<h3 style='color: #FFFFFF; margin: 30px 0 15px 0;'>📈 Positional Depth Analysis</h3>", unsafe_allow_html=True)
    
    pos_analysis_points = []
    
    # Find strongest and weakest positions
    pos_strengths = [row for row in pos_comparison_rows if row["Rank"] <= 6]
    pos_weaknesses = [row for row in pos_comparison_rows if row["Rank"] >= 13]
    
    if pos_strengths:
        strength_positions = ", ".join([row["Position"] for row in pos_strengths])
        pos_analysis_points.append(f"✅ <strong>Strong Positions:</strong> {strength_positions} - top third depth in competition")
    
    if pos_weaknesses:
        weakness_positions = ", ".join([row["Position"] for row in pos_weaknesses])
        pos_analysis_points.append(f"⚠️ <strong>Development Needs:</strong> {weakness_positions} - below average depth requiring attention")
    
    # Elite positions (beating Top 4)
    elite_positions = [row for row in pos_comparison_rows if float(row["Diff vs Top 4"].replace("+", "")) > 0]
    if elite_positions:
        elite_pos_names = ", ".join([row["Position"] for row in elite_positions])
        pos_analysis_points.append(f"⭐ <strong>Elite Depth:</strong> {elite_pos_names} - exceeding Top 4 teams")
    
    # Overall ladder position - 5 tier system
    team_overall_rank = position_ladder_df[position_ladder_df["Team"] == selected_team].index[0] + 1
    total_points = team_pos_data["Total Points"]
    league_avg_points = position_ladder_df["Total Points"].mean()
    
    if team_overall_rank <= 4:
        pos_analysis_points.append(f"🏆 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Elite list depth ({total_points:.1f} total points)")
    elif team_overall_rank <= 7:
        pos_analysis_points.append(f"📊 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Good list depth ({total_points:.1f} total points)")
    elif team_overall_rank <= 11:
        pos_analysis_points.append(f"📊 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Average list depth ({total_points:.1f} total points)")
    elif team_overall_rank <= 15:
        pos_analysis_points.append(f"📊 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Below average list depth ({total_points:.1f} total points)")
    else:
        pos_analysis_points.append(f"📊 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Poor list depth ({total_points:.1f} total points)")
    
    if pos_analysis_points:
        pos_analysis_html = "<div style='background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,215,0,0.2);'>"
        for point in pos_analysis_points:
            pos_analysis_html += f"<p style='color: #DDDDDD; line-height: 1.8; margin: 10px 0;'>{point}</p>"
        pos_analysis_html += "</div>"
        st.markdown(pos_analysis_html, unsafe_allow_html=True)
    
    # Summary section
    st.markdown("---")
    st.markdown("<h2 style='color: #FFFFFF; margin: 30px 0 20px 0;'>📋 Summary</h2>", unsafe_allow_html=True)
    
    summary_html = f"""<div style='background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%); padding: 30px; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);'>
<h3 style='color: #FFFFFF; margin-top: 0;'>{selected_team} - 2025 List Profile</h3>
<div style='display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px;'>
<div style='background: rgba(80,80,80,0.3); padding: 20px; border-radius: 8px;'>
<h4 style='color: #FFFFFF; margin-top: 0;'>List Depth Ranking</h4>
<p style='color: #FFFFFF; font-size: 2em; font-weight: 900; margin: 10px 0;'>{get_ordinal_suffix(team_overall_rank)}</p>
<p style='color: #CCCCCC; margin: 0;'>Overall Competition Position</p>
</div>
<div style='background: rgba(80,80,80,0.3); padding: 20px; border-radius: 8px;'>
<h4 style='color: #FFFFFF; margin-top: 0;'>Total List Points</h4>
<p style='color: #FFFFFF; font-size: 2em; font-weight: 900; margin: 10px 0;'>{total_points:.1f}</p>
<p style='color: #CCCCCC; margin: 0;'>League Average: {league_avg_points:.1f}</p>
</div>
</div>
</div>"""
    
    st.markdown(summary_html, unsafe_allow_html=True)
    
    # Professional footer
    render_footer()

# ================= BEST 23 (ALL-IN) =================
elif page == "Best 23":

    import base64
    import pandas as pd
    


    # ------------------------------
    # Safe defaults (prevent NameError on first render)
    # ------------------------------
    selected_a = pd.DataFrame()
    selected_b = pd.DataFrame()

    MANUAL_SLOTS = [
        ("Back 6", 6),
        ("Midfield", 6),
        ("Forward 6", 6),
        ("Bench", 5),
    ]


    render_page_header("Best 23", "Model, Compare & Select Your Team", "🏉")
    
    # Breadcrumb navigation
    render_breadcrumb([("Home", "Home"), ("Best 23", None)])

    # =====================================================
    # CONFIG
    # =====================================================
    FIELD_IMAGE_PATH = str(BASE_DIR / "assets" / "field_blank.png")
    FIELD_WIDTH_PX = 1100
    FIELD_HEIGHT_PX = 1000

    ONFIELD_SLOTS = [
        # Back 6 (2 Key, 4 Gen)
        ("Key Defender", 32, 15),
        ("Key Defender", 63, 15),
        ("Gen. Defender", 32, 33),
        ("Gen. Defender", 63, 33),
        ("Gen. Defender", 32, 24),
        ("Gen. Defender", 63, 24),

        # Midfield (butted into ruck)
        ("Wing", 20, 55),
        ("Ruck", 48, 46),
        ("Wing", 76, 55),
        ("Midfielder", 48, 52),
        ("Midfielder", 48, 58),
        ("Midfielder", 48, 64),

        # Forward 6
        ("Key Forward", 32, 93),
        ("Gen. Forward", 32, 75),
        ("Gen. Forward", 63, 75),
        ("Mid-Forward", 32, 84),
        ("Gen. Forward", 63, 84),
        ("Key Forward", 63, 93),
    ]

    BENCH_X = 116
    BENCH_YS = [24, 36, 48, 60, 72]

    # =====================================================
    # HELPERS
    # =====================================================
    def norm(s):
        return "".join(c for c in str(s).lower().strip() if c.isalnum())

    def find_col(df, keys):
        for c in df.columns:
            if all(k in norm(c) for k in [norm(x) for x in keys]):
                return c
        return None

    def split_name(n):
        p = str(n).split()
        return p[0], p[-1] if len(p) > 1 else ""

    def pos_group(p):
        p = str(p).lower()
        if "defend" in p: return "def"
        if "mid" in p: return "mid"
        if "wing" in p or "gen. forward" in p: return "wingfwd"
        if "ruck" in p or "key forward" in p: return "ruckkf"
        return "other"

    def img_b64(path):
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            return ""

    def rating_percentile(val, series) -> float:
        try:
            if val is None:
                return 0.0
            s = pd.to_numeric(series, errors="coerce")
            s = s[~pd.isna(s)]
            if s.empty:
                return 0.0
            return float((s <= float(val)).mean())
        except Exception:
            return 0.0

    def rating_style(val, series):
        """
        Returns (bg, fg, brightness) for the rating pill.
        Uses your existing rating_colour_for_value if present.
        """
        # Base colour from your existing function (if it returns tuple/list)
        bg, fg = "#ffffff", "#000000"
        try:
            c = rating_colour_for_value(val, series)
            if isinstance(c, (tuple, list)) and len(c) >= 2:
                bg, fg = str(c[0]), str(c[1])
            else:
                bg, fg = str(c), "#000000"
        except Exception:
            pass

        # Intensity (stronger rating = brighter)
        pct = rating_percentile(val, series)
        brightness = 0.85 + (0.35 * pct)   # 0.85 → 1.20
        return bg, fg, brightness


    # =====================================================
    # LOAD & MERGE DATA (ONCE)
    # =====================================================
    summary = load_player_summary()
    seasons = get_player_seasons()
    season = 2025 if 2025 in seasons else (seasons[0] if seasons else None)

    if season is None:
        st.error("No season data available.")
        st.stop()

    ratings = load_players(season)

    s_name = find_col(summary, ["player"]) or find_col(summary, ["name"])
    s_pos  = find_col(summary, ["position"])
    s_num  = find_col(summary, ["jumper"]) or find_col(summary, ["guernsey"])

    r_name = find_col(ratings, ["player"]) or find_col(ratings, ["name"])
    r_val  = find_col(ratings, ["rating"])

    if not all([s_name, s_pos, r_name, r_val]):
        st.error("Required columns missing in Summary or Ratings sheets.")
        st.stop()

    summary = summary.rename(columns={s_name:"Player", s_pos:"Position"})
    ratings = ratings.rename(columns={r_name:"Player", r_val:"Rating"})
    summary["Jumper"] = summary[s_num] if s_num else ""

    def make_key(df):
        return df["Team"].astype(str).str.lower().str.strip() + "||" + df["Player"].astype(str).str.lower().str.strip()

    summary["__k"] = make_key(summary)
    ratings["__k"] = make_key(ratings)

    merged_all = summary.merge(
        ratings[["__k", "Rating"]],
        on="__k",
        how="left"
    )

    merged_all["Rating"] = pd.to_numeric(merged_all["Rating"], errors="coerce")
    merged_all = merged_all.dropna(subset=["Rating"])

    teams = sorted(merged_all["Team"].dropna().unique())

    # =====================================================
    # BEST 23 ENGINE
    # =====================================================
    def build_best23(team):
        df = merged_all[merged_all["Team"] == team].sort_values("Rating", ascending=False)
        used = set()
        slots = []

        def pick(position):
            # exact position first
            for _, r in df[df["Position"] == position].iterrows():
                if r["Player"] not in used:
                    used.add(r["Player"])
                    return r
            # fallback: next best overall
            for _, r in df.iterrows():
                if r["Player"] not in used:
                    used.add(r["Player"])
                    return r
            return None

        def pick_best_of_positions(pos_list):
            """
            Pick best available across multiple positions (highest Rating).
            """
            sub = df[df["Position"].isin(pos_list)].copy().sort_values("Rating", ascending=False)

            for _, r in sub.iterrows():
                if r["Player"] not in used:
                    used.add(r["Player"])
                    return r

            # fallback: next best overall
            for _, r in df.iterrows():
                if r["Player"] not in used:
                    used.add(r["Player"])
                    return r
            return None

        # ------------------------------
        # On-field 18 (with 2 hybrid slots)
        # ------------------------------
        for pos, x, y in ONFIELD_SLOTS:

            # HYBRID 1: last midfield slot at (48,64)
            if pos == "Midfielder" and (x, y) == (48, 64):
                r = pick_best_of_positions(["Midfielder", "Mid-Forward"])
                slots.append((x, y, pos, r, False))
                continue

            # HYBRID 2: Mid-Forward slot at (32,84)
            if pos == "Mid-Forward" and (x, y) == (32, 84):
                r = pick_best_of_positions(["Mid-Forward", "Midfielder"])
                slots.append((x, y, pos, r, False))
                continue

            # Normal slots
            slots.append((x, y, pos, pick(pos), False))

        # ------------------------------
        # Bench: 1 defender, then best remaining 4 non-defenders
        # ------------------------------
        bench = df[~df["Player"].isin(used)]
        def_pick = bench[bench["Position"].str.contains("Defend", case=False, na=False)].head(1)

        if not def_pick.empty:
            r = def_pick.iloc[0]
            used.add(r["Player"])
            slots.append((BENCH_X, BENCH_YS[0], "Bench", r, True))

        # now next best 4 non-defenders
        for y in BENCH_YS[1:]:
            bench = df[~df["Player"].isin(used)]
            bench = bench[~bench["Position"].str.contains("Defend", case=False, na=False)]
            if bench.empty:
                break
            r = bench.iloc[0]
            used.add(r["Player"])
            slots.append((BENCH_X, y, "Bench", r, True))

        return slots, used


    # =====================================================
    # AUTO BEST 23 DISPLAY
    # =====================================================
    best23_default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        best23_default_idx = teams.index(st.session_state.default_team)
    team = st.selectbox("Select Team", teams, index=best23_default_idx)
    slots, used = build_best23(team)

    bg = img_b64(FIELD_IMAGE_PATH)

    # ✅ INITIALISE HERE
    magnets_html = ""

    team_ratings_series = merged_all.loc[
        merged_all["Team"] == team, "Rating"
    ]

    for x, y, _, r, is_bench in slots:
        if r is None:
            continue

        first, last = split_name(r["Player"])
        grp = pos_group(r["Position"])
        num = "" if pd.isna(r["Jumper"]) else str(r["Jumper"])
        rat = f"{r['Rating']:.1f}"
        fade = "opacity:0.55;" if is_bench else ""

        bgc, fgc, bri = rating_style(r["Rating"], team_ratings_series)

        magnets_html += f"""
        <div class="wrap" style="left:{x}%; top:{y}%; {fade}">
        <div class="magnet {grp}">
            <div class="num">{num}</div>
            <div class="name">
            <div class="first">{first}</div>
            <div class="last">{last}</div>
            </div>
            <div class="rating"
                style="background:{bgc};
                        color:{fgc};
                        filter:brightness({bri:.3f});">
            {rat}
            </div>
        </div>
        </div>
        """


    html = f"""
    <style>
    .field-container {{
        width: 100%;
        max-width: {FIELD_WIDTH_PX}px;
        margin: 0 auto;
    }}
    
    .field {{
        position: relative;
        width: 100%;
        padding-bottom: {(FIELD_HEIGHT_PX / FIELD_WIDTH_PX) * 100}%;  /* Maintain aspect ratio */
        background: url("data:image/png;base64,{bg}") center/contain no-repeat;
        margin: auto;
    }}

    .wrap {{
        position: absolute;
        transform: translate(-50%, -50%);
    }}

    .magnet {{
        width: clamp(140px, 18vw, 235px);  /* Responsive width */
        height: clamp(32px, 4vw, 44px);    /* Responsive height */
        display: flex;
        align-items: center;
        gap: clamp(4px, 0.6vw, 8px);
        padding: clamp(4px, 0.5vw, 6px) clamp(6px, 0.8vw, 10px);
        border-radius: 16px;
        color: #fff;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
        font-weight: 800;
        box-shadow: 0 8px 18px rgba(0,0,0,.35);
    }}

    .num {{
        min-width: clamp(20px, 2.5vw, 30px);
        text-align: center;
        font-size: clamp(10px, 1.2vw, 13px);
        opacity: 0.95;
    }}

    .name {{
        display: flex;
        flex-direction: column;
        line-height: 1.05;
    }}

    .first {{
        font-size: clamp(7px, 0.8vw, 9px);
        opacity: 0.9;
    }}

    .last {{
        font-size: clamp(10px, 1.2vw, 13px);
    }}

    .rating {{
        margin-left: auto;
        width: clamp(28px, 3.5vw, 40px);
        height: clamp(20px, 2.5vw, 28px);
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: clamp(9px, 1.1vw, 12px);
        font-weight: 900;
        background: #fff;
        color: #000;
    }}

    .def     {{ background: #c62828; }}
    .mid     {{ background: #2e7d32; }}
    .wingfwd {{ background: #ef6c00; }}
    .ruckkf  {{ background: #1565c0; }}
    .other   {{ background: #333; }}
    </style>

    <div class="field-container">
        <div class="field">
            {magnets_html}
        </div>
    </div>
    """

    import streamlit.components.v1 as components
    components.html(
        textwrap.dedent(html).strip(),
        height=int(min(FIELD_HEIGHT_PX + 20, 900)),  # Cap max height
        scrolling=True  # Allow scrolling if needed
    )


    # =====================================================
    # REMAINING SQUAD
    # =====================================================
    st.markdown("---")
    st.subheader("Remaining Squad")

    remaining = merged_all[
        (merged_all["Team"] == team) &
        (~merged_all["Player"].isin(used))
    ].sort_values("Rating", ascending=False)

    buckets = {
        "Key Defender":["Key Defender"],
        "Gen. Defender":["Gen. Defender"],
        "Wing":["Wing"],
        "Midfielder":["Midfielder"],
        "Ruck":["Ruck"],
        "Key Forward":["Key Forward"],
        "Gen. Forward":["Gen. Forward"],
        "Mid-Forward":["Mid-Forward"]
    }

    cols = st.columns(len(buckets))
    for col, (label, plist) in zip(cols, buckets.items()):
        with col:
            st.markdown(f"**{label}**")
            sub = remaining[remaining["Position"].isin(plist)]
            if sub.empty:
                st.caption("—")
            else:
                for _, r in sub.iterrows():
                    st.caption(f"{r['Player']} ({r['Rating']:.1f})")

    # =====================================================
    # FOUNDATION COMPLETE
    # =====================================================
    st.markdown("---")
    st.info("Best 23 foundation is stable. Comparison & Manual Selection ready.")

    # =====================================================
    # BEST 23 COMPARISON (TEAM A vs TEAM B)
    # =====================================================
    import os, base64, textwrap
    import pandas as pd

    st.markdown("---")
    st.header("Best 23 Comparison")

    # -----------------------------------------------------
    # Changes in this version (for your sanity)
    # -----------------------------------------------------
    # 1) Logos 4x bigger and centred
    # 2) Team average rating shown directly under each logo (centred)
    # 3) Header row height increased so logos never crop
    # 4) Removed green background from centre stat columns (clean pills only)
    # 5) Player rating pills conditionally formatted for ALL positions (incl. Mid/Mid-Fwd)
    # 6) Magnets never wrap (ellipsis)
    # 7) Forwards split: Key Forwards + Gen. Forwards (Mid-Forwards counted as Gen. Forwards)

    # ------------------------------
    # Settings
    # ------------------------------
    mode = st.radio(
        "Comparison Mode",
        ["Best 23 (All Players)", "Best 18 (On-field Only)"],
        horizontal=True,
        key="best23_compare_mode"
    )
    use_bench = (mode == "Best 23 (All Players)")

    c1, c2 = st.columns(2)
    with c1:
        best23_cmp_idx = 0
        if "default_team" in st.session_state and st.session_state.default_team in teams:
            best23_cmp_idx = teams.index(st.session_state.default_team)
        team_a = st.selectbox("Team A", teams, index=best23_cmp_idx, key="best23_team_a")
    with c2:
        team_b = st.selectbox(
            "Team B",
            [t for t in teams if t != team_a],
            key="best23_team_b"
        )
    
    # Track comparison in history
    add_to_comparison_history("best23", team_a, team_b)

    # ------------------------------
    # Helpers (logos + rating colour)
    # ------------------------------
    def _b64_file(path: str) -> str:
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""

    def _team_logo_b64(team_name: str) -> str:
        # uses your function name as per your note
        try:
            p = get_team_logo_path(team_name)
            if isinstance(p, str) and os.path.exists(p):
                return _b64_file(p)
        except Exception:
            pass
        return ""

    def _rating_percentile(val, series) -> float:
        try:
            if val is None:
                return 0.0
            s = pd.to_numeric(series, errors="coerce")
            s = s[~pd.isna(s)]
            if s.empty:
                return 0.0
            return float((s <= float(val)).mean())
        except Exception:
            return 0.0

    def _rating_style(val, series):
        """
        Returns (bg, fg, brightness) for the rating pill.
        Uses your existing rating_colour_for_value(val, series) if present.
        """
        bg, fg = "#ffffff", "#000000"
        try:
            c = rating_colour_for_value(val, series)
            if isinstance(c, (tuple, list)) and len(c) >= 2:
                bg, fg = str(c[0]), str(c[1])
            else:
                bg, fg = str(c), "#000000"
        except Exception:
            pass

        pct = _rating_percentile(val, series)
        bri = 0.85 + (0.35 * pct)  # 0.85 → 1.20
        return bg, fg, bri

    def _safe_float(x):
        try:
            return float(x)
        except Exception:
            return None

    # ------------------------------
    # Build Best 23 for both teams
    # ------------------------------
    slots_a, _used_a = build_best23(team_a)
    slots_b, _used_b = build_best23(team_b)

    # Use each team’s rating distribution for conditional pill styling
    team_a_series = merged_all.loc[merged_all["Team"] == team_a, "Rating"]
    team_b_series = merged_all.loc[merged_all["Team"] == team_b, "Rating"]

    def slots_to_df(slots, team_name: str):
        rows = []
        for _, _, _, r, is_bench in slots:
            if r is None:
                continue
            rows.append({
                "Team": team_name,
                "Player": r.get("Player"),
                "Jumper": r.get("Jumper", ""),
                "Position": r.get("Position"),
                "Rating": _safe_float(r.get("Rating")),
                "IsBench": bool(is_bench),
            })
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        if not use_bench:
            df = df[df["IsBench"] == False].copy()
        return df

    best_a = slots_to_df(slots_a, team_a)
    best_b = slots_to_df(slots_b, team_b)

    # ------------------------------
    # Category mapping (includes requested Forward split)
    # ------------------------------
    CATEGORY_MAP = {
        "Key Defender": ["Key Defender"],
        "Gen. Defender": ["Gen. Defender"],
        "Wing": ["Wing"],
        "Midfielder": ["Midfielder"],       # Mid-Forward NOT counted as midfielder here
        "Ruck": ["Ruck"],
        "Key Forward": ["Key Forward"],
        "Gen. Forward": ["Gen. Forward", "Mid-Forward"],  # includes Mid-Forwards
    }

    def cat_df(df, cat_name):
        pos_list = CATEGORY_MAP[cat_name]
        if df.empty:
            return df
        return df[df["Position"].isin(pos_list)].copy()

    def avg_rating(df):
        if df is None or df.empty:
            return None
        return float(pd.to_numeric(df["Rating"], errors="coerce").mean())

    overall_a = avg_rating(best_a)
    overall_b = avg_rating(best_b)

    import base64
    import streamlit.components.v1 as components

    def _img_to_b64(path: str) -> str:
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return ""

    def _pill(val: str, bg="rgba(255,255,255,0.08)", fg="#FFFFFF", big=False):
        fs = "34px" if big else "16px"
        pad = "16px 22px" if big else "10px 14px"
        br = "18px"
        minw = "220px" if big else "120px"
        return (
            f"<div style=\""
            f"display:inline-flex;"
            f"align-items:center;"
            f"justify-content:center;"
            f"padding:{pad};"
            f"border-radius:{br};"
            f"background:{bg};"
            f"color:{fg};"
            f"font-weight:900;"
            f"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;"
            f"font-size:{fs};"
            f"min-width:{minw};"
            f"box-shadow:0 12px 30px rgba(0,0,0,.35);"
            f"letter-spacing:0.05em;"
            f"\">{val}</div>"
        )

    def _diff_pill(d):
        if d is None:
            return _pill("—", bg="rgba(255,255,255,0.06)", big=True)
        if d > 0:
            return _pill(f"{d:+.2f}", bg="rgba(0,180,90,0.55)", big=True)
        if d < 0:
            return _pill(f"{d:+.2f}", bg="rgba(220,60,60,0.55)", big=True)
        return _pill(f"{d:+.2f}", bg="rgba(255,255,255,0.14)", big=True)

    # ------------------------------
    # Build logo b64 (uses your working helper)
    # ------------------------------
    logo_a_path = get_team_logo_path(team_a) if "get_team_logo_path" in globals() else None
    logo_b_path = get_team_logo_path(team_b) if "get_team_logo_path" in globals() else None

    logo_a_b64 = _img_to_b64(logo_a_path) if logo_a_path else ""
    logo_b_b64 = _img_to_b64(logo_b_path) if logo_b_path else ""

    # ------------------------------
    # Values
    # ------------------------------
    overall_a_val = None if overall_a is None else float(overall_a)
    overall_b_val = None if overall_b is None else float(overall_b)
    net_val = None
    if overall_a_val is not None and overall_b_val is not None:
        net_val = overall_a_val - overall_b_val

    overall_a_str = "" if overall_a_val is None else f"{overall_a_val:.2f}"
    overall_b_str = "" if overall_b_val is None else f"{overall_b_val:.2f}"

    # ------------------------------
    # Header HTML (taller + centered)
    # ------------------------------
    header_html = f"""
    <div class="b23Header">
    <div class="teamCol">
        {"<img class='logo' src='data:image/png;base64," + logo_a_b64 + "' />" if logo_a_b64 else "<div class='logoFallback'></div>"}
        <div class="teamName">{team_a}</div>
        <div class="label">OVERALL BEST 23 RATING</div>
        {_pill(overall_a_str if overall_a_str else "—", big=True)}
    </div>

    <div class="midCol">
        <div class="vsPill">VS</div>
        <div class="netLabel">NET (A − B)</div>
        {_diff_pill(net_val)}
        <div class="subNote">Positive = Team A higher</div>
    </div>

    <div class="teamCol">
        {"<img class='logo' src='data:image/png;base64," + logo_b_b64 + "' />" if logo_b_b64 else "<div class='logoFallback'></div>"}
        <div class="teamName">{team_b}</div>
        <div class="label">OVERALL BEST 23 RATING</div>
        {_pill(overall_b_str if overall_b_str else "—", big=True)}
    </div>
    </div>

    <style>
    .b23Header {{
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 0.55fr 1fr;
    gap: 18px;
    align-items: center;
    padding: 10px 8px 18px 8px;
    border-radius: 16px;
    background: rgba(255,255,255,0.02);
    }}

    .teamCol {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    min-height: 340px; /* ✅ prevents cropping */
    }}

    .logo {{
    width: 420px;          /* ✅ big */
    max-width: 90%;
    height: 220px;         /* ✅ fixed box */
    object-fit: contain;   /* ✅ never crop */
    margin-top: 8px;
    margin-bottom: 10px;
    filter: drop-shadow(0 18px 40px rgba(0,0,0,0.45));
    }}

    .logoFallback {{
    width: 420px;
    max-width: 90%;
    height: 220px;
    border-radius: 18px;
    background: rgba(255,255,255,0.04);
    margin-top: 8px;
    margin-bottom: 10px;
    }}

    .teamName {{
    font-size: 22px;
    font-weight: 900;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #fff;
    margin-bottom: 6px;
    }}

    .label {{
    font-size: 11px;
    font-weight: 900;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.18em;
    color: rgba(255,255,255,0.55);
    margin-bottom: 8px;
    text-align:center;
    }}

    .midCol {{
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    min-height: 340px; /* ✅ match sides */
    }}

    .vsPill {{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    padding: 10px 22px;
    border-radius: 999px;
    background: rgba(255,255,255,0.06);
    color: rgba(255,255,255,0.90);
    font-weight: 900;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.18em;
    box-shadow: 0 10px 26px rgba(0,0,0,.28);
    margin-bottom: 18px;
    }}

    .netLabel {{
    font-size: 11px;
    font-weight: 900;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.18em;
    color: rgba(255,255,255,0.55);
    margin-bottom: 10px;
    }}

    .subNote {{
    margin-top: 10px;
    font-size: 12px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: rgba(255,255,255,0.55);
    }}
    </style>
    """

    # ✅ Render as HTML (not markdown) — and make container tall enough
    components.html(header_html.strip(), height=400, scrolling=False)



    st.caption("Order: Team A magnets • A avg • Net (A–B) • B avg • Team B magnets. Bench players are dimmed but included in position averages (when Best 23 selected).")

    # ------------------------------
    # Magnet renderer (no wrapping; conditional rating pill for everyone)
    # ------------------------------
    def _magnet_html(row, series_for_colour, dim=False):
        first, last = split_name(row["Player"])
        num = "" if pd.isna(row.get("Jumper", "")) else str(row.get("Jumper", ""))
        rating_val = _safe_float(row.get("Rating", None))
        rat = "" if rating_val is None else f"{rating_val:.1f}"

        # base group colour from your pos_group
        grp = pos_group(row.get("Position", ""))

        bgc, fgc, bri = _rating_style(rating_val, series_for_colour)

        fade = "opacity:0.55;" if dim else ""
        return f"""
        <div class="magRow" style="{fade}">
        <div class="mag {grp}">
            <div class="magNum">{num}</div>
            <div class="magName">
            <div class="magFirst">{first}</div>
            <div class="magLast">{last}</div>
            </div>
            <div class="magRating"
            style="background:{bgc};color:{fgc};filter:brightness({bri:.3f});">
            {rat}
            </div>
        </div>
        </div>
        """

    mag_css = """
    <style>
    .mag { 
    width:100%;
    min-height:54px;
    display:flex;
    align-items:center;
    gap:12px;
    padding:10px 14px;
    border-radius:18px;
    color:#fff;
    font-weight:900;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    box-shadow:0 10px 26px rgba(0,0,0,.28);
    overflow:hidden;
    }
    .magNum{
    width:44px;
    text-align:center;
    font-size:15px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    opacity:0.95;
    flex:0 0 auto;
    }
    .magName{
    display:flex;
    flex-direction:column;
    line-height:1.05;
    min-width:0;
    flex:1 1 auto;
    }
    .magFirst{
    font-size:10px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    opacity:0.85;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
    }
    .magLast{
    font-size:15px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
    }
    .magRating{
    margin-left:auto;
    width:54px;
    height:34px;
    border-radius:12px;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:14px;
    font-weight:900;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    flex:0 0 auto;
    }
    .def{background:#c62828;}
    .mid{background:#2e7d32;}
    .wingfwd{background:#ef6c00;}
    .ruckkf{background:#1565c0;}
    .other{background:#333;}
    </style>
    """
    st.markdown(mag_css, unsafe_allow_html=True)

    # ------------------------------
    # Position rows
    # ------------------------------
    def _centre_stats(a_df, b_df, label):
        a = avg_rating(a_df)
        b = avg_rating(b_df)
        d = None if (a is None or b is None) else (a - b)

        # Titles above each pill set (clearer what numbers mean)
        hdr = f"""
        <div style="display:flex;gap:12px;justify-content:center;align-items:flex-start;">
        <div style="text-align:center;">
            <div style="font-size:10px;opacity:0.65;letter-spacing:0.05em;margin-bottom:6px;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">TEAM A AVG</div>
            {_pill("—" if a is None else f"{a:.1f}")}
        </div>
        <div style="text-align:center;">
            <div style="font-size:10px;opacity:0.65;letter-spacing:0.05em;margin-bottom:6px;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">NET (A−B)</div>
            {_diff_pill(None if d is None else round(d,1))}
        </div>
        <div style="text-align:center;">
            <div style="font-size:10px;opacity:0.65;letter-spacing:0.05em;margin-bottom:6px;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">TEAM B AVG</div>
            {_pill("—" if b is None else f"{b:.1f}")}
        </div>
        </div>
        """
        st.markdown(textwrap.dedent(hdr).strip(), unsafe_allow_html=True)

    def _render_position(cat_name, n_left=None, n_right=None):
        left_df = cat_df(best_a, cat_name)
        right_df = cat_df(best_b, cat_name)

        # sort best first
        left_df = left_df.sort_values("Rating", ascending=False)
        right_df = right_df.sort_values("Rating", ascending=False)

        # choose counts (optional)
        if n_left is not None:
            left_df = left_df.head(n_left)
        if n_right is not None:
            right_df = right_df.head(n_right)

        lcol, ccol, rcol = st.columns([4.5, 3.0, 4.5], gap="large")

        with lcol:
            st.markdown(f"**{cat_name}**")
            if left_df.empty:
                st.caption("—")
            else:
                for _, row in left_df.iterrows():
                    st.markdown(_magnet_html(row, team_a_series, dim=bool(row.get("IsBench", False))), unsafe_allow_html=True)

        with ccol:
            _centre_stats(left_df, right_df, cat_name)

        with rcol:
            st.markdown(f"**{cat_name}**")
            if right_df.empty:
                st.caption("—")
            else:
                for _, row in right_df.iterrows():
                    st.markdown(_magnet_html(row, team_b_series, dim=bool(row.get("IsBench", False))), unsafe_allow_html=True)

    st.markdown("---")

    # Tuned “how many magnets per row” so it stays clean (adjust if you want more/less)
    _render_position("Key Defender", n_left=2, n_right=2)
    st.markdown("---")
    _render_position("Gen. Defender", n_left=4, n_right=4)
    st.markdown("---")
    _render_position("Midfielder", n_left=4, n_right=4)      # often where your “green magnet formatting” was failing
    st.markdown("---")
    _render_position("Wing", n_left=2, n_right=2)
    st.markdown("---")
    _render_position("Ruck", n_left=2, n_right=2)
    st.markdown("---")
    _render_position("Key Forward", n_left=2, n_right=2)
    st.markdown("---")
    _render_position("Gen. Forward", n_left=4, n_right=4)    # includes Mid-Forwards here

    # =====================================================
    # MANUAL SELECTION (Pick your own Best 23)
    # =====================================================
    st.markdown("---")
    st.header("Manual Selection (Pick Your Own Best 23)")

    def _manual_picker(team_name, merged_all, use_bench=True):
        import pandas as pd

        df = merged_all[merged_all["Team"] == team_name].copy()
        df = df.sort_values("Rating", ascending=False)

        # Group pools (FREE PICK: any player can go anywhere)
        pools = {
            "Back 6": df,
            "Midfield": df,
            "Forward 6": df,
            "Bench": df,
        }


        counts = {"Back 6": 6, "Midfield": 6, "Forward 6": 6, "Bench": 5}

        picked_rows = []
        used = set()

        for grp in ["Back 6", "Midfield", "Forward 6"] + (["Bench"] if use_bench else []):
            sub = pools[grp].copy()
            sub = sub[~sub["Player"].isin(used)]

            options = [
                f"{r.Player} ({r.Position}) – {float(r.Rating):.1f}"
                for r in sub.itertuples()
            ]
            idx_map = {options[i]: i for i in range(len(options))}

            chosen = st.multiselect(
                f"{grp} (pick {counts[grp]})",
                options,
                default=[],
                key=f"manual_{team_name}_{grp}",
                max_selections=counts[grp],
            )

            for label in chosen:
                r = sub.iloc[idx_map[label]]
                used.add(r["Player"])
                rr = r[["Player", "Position", "Rating", "Jumper", "Team"]].to_dict()
                rr["Group"] = grp
                picked_rows.append(rr)

        if not picked_rows:
            return pd.DataFrame()

        out = pd.DataFrame(picked_rows)
        out["Rating"] = pd.to_numeric(out["Rating"], errors="coerce")
        return out


    m1, m2 = st.columns(2)
    with m1:
        st.subheader(f"{team_a} – Manual")
        selected_a = _manual_picker(team_a, merged_all, use_bench=use_bench)
    with m2:
        st.subheader(f"{team_b} – Manual")
        selected_b = _manual_picker(team_b, merged_all, use_bench=use_bench)


    # =====================================================
    # Selected vs Model – Summary (Δ)  (single clean section)
    # =====================================================
    def render_selected_vs_model(best_a, best_b, selected_a, selected_b, team_a, team_b, use_bench):
        import pandas as pd
        import streamlit as st

        st.markdown("---")
        st.header("Selected vs Model – Summary (Δ)")

        st.caption(
            "**Definitions**\n"
            "- **Δ (Delta)** = *Your Selected team average rating* − *Model Best team average rating*\n"
            "- **Positive Δ**: your selection is stronger than the model | **Negative Δ**: weaker\n"
            "- **Net advantage** = Team A Δ − Team B Δ (who gained more vs the model)"
        )

        expected = 23 if use_bench else 18

        def _is_full(df):
            return isinstance(df, pd.DataFrame) and (not df.empty) and (len(df) == expected)

        if not _is_full(selected_a) or not _is_full(selected_b):
            st.info(f"Select **{expected} players** for both teams to see results.")
            return

        # Ensure numeric
        for _df in [best_a, best_b, selected_a, selected_b]:
            if _df is not None and not _df.empty and "Rating" in _df.columns:
                _df["Rating"] = pd.to_numeric(_df["Rating"], errors="coerce")

        def _avg(df):
            if df is None or df.empty:
                return None
            v = pd.to_numeric(df["Rating"], errors="coerce").dropna()
            return float(v.mean()) if not v.empty else None

        def _delta(sel, best):
            a = _avg(sel)
            b = _avg(best)
            if a is None or b is None:
                return None
            return a - b

        # Overall deltas
        dA = _delta(selected_a, best_a)
        dB = _delta(selected_b, best_b)
        net = None if (dA is None or dB is None) else (dA - dB)

        # Simple top row
        c1, c2, c3 = st.columns([1.2, 1, 1.2])
        with c1:
            st.metric(f"{team_a} Δ (Overall)", "—" if dA is None else f"{dA:+.2f}")
        with c2:
            st.metric("Net advantage (AΔ − BΔ)", "—" if net is None else f"{net:+.2f}")
        with c3:
            st.metric(f"{team_b} Δ (Overall)", "—" if dB is None else f"{dB:+.2f}")

        # Group definitions (manual groups)
        group_order = ["Back 6", "Midfield", "Forward 6"] + (["Bench"] if use_bench else [])

        # Map model best df to comparable groups
        def best_group_avg(best_df, grp):
            if best_df is None or best_df.empty:
                return None
            if grp == "Back 6":
                sub = best_df[best_df["Position"].isin(["Key Defender", "Gen. Defender"])]
            elif grp == "Midfield":
                sub = best_df[best_df["Position"].isin(["Midfielder", "Wing", "Ruck"])]
            elif grp == "Forward 6":
                sub = best_df[best_df["Position"].isin(["Key Forward", "Gen. Forward", "Mid-Forward"])]
            elif grp == "Bench":
                if "IsBench" not in best_df.columns:
                    return None
                sub = best_df[best_df["IsBench"] == True]
            else:
                return None
            return _avg(sub)

        def selected_group_avg(sel_df, grp):
            if sel_df is None or sel_df.empty or "Group" not in sel_df.columns:
                return None
            return _avg(sel_df[sel_df["Group"] == grp])

        rows = []
        for grp in group_order:
            bestA = best_group_avg(best_a, grp)
            bestB = best_group_avg(best_b, grp)
            selA  = selected_group_avg(selected_a, grp)
            selB  = selected_group_avg(selected_b, grp)

            gdA = None if (selA is None or bestA is None) else (selA - bestA)
            gdB = None if (selB is None or bestB is None) else (selB - bestB)
            gnet = None if (gdA is None or gdB is None) else (gdA - gdB)

            rows.append({
                "Group": grp,
                f"{team_a} Δ": "—" if gdA is None else f"{gdA:+.1f}",
                "Net (AΔ−BΔ)": "—" if gnet is None else f"{gnet:+.1f}",
                f"{team_b} Δ": "—" if gdB is None else f"{gdB:+.1f}",
                "Meaning": "Positive = you improved vs model"
            })

        st.subheader("Where the differences came from")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        st.caption(
            "How to use this: If Overall Δ is negative, your selection is weaker than the model on average. "
            "Use the group rows to see which line (Back/Mid/Fwd/Bench) drove the difference."
        )


    # Call once (and only once)
    render_selected_vs_model(best_a, best_b, selected_a, selected_b, team_a, team_b, use_bench)
    
    # Professional footer
    render_footer()


# ================= LIST BREAKDOWN - TRAITS =================

elif page == "List Breakdown - Traits":
    
    import base64
    
    # Helper functions for player name and team normalization
    def get_image_base64(path):
        """Convert image file to base64 string."""
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            return ""
    
    def normalize_team_display(team_name):
        """Normalize team name for display (e.g., SYFC -> Sydney)."""
        # Handle None or empty strings
        if not team_name:
            return team_name
            
        team_map = {
            'SYFC': 'Sydney',
            'SFC': 'Sydney',
            'Sydney Swans': 'Sydney',
            'WBFC': 'Western Bulldogs',
            'GWS': 'GWS Giants',
            'GCFC': 'Gold Coast',
            'AFC': 'Adelaide',
            'BFC': 'Brisbane',
            'CFC': 'Carlton',
            'COFC': 'Collingwood',
            'EFC': 'Essendon',
            'FRFC': 'Fremantle',
            'GFC': 'Geelong',
            'HFC': 'Hawthorn',
            'MFC': 'Melbourne',
            'NMFC': 'North Melbourne',
            'PAFC': 'Port Adelaide',
            'RFC': 'Richmond',
            'SKFC': 'St Kilda',
            'WCFC': 'West Coast'
        }
        result = team_map.get(team_name, team_name)
        # Double check - if result still looks like a code, try again
        if result in team_map:
            result = team_map[result]
        return result
    
    def team_name_for_photo_guide(team_name):
        """Convert team name to format used in player_photo_guide.csv."""
        # First normalize the team name
        normalized = normalize_team_display(team_name)
        
        # Map to photo guide format (which uses specific naming)
        photo_guide_map = {
            'Sydney': 'Sydney',
            'SYFC': 'Sydney',
            'SFC': 'Sydney',
            'Western Bulldogs': 'Western Bulldogs',
            'WBFC': 'Western Bulldogs',
            'GWS Giants': 'Greater Western Sydney',
            'GWS': 'Greater Western Sydney',
            'Gold Coast': 'Gold Coast',
            'GCFC': 'Gold Coast',
            'Adelaide': 'Adelaide',
            'AFC': 'Adelaide',
            'Brisbane': 'Brisbane',
            'BFC': 'Brisbane',
            'Carlton': 'Carlton',
            'CFC': 'Carlton',
            'Collingwood': 'Collingwood',
            'COFC': 'Collingwood',
            'Essendon': 'Essendon',
            'EFC': 'Essendon',
            'Fremantle': 'Fremantle',
            'FRFC': 'Fremantle',
            'Geelong': 'Geelong',
            'GFC': 'Geelong',
            'Hawthorn': 'Hawthorn',
            'HFC': 'Hawthorn',
            'Melbourne': 'Melbourne',
            'MFC': 'Melbourne',
            'North Melbourne': 'North Melbourne',
            'NMFC': 'North Melbourne',
            'Port Adelaide': 'Port Adelaide',
            'PAFC': 'Port Adelaide',
            'Richmond': 'Richmond',
            'RFC': 'Richmond',
            'St Kilda': 'St Kilda',
            'SKFC': 'St Kilda',
            'West Coast': 'West Coast',
            'WCFC': 'West Coast'
        }
        return photo_guide_map.get(normalized, normalized)
    
    def get_full_player_name(player_name, team_name=None):
        """Get full player name by looking up in player photo guide."""
        name_map = load_player_name_mapping()
        team_player_map = name_map.get('__team_player_map__', {})
        
        # Try team-aware lookup first
        if team_name and team_player_map:
            def normalize_team(team):
                team = str(team).strip().lower()
                if 'sydney' in team or team in ['syfc', 'sfc']:
                    return 'sydney'
                if 'gws' in team or 'giants' in team:
                    return 'gws'
                if 'bulldogs' in team or team in ['wbfc']:
                    return 'western bulldogs'
                return team.replace(' ', '').replace('fc', '')
            
            norm_team = normalize_team(team_name)
            team_key = f"{norm_team}_{player_name.strip().lower()}"
            if team_key in team_player_map:
                return team_player_map[team_key]
        
        # Fall back to regular name mapping
        return name_map.get(player_name.strip(), name_map.get(player_name.strip().lower(), player_name))
    
    # Season selection
    available_seasons = get_player_seasons()
    if not available_seasons:
        st.error("No season sheets found in traits data.")
        st.stop()
    
    default_season_idx = available_seasons.index(2025) if 2025 in available_seasons else 0
    
    # Season and FC Mode controls in columns
    ctrl_col1, ctrl_col2 = st.columns([2, 1])
    with ctrl_col1:
        selected_season = st.selectbox(
            "Season",
            available_seasons,
            index=default_season_idx,
            key="traits_breakdown_season"
        )
    with ctrl_col2:
        fc_mode = st.toggle("⚽ FC Rating Mode (50-99)", key="traits_breakdown_fc_mode", help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")

    # Load traits data
    traits_df = load_traits(int(selected_season))
    if traits_df.empty:
        st.error(f"Could not load traits data for {selected_season}.")
        st.stop()

    # Load summary data to get Age and Jumper  
    summary_df = load_player_summary()
    if summary_df.empty:
        st.error("Could not load Summary sheet from AFL Player Ratings.")
        st.stop()

    # Merge traits with summary to get the correct Age, Height, Jumper, and Position from Summary
    traits_df = traits_df.merge(
        summary_df[["Player", "Age", "Height", "Jumper", "Position"]],
        left_on="Player_Full",
        right_on="Player",
        how="left",
        suffixes=("_traits", "_summary")
    )
    
    # Drop the duplicate Player column from merge and traits columns
    cols_to_drop = ["Player"]
    if "Age_traits" in traits_df.columns:
        cols_to_drop.append("Age_traits")
    if "Position_traits" in traits_df.columns:
        cols_to_drop.append("Position_traits")
    
    traits_df = traits_df.drop(columns=[c for c in cols_to_drop if c in traits_df.columns])
    
    # Rename summary columns to standard names
    rename_map = {}
    if "Age_summary" in traits_df.columns:
        rename_map["Age_summary"] = "Age"
    if "Position_summary" in traits_df.columns:
        rename_map["Position_summary"] = "Position"
    
    if rename_map:
        traits_df = traits_df.rename(columns=rename_map)
    
    # Ensure Age is numeric
    if "Age" in traits_df.columns:
        traits_df["Age"] = pd.to_numeric(traits_df["Age"], errors="coerce")
    else:
        st.error("Age column not found after merge")
        st.stop()

    # Validate required columns
    required_cols = ["Player_Full", "Team_Full", "Position_Full", "Rating", 
                     "Ball Winning", "Ball Use", "Aerial", "Defence"]
    missing = [c for c in required_cols if c not in traits_df.columns]
    if missing:
        st.error(f"Missing required columns in traits data: {missing}")
        st.stop()

    # Get teams from traits data
    teams = sorted(traits_df["Team_Full"].dropna().unique())
    
    # Set default index based on session state
    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        default_idx = teams.index(st.session_state.default_team)
    selected_team = st.selectbox("Team", teams, index=default_idx, key="traits_breakdown_team")

    # Trait phase selection
    trait_options = {
        "Overall Trait Rating": "Rating",
        "Ball Winning": "Ball Winning",
        "Ball Use": "Ball Use",
        "Aerial": "Aerial",
        "Defence": "Defence",
    }
    trait_label = st.selectbox(
        "Which trait to rank by?",
        list(trait_options.keys()),
        index=0,
        key="traits_breakdown_metric"
    )
    trait_col_name = trait_options[trait_label]
    
    # Squad size filter
    squad_size_options = {
        "Whole Squad": None,
        "Top 23": 23,
        "Top 10": 10
    }
    squad_size_label = st.selectbox(
        "Squad Size",
        list(squad_size_options.keys()),
        index=0,
        key="traits_breakdown_squad_size"
    )
    squad_size_limit = squad_size_options[squad_size_label]

    # Filter to selected team
    df_team = traits_df[traits_df["Team_Full"] == selected_team].copy()
    if df_team.empty:
        st.warning(f"No traits data for {selected_team} in {selected_season}.")
        st.stop()
    
    # Apply squad size filter - get top N players by selected trait
    if squad_size_limit is not None:
        df_team["_temp_rating"] = pd.to_numeric(df_team[trait_col_name], errors="coerce")
        df_team = df_team.nlargest(squad_size_limit, "_temp_rating").drop(columns=["_temp_rating"])

    # Calculate team averages and rankings for all traits (using filtered squad)
    team_stats = {}
    for trait_name, trait_col in [("Overall Rating", "Rating"), ("Ball Winning", "Ball Winning"), 
                                   ("Ball Use", "Ball Use"), ("Aerial", "Aerial"), ("Defence", "Defence")]:
        # Calculate averages per team using the same squad size filter
        team_averages_list = []
        for team_name in traits_df["Team_Full"].dropna().unique():
            team_data = traits_df[traits_df["Team_Full"] == team_name].copy()
            
            # Apply same squad size filter to all teams for fair comparison
            if squad_size_limit is not None:
                team_data["_temp_rating"] = pd.to_numeric(team_data[trait_col], errors="coerce")
                team_data = team_data.nlargest(squad_size_limit, "_temp_rating").drop(columns=["_temp_rating"])
            
            avg_val = pd.to_numeric(team_data[trait_col], errors="coerce").mean()
            if pd.notna(avg_val):
                team_averages_list.append({"Team_Full": team_name, "Avg": avg_val})
        
        team_averages = pd.DataFrame(team_averages_list)
        
        # Rank teams
        team_averages = team_averages.sort_values("Avg", ascending=False).reset_index(drop=True)
        team_averages["Rank"] = range(1, len(team_averages) + 1)
        
        # Get this team's stats
        team_row = team_averages[team_averages["Team_Full"] == selected_team]
        if not team_row.empty:
            avg_val = team_row.iloc[0]["Avg"]
            rank_val = team_row.iloc[0]["Rank"]
            total_teams = len(team_averages)
            
            # Determine color based on rank percentile
            percentile = 1 - (rank_val / total_teams)
            if percentile >= 0.75:  # Top 25%
                color = "#008000"  # Green
                text_color = "white"
            elif percentile >= 0.50:  # Top 50%
                color = "#90EE90"  # Light green
                text_color = "black"
            elif percentile >= 0.25:  # Top 75%
                color = "#FFA500"  # Orange
                text_color = "white"
            else:  # Bottom 25%
                color = "#FF0000"  # Red
                text_color = "white"
            
            team_stats[trait_name] = {
                "avg": avg_val,
                "rank": rank_val,
                "total": total_teams,
                "color": color,
                "text_color": text_color
            }
    
    # Team logo mapping
    team_logo_map = {
        "Adelaide": "afc.png",
        "Brisbane": "lions.png",
        "Carlton": "cfc.png",
        "Collingwood": "cofc.png",
        "Essendon": "efc.png",
        "Fremantle": "ffc.png",
        "Geelong": "gfc.png",
        "Gold Coast": "gcfc.png",
        "GWS Giants": "gws.png",
        "Hawthorn": "hfc.png",
        "Melbourne": "mfc.png",
        "North Melbourne": "nmfc.png",
        "Port Adelaide": "pafc.png",
        "Richmond": "rfc.png",
        "St Kilda": "skfc.png",
        "Sydney": "sfc.png",
        "West Coast": "wcfc.png",
        "Western Bulldogs": "wbfc.png",
    }
    
    logo_file = team_logo_map.get(selected_team, "Logo Transparent.png")
    logo_path = f"team_logos/{logo_file}"
    
    # Encode logo as base64 for HTML embedding
    import base64
    logo_base64 = ""
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode()
    
    # Build Professional broadcast-style header
    # Logo section
    logo_html = ""
    if logo_base64:
        logo_html = f"<img src='data:image/png;base64,{logo_base64}' style='max-width: 180px; max-height: 180px; filter: drop-shadow(0 0 20px rgba(255,255,255,0.4)) drop-shadow(0 4px 12px rgba(0,0,0,0.5));'/>"
    
    # Build trait cards
    trait_cards = []
    for trait_name in ["Ball Winning", "Ball Use", "Aerial", "Defence"]:
        stats = team_stats[trait_name]
        # Format value based on FC mode
        if fc_mode:
            display_val = str(convert_trait_to_fc_rating(stats["avg"]))
        else:
            display_val = f'{stats["avg"]:.2f}'
        card_html = f"""<div style='background-color: {stats["color"]}; color: {stats["text_color"]}; padding: 25px 20px; border-radius: 12px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border: 2px solid rgba(255,255,255,0.15);'>
<div style='font-size: 0.85em; font-weight: 600; letter-spacing: 0.12em; opacity: 0.9; margin-bottom: 8px; text-transform: uppercase; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{trait_name}</div>
<div style='font-size: 2.5em; font-weight: 900; line-height: 1; margin: 8px 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{display_val}</div>
<div style='font-size: 0.95em; font-weight: 700; letter-spacing: 0.08em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>#{stats["rank"]} of {stats["total"]}</div>
</div>"""
        trait_cards.append(card_html)
    
    trait_grid = "".join(trait_cards)
    
    overall_stats = team_stats["Overall Rating"]
    # Format overall value based on FC mode
    if fc_mode:
        overall_display_val = str(convert_trait_to_fc_rating(overall_stats["avg"]))
    else:
        overall_display_val = f'{overall_stats["avg"]:.2f}'
    
    header_html = f"""<div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); padding: 40px 20px; border-radius: 20px; margin-bottom: 30px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); border: 2px solid #e94560;'>
<div style='text-align: center; margin-bottom: 20px;'>{logo_html}</div>
<h1 style='text-align: center; color: #FFFFFF; margin: 10px 0 30px 0; font-size: 3em; font-weight: 900; text-transform: uppercase; letter-spacing: 0.1em; text-shadow: 3px 3px 6px rgba(0,0,0,0.7); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{selected_team}</h1>
<div style='text-align: center; margin-bottom: 30px;'>
<div style='display: inline-block; background-color: {overall_stats["color"]}; color: {overall_stats["text_color"]}; padding: 20px 40px; border-radius: 15px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); border: 3px solid rgba(255,255,255,0.2);'>
<div style='font-size: 0.9em; font-weight: 600; letter-spacing: 0.15em; opacity: 0.9; margin-bottom: 5px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>OVERALL TRAIT RATING</div>
<div style='font-size: 3.5em; font-weight: 900; line-height: 1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{overall_display_val}</div>
<div style='font-size: 1.1em; font-weight: 700; margin-top: 8px; letter-spacing: 0.1em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>RANKED #{overall_stats["rank"]} OF {overall_stats["total"]}</div>
</div>
</div>
<div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; max-width: 1200px; margin: 0 auto;'>{trait_grid}</div>
</div>"""
    
    st.markdown(header_html, unsafe_allow_html=True)

    # Rename columns to match what build_depth_chart_html expects
    df_team = df_team.rename(columns={
        "Player_Full": "Player",
        "Team_Full": "Team"
    })

    # Use the trait column for ranking
    df_team["RatingPoints_Avg"] = pd.to_numeric(
        df_team[trait_col_name], errors="coerce"
    )
    
    # Also prepare full traits_df for ranking calculations
    # Apply squad size filter to ALL teams for fair comparison in rankings
    if squad_size_limit is not None:
        traits_df_for_rankings = []
        for team_name in traits_df["Team_Full"].dropna().unique():
            team_data = traits_df[traits_df["Team_Full"] == team_name].copy()
            team_data["_temp_rating"] = pd.to_numeric(team_data[trait_col_name], errors="coerce")
            team_data_filtered = team_data.nlargest(squad_size_limit, "_temp_rating").drop(columns=["_temp_rating"])
            traits_df_for_rankings.append(team_data_filtered)
        traits_df_renamed = pd.concat(traits_df_for_rankings, ignore_index=True)
    else:
        traits_df_renamed = traits_df.copy()
    
    traits_df_renamed = traits_df_renamed.rename(columns={
        "Player_Full": "Player",
        "Team_Full": "Team"
    })
    traits_df_renamed["RatingPoints_Avg"] = pd.to_numeric(
        traits_df_renamed[trait_col_name], errors="coerce"
    )
    
    # Remove duplicate columns if they exist
    if len(traits_df_renamed.columns) != len(set(traits_df_renamed.columns)):
        traits_df_renamed = traits_df_renamed.loc[:, ~traits_df_renamed.columns.duplicated()]

    # Depth chart section header with squad size indicator
    squad_size_text = f"{squad_size_label}" if squad_size_limit else "Full Squad"
    section_header = f"""<div style='background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 12px; margin: 30px 0 20px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border-left: 5px solid #e94560;'><h3 style='color: #FFFFFF; margin: 0; font-weight: 900; letter-spacing: 0.05em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>📋 SQUAD DEPTH GRID — {trait_label.upper()}</h3><p style='color: #CCCCCC; margin: 8px 0 0 0; font-size: 0.95em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{selected_season} Season | {squad_size_text} | Coloured by team percentile</p></div>"""
    
    st.markdown(section_header, unsafe_allow_html=True)

    html = build_depth_chart_html(df_team, traits_df_renamed, fc_mode=fc_mode)
    st.markdown(html, unsafe_allow_html=True)
    
    # ============= TRAITS-BASED LIST LADDER =============
    st.markdown(f"""<div style='background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 12px; margin: 50px 0 20px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border-left: 5px solid #e94560;'><h3 style='color: #FFFFFF; margin: 0; font-weight: 900; letter-spacing: 0.05em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>🏆 TRAITS LIST LADDER — AFL RANKINGS</h3><p style='color: #CCCCCC; margin: 8px 0 0 0; font-size: 0.95em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{selected_season} Season | {squad_size_text} | Sorted by Overall Trait Rating</p></div>""", unsafe_allow_html=True)
    
    # Calculate league-wide rankings for all teams
    ladder_data = []
    for team_name in sorted(traits_df["Team_Full"].dropna().unique()):
        team_data = traits_df[traits_df["Team_Full"] == team_name].copy()
        
        # Apply squad size filter
        if squad_size_limit is not None:
            team_data["_temp_rating"] = pd.to_numeric(team_data["Rating"], errors="coerce")
            team_data = team_data.nlargest(squad_size_limit, "_temp_rating").drop(columns=["_temp_rating"])
        
        # Calculate averages for each trait
        overall_avg = pd.to_numeric(team_data["Rating"], errors="coerce").mean()
        ball_winning_avg = pd.to_numeric(team_data["Ball Winning"], errors="coerce").mean()
        ball_use_avg = pd.to_numeric(team_data["Ball Use"], errors="coerce").mean()
        aerial_avg = pd.to_numeric(team_data["Aerial"], errors="coerce").mean()
        defence_avg = pd.to_numeric(team_data["Defence"], errors="coerce").mean()
        
        if pd.notna(overall_avg):
            ladder_data.append({
                "Team": team_name,
                "Overall": overall_avg,
                "Ball Winning": ball_winning_avg,
                "Ball Use": ball_use_avg,
                "Aerial": aerial_avg,
                "Defence": defence_avg
            })
    
    # Create DataFrame and sort by Overall rating
    ladder_df = pd.DataFrame(ladder_data)
    ladder_df = ladder_df.sort_values("Overall", ascending=False).reset_index(drop=True)
    ladder_df["Rank"] = range(1, len(ladder_df) + 1)
    
    # Add ranking for each trait column
    for col in ["Overall", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
        ladder_df[f"{col}_Rank"] = ladder_df[col].rank(ascending=False, method="min").astype(int)
    
    # Helper function to get color based on rank - 5 tier system
    def get_ladder_rank_color(rank, total=18):
        """5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)"""
        if rank <= 4:
            return "#008000", "white"   # Elite - Dark Green
        elif rank <= 7:
            return "#90EE90", "black"   # Good - Light Green
        elif rank <= 11:
            return "#FFD700", "black"   # Average - Gold
        elif rank <= 15:
            return "#FFA500", "white"   # Below Average - Orange
        else:
            return "#FF0000", "white"   # Poor - Red
    
    # Build HTML table
    ladder_html = ["<table style='width:100%;border-collapse:separate;border-spacing:0;font-size:0.9em;box-shadow:0 8px 24px rgba(0,0,0,0.4);border-radius:12px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,\"Helvetica Neue\",Arial,sans-serif;'>"]
    
    # Header row
    ladder_html.append("<tr>")
    ladder_html.append("<th style='background:linear-gradient(135deg,#1a1a1a 0%,#2d2d2d 100%);color:#FFFFFF;padding:16px 12px;border-right:2px solid #444;font-weight:900;font-size:1.05em;letter-spacing:0.05em;text-transform:uppercase;text-align:center;'>Rank</th>")
    ladder_html.append("<th style='background:linear-gradient(135deg,#1a1a1a 0%,#2d2d2d 100%);color:#FFFFFF;padding:16px 12px;border-right:2px solid #444;font-weight:900;font-size:1.05em;letter-spacing:0.05em;text-transform:uppercase;text-align:left;'>Team</th>")
    
    for col_name, col_key in [("Overall Rating", "Overall"), ("Ball Winning", "Ball Winning"), ("Ball Use", "Ball Use"), ("Aerial", "Aerial"), ("Defence", "Defence")]:
        ladder_html.append(f"<th style='background:linear-gradient(135deg,#1a1a1a 0%,#2d2d2d 100%);color:#FFFFFF;padding:16px 12px;border-right:2px solid #444;font-weight:900;font-size:1.05em;letter-spacing:0.05em;text-transform:uppercase;text-align:center;'>{col_name}</th>")
    
    ladder_html.append("</tr>")
    
    # Data rows
    for idx, row in ladder_df.iterrows():
        is_selected = row["Team"] == selected_team
        row_bg = "background:linear-gradient(135deg,#e3f2fd 0%,#bbdefb 100%);" if is_selected else "background:#FFFFFF;"
        
        ladder_html.append("<tr>")
        
        # Rank column
        rank = row["Rank"]
        rank_bg, rank_fg = get_ladder_rank_color(rank, len(ladder_df))
        ladder_html.append(f"<td style='{row_bg}padding:14px 12px;border-right:2px solid #e0e0e0;border-top:2px solid #e0e0e0;text-align:center;'><span style='display:inline-block;background:{rank_bg};color:{rank_fg};padding:8px 16px;border-radius:8px;font-weight:900;font-size:1.2em;box-shadow:0 2px 8px rgba(0,0,0,0.2);min-width:45px;'>{rank}</span></td>")
        
        # Team name column
        team_style = "font-weight:900;font-size:1.1em;color:#1a1a1a;" if is_selected else "font-weight:700;color:#2d2d2d;"
        ladder_html.append(f"<td style='{row_bg}padding:14px 16px;border-right:2px solid #e0e0e0;border-top:2px solid #e0e0e0;{team_style}min-width:180px;'>{row['Team']}</td>")
        
        # Trait columns with rankings
        for col in ["Overall", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
            val = row[col]
            trait_rank = row[f"{col}_Rank"]
            bg, fg = get_ladder_rank_color(trait_rank, len(ladder_df))
            # Format value based on FC mode
            if fc_mode:
                display_val = str(convert_trait_to_fc_rating(val))
            else:
                display_val = f'{val:.2f}'
            
            ladder_html.append(f"<td style='{row_bg}padding:14px 12px;border-right:2px solid #e0e0e0;border-top:2px solid #e0e0e0;text-align:center;'><div style='display:inline-block;background:{bg};color:{fg};padding:10px 16px;border-radius:10px;font-weight:900;font-size:1.15em;box-shadow:0 3px 10px rgba(0,0,0,0.2);min-width:70px;'>{display_val}<div style='font-size:0.7em;opacity:0.8;margin-top:2px;'>#{trait_rank}</div></div></td>")
        
        ladder_html.append("</tr>")
    
    ladder_html.append("</table>")
    
    st.markdown("".join(ladder_html), unsafe_allow_html=True)
    
    # ========== TEAM TRAIT COMPARISON SECTION ==========
    st.markdown("---")
    st.markdown("<h2 style='color:#FFFFFF;margin-top:40px;'>⚖️ Team Trait Comparison</h2>", unsafe_allow_html=True)
    
    # Team selection for comparison
    st.markdown("<p style='color:rgba(255,255,255,0.8);'>Compare two teams across the five trait pillars</p>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        team1_trait = st.selectbox("Team 1 (Base)", teams, index=teams.index(selected_team) if selected_team in teams else 0, key="trait_compare_team1")
    with col2:
        default_idx = 1 if len(teams) > 1 else 0
        team2_trait = st.selectbox("Team 2 (Comparison)", teams, index=default_idx, key="trait_compare_team2")
    
    if team1_trait == team2_trait:
        st.warning("Please select two different teams to compare.")
    else:
        # Display team logos
        st.markdown("---")
        logo_col1, logo_col2 = st.columns(2)
        
        with logo_col1:
            st.markdown(f"<h3 style='text-align: center;'>{team1_trait}</h3>", unsafe_allow_html=True)
            _, center_col, _ = st.columns([1, 2, 1])
            with center_col:
                display_logo(team1_trait, st, size=180)
        
        with logo_col2:
            st.markdown(f"<h3 style='text-align: center;'>{team2_trait}</h3>", unsafe_allow_html=True)
            _, center_col, _ = st.columns([1, 2, 1])
            with center_col:
                display_logo(team2_trait, st, size=180)
        
        # Get team data from ladder
        team1_data = ladder_df[ladder_df["Team"] == team1_trait].iloc[0]
        team2_data = ladder_df[ladder_df["Team"] == team2_trait].iloc[0]
        
        # ========== RADAR CHARTS AND COLUMN CHART SECTION ==========
        st.markdown("---")
        st.subheader("Visual Comparison")
        
        # Prepare data for charts
        trait_metrics = ["Overall", "Ball Winning", "Ball Use", "Aerial", "Defence"]
        trait_display = ["Overall Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
        team1_values = []
        team2_values = []
        top4_averages = []
        
        for metric in trait_metrics:
            team1_val = float(team1_data[metric])
            team2_val = float(team2_data[metric])
            
            # Calculate Top 4 average
            top4_avg = ladder_df.nlargest(4, metric)[metric].mean()
            
            team1_values.append(team1_val)
            team2_values.append(team2_val)
            top4_averages.append(top4_avg)
        
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            
            # Close the polygon
            team1_values_closed = team1_values + [team1_values[0]]
            team2_values_closed = team2_values + [team2_values[0]]
            top4_averages_closed = top4_averages + [top4_averages[0]]
            trait_display_closed = trait_display + [trait_display[0]]
            
            # Create subplots: 2 radars + 1 column chart
            fig = make_subplots(
                rows=1, cols=3,
                specs=[[{'type': 'polar'}, {'type': 'polar'}, {'type': 'xy'}]],
                horizontal_spacing=0.15
            )
            
            # === RADAR 1: TEAM 1 ===
            fig.add_trace(
                go.Scatterpolar(
                    r=top4_averages_closed,
                    theta=trait_display_closed,
                    fill='toself',
                    fillcolor='rgba(255, 215, 0, 0.1)',
                    line=dict(color='#FFD700', width=3),
                    name='Top 4 Avg',
                    legendgroup='averages',
                    showlegend=True
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatterpolar(
                    r=team1_values_closed,
                    theta=trait_display_closed,
                    fill='toself',
                    fillcolor='rgba(100, 150, 255, 0.2)',
                    line=dict(color='#6496FF', width=3),
                    name=team1_trait,
                    legendgroup='teams',
                    showlegend=True
                ),
                row=1, col=1
            )
            
            # === RADAR 2: TEAM 2 ===
            fig.add_trace(
                go.Scatterpolar(
                    r=top4_averages_closed,
                    theta=trait_display_closed,
                    fill='toself',
                    fillcolor='rgba(255, 215, 0, 0.1)',
                    line=dict(color='#FFD700', width=3),
                    name='Top 4 Avg',
                    legendgroup='averages',
                    showlegend=False
                ),
                row=1, col=2
            )
            
            fig.add_trace(
                go.Scatterpolar(
                    r=team2_values_closed,
                    theta=trait_display_closed,
                    fill='toself',
                    fillcolor='rgba(255, 100, 100, 0.2)',
                    line=dict(color='#FF6464', width=3),
                    name=team2_trait,
                    legendgroup='teams',
                    showlegend=True
                ),
                row=1, col=2
            )
            
            # === COLUMN CHART: SIDE BY SIDE COMPARISON ===
            fig.add_trace(
                go.Bar(
                    x=trait_display,
                    y=team1_values,
                    name=team1_trait,
                    marker=dict(color='#6496FF'),
                    legendgroup='teams',
                    showlegend=False
                ),
                row=1, col=3
            )
            
            fig.add_trace(
                go.Bar(
                    x=trait_display,
                    y=team2_values,
                    name=team2_trait,
                    marker=dict(color='#FF6464'),
                    legendgroup='teams',
                    showlegend=False
                ),
                row=1, col=3
            )
            
            # Update polar axes
            max_val = max(max(team1_values), max(team2_values), max(top4_averages)) * 1.1
            
            for col_idx in [1, 2]:
                fig.update_polars(
                    radialaxis=dict(
                        visible=True,
                        range=[0, max_val],
                        showticklabels=True,
                        tickfont=dict(color='white', size=9),
                        gridcolor='gray'
                    ),
                    angularaxis=dict(
                        tickfont=dict(color='white', size=11, family='Arial Black'),
                        gridcolor='gray'
                    ),
                    bgcolor='rgba(0,0,0,0)',
                    row=1, col=col_idx
                )
            
            # Update column chart axes
            fig.update_xaxes(title_text="", tickfont=dict(color='white', size=10), row=1, col=3)
            fig.update_yaxes(title_text="Rating", tickfont=dict(color='white', size=10), row=1, col=3)
            
            # Update layout
            fig.update_layout(
                title_text=f"<b>{team1_trait} vs {team2_trait}</b> – Trait Comparison ({selected_season})",
                title_font_size=18,
                showlegend=True,
                legend=dict(
                    font=dict(color='white', size=11),
                    bgcolor='rgba(0,0,0,0.5)',
                    bordercolor='white',
                    borderwidth=1,
                    x=1.02,
                    y=1
                ),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=550,
                font=dict(color='white')
            )
            
            st.plotly_chart(fig, width="stretch")
            
        except ImportError:
            st.warning("Plotly not installed.")
        
        # ========== STRENGTH/WEAKNESS ANALYSIS ==========
        st.markdown("---")
        st.subheader(f"Strengths & Weaknesses Analysis: {team1_trait} vs {team2_trait}")
        
        # Helper function for ordinal rank format
        def format_rank_trait(rank_val):
            if pd.isna(rank_val):
                return "N/A"
            try:
                r = int(rank_val)
                if 10 <= (r % 100) <= 20:
                    suffix = "th"
                else:
                    suffix = {1: "st", 2: "nd", 3: "rd"}.get(r % 10, "th")
                return f"({r}{suffix})"
            except:
                return str(rank_val)
        
        # Analyze each trait
        trait_analysis = []
        for i, metric in enumerate(trait_metrics):
            team1_val = team1_values[i]
            team2_val = team2_values[i]
            team1_rank = int(team1_data[f"{metric}_Rank"])
            team2_rank = int(team2_data[f"{metric}_Rank"])
            
            trait_analysis.append({
                "metric": trait_display[i],
                "team1_val": team1_val,
                "team2_val": team2_val,
                "team1_rank": team1_rank,
                "team2_rank": team2_rank,
            })
        
        # Create DataFrame
        trait_df = pd.DataFrame(trait_analysis)
        
        # Strengths: Team 1 has BETTER ranking (lower number) than Team 2
        team1_strengths = trait_df[trait_df["team1_rank"] < trait_df["team2_rank"]].sort_values("team1_rank", ascending=True)
        
        # Weaknesses: Team 2 has BETTER ranking (lower number) than Team 1
        team1_weaknesses = trait_df[trait_df["team1_rank"] > trait_df["team2_rank"]].sort_values("team2_rank", ascending=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"<h3 style='color: #00CC00;'>🟢 {team1_trait} – Strengths</h3>", unsafe_allow_html=True)
            if len(team1_strengths) > 0:
                for idx, row in team1_strengths.iterrows():
                    metric = row["metric"]
                    t1_val = row["team1_val"]
                    t2_val = row["team2_val"]
                    t1_rank = row["team1_rank"]
                    t2_rank = row["team2_rank"]
                    t1_rank_str = format_rank_trait(t1_rank)
                    t2_rank_str = format_rank_trait(t2_rank)
                    
                    rank_diff = int(t2_rank - t1_rank)
                    
                    # Format values based on FC mode
                    t1_val_str = str(convert_trait_to_fc_rating(t1_val)) if fc_mode else f"{t1_val:.2f}"
                    t2_val_str = str(convert_trait_to_fc_rating(t2_val)) if fc_mode else f"{t2_val:.2f}"
                    
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(90deg, rgba(0,204,0,0.1) 0%, rgba(0,204,0,0.05) 100%); 
                                    border-left: 4px solid #00CC00; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                            <div style='font-weight: bold; color: #00CC00;'>{metric}</div>
                            <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                {team1_trait}: <span style='font-weight: bold; color: #00FF00;'>{t1_val_str}</span> {t1_rank_str} 
                                <span style='color: #888;'>vs</span> 
                                {team2_trait}: <span style='font-weight: bold;'>{t2_val_str}</span> {t2_rank_str}
                            </div>
                            <div style='font-size: 0.85em; color: #00DD00; margin-top: 4px;'>
                                +{rank_diff} positions ahead
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            else:
                st.info(f"No traits where {team1_trait} ranks higher")
        
        with col2:
            st.markdown(f"<h3 style='color: #FF4444;'>🔴 {team1_trait} – Weaknesses</h3>", unsafe_allow_html=True)
            if len(team1_weaknesses) > 0:
                for idx, row in team1_weaknesses.iterrows():
                    metric = row["metric"]
                    t1_val = row["team1_val"]
                    t2_val = row["team2_val"]
                    t1_rank = row["team1_rank"]
                    t2_rank = row["team2_rank"]
                    t1_rank_str = format_rank_trait(t1_rank)
                    t2_rank_str = format_rank_trait(t2_rank)
                    
                    rank_diff = int(t1_rank - t2_rank)
                    
                    # Format values based on FC mode
                    t1_val_str = str(convert_trait_to_fc_rating(t1_val)) if fc_mode else f"{t1_val:.2f}"
                    t2_val_str = str(convert_trait_to_fc_rating(t2_val)) if fc_mode else f"{t2_val:.2f}"
                    
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(90deg, rgba(255,68,68,0.1) 0%, rgba(255,68,68,0.05) 100%); 
                                    border-left: 4px solid #FF4444; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                            <div style='font-weight: bold; color: #FF4444;'>{metric}</div>
                            <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                {team1_trait}: <span style='font-weight: bold;'>{t1_val_str}</span> {t1_rank_str} 
                                <span style='color: #888;'>vs</span> 
                                {team2_trait}: <span style='font-weight: bold; color: #FF6666;'>{t2_val_str}</span> {t2_rank_str}
                            </div>
                            <div style='font-size: 0.85em; color: #FF6666; margin-top: 4px;'>
                                -{rank_diff} positions behind
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            else:
                st.info(f"No traits where {team1_trait} ranks lower")

    # =====================================================
    # SEASON LEADERS
    # =====================================================
    st.markdown("<div style='margin:64px 0 48px 0;'></div>", unsafe_allow_html=True)
    
    # Season filter for leaders section
    leader_filter_col1, leader_filter_col2, leader_filter_col3 = st.columns(3)
    
    with leader_filter_col1:
        selected_leaders_season = st.selectbox(
            "Select Season for Leaders",
            available_seasons,
            index=available_seasons.index(selected_season) if selected_season in available_seasons else 0,
            key="leaders_season_filter"
        )
    
    # Load traits data for selected leaders season (may be different from main page)
    leaders_traits_df = load_traits(int(selected_leaders_season))
    if leaders_traits_df.empty:
        st.warning(f"Could not load traits data for {selected_leaders_season} season leaders.")
    else:
        # Merge with summary for full data
        leaders_traits_df = leaders_traits_df.merge(
            summary_df[["Player", "Age", "Height", "Jumper", "Position"]],
            left_on="Player_Full",
            right_on="Player",
            how="left",
            suffixes=("_traits", "_summary")
        )
        
        # Clean up columns
        cols_to_drop = ["Player"]
        if "Age_traits" in leaders_traits_df.columns:
            cols_to_drop.append("Age_traits")
        if "Position_traits" in leaders_traits_df.columns:
            cols_to_drop.append("Position_traits")
        
        leaders_traits_df = leaders_traits_df.drop(columns=[c for c in cols_to_drop if c in leaders_traits_df.columns])
        
        # Rename summary columns
        rename_map = {}
        if "Age_summary" in leaders_traits_df.columns:
            rename_map["Age_summary"] = "Age"
        if "Position_summary" in leaders_traits_df.columns:
            rename_map["Position_summary"] = "Position"
        
        if rename_map:
            leaders_traits_df = leaders_traits_df.rename(columns=rename_map)
        
        st.markdown(f"""
        <div style="text-align:center;margin-bottom:48px;">
            <h1 style="font-size:42px;font-weight:900;color:#FFFFFF;margin:0 0 8px 0;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;letter-spacing:0.02em;">
                {selected_leaders_season} Season Leaders
            </h1>
            <p style="font-size:16px;color:rgba(255,255,255,0.7);margin:0;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-weight:600;">
                Top 5 performers across all trait categories
            </p>
        </div>
        """, unsafe_allow_html=True)
    
    # Filters
    filter_col1, filter_col2 = st.columns(2)
    
    with filter_col1:
        # Position filter
        all_positions = sorted(leaders_traits_df["Position_Full"].dropna().unique())
        position_options = ["All Positions"] + all_positions
        selected_position_leaders = st.selectbox(
            "Filter by Position",
            position_options,
            key="leaders_position_filter"
        )
    
    with filter_col2:
        # Team filter
        leaders_teams = sorted(leaders_traits_df["Team_Full"].dropna().unique())
        team_options = ["All Teams"] + leaders_teams
        selected_team_leaders = st.selectbox(
            "Filter by Team",
            team_options,
            key="leaders_team_filter"
        )
    
    # Filter the dataframe based on selections
    filtered_leaders_df = leaders_traits_df.copy()
    
    if selected_position_leaders != "All Positions":
        filtered_leaders_df = filtered_leaders_df[filtered_leaders_df["Position_Full"] == selected_position_leaders]
    
    if selected_team_leaders != "All Teams":
        filtered_leaders_df = filtered_leaders_df[filtered_leaders_df["Team_Full"] == selected_team_leaders]
    
    # Define the 5 pillars
    pillars = {
        "OVERALL RATING": "Rating",
        "BALL USE": "Ball Use",
        "BALL WINNING": "Ball Winning",
        "AERIAL": "Aerial",
        "DEFENCE": "Defence"
    }
    
    # Define gradient colors for each pillar (matching the image)
    pillar_colors = {
        "OVERALL RATING": ("#6B46C1", "#4A148C"),  # Purple
        "BALL USE": ("#1E88E5", "#0D47A1"),  # Blue
        "BALL WINNING": ("#00ACC1", "#006064"),  # Cyan
        "AERIAL": ("#43A047", "#1B5E20"),  # Green
        "DEFENCE": ("#8E24AA", "#4A148C")   # Purple/Magenta
    }
    
    # Create 5 columns for the 5 pillars
    pillar_cols = st.columns(5, gap="medium")
    
    for idx, (pillar_name, metric_col) in enumerate(pillars.items()):
        with pillar_cols[idx]:
            # Get top 5 for this pillar
            top5 = filtered_leaders_df.nlargest(5, metric_col)[["Player_Full", "Team_Full", metric_col, "Position_Full"]].reset_index(drop=True)
            
            if len(top5) == 0:
                st.warning(f"No data for {pillar_name}")
                continue
            
            # Get gradient colors
            color_start, color_end = pillar_colors[pillar_name]
            
            # Display pillar header with gradient background
            st.markdown(
                f"""
                <div style="background: linear-gradient(135deg, {color_start} 0%, {color_end} 100%);
                            padding: 16px;
                            border-radius: 12px 12px 0 0;
                            text-align: center;
                            border: 1px solid rgba(255,255,255,0.2);
                            border-bottom: none;">
                    <div style="font-size: 13px;
                                font-weight: 900;
                                color: #FFFFFF;
                                letter-spacing: 0.1em;
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
                        {pillar_name}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            # Display top player (rank 1) with photo
            if len(top5) > 0:
                top_player = top5.iloc[0]
                player_name = top_player["Player_Full"]
                team_name = top_player["Team_Full"]
                value = top_player[metric_col]
                
                # Normalize team name for photo lookup
                normalized_team = normalize_team_display(team_name)
                photo_team = team_name_for_photo_guide(normalized_team)
                
                # Get full name
                full_name = get_full_player_name(player_name, normalized_team)
                
                # Split name for display
                name_parts = full_name.split()
                if len(name_parts) >= 2:
                    first_name = " ".join(name_parts[:-1])
                    last_name = name_parts[-1]
                else:
                    first_name = ""
                    last_name = full_name
                
                # Look up photo
                photo_path = None
                photo_guide_path = str(BASE_DIR / "player_photo_guide.csv")
                if os.path.exists(photo_guide_path):
                    photo_guide = pd.read_csv(photo_guide_path)
                    # Try exact match with photo_team first
                    photo_match = photo_guide[
                        (photo_guide["Player"] == full_name) & 
                        (photo_guide["Team"] == photo_team)
                    ]
                    # If no match, try just by player name
                    if photo_match.empty:
                        photo_match = photo_guide[photo_guide["Player"] == full_name]
                    
                    if not photo_match.empty:
                        photo_filename = photo_match.iloc[0]["Filename"]
                        potential_path = str(BASE_DIR / "player_photos" / photo_filename)
                        if os.path.exists(potential_path):
                            photo_path = potential_path
                
                # Display top player card with photo
                if photo_path:
                    photo_base64 = get_image_base64(photo_path)
                    photo_html = f'<img src="data:image/jpeg;base64,{photo_base64}" style="width:100%;height:280px;object-fit:cover;display:block;">'
                else:
                    photo_html = f'<div style="width:100%;height:280px;background:linear-gradient(135deg, {color_start}40 0%, {color_end}40 100%);display:flex;align-items:center;justify-content:center;"><span style="font-size:72px;opacity:0.3;">👤</span></div>'
                
                # Get conditional color for value
                rating_color = rating_colour_for_value(value, filtered_leaders_df[metric_col])[0]
                
                # Format value based on FC mode
                value_display = str(convert_trait_to_fc_rating(value)) if fc_mode else f"{value:.2f}"
                
                st.markdown(
                    f"""
                    <div style="background: linear-gradient(145deg, rgba(20,20,30,0.98), rgba(30,30,45,0.98));
                                border-radius: 0 0 12px 12px;
                                border: 1px solid rgba(255,255,255,0.15);
                                border-top: none;
                                overflow: hidden;
                                box-shadow: 0 8px 24px rgba(0,0,0,0.5);
                                transition: transform 0.3s ease;">
                        {photo_html}
                        <div style="padding: 20px 16px;">
                            <div style="text-align: center;">
                                <div style="font-size: 48px;
                                            font-weight: 900;
                                            color: {rating_color};
                                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                                            line-height: 1;
                                            margin-bottom: 4px;">
                                    {value_display}
                                </div>
                                <div style="font-size: 10px;
                                            color: rgba(255,255,255,0.5);
                                            font-weight: 700;
                                            letter-spacing: 0.1em;
                                            margin-bottom: 16px;">
                                    {"PER GAME" if pillar_name in ["DISPOSALS", "MARKS", "GOALS"] else "RATING"}
                                </div>
                            </div>
                            <div style="text-align: center;
                                        border-top: 1px solid rgba(255,255,255,0.1);
                                        padding-top: 16px;">
                                <div style="font-size: 18px;
                                            font-weight: 700;
                                            color: #FFFFFF;
                                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                                            margin-bottom: 4px;">
                                    {first_name}
                                </div>
                                <div style="font-size: 24px;
                                            font-weight: 900;
                                            color: #FFFFFF;
                                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                                            letter-spacing: 0.02em;
                                            text-transform: uppercase;">
                                    {last_name}
                                </div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            # Display ranks 2-5
            for rank_idx in range(1, min(5, len(top5))):
                player_row = top5.iloc[rank_idx]
                player_name = player_row["Player_Full"]
                team_name = player_row["Team_Full"]
                value = player_row[metric_col]
                
                # Normalize team
                normalized_team = normalize_team_display(team_name)
                photo_team = team_name_for_photo_guide(normalized_team)
                
                # Get full name
                full_name = get_full_player_name(player_name, normalized_team)
                
                # Look up team logo
                logo_path = f"team_logos/{normalized_team}.png"
                if os.path.exists(logo_path):
                    logo_base64 = get_image_base64(logo_path)
                    logo_html = f'<img src="data:image/png;base64,{logo_base64}" style="width:24px;height:24px;object-fit:contain;margin-right:8px;vertical-align:middle;">'
                else:
                    logo_html = ""
                
                # Get conditional color
                rating_color = rating_colour_for_value(value, filtered_leaders_df[metric_col])[0]
                
                # Format value based on FC mode
                formatted_value = str(convert_trait_to_fc_rating(value)) if fc_mode else f"{value:.2f}"
                
                # Render rank card
                st.markdown(f'<div style="background: rgba(20,20,30,0.6);border: 1px solid rgba(255,255,255,0.1);border-radius: 8px;padding: 12px 14px;margin-bottom: 8px;display: flex;align-items: center;justify-content: space-between;"><div style="display: flex;align-items: center;flex: 1;min-width: 0;">{logo_html}<div style="overflow: hidden;text-overflow: ellipsis;white-space: nowrap;"><span style="font-size: 14px;font-weight: 700;color: #FFFFFF;font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;">{full_name}</span></div></div><div style="font-size: 20px;font-weight: 900;color: {rating_color};font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;margin-left: 12px;white-space: nowrap;">{formatted_value}</div></div>', unsafe_allow_html=True)
            
            # Add spacing before expander
            st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
            
            # "View Full Table" expandable section showing all remaining players in card format
            with st.expander(f"📊 View Full {pillar_name} Table", expanded=False):
                # Get all players sorted by this metric (skip the top 5 already shown)
                remaining_players = filtered_leaders_df.nlargest(len(filtered_leaders_df), metric_col)[["Player_Full", "Team_Full", metric_col]].reset_index(drop=True)
                
                # Display players from rank 6 onwards
                for rank_idx in range(5, len(remaining_players)):
                    player_row = remaining_players.iloc[rank_idx]
                    player_name = player_row["Player_Full"]
                    team_name = player_row["Team_Full"]
                    value = player_row[metric_col]
                    rank = rank_idx + 1  # Rank starts from 1
                    
                    # Normalize team
                    normalized_team = normalize_team_display(team_name)
                    
                    # Get full name
                    full_name = get_full_player_name(player_name, normalized_team)
                    
                    # Look up team logo
                    logo_path = f"team_logos/{normalized_team}.png"
                    if os.path.exists(logo_path):
                        logo_base64 = get_image_base64(logo_path)
                        logo_html = f'<img src="data:image/png;base64,{logo_base64}" style="width:24px;height:24px;object-fit:contain;margin-right:8px;vertical-align:middle;">'
                    else:
                        logo_html = ""
                    
                    # Get conditional color (returns tuple of color, text_color)
                    rating_color, rating_text_color = rating_colour_for_value(value, filtered_leaders_df[metric_col])
                    
                    # Format value based on FC mode
                    formatted_value = str(convert_trait_to_fc_rating(value)) if fc_mode else f"{value:.2f}"
                    
                    # Create rank badge using the same color as the rating with contrasting text
                    rank_badge = f'<div style="background: {rating_color};border-radius: 6px;padding: 4px 10px;margin-right: 10px;min-width: 32px;text-align: center;box-shadow: 0 2px 4px rgba(0,0,0,0.2);"><span style="font-size: 12px;font-weight: 900;color: {rating_text_color};font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;">#{rank}</span></div>'
                    
                    # Render card with rank badge
                    st.markdown(f'<div style="background: rgba(20,20,30,0.6);border: 1px solid rgba(255,255,255,0.1);border-radius: 8px;padding: 12px 14px;margin-bottom: 8px;display: flex;align-items: center;justify-content: space-between;"><div style="display: flex;align-items: center;flex: 1;min-width: 0;">{rank_badge}{logo_html}<div style="overflow: hidden;text-overflow: ellipsis;white-space: nowrap;"><span style="font-size: 14px;font-weight: 700;color: #FFFFFF;font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;">{full_name}</span></div></div><div style="font-size: 20px;font-weight: 900;color: {rating_color};font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;margin-left: 12px;white-space: nowrap;">{formatted_value}</div></div>', unsafe_allow_html=True)


# ================= CONTRACT STATUS =================
elif page == "Contract Status":
    render_page_header("Contract Status", "Player Contract & Free Agency Overview", "📝")

    # ---------- Season selector ----------
    seasons = sorted(get_player_seasons(), reverse=True)
    if not seasons:
        st.error("No player seasons found.")
        st.stop()

    default_season_idx = seasons.index(2025) if 2025 in seasons else 0
    season = st.selectbox(
        "Select Season",
        seasons,
        index=default_season_idx,
        key="contract_status_season",
    )

    # ---------- Load player data ----------
    try:
        df = load_full_squad(int(season))
    except Exception as e:
        st.error(f"Failed to load player data for {season}: {e}")
        st.stop()

    if df is None or df.empty:
        st.warning(f"No player data available for {season}.")
        st.stop()

    df = df.copy()

    # ---------- Validate required columns ----------
    required = ["Player", "Team", "RatingPoints_Avg"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Contract Status can't run for {season}. Missing column(s): {', '.join(missing)}")
        st.stop()

    # ---------- Clean + numeric ----------
    df["Player"] = df["Player"].astype(str).str.strip()
    df["Team"] = df["Team"].astype(str).str.strip()
    df["RatingPoints_Avg"] = pd.to_numeric(df["RatingPoints_Avg"], errors="coerce").fillna(0)

    if "Age" in df.columns:
        df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
    else:
        df["Age"] = np.nan

    # ---------- Load Contract & FA Status from Footywire data ----------
    footywire_path = Path(__file__).parent / "data" / "raw" / "player" / "footywire_2026_complete.csv"
    has_footywire = footywire_path.exists()
    
    if has_footywire:
        try:
            fw_df = pd.read_csv(footywire_path)
            fw_df["Player"] = fw_df["Player"].astype(str).str.strip()
            fw_df["Team"] = fw_df["Team"].astype(str).str.strip()
            # Merge contract data and FA status from footywire
            fw_cols = ["Player", "Team", "Contract_Expiry", "FA_Status"]
            fw_merge = fw_df[[c for c in fw_cols if c in fw_df.columns]].copy()
            df = df.merge(fw_merge, on=["Player", "Team"], how="left")
        except Exception as e:
            st.warning(f"⚠️ Could not load Footywire data: {e}")
            df["Contract_Expiry"] = np.nan
            df["FA_Status"] = "Unknown"
    else:
        # Fallback to registry if footywire not available
        registry_df = get_all_player_registry_data()
        if not registry_df.empty:
            registry_cols = ["Player", "Team", "Contract_Expiry"]
            registry_merge = registry_df[registry_cols].copy()
            registry_merge["Player"] = registry_merge["Player"].astype(str).str.strip()
            registry_merge["Team"] = registry_merge["Team"].astype(str).str.strip()
            df = df.merge(registry_merge, on=["Player", "Team"], how="left")
            df["FA_Status"] = "Unknown"  # Registry doesn't have FA status
        else:
            df["Contract_Expiry"] = np.nan
            df["FA_Status"] = "Unknown"
            st.warning("⚠️ Contract data not available.")

    # ---------- Team selector ----------
    teams = sorted([t for t in df["Team"].dropna().unique().tolist() if str(t).strip() != ""])
    if not teams:
        st.warning(f"No teams found in data for {season}.")
        st.stop()

    default_team = st.session_state.get("default_team")
    default_selection = [default_team] if default_team in teams else [teams[0]]

    selected_teams = st.multiselect(
        "Select Team(s)",
        teams,
        default=default_selection,
        key="contract_status_teams",
    )

    if selected_teams:
        st.session_state.default_team = selected_teams[0]
    else:
        st.session_state.default_team = default_selection[0]

    # ---------- TPP Input ----------
    tpp_col1, tpp_col2 = st.columns([2, 6])
    with tpp_col1:
        tpp_value = st.number_input(
            "TPP (Total Player Payments $)",
            min_value=0,
            max_value=50_000_000,
            value=18_000_000,
            step=100_000,
            format="%d",
            key="contract_status_tpp",
            help="Enter the Total Player Payments cap for the selected season"
        )

    # ---------- Contract Expiry Filter ----------
    filter_col1, filter_col2 = st.columns([2, 6])
    with filter_col1:
        expiry_years = sorted([int(y) for y in df["Contract_Expiry"].dropna().unique() if pd.notna(y)])
        if expiry_years:
            contract_filter = st.multiselect(
                "Filter by Contract Expiry",
                options=["All"] + expiry_years,
                default=["All"],
                key="contract_status_expiry_filter",
            )
        else:
            contract_filter = ["All"]

    # ---------- Filter data ----------
    if not selected_teams:
        st.info("Select at least one team to display.")
        st.stop()

    team_df = df[df["Team"].isin(selected_teams)].copy()

    if team_df.empty:
        st.info("No players found for this team.")
        st.stop()

    # Apply contract expiry filter
    if "All" not in contract_filter and contract_filter:
        team_df = team_df[team_df["Contract_Expiry"].isin(contract_filter)]

    # Use standard rating column
    display_rating_col = "RatingPoints_Avg"

    team_df = team_df.sort_values(display_rating_col, ascending=False).reset_index(drop=True)

    # Calculate Cap Value (% of Team's Ratings * TPP)
    if "Matches" in team_df.columns:
        team_df["Matches"] = pd.to_numeric(team_df["Matches"], errors="coerce").fillna(0)
    else:
        team_df["Matches"] = 0
    
    team_df["RatingsTotal"] = team_df["Matches"] * team_df[display_rating_col]
    team_ratings_sum = team_df.groupby("Team")["RatingsTotal"].transform("sum")
    team_df["PctOfTeamRatings"] = (team_df["RatingsTotal"] / team_ratings_sum * 100).round(1)
    
    MIN_PLAYER_PAYMENT = 92_000
    team_df["CapValue"] = (team_df["PctOfTeamRatings"] / 100 * tpp_value).clip(lower=MIN_PLAYER_PAYMENT).round(0)
    team_df["PctOfCap"] = (team_df["CapValue"] / tpp_value * 100).round(2)

    # ---------- Build output dataframe ----------
    age_col = "Age_Decimal" if "Age_Decimal" in team_df.columns else "Age"
    
    rating_values = team_df[display_rating_col]
    rating_decimals = 1
    
    # Get position - use DepthPos mapping if available, otherwise use raw Position
    if "Position" in team_df.columns:
        team_df["DepthPos"] = team_df["Position"].apply(
            lambda x: map_position_to_depth(x) if pd.notna(x) and str(x).strip() != "" else "—"
        )
    else:
        team_df["DepthPos"] = "—"
    
    out = pd.DataFrame({
        "PLAYER": team_df["Player"].fillna("—"),
        "TEAM": team_df["Team"].fillna("—"),
        "POSITION": team_df["DepthPos"].fillna("—"),
        "AGE": pd.to_numeric(team_df[age_col], errors="coerce").round(1),
        "GAMES": pd.to_numeric(team_df["Matches"], errors="coerce").fillna(0).astype(int),
        "RATING": pd.to_numeric(team_df[display_rating_col], errors="coerce").round(1),
        "CAP VALUE": team_df["CapValue"],
        "% OF CAP": team_df["PctOfCap"],
        "CONTRACT EXPIRY": team_df["Contract_Expiry"],
        "FA STATUS": team_df["FA_Status"].fillna("Unknown"),
    })

    # ---------- Get league ratings for color scaling ----------
    league_ratings = df[display_rating_col].dropna()

    # Rating column header
    rating_header = "RATING"

    # ---------- Build HTML table ----------
    html = f"""
<table class="fe-table fe-sortable">
<thead>
<tr>
<th>PLAYER</th>
<th>TEAM</th>
<th>POSITION</th>
<th>AGE</th>
<th>GAMES</th>
<th>RATING</th>
<th>CAP VALUE</th>
<th>% OF CAP</th>
<th>CONTRACT EXPIRY</th>
<th>FA STATUS</th>
</tr>
</thead>
<tbody>
"""

    # FA Status color coding (matching Footywire values)
    FA_COLORS = {
        "Unrestricted Free Agent": ("#FF4444", "#FFFFFF"),
        "Restricted Free Agent": ("#FFA500", "#000000"),
        "Non-Free Agent": ("#4CAF50", "#FFFFFF"),
        "Delisted Free Agent": ("#FF6666", "#FFFFFF"),
        "Out of Contract": ("#FF8800", "#000000"),
        "Unknown": ("#888888", "#FFFFFF"),
    }

    # Contract expiry color coding (red for soon, green for long-term)
    def get_expiry_color(expiry, current_year):
        if pd.isna(expiry):
            return "#888888", "#FFFFFF"
        years_left = int(expiry) - int(current_year)
        if years_left <= 0:
            return "#FF4444", "#FFFFFF"  # Expired/expiring
        elif years_left == 1:
            return "#FF8800", "#000000"  # 1 year
        elif years_left == 2:
            return "#FFCC00", "#000000"  # 2 years
        elif years_left <= 4:
            return "#88CC44", "#000000"  # 3-4 years
        else:
            return "#4CAF50", "#FFFFFF"  # 5+ years

    for _, r in out.iterrows():
        # Rating colors
        rating_val = r["RATING"]
        bg_rating, fg_rating = rating_colour_for_value(rating_val, df[display_rating_col].dropna())

        age_val = r["AGE"]
        age_str = "—" if pd.isna(age_val) else f"{float(age_val):.1f}"

        games_val = r["GAMES"]
        games_str = "—" if pd.isna(games_val) else str(int(games_val))

        rating_str = "—" if pd.isna(rating_val) else f"{float(rating_val):.1f}"

        cap_val = r["CAP VALUE"]
        cap_str = "—" if pd.isna(cap_val) else f"${int(cap_val):,}"

        pct_cap_val = r["% OF CAP"]
        pct_cap_str = "—" if pd.isna(pct_cap_val) else f"{float(pct_cap_val):.2f}%"

        expiry_val = r["CONTRACT EXPIRY"]
        expiry_str = "—" if pd.isna(expiry_val) else str(int(expiry_val))
        bg_expiry, fg_expiry = get_expiry_color(expiry_val, season)

        fa_status = r["FA STATUS"]
        bg_fa, fg_fa = FA_COLORS.get(fa_status, ("#888888", "#FFFFFF"))

        position_str = r["POSITION"] if pd.notna(r["POSITION"]) else "—"

        html += f"""
<tr>
<td>{r['PLAYER']}</td>
<td>{r['TEAM']}</td>
<td>{position_str}</td>
<td>{age_str}</td>
<td>{games_str}</td>
<td style="background-color:{bg_rating}; color:{fg_rating}; font-weight:700;">{rating_str}</td>
<td style="font-weight:600;">{cap_str}</td>
<td>{pct_cap_str}</td>
<td style="background-color:{bg_expiry}; color:{fg_expiry}; font-weight:700; text-align:center;">{expiry_str}</td>
<td style="background-color:{bg_fa}; color:{fg_fa}; font-weight:700; text-align:center;">{fa_status}</td>
</tr>
"""

    html += "</tbody></table>"

    render_sortable_table(html)

    # ---------- Contract Summary Section ----------
    import plotly.graph_objects as go
    
    st.markdown("---")
    
    # Professional header for summary section
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 24px 20px;
        border-radius: 12px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.3);
        margin-bottom: 24px;
        text-align: center;
    ">
        <h2 style="
            color: #FFFFFF;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            font-weight: 800;
            font-size: 28px;
            margin: 0;
            letter-spacing: 0.02em;
        ">📊 Contract Summary</h2>
    </div>
    """, unsafe_allow_html=True)
    
    # Count by expiry year and FA status
    expiry_counts = team_df["Contract_Expiry"].value_counts().sort_index()
    fa_counts = team_df["FA_Status"].value_counts()
    
    # Calculate key metrics
    expiring_this_year = len(team_df[team_df["Contract_Expiry"] <= int(season)])
    expiring_next_year = len(team_df[team_df["Contract_Expiry"] == int(season) + 1])
    ufas = len(team_df[team_df["FA_Status"].str.contains("Unrestricted", na=False)])
    rfas = len(team_df[team_df["FA_Status"].str.contains("Restricted", na=False) & ~team_df["FA_Status"].str.contains("Unrestricted", na=False)])
    total_players = len(team_df)
    
    # Key Metrics Cards
    st.markdown("""
    <style>
    .contract-metric-card {
        background: linear-gradient(145deg, rgba(30,30,45,0.95), rgba(40,40,60,0.95));
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.1);
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .contract-metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.4);
    }
    .contract-metric-value {
        font-size: 36px;
        font-weight: 900;
        margin: 0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
    .contract-metric-label {
        font-size: 13px;
        font-weight: 600;
        color: rgba(255,255,255,0.7);
        margin-top: 8px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    </style>
    """, unsafe_allow_html=True)
    
    metric_cols = st.columns(5)
    
    with metric_cols[0]:
        st.markdown(f"""
        <div class="contract-metric-card">
            <p class="contract-metric-value" style="color: #4ECDC4;">{total_players}</p>
            <p class="contract-metric-label">Total Players</p>
        </div>
        """, unsafe_allow_html=True)
    
    with metric_cols[1]:
        st.markdown(f"""
        <div class="contract-metric-card">
            <p class="contract-metric-value" style="color: #FF6B6B;">{expiring_this_year}</p>
            <p class="contract-metric-label">Expiring {season}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with metric_cols[2]:
        st.markdown(f"""
        <div class="contract-metric-card">
            <p class="contract-metric-value" style="color: #FFE66D;">{expiring_next_year}</p>
            <p class="contract-metric-label">Expiring {int(season)+1}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with metric_cols[3]:
        st.markdown(f"""
        <div class="contract-metric-card">
            <p class="contract-metric-value" style="color: #FF8C42;">{ufas}</p>
            <p class="contract-metric-label">Unrestricted FAs</p>
        </div>
        """, unsafe_allow_html=True)
    
    with metric_cols[4]:
        st.markdown(f"""
        <div class="contract-metric-card">
            <p class="contract-metric-value" style="color: #98D8C8;">{rfas}</p>
            <p class="contract-metric-label">Restricted FAs</p>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Pie Charts Section
    chart_cols = st.columns(2)
    
    # Contract Expiry Pie Chart
    with chart_cols[0]:
        st.markdown("""
        <div style="
            background: linear-gradient(145deg, rgba(25,25,40,0.95), rgba(35,35,55,0.95));
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        ">
            <h3 style="
                color: #FFFFFF;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                font-weight: 700;
                font-size: 18px;
                margin: 0 0 16px 0;
                text-align: center;
            ">📅 Contract Expiry Distribution</h3>
        </div>
        """, unsafe_allow_html=True)
        
        if not expiry_counts.empty:
            # Color palette for expiry years
            expiry_colors = ['#FF6B6B', '#FFE66D', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#98D8C8']
            
            fig_expiry = go.Figure(data=[go.Pie(
                labels=[str(int(y)) for y in expiry_counts.index],
                values=expiry_counts.values,
                hole=0.45,
                marker=dict(
                    colors=expiry_colors[:len(expiry_counts)],
                    line=dict(color='rgba(0,0,0,0.3)', width=2)
                ),
                textinfo='label+percent',
                textfont=dict(size=13, color='white', family='-apple-system, BlinkMacSystemFont, Segoe UI, Roboto'),
                hovertemplate='<b>%{label}</b><br>Players: %{value}<br>%{percent}<extra></extra>',
                pull=[0.02] * len(expiry_counts)
            )])
            
            fig_expiry.update_layout(
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.15,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=12, color='white')
                ),
                margin=dict(t=20, b=60, l=20, r=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=350,
                annotations=[dict(
                    text=f'<b>{total_players}</b><br>Players',
                    x=0.5, y=0.5,
                    font=dict(size=16, color='white', family='-apple-system, BlinkMacSystemFont, Segoe UI, Roboto'),
                    showarrow=False
                )]
            )
            
            st.plotly_chart(fig_expiry, use_container_width=True, key="contract_expiry_pie")
        else:
            st.info("No contract expiry data available.")
    
    # Free Agency Status Pie Chart
    with chart_cols[1]:
        st.markdown("""
        <div style="
            background: linear-gradient(145deg, rgba(25,25,40,0.95), rgba(35,35,55,0.95));
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        ">
            <h3 style="
                color: #FFFFFF;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                font-weight: 700;
                font-size: 18px;
                margin: 0 0 16px 0;
                text-align: center;
            ">🏷️ Free Agency Status</h3>
        </div>
        """, unsafe_allow_html=True)
        
        if not fa_counts.empty:
            # Color mapping for FA status
            fa_color_map = {
                "Unrestricted Free Agent": "#FF8C42",
                "Restricted Free Agent": "#98D8C8",
                "Non-Free Agent": "#4ECDC4",
                "Delisted Free Agent": "#FF6B6B",
                "Unknown": "#888888"
            }
            fa_colors = [fa_color_map.get(status, "#666666") for status in fa_counts.index]
            
            # Shorten labels for display
            short_labels = []
            for status in fa_counts.index:
                if "Unrestricted" in str(status):
                    short_labels.append("UFA")
                elif "Restricted" in str(status) and "Unrestricted" not in str(status):
                    short_labels.append("RFA")
                elif "Non-Free" in str(status):
                    short_labels.append("Non-FA")
                elif "Delisted" in str(status):
                    short_labels.append("DFA")
                else:
                    short_labels.append(str(status)[:10])
            
            fig_fa = go.Figure(data=[go.Pie(
                labels=short_labels,
                values=fa_counts.values,
                hole=0.45,
                marker=dict(
                    colors=fa_colors,
                    line=dict(color='rgba(0,0,0,0.3)', width=2)
                ),
                textinfo='label+percent',
                textfont=dict(size=13, color='white', family='-apple-system, BlinkMacSystemFont, Segoe UI, Roboto'),
                hovertemplate='<b>%{label}</b><br>Players: %{value}<br>%{percent}<extra></extra>',
                customdata=list(fa_counts.index),
                pull=[0.02] * len(fa_counts)
            )])
            
            fig_fa.update_layout(
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.15,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=12, color='white')
                ),
                margin=dict(t=20, b=60, l=20, r=20),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                height=350,
                annotations=[dict(
                    text=f'<b>{total_players}</b><br>Players',
                    x=0.5, y=0.5,
                    font=dict(size=16, color='white', family='-apple-system, BlinkMacSystemFont, Segoe UI, Roboto'),
                    showarrow=False
                )]
            )
            
            st.plotly_chart(fig_fa, use_container_width=True, key="fa_status_pie")
        else:
            st.info("No free agency status data available.")
    
    # Detailed breakdown tables in expandable sections
    st.markdown("<br>", unsafe_allow_html=True)
    
    detail_cols = st.columns(2)
    
    with detail_cols[0]:
        with st.expander("📋 Contract Expiry Details", expanded=False):
            if not expiry_counts.empty:
                expiry_df = pd.DataFrame({
                    "Year": [int(y) for y in expiry_counts.index],
                    "Players": expiry_counts.values,
                    "% of Squad": [f"{v/total_players*100:.1f}%" for v in expiry_counts.values]
                })
                st.dataframe(expiry_df, hide_index=True, use_container_width=True)
    
    with detail_cols[1]:
        with st.expander("📋 Free Agency Status Details", expanded=False):
            if not fa_counts.empty:
                fa_df = pd.DataFrame({
                    "Status": fa_counts.index,
                    "Players": fa_counts.values,
                    "% of Squad": [f"{v/total_players*100:.1f}%" for v in fa_counts.values]
                })
                st.dataframe(fa_df, hide_index=True, use_container_width=True)

    render_footer()


#### GAME DAY PLAYEGROUND

elif page == "Game Day Playground":
   

   

    render_game_day_playground(teams)


# ================= IDP (INDIVIDUAL DEVELOPMENT PLAN) =================
elif page == "IDP":
    st.markdown("""<div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);padding: 40px 20px;border-radius: 16px;box-shadow: 0 8px 24px rgba(0,0,0,0.4);margin-bottom: 32px;text-align: center;"><h1 style="color: #FFFFFF;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-weight: 900;font-size: 48px;margin: 0 0 12px 0;letter-spacing: 0.02em;text-shadow: 2px 2px 8px rgba(0,0,0,0.5);">📋 Individual Development Plan</h1><p style="color: rgba(255,255,255,0.8);font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-size: 16px;margin: 0;font-weight: 600;letter-spacing: 0.03em;">Comprehensive player analysis with position benchmarking and comparison tools</p></div>""", unsafe_allow_html=True)
    
    # Enhanced styling
    st.markdown("""
    <style>
    .idp-card {
        background: linear-gradient(145deg, rgba(20,20,30,0.95), rgba(30,30,45,0.95));
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,0.15);
        padding: 24px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        margin-bottom: 20px;
        transition: all 0.3s ease;
    }
    .idp-card:hover {
        box-shadow: 0 12px 32px rgba(0,0,0,0.6);
        transform: translateY(-2px);
    }
    .idp-stat-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 14px 18px;
        margin: 10px 0;
        background: rgba(255,255,255,0.05);
        border-radius: 12px;
        border-left: 5px solid;
        transition: all 0.2s ease;
    }
    .idp-stat-row:hover {
        background: rgba(255,255,255,0.08);
        transform: translateX(4px);
    }
    .idp-section-header {
        font-size: 28px;
        font-weight: 900;
        margin: 40px 0 20px 0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        letter-spacing: 0.03em;
        color: #FFFFFF;
        text-align: center;
        text-shadow: 2px 2px 6px rgba(0,0,0,0.4);
    }
    .idp-badge {
        display: inline-block;
        padding: 10px 20px;
        border-radius: 20px;
        font-weight: 900;
        font-size: 14px;
        letter-spacing: 0.05em;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
    .strength { border-color: #00FF00; }
    .focus { border-color: #FF6B6B; }
    .neutral { border-color: #FFA500; }
    /* idp-comparison-table now uses unified .fe-table CSS */
    </style>
    """, unsafe_allow_html=True)
    
    # Helper functions
    def safe_float(x):
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        try:
            return float(str(x).replace("%", "").strip())
        except:
            return None
    
    def get_full_player_name(player_name, team_name=None):
        """Get full player name by looking up in player photo guide."""
        name_map = load_player_name_mapping()
        team_player_map = name_map.get('__team_player_map__', {})
        
        # Try team-aware lookup first
        if team_name and team_player_map:
            def normalize_team(team):
                team = str(team).strip().lower()
                if 'sydney' in team or team in ['syfc', 'sfc']:
                    return 'sydney'
                if 'gws' in team or 'giants' in team:
                    return 'gws'
                if 'bulldogs' in team or team in ['wbfc']:
                    return 'western bulldogs'
                return team.replace(' ', '').replace('fc', '')
            
            norm_team = normalize_team(team_name)
            team_key = f"{norm_team}_{player_name.strip().lower()}"
            if team_key in team_player_map:
                return team_player_map[team_key]
        
        # Fall back to regular name mapping
        return name_map.get(player_name.strip(), name_map.get(player_name.strip().lower(), player_name))
    
    def normalize_team_display(team_name):
        """Normalize team name for display (e.g., SYFC -> Sydney)."""
        team_map = {
            'SYFC': 'Sydney',
            'SFC': 'Sydney',
            'Sydney Swans': 'Sydney',
            'WBFC': 'Western Bulldogs',
            'GWS': 'GWS Giants',
            'GCFC': 'Gold Coast',
            'AFC': 'Adelaide',
            'BFC': 'Brisbane',
            'CFC': 'Carlton',
            'COFC': 'Collingwood',
            'EFC': 'Essendon',
            'FRFC': 'Fremantle',
            'GFC': 'Geelong',
            'HFC': 'Hawthorn',
            'MFC': 'Melbourne',
            'NMFC': 'North Melbourne',
            'PAFC': 'Port Adelaide',
            'RFC': 'Richmond',
            'SKFC': 'St Kilda',
            'WCFC': 'West Coast'
        }
        return team_map.get(team_name, team_name)
    
    # Season selection
    seasons_available = sorted(get_player_seasons(), reverse=True)
    if not seasons_available:
        seasons_available = [2025, 2024, 2023]
    
    # Season and FC Mode controls
    ctrl_col1, ctrl_col2 = st.columns([2, 1])
    with ctrl_col1:
        selected_season = st.selectbox("Select Season", seasons_available, index=0, key="idp_season")
    with ctrl_col2:
        fc_mode = st.toggle("⚽ FC Rating Mode (50-99)", key="idp_fc_mode", help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")
    
    # Helper function to format trait values based on FC mode
    def format_trait_val(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "—"
        if fc_mode:
            fc_val = convert_trait_to_fc_rating(val)
            return str(fc_val) if fc_val is not None else "—"
        return f"{float(val):.2f}"
    
    # Load traits data
    traits_df = load_traits(int(selected_season))
    if traits_df is None or traits_df.empty:
        st.error("Could not load traits data for this season.")
        st.stop()
    
    # Team and Player selection
    teams = sorted([t for t in traits_df["Team_Full"].dropna().unique().tolist() if str(t).strip() != ""])
    if not teams:
        st.warning("No teams found in traits data.")
        st.stop()
    
    selected_team = st.selectbox("Select Team", teams, key="idp_team")
    
    team_traits = traits_df[traits_df["Team_Full"] == selected_team].copy()
    player_names = sorted(team_traits["Player_Full"].dropna().unique().tolist())
    if not player_names:
        st.warning("No players found for this team.")
        st.stop()
    
    selected_player = st.selectbox("Select Player", player_names, key="idp_player")
    
    # Get player data
    player_data = team_traits[team_traits["Player_Full"] == selected_player].iloc[0]
    player_position = str(player_data.get("Position_Full", ""))
    player_age = player_data.get("Age", "N/A")
    
    # Normalize names for display
    selected_player_display = get_full_player_name(selected_player, selected_team)
    selected_team_display = normalize_team_display(selected_team)
    
    # ========== CALCULATE TOP 10 POSITION DATA FIRST ==========
    # Get top 10 in position (needed for spider graph)
    position_players = traits_df[traits_df["Position_Full"] == player_position].copy()
    position_players["Rating"] = pd.to_numeric(position_players["Rating"], errors="coerce")
    top_10_position = position_players.nlargest(10, "Rating")
    
    # ========== PLAYER HEADER WITH PHOTO ==========
    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    
    col_photo, col_info = st.columns([1, 3])
    
    # Display player photo and team logo
    with col_photo:
        _, logo_col, _ = st.columns([1, 2, 1])
        display_logo(selected_team_display, logo_col, size=160)
        display_player_photo(selected_player_display, col_photo, use_container_width=True, team_name=selected_team_display)
    
    # Display player info
    with col_info:
        st.markdown(f"""
        <div class="idp-card" style="background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);border-left:6px solid #FFFFFF;">
            <h2 style="color:#FFFFFF;margin:0 0 16px 0;font-size:42px;font-weight:900;letter-spacing:0.02em;">{selected_player_display}</h2>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
                <span class="idp-badge" style="background:#1a1a2e;color:#FFFFFF;">{selected_team_display}</span>
                <span class="idp-badge" style="background:#0f3460;color:#FFFFFF;">{player_position}</span>
                <span class="idp-badge" style="background:#16213e;color:#FFFFFF;">Age: {player_age}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # ========== TRAIT PILLARS WITH EXPANDABLE SUB-TRAITS ==========
    st.markdown("<div class='idp-section-header'>📊 Trait Overview</div>", unsafe_allow_html=True)
    
    # Define trait pillars and their sub-stats (updated to use correct column names)
    trait_pillars = {
        "Ball Winning": {
            "color": "#1B4D3E",  # Dark green
            "icon": "🏃",
            "substats": ["Stoppage", "Contest", "Power", "Receives"]
        },
        "Ball Use": {
            "color": "#1B3D5D",  # Dark blue
            "icon": "🎯",
            "substats": ["Handballing", "Kicking", "Goal Kicking", "Connecting"]
        },
        "Aerial": {
            "color": "#4A4A2A",  # Olive
            "icon": "✈️",
            "substats": ["Marking", "Contested", "Moks", "Ruck"]
        },
        "Defence": {
            "color": "#5D1B1B",  # Dark red/maroon
            "icon": "🛡️",
            "substats": ["Pressure", "Tackling", "Intercepting", "Neutralise"]
        }
    }
    
    # Helper function to get tier label for trait value (1-4 scale)
    def get_trait_tier(value):
        """Get tier label for trait value on 1-4 scale."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "N/A", "#666666"
        try:
            val = float(value)
            if val >= 3.0:
                return "Elite", "#00FF00"
            elif val >= 2.5:
                return "Above Average", "#90EE90"
            elif val >= 2.0:
                return "Below Average", "#FFA500"
            else:
                return "Poor", "#FF6B6B"
        except:
            return "N/A", "#666666"
    
    # Display 4 trait pillars in 2x2 grid
    pillar_cols = st.columns(2)
    
    for idx, (pillar_name, pillar_info) in enumerate(trait_pillars.items()):
        col_idx = idx % 2
        
        with pillar_cols[col_idx]:
            # Get main pillar value
            pillar_val = safe_float(player_data.get(pillar_name))
            tier_label, tier_color = get_trait_tier(pillar_val)
            
            # Format display value
            if fc_mode and pillar_val is not None:
                pillar_display = str(convert_trait_to_fc_rating(pillar_val))
                tier_label = get_fc_rating_label(convert_trait_to_fc_rating(pillar_val))
                tier_color = "#00FF00" if tier_label == "Elite" else "#90EE90" if tier_label == "Above Average" else "#FFA500" if tier_label == "Below Average" else "#FF6B6B"
            else:
                pillar_display = f"{pillar_val:.2f}" if pillar_val is not None else "—"
            
            # Main pillar card
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, {pillar_info['color']} 0%, {pillar_info['color']}CC 100%);
                        border-radius: 16px; padding: 20px; margin-bottom: 8px;
                        border: 2px solid {tier_color}40;
                        box-shadow: 0 8px 24px rgba(0,0,0,0.4);'>
                <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;'>
                    <div style='font-size: 14px; font-weight: 700; color: rgba(255,255,255,0.7); text-transform: uppercase; letter-spacing: 1px;'>
                        {pillar_info['icon']} {pillar_name}
                    </div>
                </div>
                <div style='display: flex; align-items: baseline; gap: 12px;'>
                    <span style='font-size: 42px; font-weight: 900; color: #FFFFFF;'>{pillar_display}</span>
                    <span style='font-size: 16px; font-weight: 700; color: {tier_color};'>{tier_label}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Expandable sub-traits
            with st.expander(f"📋 View {pillar_name} Details", expanded=False):
                for substat in pillar_info['substats']:
                    substat_val = safe_float(player_data.get(substat))
                    sub_tier, sub_color = get_trait_tier(substat_val)
                    
                    # Format based on FC mode
                    if fc_mode and substat_val is not None:
                        sub_display = str(convert_trait_to_fc_rating(substat_val))
                        sub_tier = get_fc_rating_label(convert_trait_to_fc_rating(substat_val))
                        sub_color = "#00FF00" if sub_tier == "Elite" else "#90EE90" if sub_tier == "Above Average" else "#FFA500" if sub_tier == "Below Average" else "#FF6B6B"
                    else:
                        sub_display = f"{substat_val:.2f}" if substat_val is not None else "—"
                    
                    st.markdown(f"""
                    <div style='display: flex; justify-content: space-between; align-items: center;
                                padding: 12px 16px; margin: 6px 0;
                                background: rgba(255,255,255,0.05); border-radius: 10px;
                                border-left: 4px solid {sub_color};'>
                        <span style='font-weight: 600; color: #FFFFFF; font-size: 14px;'>{substat}</span>
                        <div style='display: flex; align-items: center; gap: 12px;'>
                            <span style='font-size: 20px; font-weight: 900; color: #FFFFFF;'>{sub_display}</span>
                            <span style='font-size: 12px; font-weight: 700; color: {sub_color}; 
                                        background: {sub_color}20; padding: 4px 10px; border-radius: 12px;'>{sub_tier}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
    
    # ========== SECTION 1: TOP 10 POSITION BENCHMARKING ==========
    st.markdown("<div class='idp-section-header'>🎯 Position Benchmarking (Top 10)</div>", unsafe_allow_html=True)
    
    # Trait selection
    trait_options = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    selected_trait = st.selectbox("Select Trait to Analyze", trait_options, key="idp_trait_select")
    
    # Define sub-stats for each trait (updated to use correct column names)
    trait_substats = {
        "Rating": ["Ball Winning", "Ball Use", "Aerial", "Defence"],
        "Ball Winning": ["Stoppage", "Contest", "Power", "Receives"],
        "Ball Use": ["Handballing", "Kicking", "Goal Kicking", "Connecting"],
        "Aerial": ["Marking", "Contested", "Moks", "Ruck"],
        "Defence": ["Pressure", "Tackling", "Intercepting", "Neutralise"]
    }
    
    substats = trait_substats.get(selected_trait, [])
    
    # Main trait comparison
    player_trait_val = safe_float(player_data.get(selected_trait))
    top10_trait_avg = pd.to_numeric(top_10_position[selected_trait], errors="coerce").mean()
    
    st.markdown(f"<div class='idp-card'><h3 style='color:#FFFFFF;margin:0 0 24px 0;font-weight:900;font-size:22px;'>📊 {selected_trait} Analysis vs Top 10 {player_position}s</h3>", unsafe_allow_html=True)
    
    if player_trait_val is not None and not pd.isna(top10_trait_avg):
        delta = player_trait_val - top10_trait_avg
        delta_pct = (delta / top10_trait_avg * 100) if top10_trait_avg != 0 else 0
        
        # Determine colors based on competition-wide percentile
        trait_values = pd.to_numeric(traits_df[selected_trait], errors="coerce")
        player_bg, player_text = rating_colour_for_value(player_trait_val, trait_values)
        
        # Delta color based on sign
        if delta >= 0:
            delta_bg = player_bg
            delta_text = player_text
        else:
            delta_bg = "#FF0000" if delta < -0.5 else "#FF6B6B"
            delta_text = "#FFFFFF"
        
        # Format values based on FC mode
        if fc_mode:
            player_display_val = convert_trait_to_fc_rating(player_trait_val)
            top10_display_val = convert_trait_to_fc_rating(top10_trait_avg)
            delta_display = player_display_val - top10_display_val if player_display_val is not None and top10_display_val is not None else 0
            player_val_str = str(player_display_val) if player_display_val is not None else "—"
            top10_val_str = str(top10_display_val) if top10_display_val is not None else "—"
            delta_val_str = f"{delta_display:+d}"
        else:
            player_val_str = f"{player_trait_val:.2f}"
            top10_val_str = f"{top10_trait_avg:.2f}"
            delta_val_str = f"{delta:+.2f}"
        
        # Create visually appealing metric cards
        st.markdown(f"""
        <div style='display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:24px;'>
            <div style='background:linear-gradient(135deg,{player_bg}25 0%,{player_bg}15 100%);border:2px solid {player_bg};border-radius:16px;padding:24px;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,0.3);'>
                <div style='color:rgba(255,255,255,0.8);font-size:13px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;'>Your Rating</div>
                <div style='color:{player_text};background:{player_bg};font-size:48px;font-weight:900;line-height:1;padding:16px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);'>{player_val_str}</div>
            </div>
            <div style='background:linear-gradient(135deg,rgba(100,149,237,0.25) 0%,rgba(100,149,237,0.15) 100%);border:2px solid #6495ED;border-radius:16px;padding:24px;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,0.3);'>
                <div style='color:rgba(255,255,255,0.8);font-size:13px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;'>Top 10 Average</div>
                <div style='color:#FFFFFF;background:#6495ED;font-size:48px;font-weight:900;line-height:1;padding:16px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);'>{top10_val_str}</div>
            </div>
            <div style='background:linear-gradient(135deg,{delta_bg}25 0%,{delta_bg}15 100%);border:2px solid {delta_bg};border-radius:16px;padding:24px;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,0.3);'>
                <div style='color:rgba(255,255,255,0.8);font-size:13px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;'>Difference</div>
                <div style='color:{delta_text};background:{delta_bg};font-size:48px;font-weight:900;line-height:1;padding:16px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);'>{delta_val_str}</div>
                <div style='color:{delta_text};background:rgba(0,0,0,0.3);font-size:14px;font-weight:700;margin-top:10px;padding:6px 12px;border-radius:8px;'>{delta_pct:+.1f}%</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Spider graph comparing player to Top 10 average
    st.markdown("<h4 style='color:#FFFFFF;margin:28px 0 16px 0;font-weight:900;font-size:18px;'>Visual Comparison</h4>", unsafe_allow_html=True)
    
    import plotly.graph_objects as go
    
    # Get player values for the 5 main traits
    trait_categories = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    player_values_raw = [safe_float(player_data.get(trait, 0)) or 0 for trait in trait_categories]
    
    # Calculate Top 10 averages for each trait
    top10_values_raw = []
    for trait in trait_categories:
        trait_avg = pd.to_numeric(top_10_position[trait], errors="coerce").mean()
        top10_values_raw.append(trait_avg if pd.notna(trait_avg) else 0)
    
    # Convert to FC mode if enabled
    if fc_mode:
        player_values = [convert_trait_to_fc_rating(v) or 50 for v in player_values_raw]
        top10_values = [convert_trait_to_fc_rating(v) or 50 for v in top10_values_raw]
        spider_range = [50, 99]
    else:
        player_values = player_values_raw
        top10_values = top10_values_raw
        spider_range = [0, max(max(player_values), max(top10_values)) * 1.1]
    
    # Create spider chart
    fig = go.Figure()
    
    # Add Top 10 average trace
    fig.add_trace(go.Scatterpolar(
        r=top10_values + [top10_values[0]],
        theta=trait_categories + [trait_categories[0]],
        fill='toself',
        name='Top 10 Avg',
        line=dict(color='#6495ED', width=3),
        fillcolor='rgba(100, 149, 237, 0.25)'
    ))
    
    # Add player trace
    fig.add_trace(go.Scatterpolar(
        r=player_values + [player_values[0]],
        theta=trait_categories + [trait_categories[0]],
        fill='toself',
        name=selected_player_display.split()[0] if ' ' in selected_player_display else selected_player_display,
        line=dict(color='#00FF00', width=3),
        fillcolor='rgba(0, 255, 0, 0.25)'
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=spider_range,
                gridcolor='rgba(255,255,255,0.2)',
                tickfont=dict(color='white', size=12)
            ),
            angularaxis=dict(
                gridcolor='rgba(255,255,255,0.2)',
                tickfont=dict(color='white', size=13, family='Arial Black')
            ),
            bgcolor='rgba(0,0,0,0)'
        ),
        showlegend=True,
        legend=dict(
            font=dict(color='white', size=13),
            bgcolor='rgba(0,0,0,0.5)',
            bordercolor='rgba(255,255,255,0.3)',
            borderwidth=1,
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='center',
            x=0.5
        ),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=60, r=60, t=100, b=60),
        height=550
    )
    
    st.plotly_chart(fig, width="stretch", key="player_spider")
    
    # Sub-stats breakdown - organized by pillar with expandable details
    st.markdown("<h4 style='color:#FFFFFF;margin:24px 0 16px 0;font-weight:900;font-size:18px;'>Contributing Statistics</h4>", unsafe_allow_html=True)
    
    strengths = []
    focus_areas = []
    
    # If Rating is selected, group substats (the 4 pillars) and show their sub-traits in expanders
    if selected_trait == "Rating":
        for pillar_name in substats:  # substats = ["Ball Winning", "Ball Use", "Aerial", "Defence"]
            if pillar_name not in top_10_position.columns:
                continue
            
            pillar_info = trait_pillars.get(pillar_name, {})
            pillar_substats = pillar_info.get('substats', [])
            pillar_icon = pillar_info.get('icon', '📊')
            pillar_color = pillar_info.get('color', '#333333')
            
            player_val = safe_float(player_data.get(pillar_name))
            top10_avg = pd.to_numeric(top_10_position[pillar_name], errors="coerce").mean()
            
            if player_val is None or pd.isna(top10_avg):
                continue
            
            delta = player_val - top10_avg
            delta_pct = (delta / top10_avg * 100) if top10_avg != 0 else 0
            
            # Determine if strength or focus area
            if delta_pct >= 10:
                category = "strength"
                strengths.append((pillar_name, delta_pct))
            elif delta_pct <= -10:
                category = "focus"
                focus_areas.append((pillar_name, delta_pct))
            else:
                category = "neutral"
            
            # Color coding
            border_color = "#00FF00" if delta >= 0 else "#FF6B6B"
            
            # Format values based on FC mode
            if fc_mode:
                player_val_fc = convert_trait_to_fc_rating(player_val)
                top10_avg_fc = convert_trait_to_fc_rating(top10_avg)
                player_val_str = str(player_val_fc) if player_val_fc is not None else "—"
                top10_avg_str = str(top10_avg_fc) if top10_avg_fc is not None else "—"
                delta_str = f"{(player_val_fc or 0) - (top10_avg_fc or 0):+d}"
            else:
                player_val_str = f"{player_val:.2f}"
                top10_avg_str = f"{top10_avg:.2f}"
                delta_str = f"{delta:+.2f}"
            
            # Pillar header row
            st.markdown(f"""<div class="idp-stat-row {category}" style="border-left-color:{border_color};background:{pillar_color}30;">
                <div style="flex:1;"><span style="font-weight:900;font-size:16px;color:#FFFFFF;">{pillar_icon} {pillar_name}</span></div>
                <div style="display:flex;gap:24px;align-items:center;">
                    <div style="text-align:center;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">You</div><div style="font-size:18px;font-weight:900;color:#FFFFFF;">{player_val_str}</div></div>
                    <div style="text-align:center;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">Top 10 Avg</div><div style="font-size:18px;font-weight:900;color:#FFFFFF;">{top10_avg_str}</div></div>
                    <div style="text-align:center;min-width:90px;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">+/-</div><div style="font-size:20px;font-weight:900;color:{border_color};">{delta_str}</div></div>
                    <div style="text-align:center;min-width:80px;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">%</div><div style="font-size:18px;font-weight:900;color:{border_color};">{delta_pct:+.1f}%</div></div>
                </div>
            </div>""", unsafe_allow_html=True)
            
            # Expandable sub-traits for this pillar
            with st.expander(f"📋 View {pillar_name} Sub-Traits", expanded=False):
                for substat in pillar_substats:
                    if substat not in top_10_position.columns:
                        continue
                    
                    sub_player_val = safe_float(player_data.get(substat))
                    sub_top10_avg = pd.to_numeric(top_10_position[substat], errors="coerce").mean()
                    
                    if sub_player_val is None or pd.isna(sub_top10_avg):
                        continue
                    
                    sub_delta = sub_player_val - sub_top10_avg
                    sub_delta_pct = (sub_delta / sub_top10_avg * 100) if sub_top10_avg != 0 else 0
                    sub_border_color = "#00FF00" if sub_delta >= 0 else "#FF6B6B"
                    
                    if fc_mode:
                        sub_pv_fc = convert_trait_to_fc_rating(sub_player_val)
                        sub_ta_fc = convert_trait_to_fc_rating(sub_top10_avg)
                        sub_pv_str = str(sub_pv_fc) if sub_pv_fc is not None else "—"
                        sub_ta_str = str(sub_ta_fc) if sub_ta_fc is not None else "—"
                        sub_delta_str = f"{(sub_pv_fc or 0) - (sub_ta_fc or 0):+d}"
                    else:
                        sub_pv_str = f"{sub_player_val:.2f}"
                        sub_ta_str = f"{sub_top10_avg:.2f}"
                        sub_delta_str = f"{sub_delta:+.2f}"
                    
                    tier, tier_color = get_trait_tier(sub_player_val)
                    
                    st.markdown(f"""
                    <div style='padding:12px 16px;margin:6px 0;background:rgba(255,255,255,0.05);
                                border-radius:8px;border-left:4px solid {tier_color};display:flex;
                                justify-content:space-between;align-items:center;'>
                        <span style='font-weight:700;color:#FFFFFF;font-size:14px;'>{substat}</span>
                        <div style='display:flex;gap:20px;align-items:center;'>
                            <div style='text-align:center;'>
                                <div style='font-size:10px;color:rgba(255,255,255,0.5);'>You</div>
                                <div style='font-size:16px;font-weight:900;color:#FFFFFF;'>{sub_pv_str}</div>
                            </div>
                            <div style='text-align:center;'>
                                <div style='font-size:10px;color:rgba(255,255,255,0.5);'>Top 10</div>
                                <div style='font-size:16px;font-weight:900;color:#6495ED;'>{sub_ta_str}</div>
                            </div>
                            <div style='text-align:center;min-width:60px;'>
                                <div style='font-size:10px;color:rgba(255,255,255,0.5);'>+/-</div>
                                <div style='font-size:16px;font-weight:900;color:{sub_border_color};'>{sub_delta_str}</div>
                            </div>
                            <div style='text-align:center;min-width:60px;'>
                                <div style='font-size:10px;color:rgba(255,255,255,0.5);'>%</div>
                                <div style='font-size:16px;font-weight:900;color:{sub_border_color};'>{sub_delta_pct:+.1f}%</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
    else:
        # Specific pillar selected - show its substats directly
        for substat in substats:
            if substat not in top_10_position.columns:
                continue
            
            player_val = safe_float(player_data.get(substat))
            top10_avg = pd.to_numeric(top_10_position[substat], errors="coerce").mean()
            
            if player_val is None or pd.isna(top10_avg):
                continue
            
            delta = player_val - top10_avg
            delta_pct = (delta / top10_avg * 100) if top10_avg != 0 else 0
            
            # Determine if strength or focus area
            if delta_pct >= 10:
                category = "strength"
                strengths.append((substat, delta_pct))
            elif delta_pct <= -10:
                category = "focus"
                focus_areas.append((substat, delta_pct))
            else:
                category = "neutral"
            
            # Color coding
            border_color = "#00FF00" if delta >= 0 else "#FF6B6B"
            
            # Format values based on FC mode
            if fc_mode:
                player_val_fc = convert_trait_to_fc_rating(player_val)
                top10_avg_fc = convert_trait_to_fc_rating(top10_avg)
                player_val_str = str(player_val_fc) if player_val_fc is not None else "—"
                top10_avg_str = str(top10_avg_fc) if top10_avg_fc is not None else "—"
                delta_str = f"{(player_val_fc or 0) - (top10_avg_fc or 0):+d}"
            else:
                player_val_str = f"{player_val:.2f}"
                top10_avg_str = f"{top10_avg:.2f}"
                delta_str = f"{delta:+.2f}"
            
            tier, tier_color = get_trait_tier(player_val)
            
            st.markdown(f"""<div class="idp-stat-row {category}" style="border-left-color:{border_color};">
                <div style="flex:1;"><span style="font-weight:900;font-size:15px;color:#FFFFFF;">{substat}</span>
                    <span style="font-size:12px;color:{tier_color};margin-left:10px;background:{tier_color}20;padding:2px 8px;border-radius:10px;">{tier}</span>
                </div>
                <div style="display:flex;gap:24px;align-items:center;">
                    <div style="text-align:center;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">You</div><div style="font-size:18px;font-weight:900;color:#FFFFFF;">{player_val_str}</div></div>
                    <div style="text-align:center;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">Top 10 Avg</div><div style="font-size:18px;font-weight:900;color:#FFFFFF;">{top10_avg_str}</div></div>
                    <div style="text-align:center;min-width:90px;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">+/-</div><div style="font-size:20px;font-weight:900;color:{border_color};">{delta_str}</div></div>
                    <div style="text-align:center;min-width:80px;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">%</div><div style="font-size:18px;font-weight:900;color:{border_color};">{delta_pct:+.1f}%</div></div>
                </div>
            </div>""", unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # ========== STRENGTHS AND FOCUS AREAS ==========
    st.markdown("<div class='idp-section-header'>💪 Strengths & Focus Areas</div>", unsafe_allow_html=True)
    
    col_strength, col_focus = st.columns(2)
    
    with col_strength:
        st.markdown("<div class='idp-card' style='border-left:6px solid #00FF00;'><h3 style='color:#00FF00;margin:0 0 16px 0;font-weight:900;font-size:20px;'>✅ Key Strengths</h3>", unsafe_allow_html=True)
        
        if strengths:
            strengths.sort(key=lambda x: x[1], reverse=True)
            for stat, pct in strengths[:5]:
                st.markdown(f"<div style='padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.1);'><span style='color:#FFFFFF;font-weight:700;font-size:14px;'>{stat}</span><span style='color:#00FF00;font-weight:900;float:right;font-size:14px;'>+{pct:.1f}% above avg</span></div>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='color:rgba(255,255,255,0.6);font-style:italic;'>Performing at or near Top 10 average across all metrics</p>", unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    with col_focus:
        st.markdown("<div class='idp-card' style='border-left:6px solid #FF6B6B;'><h3 style='color:#FF6B6B;margin:0 0 16px 0;font-weight:900;font-size:20px;'>🎯 Focus Areas</h3>", unsafe_allow_html=True)
        
        if focus_areas:
            focus_areas.sort(key=lambda x: x[1])
            for stat, pct in focus_areas[:5]:
                st.markdown(f"<div style='padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.1);'><span style='color:#FFFFFF;font-weight:700;font-size:14px;'>{stat}</span><span style='color:#FF6B6B;font-weight:900;float:right;font-size:14px;'>{pct:.1f}% below avg</span></div>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='color:rgba(255,255,255,0.6);font-style:italic;'>No significant areas below Top 10 average</p>", unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # ========== SECTION: 5 MOST SIMILAR PLAYERS ==========
    # Calculate similarity for all players in same position (excluding selected player)
    trait_cols = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    same_position_players = traits_df[
        (traits_df["Position_Full"] == player_position) & 
        (traits_df["Player_Full"] != selected_player)
    ].copy()
    
    # Calculate similarity scores (Euclidean distance - lower = more similar)
    most_similar_player = None
    most_similar_team = None
    top_5_similar = []
    
    if not same_position_players.empty:
        player_traits = [safe_float(player_data.get(t)) or 0 for t in trait_cols]
        
        def calc_similarity(row):
            other_traits = [safe_float(row.get(t)) or 0 for t in trait_cols]
            return sum((a - b) ** 2 for a, b in zip(player_traits, other_traits)) ** 0.5
        
        same_position_players["similarity_score"] = same_position_players.apply(calc_similarity, axis=1)
        
        # Get top 5 most similar (lowest distance)
        top_5_df = same_position_players.nsmallest(5, "similarity_score")
        top_5_similar = top_5_df.to_dict('records')
        
        most_similar_row = same_position_players.loc[same_position_players["similarity_score"].idxmin()]
        most_similar_player = most_similar_row["Player_Full"]
        most_similar_team = most_similar_row["Team_Full"]
    
    st.markdown("<div class='idp-section-header'>👥 5 Most Similar Players</div>", unsafe_allow_html=True)
    
    if top_5_similar:
        # Create 5 columns for the similar players
        sim_cols = st.columns(5)
        
        for idx, sim_player_data in enumerate(top_5_similar):
            with sim_cols[idx]:
                sim_player_name = sim_player_data.get("Player_Full", "")
                sim_team = str(sim_player_data.get("Team_Full", ""))
                sim_position = str(sim_player_data.get("Position_Full", ""))
                sim_age = sim_player_data.get("Age", "N/A")
                
                # Normalize names for display
                sim_player_display = get_full_player_name(sim_player_name, sim_team)
                sim_team_display = normalize_team_display(sim_team)
                
                # Get ratings
                sim_overall = safe_float(sim_player_data.get("Rating"))
                sim_ball_winning = safe_float(sim_player_data.get("Ball Winning"))
                sim_ball_use = safe_float(sim_player_data.get("Ball Use"))
                sim_aerial = safe_float(sim_player_data.get("Aerial"))
                sim_defence = safe_float(sim_player_data.get("Defence"))
                
                # Format ratings for display
                if fc_mode:
                    sim_overall_str = str(convert_trait_to_fc_rating(sim_overall)) if sim_overall else "—"
                    sim_ball_winning_str = str(convert_trait_to_fc_rating(sim_ball_winning)) if sim_ball_winning else "—"
                    sim_ball_use_str = str(convert_trait_to_fc_rating(sim_ball_use)) if sim_ball_use else "—"
                    sim_aerial_str = str(convert_trait_to_fc_rating(sim_aerial)) if sim_aerial else "—"
                    sim_defence_str = str(convert_trait_to_fc_rating(sim_defence)) if sim_defence else "—"
                else:
                    sim_overall_str = f"{sim_overall:.2f}" if sim_overall else "—"
                    sim_ball_winning_str = f"{sim_ball_winning:.2f}" if sim_ball_winning else "—"
                    sim_ball_use_str = f"{sim_ball_use:.2f}" if sim_ball_use else "—"
                    sim_aerial_str = f"{sim_aerial:.2f}" if sim_aerial else "—"
                    sim_defence_str = f"{sim_defence:.2f}" if sim_defence else "—"
                
                # Get rating colors for visual feedback
                overall_color = "#00FF00"
                if sim_overall is not None and "Rating" in traits_df.columns:
                    overall_color, _ = rating_colour_for_value(sim_overall, pd.to_numeric(traits_df["Rating"], errors="coerce"))
                
                # Determine badge color based on rank
                rank_colors = ["#FFD700", "#C0C0C0", "#CD7F32", "#4A90D9", "#7B68EE"]
                badge_color = rank_colors[idx] if idx < len(rank_colors) else "#666666"
                
                st.markdown(f"""
                <div class='idp-card' style='padding:16px;text-align:center;position:relative;'>
                    <div style='position:absolute;top:8px;left:8px;background:{badge_color};color:#000;font-weight:900;font-size:14px;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,0.4);'>
                        {idx + 1}
                    </div>
                """, unsafe_allow_html=True)
                
                # Display player photo
                display_player_photo(sim_player_display, st, size=120, team_name=sim_team_display)
                
                st.markdown(f"""
                    <div style='margin-top:12px;'>
                        <h4 style='color:#FFFFFF;margin:0 0 4px 0;font-size:14px;font-weight:900;line-height:1.2;'>{sim_player_display}</h4>
                        <p style='color:rgba(255,255,255,0.7);margin:2px 0;font-size:12px;font-weight:600;'>{sim_team_display}</p>
                        <p style='color:rgba(255,255,255,0.5);margin:2px 0;font-size:11px;'>{sim_position} • Age {sim_age}</p>
                    </div>
                    <div style='margin-top:12px;background:rgba(0,0,0,0.3);border-radius:8px;padding:10px;'>
                        <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;'>
                            <span style='color:rgba(255,255,255,0.6);font-size:10px;'>Overall</span>
                            <span style='color:{overall_color};font-weight:900;font-size:28px;'>{sim_overall_str}</span>
                        </div>
                        <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;'>
                            <span style='color:rgba(255,255,255,0.5);font-size:9px;'>Ball Win</span>
                            <span style='color:rgba(255,255,255,0.8);font-weight:700;font-size:22px;'>{sim_ball_winning_str}</span>
                        </div>
                        <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;'>
                            <span style='color:rgba(255,255,255,0.5);font-size:9px;'>Ball Use</span>
                            <span style='color:rgba(255,255,255,0.8);font-weight:700;font-size:22px;'>{sim_ball_use_str}</span>
                        </div>
                        <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;'>
                            <span style='color:rgba(255,255,255,0.5);font-size:9px;'>Aerial</span>
                            <span style='color:rgba(255,255,255,0.8);font-weight:700;font-size:22px;'>{sim_aerial_str}</span>
                        </div>
                        <div style='display:flex;justify-content:space-between;align-items:center;'>
                            <span style='color:rgba(255,255,255,0.5);font-size:9px;'>Defence</span>
                            <span style='color:rgba(255,255,255,0.8);font-weight:700;font-size:22px;'>{sim_defence_str}</span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.markdown("<div class='idp-card'><p style='color:rgba(255,255,255,0.6);text-align:center;padding:20px;'>No similar players found for this position.</p></div>", unsafe_allow_html=True)
    
    # ========== SECTION 2: PLAYER COMPARISON TOOL ==========
    st.markdown("<div class='idp-section-header'>⚖️ Player Comparison Tool</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='idp-card'><h3 style='color:#FFFFFF;margin:0 0 20px 0;font-weight:900;font-size:22px;'>Compare Against Specific Player</h3>", unsafe_allow_html=True)
    
    # Season selector for comparison - allows comparing across seasons
    st.markdown("<p style='color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:8px;'>Compare against players from different seasons to track development over time.</p>", unsafe_allow_html=True)
    
    comp_col1, comp_col2 = st.columns(2)
    
    with comp_col1:
        # Season filter for comparison player
        comparison_season = st.selectbox(
            "Comparison Season",
            AVAILABLE_SEASONS,
            index=0,  # Default to current season
            key=f"idp_comparison_season_{selected_player}"
        )
    
    # Load traits data for the comparison season
    if comparison_season != CURRENT_SEASON:
        comp_traits_df = load_traits(comparison_season)
        if comp_traits_df is None or comp_traits_df.empty:
            st.warning(f"No traits data available for {comparison_season}. Using current season.")
            comp_traits_df = traits_df
            comparison_season = CURRENT_SEASON
    else:
        comp_traits_df = traits_df
    
    with comp_col2:
        # Team filter for comparison - default to most similar player's team
        comparison_teams = sorted(comp_traits_df["Team_Full"].dropna().unique().tolist())
        default_team_idx = 0
        if most_similar_team and most_similar_team in comparison_teams:
            default_team_idx = comparison_teams.index(most_similar_team)
        
        comparison_team = st.selectbox(
            "Select Team",
            comparison_teams,
            index=default_team_idx,
            key=f"idp_comparison_team_{selected_player}_{comparison_season}"
        )
    
    # Filter players by selected team from the comparison season's data
    team_players_df = comp_traits_df[comp_traits_df["Team_Full"] == comparison_team]
    team_players = sorted(team_players_df["Player_Full"].dropna().unique().tolist())
    
    # Pre-select most similar player if they're on the selected team (only for current season)
    default_player_idx = 0
    if comparison_season == CURRENT_SEASON and comparison_team == most_similar_team and most_similar_player and most_similar_player in team_players:
        default_player_idx = team_players.index(most_similar_player)
    
    # Select comparison player from filtered team
    comparison_player = st.selectbox(
        f"Select Player to Compare ({comparison_season})",
        team_players,
        index=default_player_idx,
        key=f"idp_comparison_player_{selected_player}_{comparison_season}"
    )
    
    if comparison_player:
        comp_data = comp_traits_df[comp_traits_df["Player_Full"] == comparison_player].iloc[0]
        comp_position = str(comp_data.get("Position_Full", ""))
        comp_team = str(comp_data.get("Team_Full", ""))
        comp_age = comp_data.get("Age", "N/A")
        
        # Check if comparing same player across seasons
        is_same_player = (comparison_player == selected_player) or (
            selected_player_display and comparison_player and 
            selected_player_display.lower() in comparison_player.lower() or 
            comparison_player.lower() in selected_player_display.lower()
        )
        
        # Normalize names for display
        comparison_player_display = get_full_player_name(comparison_player, comp_team)
        comp_team_display = normalize_team_display(comp_team)
        
        # Add season to display if comparing across seasons
        if comparison_season != CURRENT_SEASON:
            comparison_player_display_with_season = f"{comparison_player_display} ({comparison_season})"
            selected_player_display_with_season = f"{selected_player_display} ({CURRENT_SEASON})"
        else:
            comparison_player_display_with_season = comparison_player_display
            selected_player_display_with_season = selected_player_display
        
        # Calculate similarity percentage between the two players
        all_trait_cols = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence", 
                         "Stoppage", "Contest", "Power", "Receives",
                         "Handballing", "Kicking", "Goal Kicking", "Connecting",
                         "Marking", "Contested", "Moks", "Ruck",
                         "Pressure", "Tackling", "Intercepting", "Neutralise"]
        
        similarity_scores = []
        for col in all_trait_cols:
            if col not in comp_traits_df.columns:
                continue
            p1_val = safe_float(player_data.get(col))
            p2_val = safe_float(comp_data.get(col))
            if p1_val is None or p2_val is None:
                continue
            # Get column range for normalization (use current season for consistent scaling)
            col_vals = pd.to_numeric(traits_df[col], errors="coerce")
            col_min = col_vals.min()
            col_max = col_vals.max()
            if pd.isna(col_min) or pd.isna(col_max) or col_max == col_min:
                continue
            # Normalize both values to 0-100 scale
            norm1 = ((p1_val - col_min) / (col_max - col_min)) * 100
            norm2 = ((p2_val - col_min) / (col_max - col_min)) * 100
            # Calculate similarity (100 - absolute difference)
            similarity = 100 - abs(norm1 - norm2)
            similarity_scores.append(similarity)
        
        if similarity_scores:
            player_similarity = sum(similarity_scores) / len(similarity_scores)
        else:
            player_similarity = 0
        
        # Determine comparison type label
        if is_same_player and comparison_season != CURRENT_SEASON:
            comparison_type = "Season Progress"
            vs_label = "THEN vs NOW"
        elif comparison_season != CURRENT_SEASON:
            comparison_type = "Cross-Season"
            vs_label = "VS"
        else:
            comparison_type = "Head-to-Head"
            vs_label = "VS"
        
        # Comparison header with photos
        col_p1, col_vs, col_p2 = st.columns([2, 1, 2])
        
        with col_p1:
            # Center the photo
            _, photo_col, _ = st.columns([0.5, 1, 0.5])
            with photo_col:
                display_player_photo(selected_player_display, st, size=200, team_name=selected_team_display)
            season_badge_p1 = f"<span style='background:#00FF00;color:#000;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;margin-left:8px;'>{CURRENT_SEASON}</span>" if comparison_season != CURRENT_SEASON else ""
            st.markdown(f"<div style='text-align:center;margin-top:12px;'><h4 style='color:#FFFFFF;margin:0;font-size:20px;font-weight:900;'>{selected_player_display}{season_badge_p1}</h4><p style='color:rgba(255,255,255,0.7);margin:4px 0;font-size:14px;font-weight:600;'>{selected_team_display}</p><p style='color:rgba(255,255,255,0.6);margin:4px 0;font-size:13px;'>{player_position} • Age {player_age}</p></div>", unsafe_allow_html=True)
        
        with col_vs:
            st.markdown(f"""
            <div style='display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;'>
                <div style='font-size:48px;font-weight:900;color:rgba(255,255,255,0.5);text-shadow:2px 2px 6px rgba(0,0,0,0.5);'>{vs_label}</div>
                <div style='background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%); 
                            border-radius: 12px; padding: 16px 20px; margin-top: 16px;
                            border: 1px solid rgba(255,255,255,0.2); box-shadow: 0 4px 12px rgba(0,0,0,0.3);text-align:center;'>
                    <div style='font-size: 11px; font-weight: 700; color: rgba(255,255,255,0.6); 
                                text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;'>
                        {"Growth" if is_same_player and comparison_season != CURRENT_SEASON else "Similarity"}
                    </div>
                    <div style='font-size: 32px; font-weight: 900; color: #ffffff;'>
                        {player_similarity:.1f}%
                    </div>
                    <div style='font-size: 10px; color: rgba(255,255,255,0.4); margin-top: 4px;'>
                        {comparison_type}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        with col_p2:
            # Center the photo
            _, photo_col, _ = st.columns([0.5, 1, 0.5])
            with photo_col:
                display_player_photo(comparison_player_display, st, size=200, team_name=comp_team_display)
            season_badge_p2 = f"<span style='background:#FF6B6B;color:#FFF;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;margin-left:8px;'>{comparison_season}</span>" if comparison_season != CURRENT_SEASON else ""
            st.markdown(f"<div style='text-align:center;margin-top:12px;'><h4 style='color:#FFFFFF;margin:0;font-size:20px;font-weight:900;'>{comparison_player_display}{season_badge_p2}</h4><p style='color:rgba(255,255,255,0.7);margin:4px 0;font-size:14px;font-weight:600;'>{comp_team_display}</p><p style='color:rgba(255,255,255,0.6);margin:4px 0;font-size:13px;'>{comp_position} • Age {comp_age}</p></div>", unsafe_allow_html=True)
        
        st.markdown("<div style='margin:24px 0;'></div>", unsafe_allow_html=True)
        
        # Spider graph comparing the two players
        import plotly.graph_objects as go
        
        # Get values for both players
        trait_categories = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
        player1_values_raw = [safe_float(player_data.get(trait, 0)) or 0 for trait in trait_categories]
        player2_values_raw = [safe_float(comp_data.get(trait, 0)) or 0 for trait in trait_categories]
        
        # Convert to FC mode if enabled
        if fc_mode:
            player1_values = [convert_trait_to_fc_rating(v) or 50 for v in player1_values_raw]
            player2_values = [convert_trait_to_fc_rating(v) or 50 for v in player2_values_raw]
            comp_spider_range = [50, 99]
        else:
            player1_values = player1_values_raw
            player2_values = player2_values_raw
            comp_spider_range = [0, max(max(player1_values), max(player2_values)) * 1.1]
        
        # Create spider chart
        fig_comp = go.Figure()
        
        # Add player 1 trace (current season)
        p1_legend_name = f"{selected_player_display.split()[0]} ({CURRENT_SEASON})" if comparison_season != CURRENT_SEASON else selected_player_display.split()[0]
        fig_comp.add_trace(go.Scatterpolar(
            r=player1_values + [player1_values[0]],
            theta=trait_categories + [trait_categories[0]],
            fill='toself',
            name=p1_legend_name,
            line=dict(color='#00FF00', width=3),
            fillcolor='rgba(0, 255, 0, 0.2)'
        ))
        
        # Add player 2 trace (comparison season)
        p2_legend_name = f"{comparison_player_display.split()[0]} ({comparison_season})" if comparison_season != CURRENT_SEASON else comparison_player_display.split()[0]
        fig_comp.add_trace(go.Scatterpolar(
            r=player2_values + [player2_values[0]],
            theta=trait_categories + [trait_categories[0]],
            fill='toself',
            name=p2_legend_name,
            line=dict(color='#FF6B6B', width=3),
            fillcolor='rgba(255, 107, 107, 0.2)'
        ))
        
        fig_comp.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=comp_spider_range,
                    gridcolor='rgba(255,255,255,0.2)',
                    tickfont=dict(color='white', size=11)
                ),
                angularaxis=dict(
                    gridcolor='rgba(255,255,255,0.2)',
                    tickfont=dict(color='white', size=12, family='Arial Black')
                ),
                bgcolor='rgba(0,0,0,0)'
            ),
            showlegend=True,
            legend=dict(
                font=dict(color='white', size=12),
                bgcolor='rgba(0,0,0,0.5)',
                bordercolor='rgba(255,255,255,0.3)',
                borderwidth=1,
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='center',
                x=0.5
            ),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=60, r=60, t=80, b=60),
            height=450
        )
        
        st.plotly_chart(fig_comp, width="stretch", key="comparison_spider")
        
        st.markdown("<div style='margin:24px 0;'></div>", unsafe_allow_html=True)
        
        # Trait comparison
        comp_trait = st.selectbox("Select Trait for Comparison", trait_options, key="idp_comp_trait")
        comp_substats = trait_substats.get(comp_trait, [])
        
        # Main trait comparison
        player_comp_val = safe_float(player_data.get(comp_trait))
        comp_player_val = safe_float(comp_data.get(comp_trait))
        
        if player_comp_val is not None and comp_player_val is not None:
            delta = player_comp_val - comp_player_val
            delta_pct = (delta / comp_player_val * 100) if comp_player_val != 0 else 0
            
            # Determine colors based on competition-wide percentiles
            trait_values = pd.to_numeric(traits_df[comp_trait], errors="coerce")
            p1_color, _ = rating_colour_for_value(player_comp_val, trait_values)
            p2_color, _ = rating_colour_for_value(comp_player_val, trait_values)
            
            # Format values for display
            if fc_mode:
                p1_fc = convert_trait_to_fc_rating(player_comp_val)
                p2_fc = convert_trait_to_fc_rating(comp_player_val)
                p1_val_str = str(p1_fc) if p1_fc is not None else "—"
                p2_val_str = str(p2_fc) if p2_fc is not None else "—"
                delta_fc = (p1_fc or 0) - (p2_fc or 0)
                delta_str = f"{delta_fc:+d}"
            else:
                p1_val_str = f"{player_comp_val:.2f}"
                p2_val_str = f"{comp_player_val:.2f}"
                delta_str = f"{delta:+.2f}"
            
            # Determine advantage text and color
            if abs(delta) < 0.05:
                advantage_text = "Even"
                advantage_color = "#FFA500"
            elif delta > 0:
                advantage_text = selected_player_display.split()[-1] if ' ' in selected_player_display else selected_player_display
                advantage_color = p1_color
            else:
                advantage_text = comparison_player_display.split()[-1] if ' ' in comparison_player_display else comparison_player_display
                advantage_color = p2_color
            
            col1, col2, col3 = st.columns(3)
            with col1:
                p1_display = selected_player_display.split()[-1] if ' ' in selected_player_display else selected_player_display
                st.markdown(f"<div style='background:linear-gradient(135deg, {p1_color}25 0%, {p1_color}15 100%);border:2px solid {p1_color};border-radius:16px;padding:28px 24px;box-shadow:0 6px 20px rgba(0,0,0,0.4);text-align:center;'><div style='color:rgba(255,255,255,0.75);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;'>{p1_display}</div><div style='background:rgba(0,0,0,0.3);border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:48px;font-weight:900;color:{p1_color};line-height:1;text-shadow:2px 2px 8px rgba(0,0,0,0.5);'>{p1_val_str}</div></div></div>", unsafe_allow_html=True)
            with col2:
                p2_display = comparison_player_display.split()[-1] if ' ' in comparison_player_display else comparison_player_display
                st.markdown(f"<div style='background:linear-gradient(135deg, {p2_color}25 0%, {p2_color}15 100%);border:2px solid {p2_color};border-radius:16px;padding:28px 24px;box-shadow:0 6px 20px rgba(0,0,0,0.4);text-align:center;'><div style='color:rgba(255,255,255,0.75);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;'>{p2_display}</div><div style='background:rgba(0,0,0,0.3);border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:48px;font-weight:900;color:{p2_color};line-height:1;text-shadow:2px 2px 8px rgba(0,0,0,0.5);'>{p2_val_str}</div></div></div>", unsafe_allow_html=True)
            with col3:
                st.markdown(f"<div style='background:linear-gradient(135deg, {advantage_color}25 0%, {advantage_color}15 100%);border:2px solid {advantage_color};border-radius:16px;padding:28px 24px;box-shadow:0 6px 20px rgba(0,0,0,0.4);text-align:center;'><div style='color:rgba(255,255,255,0.75);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;'>Advantage</div><div style='background:rgba(0,0,0,0.3);border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:48px;font-weight:900;color:{advantage_color};line-height:1;text-shadow:2px 2px 8px rgba(0,0,0,0.5);'>{advantage_text}</div><div style='margin-top:12px;font-size:14px;font-weight:700;color:rgba(255,255,255,0.7);background:rgba(0,0,0,0.25);padding:8px 16px;border-radius:20px;display:inline-block;'>{delta_str} ({delta_pct:+.1f}%)</div></div></div>", unsafe_allow_html=True)
        
        # Sub-stats comparison - organized by pillar with expandable details
        st.markdown("<h4 style='color:#FFFFFF;margin:28px 0 16px 0;font-weight:900;font-size:18px;'>Detailed Comparison</h4>", unsafe_allow_html=True)
        
        if comp_trait == "Rating":
            # Show pillars with expandable sub-traits
            for pillar_name in comp_substats:  # comp_substats = ["Ball Winning", "Ball Use", "Aerial", "Defence"]
                if pillar_name not in traits_df.columns:
                    continue
                
                pillar_info = trait_pillars.get(pillar_name, {})
                pillar_substats_list = pillar_info.get('substats', [])
                pillar_icon = pillar_info.get('icon', '📊')
                pillar_color = pillar_info.get('color', '#333333')
                
                p1_val = safe_float(player_data.get(pillar_name))
                p2_val = safe_float(comp_data.get(pillar_name))
                
                if p1_val is None or p2_val is None:
                    continue
                
                delta = p1_val - p2_val
                delta_color = "#00FF00" if delta > 0 else "#FF6B6B" if delta < 0 else "#FFA500"
                winner_bg = f"{pillar_color}40"
                
                # Format values
                if fc_mode:
                    p1_fc = convert_trait_to_fc_rating(p1_val)
                    p2_fc = convert_trait_to_fc_rating(p2_val)
                    p1_str = str(p1_fc) if p1_fc is not None else "—"
                    p2_str = str(p2_fc) if p2_fc is not None else "—"
                    delta_display = f"{(p1_fc or 0) - (p2_fc or 0):+d}"
                else:
                    p1_str = f"{p1_val:.2f}"
                    p2_str = f"{p2_val:.2f}"
                    delta_display = f"{delta:+.2f}"
                
                # Pillar comparison row
                p1_display = selected_player_display.split()[-1] if ' ' in selected_player_display else selected_player_display
                p2_display = comparison_player_display.split()[-1] if ' ' in comparison_player_display else comparison_player_display
                
                p1_bg = "rgba(0,255,0,0.2)" if delta > 0 else "transparent"
                p2_bg = "rgba(0,255,0,0.2)" if delta < 0 else "transparent"
                
                st.markdown(f"""
                <div style='background:{pillar_color}30;border-radius:12px;padding:16px 20px;margin:12px 0;
                            border-left:5px solid {pillar_color};box-shadow:0 4px 12px rgba(0,0,0,0.3);'>
                    <div style='display:flex;justify-content:space-between;align-items:center;'>
                        <span style='font-weight:900;font-size:16px;color:#FFFFFF;'>{pillar_icon} {pillar_name}</span>
                        <div style='display:flex;gap:24px;align-items:center;'>
                            <div style='text-align:center;background:{p1_bg};padding:8px 16px;border-radius:8px;'>
                                <div style='font-size:10px;color:rgba(255,255,255,0.6);'>{p1_display}</div>
                                <div style='font-size:20px;font-weight:900;color:#FFFFFF;'>{p1_str}</div>
                            </div>
                            <div style='text-align:center;background:{p2_bg};padding:8px 16px;border-radius:8px;'>
                                <div style='font-size:10px;color:rgba(255,255,255,0.6);'>{p2_display}</div>
                                <div style='font-size:20px;font-weight:900;color:#FFFFFF;'>{p2_str}</div>
                            </div>
                            <div style='text-align:center;min-width:70px;'>
                                <div style='font-size:10px;color:rgba(255,255,255,0.5);'>+/-</div>
                                <div style='font-size:20px;font-weight:900;color:{delta_color};'>{delta_display}</div>
                            </div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Expandable sub-traits for this pillar
                with st.expander(f"📋 View {pillar_name} Sub-Trait Comparison", expanded=False):
                    for substat in pillar_substats_list:
                        if substat not in traits_df.columns:
                            continue
                        
                        sub_p1_val = safe_float(player_data.get(substat))
                        sub_p2_val = safe_float(comp_data.get(substat))
                        
                        if sub_p1_val is None or sub_p2_val is None:
                            continue
                        
                        sub_delta = sub_p1_val - sub_p2_val
                        sub_delta_color = "#00FF00" if sub_delta > 0 else "#FF6B6B" if sub_delta < 0 else "#FFA500"
                        
                        if fc_mode:
                            sub_p1_fc = convert_trait_to_fc_rating(sub_p1_val)
                            sub_p2_fc = convert_trait_to_fc_rating(sub_p2_val)
                            sub_p1_str = str(sub_p1_fc) if sub_p1_fc is not None else "—"
                            sub_p2_str = str(sub_p2_fc) if sub_p2_fc is not None else "—"
                            sub_delta_display = f"{(sub_p1_fc or 0) - (sub_p2_fc or 0):+d}"
                        else:
                            sub_p1_str = f"{sub_p1_val:.2f}"
                            sub_p2_str = f"{sub_p2_val:.2f}"
                            sub_delta_display = f"{sub_delta:+.2f}"
                        
                        sub_p1_bg = "rgba(0,255,0,0.15)" if sub_delta > 0 else "transparent"
                        sub_p2_bg = "rgba(0,255,0,0.15)" if sub_delta < 0 else "transparent"
                        
                        tier1, tier1_color = get_trait_tier(sub_p1_val)
                        tier2, tier2_color = get_trait_tier(sub_p2_val)
                        
                        st.markdown(f"""
                        <div style='padding:12px 16px;margin:6px 0;background:rgba(255,255,255,0.05);
                                    border-radius:8px;display:flex;justify-content:space-between;align-items:center;'>
                            <span style='font-weight:700;color:#FFFFFF;font-size:14px;'>{substat}</span>
                            <div style='display:flex;gap:20px;align-items:center;'>
                                <div style='text-align:center;background:{sub_p1_bg};padding:6px 12px;border-radius:6px;min-width:60px;'>
                                    <div style='font-size:16px;font-weight:900;color:{tier1_color};'>{sub_p1_str}</div>
                                </div>
                                <div style='text-align:center;background:{sub_p2_bg};padding:6px 12px;border-radius:6px;min-width:60px;'>
                                    <div style='font-size:16px;font-weight:900;color:{tier2_color};'>{sub_p2_str}</div>
                                </div>
                                <div style='text-align:center;min-width:50px;'>
                                    <div style='font-size:16px;font-weight:900;color:{sub_delta_color};'>{sub_delta_display}</div>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
        else:
            # Specific pillar selected - show simple comparison table
            comparison_rows = []
            for substat in comp_substats:
                if substat not in traits_df.columns:
                    continue
                
                p1_val = safe_float(player_data.get(substat))
                p2_val = safe_float(comp_data.get(substat))
                
                if p1_val is None or p2_val is None:
                    continue
                
                delta = p1_val - p2_val
                delta_color = "#00FF00" if delta > 0 else "#FF6B6B" if delta < 0 else "#FFA500"
                
                # Highlight winner
                p1_bg = "rgba(0,255,0,0.2)" if delta > 0 else "transparent"
                p2_bg = "rgba(0,255,0,0.2)" if delta < 0 else "transparent"
                
                # Get tier for display
                tier1, tier1_color = get_trait_tier(p1_val)
                tier2, tier2_color = get_trait_tier(p2_val)
                
                # Format values based on FC mode
                if fc_mode:
                    p1_fc = convert_trait_to_fc_rating(p1_val)
                    p2_fc = convert_trait_to_fc_rating(p2_val)
                    p1_str = str(p1_fc) if p1_fc is not None else "—"
                    p2_str = str(p2_fc) if p2_fc is not None else "—"
                    delta_fc = (p1_fc or 0) - (p2_fc or 0)
                    delta_display = f"{delta_fc:+d}"
                else:
                    p1_str = f"{p1_val:.2f}"
                    p2_str = f"{p2_val:.2f}"
                    delta_display = f"{delta:+.2f}"
                
                comparison_rows.append(f"""<tr>
                    <td style='text-align:left;font-weight:600;'>{substat}
                        <span style='font-size:11px;color:{tier1_color};margin-left:8px;background:{tier1_color}20;padding:2px 6px;border-radius:8px;'>{tier1}</span>
                    </td>
                    <td style='background:{p1_bg};font-weight:700;color:{tier1_color};'>{p1_str}</td>
                    <td style='background:{p2_bg};font-weight:700;color:{tier2_color};'>{p2_str}</td>
                    <td style='color:{delta_color};font-weight:700;'>{delta_display}</td>
                </tr>""")
            
            if comparison_rows:
                st.markdown(f"<table class='fe-table fe-table-compact'><thead><tr><th style='text-align:left;'>Statistic</th><th>{selected_player}</th><th>{comparison_player}</th><th>Difference</th></tr></thead><tbody>{''.join(comparison_rows)}</tbody></table>", unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Development recommendations
    st.markdown("<div class='idp-section-header'>📈 Development Recommendations</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='idp-card'><h3 style='color:#FFFFFF;margin:0 0 20px 0;font-weight:900;font-size:22px;'>Personalized Development Path</h3>", unsafe_allow_html=True)
    
    # Calculate all sub-trait comparisons for detailed recommendations
    all_focus_details = {}  # {pillar: [(substat, player_val, top10_avg, delta_pct), ...]}
    all_strength_details = {}
    
    for pillar_name, pillar_info in trait_pillars.items():
        focus_list = []
        strength_list = []
        for substat in pillar_info['substats']:
            if substat not in top_10_position.columns:
                continue
            
            player_val = safe_float(player_data.get(substat))
            top10_avg = pd.to_numeric(top_10_position[substat], errors="coerce").mean()
            
            if player_val is None or pd.isna(top10_avg):
                continue
            
            delta = player_val - top10_avg
            delta_pct = (delta / top10_avg * 100) if top10_avg != 0 else 0
            
            if delta_pct <= -10:
                focus_list.append((substat, player_val, top10_avg, delta_pct))
            elif delta_pct >= 10:
                strength_list.append((substat, player_val, top10_avg, delta_pct))
        
        if focus_list:
            all_focus_details[pillar_name] = sorted(focus_list, key=lambda x: x[3])
        if strength_list:
            all_strength_details[pillar_name] = sorted(strength_list, key=lambda x: x[3], reverse=True)
    
    # Check if there are any focus areas or strengths across ALL pillars
    has_any_focus = any(all_focus_details.values())
    has_any_strengths = any(all_strength_details.values())
    
    if has_any_focus:
        st.markdown("<h4 style='color:#FF6B6B;font-weight:900;font-size:18px;margin-top:16px;'>🎯 Priority Focus Areas:</h4>", unsafe_allow_html=True)
        
        # Display focus areas by pillar using all_focus_details
        for pillar_name, pillar_info in trait_pillars.items():
            pillar_focus = all_focus_details.get(pillar_name, [])
            if pillar_focus:
                pillar_val = safe_float(player_data.get(pillar_name))
                pillar_tier, pillar_color = get_trait_tier(pillar_val)
                
                st.markdown(f"""
                <div style='margin:16px 0;padding:20px;background:rgba(255,107,107,0.08);
                            border-left:5px solid #FF6B6B;border-radius:12px;
                            box-shadow:0 4px 12px rgba(0,0,0,0.3);'>
                    <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>
                        <span style='font-size:20px;font-weight:900;color:#FF6B6B;'>
                            {pillar_info['icon']} {pillar_name}
                        </span>
                        <span style='font-size:16px;font-weight:700;color:{pillar_color};
                                    background:{pillar_color}20;padding:6px 14px;border-radius:16px;'>
                            {format_trait_val(pillar_val)} • {pillar_tier}
                        </span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander(f"📋 View {pillar_name} Sub-Trait Analysis", expanded=False):
                    for substat, player_val, top10_avg, delta_pct in pillar_focus:
                        # Format values
                        if fc_mode:
                            pv_fc = convert_trait_to_fc_rating(player_val)
                            ta_fc = convert_trait_to_fc_rating(top10_avg)
                            pv_str = str(pv_fc) if pv_fc is not None else "—"
                            ta_str = str(ta_fc) if ta_fc is not None else "—"
                        else:
                            pv_str = f"{player_val:.2f}"
                            ta_str = f"{top10_avg:.2f}"
                        
                        tier, tier_color = get_trait_tier(player_val)
                        if fc_mode:
                            tier = get_fc_rating_label(convert_trait_to_fc_rating(player_val))
                            tier_color = "#00FF00" if tier == "Elite" else "#90EE90" if tier == "Above Average" else "#FFA500" if tier == "Below Average" else "#FF6B6B"
                        
                        st.markdown(f"""
                        <div style='padding:14px 18px;margin:8px 0;background:rgba(255,255,255,0.05);
                                    border-radius:10px;border-left:4px solid {tier_color};'>
                            <div style='display:flex;justify-content:space-between;align-items:center;'>
                                <span style='font-weight:700;color:#FFFFFF;font-size:15px;'>{substat}</span>
                                <div style='display:flex;gap:16px;align-items:center;'>
                                    <div style='text-align:center;'>
                                        <div style='font-size:10px;color:rgba(255,255,255,0.5);'>You</div>
                                        <div style='font-size:18px;font-weight:900;color:#FFFFFF;'>{pv_str}</div>
                                    </div>
                                    <div style='text-align:center;'>
                                        <div style='font-size:10px;color:rgba(255,255,255,0.5);'>Top 10</div>
                                        <div style='font-size:18px;font-weight:900;color:#6495ED;'>{ta_str}</div>
                                    </div>
                                    <div style='text-align:center;min-width:70px;'>
                                        <div style='font-size:10px;color:rgba(255,255,255,0.5);'>Gap</div>
                                        <div style='font-size:18px;font-weight:900;color:#FF6B6B;'>{delta_pct:.1f}%</div>
                                    </div>
                                </div>
                            </div>
                            <div style='margin-top:10px;color:rgba(255,255,255,0.7);font-size:13px;line-height:1.5;'>
                                Focus on improving {substat.lower()} to reach elite {player_position} standards.
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
    
    if has_any_strengths:
        st.markdown("<h4 style='color:#00FF00;font-weight:900;margin-top:28px;font-size:18px;'>💪 Key Strengths to Maintain:</h4>", unsafe_allow_html=True)
        
        # Display strengths by pillar using all_strength_details
        for pillar_name, pillar_info in trait_pillars.items():
            pillar_strengths = all_strength_details.get(pillar_name, [])
            if pillar_strengths:
                pillar_val = safe_float(player_data.get(pillar_name))
                pillar_tier, pillar_color = get_trait_tier(pillar_val)
                
                st.markdown(f"""
                <div style='margin:16px 0;padding:20px;background:rgba(0,255,0,0.08);
                            border-left:5px solid #00FF00;border-radius:12px;
                            box-shadow:0 4px 12px rgba(0,0,0,0.3);'>
                    <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>
                        <span style='font-size:20px;font-weight:900;color:#00FF00;'>
                            {pillar_info['icon']} {pillar_name}
                        </span>
                        <span style='font-size:16px;font-weight:700;color:{pillar_color};
                                    background:{pillar_color}20;padding:6px 14px;border-radius:16px;'>
                            {format_trait_val(pillar_val)} • {pillar_tier}
                        </span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander(f"📋 View {pillar_name} Sub-Trait Analysis", expanded=False):
                    for substat, player_val, top10_avg, delta_pct in pillar_strengths:
                        # Format values
                        if fc_mode:
                            pv_fc = convert_trait_to_fc_rating(player_val)
                            ta_fc = convert_trait_to_fc_rating(top10_avg)
                            pv_str = str(pv_fc) if pv_fc is not None else "—"
                            ta_str = str(ta_fc) if ta_fc is not None else "—"
                        else:
                            pv_str = f"{player_val:.2f}"
                            ta_str = f"{top10_avg:.2f}"
                        
                        tier, tier_color = get_trait_tier(player_val)
                        if fc_mode:
                            tier = get_fc_rating_label(convert_trait_to_fc_rating(player_val))
                            tier_color = "#00FF00" if tier == "Elite" else "#90EE90" if tier == "Above Average" else "#FFA500" if tier == "Below Average" else "#FF6B6B"
                        
                        st.markdown(f"""
                        <div style='padding:14px 18px;margin:8px 0;background:rgba(255,255,255,0.05);
                                    border-radius:10px;border-left:4px solid {tier_color};'>
                            <div style='display:flex;justify-content:space-between;align-items:center;'>
                                <span style='font-weight:700;color:#FFFFFF;font-size:15px;'>{substat}</span>
                                <div style='display:flex;gap:16px;align-items:center;'>
                                    <div style='text-align:center;'>
                                        <div style='font-size:10px;color:rgba(255,255,255,0.5);'>You</div>
                                        <div style='font-size:18px;font-weight:900;color:#FFFFFF;'>{pv_str}</div>
                                    </div>
                                    <div style='text-align:center;'>
                                        <div style='font-size:10px;color:rgba(255,255,255,0.5);'>Top 10</div>
                                        <div style='font-size:18px;font-weight:900;color:#6495ED;'>{ta_str}</div>
                                    </div>
                                    <div style='text-align:center;min-width:70px;'>
                                        <div style='font-size:10px;color:rgba(255,255,255,0.5);'>Lead</div>
                                        <div style='font-size:18px;font-weight:900;color:#00FF00;'>+{delta_pct:.1f}%</div>
                                    </div>
                                </div>
                            </div>
                            <div style='margin-top:10px;color:rgba(255,255,255,0.7);font-size:13px;line-height:1.5;'>
                                ✓ Excellent {substat.lower()} performance. Maintain this competitive advantage.
                            </div>
                            </div>
                            """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Professional footer
    render_footer()

# ================= CUSTOM PLAYER COMPARISON =================
elif page == "Custom Player Comparison":
    render_page_header("Custom Player Comparison", "Build & Compare Custom Player Profiles", "🧬")
    
    # Custom CSS for player card containers - style all bordered containers
    st.markdown("""
    <style>
    /* Make all bordered containers in this page have consistent styling */
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%) !important;
        border-width: 3px !important;
        border-radius: 16px !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # -------------------------
    # Imports and Constants
    # -------------------------
    from sklearn.metrics.pairwise import cosine_similarity  # type: ignore
    import numpy as np
    
    # Rating scale mapping
    RATING_OPTIONS = ["Elite", "Good", "Average", "Below Average", "Poor"]
    RATING_TO_NUMERIC = {
        "Elite": 5,
        "Good": 4,
        "Average": 3,
        "Below Average": 2,
        "Poor": 1
    }
    NUMERIC_TO_RATING = {v: k for k, v in RATING_TO_NUMERIC.items()}
    
    # Core traits and their subcategories (dynamically detected from data)
    CORE_TRAITS = ["Ball Winning", "Ball Use", "Aerial", "Defence"]
    
    TRAIT_SUBCATEGORIES = {
        "Ball Winning": ["Stoppage", "Contest", "Power", "Receives"],
        "Ball Use": ["Handballing", "Kicking", "Goal Kicking", "Connecting"],
        "Aerial": ["Marking", "Contested", "Moks", "Ruck"],
        "Defence": ["Pressure", "Tackling", "Intercepting", "Neutralise"]
    }
    
    # Trait colors for visual consistency
    TRAIT_COLORS = {
        "Ball Winning": "#0066CC",
        "Ball Use": "#009933",
        "Aerial": "#FFEB3B",
        "Defence": "#CC0000"
    }
    
    # -------------------------
    # Helper Functions
    # -------------------------
    def get_tier_color(rating_label: str) -> tuple[str, str]:
        """Get background and text color for a rating tier."""
        colors = {
            "Elite": ("#008000", "#FFFFFF"),
            "Good": ("#90EE90", "#000000"),
            "Average": ("#FFD700", "#000000"),
            "Below Average": ("#FFA500", "#FFFFFF"),
            "Poor": ("#FF0000", "#FFFFFF")
        }
        return colors.get(rating_label, ("#666666", "#FFFFFF"))
    
    def numeric_to_rating_label(value: float) -> str:
        """Convert numeric value (1-5 scale or 1-4 trait scale) to rating label."""
        if value >= 4.5:
            return "Elite"
        elif value >= 3.5:
            return "Good"
        elif value >= 2.5:
            return "Average"
        elif value >= 1.5:
            return "Below Average"
        else:
            return "Poor"
    
    def trait_value_to_rating_label(value: float) -> str:
        """Convert trait value (1-4 scale) to rating label."""
        if value >= 3.0:
            return "Elite"
        elif value >= 2.5:
            return "Good"
        elif value >= 2.0:
            return "Average"
        elif value >= 1.5:
            return "Below Average"
        else:
            return "Poor"
    
    def rating_label_to_trait_value(label: str) -> float:
        """Convert rating label to trait value (1-4 scale)."""
        mapping = {
            "Elite": 3.5,
            "Good": 2.75,
            "Average": 2.25,
            "Below Average": 1.75,
            "Poor": 1.25
        }
        return mapping.get(label, 2.25)
    
    @st.cache_data(show_spinner=False)
    def load_traits_for_comparison(season: int) -> pd.DataFrame:
        """Load and prepare traits data for comparison."""
        traits_df = load_traits(season)
        if traits_df is None or traits_df.empty:
            return pd.DataFrame()
        
        # Ensure required columns exist
        required_cols = ["Player_Full", "Team_Full", "Position_Full"]
        if not all(col in traits_df.columns for col in required_cols):
            return pd.DataFrame()
        
        return traits_df.copy()
    
    def get_available_trait_columns(traits_df: pd.DataFrame) -> dict[str, list[str]]:
        """Dynamically detect available trait columns and subcategories."""
        available = {}
        for trait, subcats in TRAIT_SUBCATEGORIES.items():
            if trait in traits_df.columns:
                available_subcats = [s for s in subcats if s in traits_df.columns]
                available[trait] = available_subcats
        return available
    
    def build_custom_player_vector(
        core_ratings: dict[str, str],
        subcategory_ratings: dict[str, dict[str, str]],
        available_traits: dict[str, list[str]]
    ) -> np.ndarray:
        """Build a numeric vector from custom player ratings."""
        vector = []
        
        for trait in CORE_TRAITS:
            if trait not in available_traits:
                continue
            
            # Add core trait value
            core_value = rating_label_to_trait_value(core_ratings.get(trait, "Average"))
            vector.append(core_value)
            
            # Add subcategory values
            for subcat in available_traits[trait]:
                subcat_rating = subcategory_ratings.get(trait, {}).get(subcat)
                if subcat_rating is None:
                    # Inherit from parent
                    subcat_value = core_value
                else:
                    subcat_value = rating_label_to_trait_value(subcat_rating)
                vector.append(subcat_value)
        
        return np.array(vector)
    
    def build_player_vector(
        player_row: pd.Series,
        available_traits: dict[str, list[str]]
    ) -> np.ndarray:
        """Build a numeric vector from an AFL player's data."""
        vector = []
        
        for trait in CORE_TRAITS:
            if trait not in available_traits:
                continue
            
            # Add core trait value
            core_value = pd.to_numeric(player_row.get(trait), errors="coerce")
            if pd.isna(core_value):
                core_value = 2.0  # Default to average
            vector.append(core_value)
            
            # Add subcategory values
            for subcat in available_traits[trait]:
                subcat_value = pd.to_numeric(player_row.get(subcat), errors="coerce")
                if pd.isna(subcat_value):
                    subcat_value = core_value  # Inherit from parent
                vector.append(subcat_value)
        
        return np.array(vector)
    
    @st.cache_data(show_spinner=False)
    def calculate_all_similarities(
        custom_vector: tuple,  # Use tuple for caching
        traits_data: str,  # Serialized data for caching
        available_traits_keys: tuple,
        filter_position: str = None  # Filter by position
    ) -> pd.DataFrame:
        """Calculate cosine similarity between custom player and all AFL players."""
        import json
        
        # Deserialize
        custom_vec = np.array(custom_vector)
        traits_df = pd.read_json(traits_data)
        available_traits = {k: TRAIT_SUBCATEGORIES.get(k, []) for k in available_traits_keys}
        
        # Filter by position if specified
        if filter_position:
            traits_df = traits_df[traits_df["Position_Full"] == filter_position].copy()
        
        results = []
        
        for idx, row in traits_df.iterrows():
            try:
                player_vec = build_player_vector(row, available_traits)
                
                if len(player_vec) != len(custom_vec):
                    continue
                
                # Calculate cosine similarity
                similarity = cosine_similarity(
                    custom_vec.reshape(1, -1),
                    player_vec.reshape(1, -1)
                )[0][0]
                
                # Convert to percentage
                similarity_pct = similarity * 100
                
                results.append({
                    "Player": row.get("Player_Full", "Unknown"),
                    "Team": row.get("Team_Full", "Unknown"),
                    "Position": row.get("Position_Full", "Unknown"),
                    "Age": row.get("Age"),
                    "Similarity": similarity_pct,
                    "Ball Winning": row.get("Ball Winning"),
                    "Ball Use": row.get("Ball Use"),
                    "Aerial": row.get("Aerial"),
                    "Defence": row.get("Defence"),
                    "Rating": row.get("Rating"),
                    **{subcat: row.get(subcat) for trait_subcats in available_traits.values() for subcat in trait_subcats}
                })
            except Exception:
                continue
        
        if not results:
            return pd.DataFrame()
        
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values("Similarity", ascending=False).reset_index(drop=True)
        
        return results_df
    
    def render_player_card(
        player_data: dict,
        is_primary: bool = False,
        fc_mode: bool = False,
        show_subcategories: bool = False,
        available_traits: dict = None,
        card_key: str = ""
    ):
        """Render a premium player card."""
        player_name_raw = player_data.get("Player", "Unknown")
        team = player_data.get("Team", "Unknown")
        # Resolve abbreviated name to full name
        player_name = resolve_player_full_name(player_name_raw, team)
        position = player_data.get("Position", "Unknown")
        similarity = player_data.get("Similarity", 0)
        age = player_data.get("Age")
        age_str = f"{int(age)} years old" if pd.notna(age) else ""
        
        # Get similarity color
        if similarity >= 90:
            sim_color = "#008000"
        elif similarity >= 80:
            sim_color = "#90EE90"
        elif similarity >= 70:
            sim_color = "#FFD700"
        elif similarity >= 60:
            sim_color = "#FFA500"
        else:
            sim_color = "#FF6666"
        
        # Card size based on primary or secondary
        if is_primary:
            # Professional layout: Photo with logo overlay, then details
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                        border-radius: 16px; padding: 0; overflow: hidden;
                        border: 2px solid {sim_color}; box-shadow: 0 8px 32px rgba(0,0,0,0.4);'>
            </div>
            """, unsafe_allow_html=True)
            
            col_visual, col_details = st.columns([1, 2])
            
            with col_visual:
                # Photo with logo in corner
                st.markdown("<div style='position: relative; padding: 15px;'>", unsafe_allow_html=True)
                display_player_photo(player_name, st, size=160, team_name=team)
                logo_path = get_team_logo_path(team)
                if logo_path:
                    st.image(logo_path, width=45)
                st.markdown("</div>", unsafe_allow_html=True)
            
            with col_details:
                st.markdown(f"""
                <div style='padding: 20px 20px 20px 0;'>
                    <div style='display: flex; justify-content: space-between; align-items: flex-start;'>
                        <div>
                            <h2 style='color: #FFFFFF; margin: 0 0 8px 0; font-size: 1.6em; font-weight: 900;'>{player_name}</h2>
                            <p style='color: rgba(255,255,255,0.7); margin: 0; font-size: 1em;'>{team} • {position}</p>
                            <p style='color: rgba(255,255,255,0.5); margin: 8px 0 0 0; font-size: 0.85em;'>{age_str}</p>
                        </div>
                        <div style='text-align: right;'>
                            <div style='font-size: 2.5em; font-weight: 900; color: {sim_color}; line-height: 1;'>{similarity:.1f}%</div>
                            <div style='color: rgba(255,255,255,0.6); font-size: 0.85em; margin-top: 5px;'>MATCH</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Trait bars
                st.markdown("<div style='margin-top: 15px;'>", unsafe_allow_html=True)
                
                trait_cols = st.columns(4)
                for i, trait in enumerate(CORE_TRAITS):
                    trait_val = player_data.get(trait)
                    if trait_val is not None:
                        trait_val = float(trait_val)
                        if fc_mode:
                            display_val = convert_trait_to_fc_rating(trait_val)
                            label = get_fc_rating_label(display_val)
                        else:
                            display_val = f"{trait_val:.2f}"
                            label = trait_value_to_rating_label(trait_val)
                        
                        bg_color, text_color = get_tier_color(label)
                        trait_color = TRAIT_COLORS.get(trait, "#666666")
                        
                        with trait_cols[i]:
                            st.markdown(f"""
                            <div style='background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
                                        border-radius: 10px; padding: 12px; text-align: center;
                                        border-left: 3px solid {trait_color};'>
                                <div style='color: rgba(255,255,255,0.6); font-size: 0.7em; text-transform: uppercase; letter-spacing: 0.5px;'>{trait}</div>
                                <div style='color: #FFFFFF; font-size: 1.5em; font-weight: 900; margin: 5px 0;'>{display_val}</div>
                                <div style='background: {bg_color}; color: {text_color}; padding: 3px 8px; border-radius: 4px; font-size: 0.7em; font-weight: 700;'>{label}</div>
                            </div>
                            """, unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)
                
                # Subcategories expander
                if show_subcategories and available_traits:
                    with st.expander("📊 View Subcategories", expanded=False):
                        for trait in CORE_TRAITS:
                            if trait in available_traits:
                                st.markdown(f"**{trait}**")
                                subcat_cols = st.columns(len(available_traits[trait]))
                                for j, subcat in enumerate(available_traits[trait]):
                                    subcat_val = player_data.get(subcat)
                                    if subcat_val is not None:
                                        subcat_val = float(subcat_val)
                                        if fc_mode:
                                            sub_display = convert_trait_to_fc_rating(subcat_val)
                                        else:
                                            sub_display = f"{subcat_val:.2f}"
                                        label = trait_value_to_rating_label(subcat_val)
                                        bg, fg = get_tier_color(label)
                                        
                                        with subcat_cols[j]:
                                            st.markdown(f"""
                                            <div style='background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;'>
                                                <div style='color: rgba(255,255,255,0.5); font-size: 0.65em;'>{subcat}</div>
                                                <div style='color: #FFF; font-weight: 800;'>{sub_display}</div>
                                            </div>
                                            """, unsafe_allow_html=True)
                                st.markdown("---")
        else:
            # Compact card for grid
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                        border-radius: 12px; padding: 15px; height: 100%;
                        border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 16px rgba(0,0,0,0.3);'>
                <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'>
                    <div>
                        <div style='color: #FFFFFF; font-weight: 800; font-size: 1em;'>{player_name}</div>
                        <div style='color: rgba(255,255,255,0.5); font-size: 0.75em;'>{team} • {position}</div>
                    </div>
                    <div style='background: {sim_color}; color: {"#000" if sim_color in ["#90EE90", "#FFD700"] else "#FFF"};
                                padding: 5px 10px; border-radius: 6px; font-weight: 900; font-size: 0.9em;'>
                        {similarity:.1f}%
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # Mini trait bars
            traits_html = "<div style='display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px;'>"
            for trait in CORE_TRAITS:
                trait_val = player_data.get(trait)
                if trait_val is not None:
                    trait_val = float(trait_val)
                    if fc_mode:
                        display_val = convert_trait_to_fc_rating(trait_val)
                    else:
                        display_val = f"{trait_val:.1f}"
                    label = trait_value_to_rating_label(trait_val)
                    bg_color, text_color = get_tier_color(label)
                    
                    traits_html += f"""
                    <div style='text-align: center;'>
                        <div style='color: rgba(255,255,255,0.4); font-size: 0.55em; text-transform: uppercase;'>{trait[:4]}</div>
                        <div style='background: {bg_color}; color: {text_color}; padding: 2px 4px; border-radius: 3px;
                                    font-size: 0.7em; font-weight: 800;'>{display_val}</div>
                    </div>
                    """
            traits_html += "</div></div>"
            st.markdown(traits_html, unsafe_allow_html=True)
            
            # Display photo
            display_player_photo(player_name, st, size=80, team_name=team)
    
    # -------------------------
    # Load Data
    # -------------------------
    seasons_available = sorted(get_player_seasons(), reverse=True)
    if not seasons_available:
        seasons_available = [CURRENT_SEASON, 2025, 2024, 2023]
    
    selected_season = st.selectbox("Select Season", seasons_available, index=0, key="cpc_season")
    
    traits_df = load_traits_for_comparison(int(selected_season))
    
    if traits_df.empty:
        st.error("Could not load traits data for comparison. Please check your data files.")
        st.stop()
    
    available_traits = get_available_trait_columns(traits_df)
    
    if not available_traits:
        st.error("No trait columns found in the data.")
        st.stop()
    
    # Get unique positions
    positions = sorted(traits_df["Position_Full"].dropna().unique().tolist())
    if not positions:
        positions = ["Midfielder", "Key Forward", "Key Defender", "Gen. Forward", "Gen. Defender", "Ruck", "Wing"]
    
    # FC Mode toggle (consistent with other pages)
    fc_mode = st.toggle("⚽ FC Rating Mode (50-99)", key="cpc_fc_mode", 
                        help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")
    
    st.divider()
    
    # -------------------------
    # Build Your Player Section
    # -------------------------
    st.markdown("""
    <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                border-radius: 16px; padding: 25px; margin-bottom: 25px;
                border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 8px 32px rgba(0,0,0,0.4);'>
        <h3 style='color: #FFFFFF; margin: 0 0 5px 0; font-size: 1.4em;'>🧬 Build Your Player</h3>
        <p style='color: rgba(255,255,255,0.6); margin: 0; font-size: 0.9em;'>Create a custom player profile to find similar AFL players</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Basic info inputs
    info_col1, info_col2, info_col3 = st.columns(3)
    
    with info_col1:
        custom_player_name = st.text_input("Player Name", value="Custom Player", key="cpc_player_name",
                                            placeholder="Enter a name for your player")
    
    with info_col2:
        custom_position = st.selectbox("Position", positions, key="cpc_position")
    
    with info_col3:
        custom_age = st.number_input("Age", min_value=17, max_value=45, value=25, key="cpc_age")
    
    st.markdown("---")
    st.markdown("### Core Trait Ratings")
    
    # Store ratings
    core_ratings = {}
    subcategory_ratings = {}
    
    # Create columns for core traits
    trait_cols = st.columns(len(CORE_TRAITS))
    
    for i, trait in enumerate(CORE_TRAITS):
        if trait not in available_traits:
            continue
        
        trait_color = TRAIT_COLORS.get(trait, "#666666")
        
        with trait_cols[i]:
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
                        border-radius: 10px; padding: 15px; border-left: 4px solid {trait_color};'>
                <div style='color: #FFFFFF; font-weight: 800; font-size: 0.95em; margin-bottom: 10px;'>{trait}</div>
            </div>
            """, unsafe_allow_html=True)
            
            core_ratings[trait] = st.selectbox(
                f"{trait} Rating",
                RATING_OPTIONS,
                index=2,  # Default to "Average"
                key=f"cpc_core_{trait}",
                label_visibility="collapsed"
            )
            
            # Subcategory expander
            with st.expander(f"⚙️ Adjust Subcategories", expanded=False):
                subcategory_ratings[trait] = {}
                
                for subcat in available_traits[trait]:
                    # Default is None (inherit from parent)
                    subcat_rating = st.selectbox(
                        subcat,
                        ["(Inherit from parent)"] + RATING_OPTIONS,
                        index=0,
                        key=f"cpc_sub_{trait}_{subcat}"
                    )
                    
                    if subcat_rating != "(Inherit from parent)":
                        subcategory_ratings[trait][subcat] = subcat_rating
    
    # -------------------------
    # Calculate Similarities
    # -------------------------
    st.divider()
    
    if st.button("🔍 Find Similar Players", type="primary", use_container_width=True):
        with st.spinner("Analyzing player database..."):
            # Build custom player vector
            custom_vector = build_custom_player_vector(core_ratings, subcategory_ratings, available_traits)
            
            # Calculate similarities
            results_df = calculate_all_similarities(
                tuple(custom_vector),
                traits_df.to_json(),
                tuple(available_traits.keys()),
                filter_position=custom_position  # Filter by selected position
            )
            
            if results_df.empty:
                st.error("Could not calculate similarities. Please check your data.")
                st.stop()
            
            # Store in session state
            st.session_state.cpc_results = results_df
            st.session_state.cpc_custom_name = custom_player_name
            st.session_state.cpc_custom_position = custom_position
            st.session_state.cpc_custom_age = custom_age
            st.session_state.cpc_core_ratings = core_ratings
    
    # -------------------------
    # Display Results
    # -------------------------
    if "cpc_results" in st.session_state and not st.session_state.cpc_results.empty:
        results_df = st.session_state.cpc_results
        custom_name = st.session_state.get("cpc_custom_name", "Custom Player")
        custom_pos = st.session_state.get("cpc_custom_position", "Unknown")
        custom_age = st.session_state.get("cpc_custom_age", 25)
        stored_ratings = st.session_state.get("cpc_core_ratings", {})
        
        st.divider()
        
        # Helper function to render a player card
        def render_comparison_card(
            player_name: str,
            team: str,
            position: str,
            age_str: str,
            similarity: float,
            trait_ratings: dict,  # trait_name -> (display_val, label)
            border_color: str,
            is_custom: bool = False
        ):
            """Render a professional player comparison card with Photo | Name | Logo layout."""
            # Use st.container with border - global CSS handles background styling
            card_container = st.container(border=True)
            
            with card_container:
                # ROW 1: Photo | Name Card | Logo (3 columns: 2-3-2 ratio)
                col_photo, col_info, col_logo = st.columns([2, 3, 2])
                
                with col_photo:
                    if is_custom:
                        st.markdown("""<div style='width: 180px; height: 180px; background: linear-gradient(135deg, #9333EA 0%, #6B21A8 100%); border-radius: 16px; display: flex; align-items: center; justify-content: center; margin: 0 auto; box-shadow: 0 4px 16px rgba(147,51,234,0.4);'><span style='font-size: 5em;'>👤</span></div>""", unsafe_allow_html=True)
                    else:
                        display_player_photo(player_name, st, size=180, team_name=team)
                
                with col_info:
                    # Compact info card in center
                    pos_color = "#9333EA" if is_custom else "rgba(255,255,255,0.7)"
                    team_text = "Custom Build" if is_custom else team
                    
                    if is_custom:
                        st.markdown(f"""<div style='background: rgba(147,51,234,0.15); border-radius: 12px; padding: 15px; text-align: center; border: 1px solid rgba(147,51,234,0.3);'><h3 style='color: #FFFFFF; margin: 0 0 8px 0; font-size: 1.3em; font-weight: 900;'>{player_name}</h3><p style='color: {pos_color}; margin: 0 0 4px 0; font-size: 0.85em; font-weight: 600;'>{position}</p><p style='color: rgba(255,255,255,0.5); margin: 0 0 8px 0; font-size: 0.75em;'>{team_text}</p><p style='color: rgba(255,255,255,0.4); margin: 0 0 10px 0; font-size: 0.7em;'>{age_str}</p><div style='font-size: 1.5em;'>🧬</div><div style='color: rgba(255,255,255,0.5); font-size: 0.65em; margin-top: 4px;'>CUSTOM BUILD</div></div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""<div style='background: rgba(255,255,255,0.05); border-radius: 12px; padding: 15px; text-align: center; border: 1px solid rgba(255,255,255,0.1);'><h3 style='color: #FFFFFF; margin: 0 0 8px 0; font-size: 1.3em; font-weight: 900;'>{player_name}</h3><p style='color: {pos_color}; margin: 0 0 4px 0; font-size: 0.85em; font-weight: 500;'>{position}</p><p style='color: rgba(255,255,255,0.5); margin: 0 0 4px 0; font-size: 0.75em;'>{team_text}</p><p style='color: rgba(255,255,255,0.4); margin: 0 0 10px 0; font-size: 0.7em;'>{age_str}</p><div style='font-size: 2em; font-weight: 900; color: {border_color}; line-height: 1;'>{similarity:.1f}%</div><div style='color: rgba(255,255,255,0.5); font-size: 0.65em; margin-top: 4px;'>MATCH</div></div>""", unsafe_allow_html=True)
                
                with col_logo:
                    if is_custom:
                        st.markdown("""<div style='width: 180px; height: 180px; background: rgba(147, 51, 234, 0.15); border-radius: 16px; display: flex; align-items: center; justify-content: center; border: 2px solid rgba(147, 51, 234, 0.3); margin: 0 auto;'><span style='font-size: 5em;'>🎯</span></div>""", unsafe_allow_html=True)
                    else:
                        logo_path = get_team_logo_path(team)
                        if logo_path:
                            st.image(logo_path, width=180)
                        else:
                            st.markdown(f"""<div style='width: 180px; height: 180px; background: rgba(255,255,255,0.05); border-radius: 16px; display: flex; align-items: center; justify-content: center; margin: 0 auto;'><span style='color: rgba(255,255,255,0.5); font-size: 1em;'>{team}</span></div>""", unsafe_allow_html=True)
                
                # ROW 2: Trait ratings below
                st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
                trait_cols = st.columns(4)
                for i, trait in enumerate(CORE_TRAITS):
                    if trait in trait_ratings:
                        display_val, label = trait_ratings[trait]
                        bg_color, text_color = get_tier_color(label)
                        
                        with trait_cols[i]:
                            st.markdown(f"""<div style='text-align: center; padding: 10px; background: rgba(255,255,255,0.03); border-radius: 8px;'><div style='color: rgba(255,255,255,0.5); font-size: 0.65em; text-transform: uppercase; margin-bottom: 6px;'>{trait}</div><div style='color: #FFFFFF; font-size: 1.4em; font-weight: 900; margin-bottom: 6px;'>{display_val}</div><div style='background: {bg_color}; color: {text_color}; padding: 5px 10px; border-radius: 4px; font-size: 0.65em; font-weight: 700; display: inline-block;'>{label}</div></div>""", unsafe_allow_html=True)
        
        # =====================================================
        # ROW 1: Custom Player vs Most Similar Player
        # =====================================================
        st.markdown("### 🎯 Comparison")
        
        col_custom, col_match = st.columns(2)
        
        # --- Custom Player Card (Left) ---
        with col_custom:
            # Build trait ratings dict for custom player
            custom_trait_ratings = {}
            for trait in CORE_TRAITS:
                if trait in stored_ratings:
                    rating = stored_ratings[trait]
                    custom_trait_ratings[trait] = (rating, rating)  # display_val = label for custom
            
            custom_age_str = f"{custom_age} years old"
            
            render_comparison_card(
                player_name=custom_name,
                team="",
                position=custom_pos,
                age_str=custom_age_str,
                similarity=0,
                trait_ratings=custom_trait_ratings,
                border_color="#9333EA",
                is_custom=True
            )
        
        # --- Most Similar Player Card (Right) ---
        with col_match:
            top_player = results_df.iloc[0].to_dict()
            player_name_raw = top_player.get("Player", "Unknown")
            team = top_player.get("Team", "Unknown")
            player_name = resolve_player_full_name(player_name_raw, team)
            position = top_player.get("Position", "Unknown")
            similarity = top_player.get("Similarity", 0)
            age = top_player.get("Age")
            age_str = f"{int(age)} years old" if pd.notna(age) else ""
            
            # Similarity color
            if similarity >= 90:
                sim_color = "#008000"
            elif similarity >= 80:
                sim_color = "#90EE90"
            elif similarity >= 70:
                sim_color = "#FFD700"
            elif similarity >= 60:
                sim_color = "#FFA500"
            else:
                sim_color = "#FF6666"
            
            # Build trait ratings dict
            match_trait_ratings = {}
            for trait in CORE_TRAITS:
                trait_val = top_player.get(trait)
                if trait_val is not None:
                    trait_val = float(trait_val)
                    if fc_mode:
                        display_val = str(convert_trait_to_fc_rating(trait_val))
                        label = get_fc_rating_label(convert_trait_to_fc_rating(trait_val))
                    else:
                        display_val = f"{trait_val:.2f}"
                        label = trait_value_to_rating_label(trait_val)
                    match_trait_ratings[trait] = (display_val, label)
            
            render_comparison_card(
                player_name=player_name,
                team=team,
                position=position,
                age_str=age_str,
                similarity=similarity,
                trait_ratings=match_trait_ratings,
                border_color=sim_color,
                is_custom=False
            )
        
        st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
        
        # =====================================================
        # ROW 2: Next 2 Similar Players (aligned under row 1)
        # =====================================================
        if len(results_df) > 1:
            next_players = results_df.iloc[1:3]  # Get players 2-3 (2 players)
            cols = st.columns(2)
            
            for i, (idx, player_row) in enumerate(next_players.iterrows()):
                with cols[i]:
                    player_data = player_row.to_dict()
                    
                    # Extract and resolve player info
                    similarity = player_data.get("Similarity", 0)
                    player_name_raw = player_data.get("Player", "Unknown")
                    team = player_data.get("Team", "Unknown")
                    player_name = resolve_player_full_name(player_name_raw, team)
                    position = player_data.get("Position", "Unknown")
                    age = player_data.get("Age")
                    age_str = f"{int(age)} yrs" if pd.notna(age) else ""
                    
                    # Similarity color
                    if similarity >= 90:
                        sim_color = "#008000"
                    elif similarity >= 80:
                        sim_color = "#90EE90"
                    elif similarity >= 70:
                        sim_color = "#FFD700"
                    elif similarity >= 60:
                        sim_color = "#FFA500"
                    else:
                        sim_color = "#FF6666"
                    
                    # Build trait ratings dict
                    player_trait_ratings = {}
                    for trait in CORE_TRAITS:
                        trait_val = player_data.get(trait)
                        if trait_val is not None:
                            try:
                                trait_val = float(trait_val)
                                if fc_mode:
                                    display_val = str(convert_trait_to_fc_rating(trait_val))
                                    label = get_fc_rating_label(convert_trait_to_fc_rating(trait_val))
                                else:
                                    display_val = f"{trait_val:.2f}"
                                    label = trait_value_to_rating_label(trait_val)
                                player_trait_ratings[trait] = (display_val, label)
                            except (ValueError, TypeError):
                                pass
                    
                    render_comparison_card(
                        player_name=player_name,
                        team=team,
                        position=position,
                        age_str=age_str,
                        similarity=similarity,
                        trait_ratings=player_trait_ratings,
                        border_color=sim_color,
                        is_custom=False
                    )
        
        st.divider()
        
        # =====================================================
        # RESULTS TABLE
        # =====================================================
        with st.expander("📋 View All Results", expanded=False):
            cols_to_show = ["Player", "Team", "Position", "Age", "Similarity", "Ball Winning", "Ball Use", "Aerial", "Defence"]
            cols_available = [c for c in cols_to_show if c in results_df.columns]
            display_df = results_df.head(20)[cols_available].copy()
            
            # Resolve abbreviated player names
            if "Player" in display_df.columns and "Team" in display_df.columns:
                display_df["Player"] = display_df.apply(
                    lambda row: resolve_player_full_name(row["Player"], row["Team"]), axis=1
                )
            
            display_df["Similarity"] = display_df["Similarity"].apply(lambda x: f"{x:.1f}%")
            
            if "Age" in display_df.columns:
                display_df["Age"] = display_df["Age"].apply(lambda x: int(x) if pd.notna(x) else "—")
            
            for col in ["Ball Winning", "Ball Use", "Aerial", "Defence"]:
                if col in display_df.columns:
                    if fc_mode:
                        display_df[col] = display_df[col].apply(lambda x: str(convert_trait_to_fc_rating(float(x))) if pd.notna(x) else "—")
                    else:
                        display_df[col] = display_df[col].apply(lambda x: f"{float(x):.2f}" if pd.notna(x) else "—")
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    # Professional footer
    render_footer()

# ================= GAME MODEL SCORECARD =================
elif page == "Game Model Scorecard":
    render_page_header("Game Model Scorecard", "Match Analysis & KPI Tracking", "📊")
    
    # Available KPIs from team data
    ALL_KPIS = [
        "Post Clear CP Diff",
        "Ground Ball Diff",
        "1st Poss to Clear %",
        "Clearance Diff",
        "Ball Winning Ranking",
        "Def Half to Score %",
        "Chain to Score %",
        "D50 to F50 %",
        "Kick Rating",
        "Ball Movement Ranking",
        "Scores per I50 %",
        "Goals Per I 50 %",
        "Accuracy %",
        "+/- Exp Score",
        "Scoring Ranking",
        "Def Half to Score Ag %",
        "Chain to Score Ag %",
        "D50 to F50 Ag %",
        "Goals Per I50 Ag %",
        "Defence Ranking",
        "Tackle Diff",
        "F50 Tackles",
        "Pressure Acts",
        "1%'ers",
        "Pressure Ranking",
        "Score from Turnover For",
        "Scores from Turnover Ag",
        "Scores from Stoppages For",
        "Scores from Stoppage Ag",
        "Territory %",
        "Post-Clearance CP Diff",
        "Health Check Ranking",
        "Attack Rating",
        "Defence Rating",
        "Overall Rating"
    ]
    
    # Define complementary stat pairs (For stat pairs with Against stat)
    STAT_PAIRS = {
        # For stats → Ag stats (for opposition)
        "Def Half to Score %": "Def Half to Score Ag %",
        "Chain to Score %": "Chain to Score Ag %",
        "D50 to F50 %": "D50 to F50 Ag %",
        "Goals Per I 50 %": "Goals Per I50 Ag %",
        "Scores per I50 %": "Scores per I50 Ag %",
        "Score from Turnover For": "Scores from Turnover Ag",
        "Scores from Stoppages For": "Scores from Stoppage Ag",
        # Ag stats → For stats (reverse mapping)
        "Def Half to Score Ag %": "Def Half to Score %",
        "Chain to Score Ag %": "Chain to Score %",
        "D50 to F50 Ag %": "D50 to F50 %",
        "Goals Per I50 Ag %": "Goals Per I 50 %",
        "Scores per I50 Ag %": "Scores per I50 %",
        "Scores from Turnover Ag": "Score from Turnover For",
        "Scores from Stoppage Ag": "Scores from Stoppages For"
    }
    
    # Categorize KPIs into groups - all KPIs available in each category
    KPI_CATEGORIES = {
        "Team": ALL_KPIS,
        "Offence": ALL_KPIS,
        "Defence": ALL_KPIS,
        "Contest": ALL_KPIS
    }
    
    # Filter controls
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Team selection - default to Home page selection
        all_teams = [
            "Adelaide", "Brisbane", "Carlton", "Collingwood", "Essendon", 
            "Fremantle", "Geelong", "Gold Coast", "GWS Giants",
            "Hawthorn", "Melbourne", "North Melbourne", "Port Adelaide", 
            "Richmond", "St Kilda", "Sydney", "West Coast", "Western Bulldogs"
        ]
        default_idx = 0
        if "default_team" in st.session_state and st.session_state.default_team in all_teams:
            default_idx = all_teams.index(st.session_state.default_team)
        
        selected_team = st.selectbox("Select Team", all_teams, index=default_idx, key="scorecard_team")
    
    with col2:
        available_years = [2025, 2024, 2023]
        selected_year = st.selectbox("Select Year", available_years, key="scorecard_year")
    
    # Display team logo
    st.markdown("---")
    team_code = TEAM_CODE_MAP.get(selected_team, selected_team.lower().replace(" ", ""))
    team_logo_path = f"{LOGO_FOLDER}/{team_code}.png"
    
    if os.path.exists(team_logo_path):
        try:
            img = Image.open(team_logo_path)
            # Center the logo
            logo_col1, logo_col2, logo_col3 = st.columns([1, 1, 1])
            with logo_col2:
                st.image(img, width=200)
        except Exception as e:
            pass
    
    # KPI Selection by Category
    st.markdown("---")
    st.subheader("Select KPIs by Category (up to 5 per category)")
    
    # Initialize session state for each category
    category_selections = {}
    for category in ["Team", "Offence", "Defence", "Contest"]:
        session_key = f'scorecard_kpis_{category.lower()}'
        if session_key not in st.session_state:
            st.session_state[session_key] = []
    
    # Create columns for each category
    cat_cols = st.columns(4)
    
    for idx, (category, kpis) in enumerate(KPI_CATEGORIES.items()):
        with cat_cols[idx]:
            st.markdown(f"**{category}**")
            session_key = f'scorecard_kpis_{category.lower()}'
            selector_key = f'scorecard_kpis_{category.lower()}_selector'
            
            selected = st.multiselect(
                f"{category} metrics",
                options=kpis,
                default=st.session_state[session_key],
                max_selections=5,
                key=selector_key,
                label_visibility="collapsed"
            )
            
            # Update session state
            if selected != st.session_state[session_key]:
                st.session_state[session_key] = selected
            
            category_selections[category] = selected
    
    # Combine all selections
    selected_kpis = []
    for category in ["Team", "Offence", "Defence", "Contest"]:
        selected_kpis.extend(category_selections[category])
    
    if len(selected_kpis) == 0:
        st.info("Please select at least one KPI to display.")
        st.stop()
    
    # Load data
    try:
        # Load season data
        xl = pd.ExcelFile(TEAM_FILE)
        sheet_name = f"{selected_year} Summary"
        raw_df = xl.parse(sheet_name, header=None)
        
        # Structure: Row 3 has metric names, Row 4 onwards has teams
        metric_row_idx = 3
        first_team_row_idx = 4
        
        # Get metric names from row 3 and create column index mapping
        metric_to_col = {}
        for col_idx in range(len(raw_df.columns)):
            metric = raw_df.iloc[metric_row_idx, col_idx]
            if pd.notna(metric) and str(metric).strip() != 'Rank':
                metric_to_col[str(metric).strip()] = col_idx
        
        # Build data dictionary by reading team rows
        team_data = {}
        for row_idx in range(first_team_row_idx, len(raw_df)):
            team_name = raw_df.iloc[row_idx, 0]
            if pd.notna(team_name):
                team_name = str(team_name).strip()
                if team_name == "GWS":
                    team_name = "GWS Giants"
                
                if team_name in all_teams:
                    team_data[team_name] = {}
                    for metric_name, col_idx in metric_to_col.items():
                        value = raw_df.iloc[row_idx, col_idx]
                        if pd.notna(value):
                            try:
                                team_data[team_name][metric_name] = float(value)
                            except:
                                pass
        
        # Load Last 10 if needed
        last10_data = {}
        if selected_year == 2025:
            try:
                sheet_name_l10 = f"{selected_year} Last 10 Summary"
                raw_df_l10 = xl.parse(sheet_name_l10, header=None)
                
                metric_to_col_l10 = {}
                for col_idx in range(len(raw_df_l10.columns)):
                    metric = raw_df_l10.iloc[metric_row_idx, col_idx]
                    if pd.notna(metric) and str(metric).strip() != 'Rank':
                        metric_to_col_l10[str(metric).strip()] = col_idx
                
                for row_idx in range(first_team_row_idx, len(raw_df_l10)):
                    team_name = raw_df_l10.iloc[row_idx, 0]
                    if pd.notna(team_name):
                        team_name = str(team_name).strip()
                        if team_name == "GWS":
                            team_name = "GWS Giants"
                        
                        if team_name in all_teams:
                            last10_data[team_name] = {}
                            for metric_name, col_idx in metric_to_col_l10.items():
                                value = raw_df_l10.iloc[row_idx, col_idx]
                                if pd.notna(value):
                                    try:
                                        last10_data[team_name][metric_name] = float(value)
                                    except:
                                        pass
            except Exception as e:
                st.warning(f"Last 10 Games data not available: {e}")
                last10_data = {}
        
        # Helper functions
        def calculate_ranking(kpi_name, team_name, dataset):
            """Calculate league-wide ranking for a KPI"""
            values = []
            for team, metrics in dataset.items():
                if kpi_name in metrics:
                    val = metrics[kpi_name]
                    try:
                        val_num = float(val)
                        if not pd.isna(val_num):
                            values.append((team, val_num))
                    except:
                        pass
            
            if not values:
                return None, None
            
            # Sort - higher is better for most metrics, lower for "Against" metrics
            is_against = "Ag %" in kpi_name or "Ag" in kpi_name.split()[-1]
            values.sort(key=lambda x: x[1], reverse=not is_against)
            
            for rank, (team, val) in enumerate(values, 1):
                if team == team_name:
                    return rank, len(values)
            
            return None, len(values)
        
        def get_conditional_color(rank, total):
            """Get color based on ranking percentile"""
            if rank is None or total is None or total == 0:
                return "#666666", "white"
            
            percentile = (total - rank + 1) / total * 100
            
            if percentile >= 85:
                return "#008000", "white"  # Dark Green
            elif percentile >= 60:
                return "#90EE90", "black"  # Light Green
            elif percentile >= 35:
                return "#FFA500", "white"  # Orange
            else:
                return "#FF0000", "white"  # Red
        
        def format_ordinal(rank):
            """Format rank as ordinal"""
            if rank is None:
                return "N/A"
            if 10 <= rank % 100 <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
            return f"{rank}{suffix}"
        
        # Display scorecard
        st.markdown("---")
        st.markdown(f"<h2 style='text-align: center; margin-bottom: 30px; font-weight: 900; font-size: 36px;'>{selected_team} - {selected_year}</h2>", unsafe_allow_html=True)
        
        # Build data tables
        if not selected_kpis:
            st.info("Please select at least one KPI to display.")
        else:
            # Display cards by category
            for category in ["Team", "Offence", "Defence", "Contest"]:
                category_kpis = category_selections.get(category, [])
                if not category_kpis:
                    continue
                
                st.markdown(f"<h3 style='margin-top: 30px; margin-bottom: 20px; font-weight: 800; font-size: 24px; color: rgba(255,255,255,0.9);'>📊 {category}</h3>", unsafe_allow_html=True)
                
                # Prepare data for cards in this category
                card_data = []
                for kpi in category_kpis:
                    # Get season value
                    season_val = team_data.get(selected_team, {}).get(kpi, None)
                    season_rank, total_teams = calculate_ranking(kpi, selected_team, team_data)
                    season_color, season_text_color = get_conditional_color(season_rank, total_teams)
                    
                    # Get Last 10 value if applicable
                    l10_val = None
                    l10_rank = None
                    l10_color = "#666666"
                    l10_text_color = "white"
                    
                    if last10_data:
                        l10_val = last10_data.get(selected_team, {}).get(kpi, None)
                        l10_rank, _ = calculate_ranking(kpi, selected_team, last10_data)
                        l10_color, l10_text_color = get_conditional_color(l10_rank, total_teams)
                    
                    # Calculate difference
                    diff_val = None
                    if l10_val is not None and season_val is not None:
                        try:
                            diff_val = float(l10_val) - float(season_val)
                        except:
                            pass
                    
                    card_data.append({
                        'kpi': kpi,
                        'season_val': season_val,
                        'season_rank': season_rank,
                        'season_color': season_color,
                        'season_text_color': season_text_color,
                        'l10_val': l10_val,
                        'l10_rank': l10_rank,
                        'l10_color': l10_color,
                        'l10_text_color': l10_text_color,
                        'diff_val': diff_val,
                        'total_teams': total_teams
                    })
                
                # Display cards in grid layout
                num_cards = len(card_data)
                cols_per_row = 5
                
                for i in range(0, num_cards, cols_per_row):
                    cols = st.columns(cols_per_row)
                    
                    for j in range(cols_per_row):
                        idx = i + j
                        if idx >= num_cards:
                            break
                        
                        data = card_data[idx]
                        
                        with cols[j]:
                            # Format values
                            season_val_display = f"{float(data['season_val']):.2f}" if data['season_val'] is not None else "N/A"
                            season_rank_display = format_ordinal(data['season_rank'])
                            l10_val_display = f"{float(data['l10_val']):.2f}" if data['l10_val'] is not None else "—"
                            l10_rank_display = format_ordinal(data['l10_rank']) if data['l10_rank'] is not None else "—"
                        
                            # Calculate trend
                            if data['diff_val'] is not None:
                                diff_display = f"{data['diff_val']:+.2f}"
                                if data['diff_val'] > 0.05:
                                    trend_color = "#00ff00"
                                    trend_icon = "↑"
                                    trend_bg = "rgba(0, 255, 0, 0.1)"
                                elif data['diff_val'] < -0.05:
                                    trend_color = "#ff0000"
                                    trend_icon = "↓"
                                    trend_bg = "rgba(255, 0, 0, 0.1)"
                                else:
                                    trend_color = "rgba(255,255,255,0.5)"
                                    trend_icon = "→"
                                    trend_bg = "rgba(255,255,255,0.05)"
                            else:
                                diff_display = "—"
                                trend_color = "rgba(255,255,255,0.3)"
                                trend_icon = ""
                                trend_bg = "rgba(255,255,255,0.05)"
                            
                            # Build card HTML with smaller sizes
                            card_html = f"<div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 10px; padding: 12px; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 12px rgba(0,0,0,0.3); position: relative; overflow: hidden;'><div style='position: absolute; top: 0; right: 0; width: 80px; height: 80px; background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 70%); border-radius: 50%; transform: translate(30%, -30%);'></div><div style='font-size: 9px; font-weight: 800; color: rgba(255,255,255,0.5); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.8px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{data['kpi']}</div><div style='display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;'><div style='background: rgba(255,255,255,0.03); border-radius: 8px; padding: 10px; border-left: 3px solid {data['season_color']};'><div style='font-size: 8px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;'>SEASON</div><div style='font-size: 32px; font-weight: 900; color: #ffffff; margin-bottom: 4px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{season_val_display}</div><div style='display: inline-block; background-color: {data['season_color']}; color: {data['season_text_color']}; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 14px;'>{season_rank_display}</div></div><div style='background: rgba(255,255,255,0.03); border-radius: 8px; padding: 10px; border-left: 3px solid {data['l10_color']};'><div style='font-size: 8px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;'>LAST 10</div><div style='font-size: 32px; font-weight: 900; color: #ffffff; margin-bottom: 4px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{l10_val_display}</div><div style='display: inline-block; background-color: {data['l10_color']}; color: {data['l10_text_color']}; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 14px;'>{l10_rank_display}</div></div></div><div style='background: {trend_bg}; border-radius: 6px; padding: 8px; text-align: center; border: 1px solid {trend_color}33;'><div style='font-size: 8px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px;'>TREND</div><div style='font-size: 24px; font-weight: 900; color: {trend_color}; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{diff_display} {trend_icon}</div></div></div>"
                            st.markdown(card_html, unsafe_allow_html=True)
            
            # Opposition Snapshot Section
            st.markdown("---")
            st.markdown(f"<h2 style='text-align: center; margin: 40px 0 30px 0; font-weight: 900; font-size: 36px;'>⚔️ Opposition Snapshot</h2>", unsafe_allow_html=True)
            
            # Opposition team and data window selection
            opp_col1, opp_col2 = st.columns(2)
            
            with opp_col1:
                opposition_team = st.selectbox(
                    "Opposition Team",
                    options=sorted(team_data.keys()),
                    index=0,
                    key="opposition_team_select"
                )
            
            with opp_col2:
                comparison_window = st.selectbox(
                    "Compare Using",
                    options=["Season", "Last 10"],
                    index=0,
                    key="comparison_window_select"
                )
            
            # Display team logos side by side
            st.markdown("---")
            logo_col1, logo_col2 = st.columns(2)
            
            with logo_col1:
                st.markdown(f"<h3 style='text-align: center;'>{selected_team}</h3>", unsafe_allow_html=True)
                selected_team_code = TEAM_CODE_MAP.get(selected_team, selected_team.lower().replace(" ", ""))
                selected_team_logo_path = f"{LOGO_FOLDER}/{selected_team_code}.png"
                if os.path.exists(selected_team_logo_path):
                    try:
                        img1 = Image.open(selected_team_logo_path)
                        inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
                        with inner_col2:
                            st.image(img1, width=200)
                    except Exception as e:
                        pass
            
            with logo_col2:
                st.markdown(f"<h3 style='text-align: center;'>{opposition_team}</h3>", unsafe_allow_html=True)
                opposition_team_code = TEAM_CODE_MAP.get(opposition_team, opposition_team.lower().replace(" ", ""))
                opposition_team_logo_path = f"{LOGO_FOLDER}/{opposition_team_code}.png"
                if os.path.exists(opposition_team_logo_path):
                    try:
                        img2 = Image.open(opposition_team_logo_path)
                        inner_col1, inner_col2, inner_col3 = st.columns([1, 2, 1])
                        with inner_col2:
                            st.image(img2, width=200)
                    except Exception as e:
                        pass
            
            # Get opposition data based on selected window
            if comparison_window == "Last 10" and last10_data:
                opp_data_source = last10_data
                own_data_source = last10_data
            else:
                opp_data_source = team_data
                own_data_source = team_data
            
            # Build comparison cards by category
            st.markdown(f"<h3 style='margin-top: 30px; margin-bottom: 20px; text-align: center; color: rgba(255,255,255,0.7);'>{selected_team} vs {opposition_team} ({comparison_window})</h3>", unsafe_allow_html=True)
            
            # Store opportunities and threats by category
            category_opportunities = {"Team": [], "Offence": [], "Defence": [], "Contest": []}
            category_threats = {"Team": [], "Offence": [], "Defence": [], "Contest": []}
            
            # Display comparison cards by category
            for category in ["Team", "Offence", "Defence", "Contest"]:
                category_kpis = category_selections.get(category, [])
                if not category_kpis:
                    continue
                
                st.markdown(f"<h3 style='margin-top: 30px; margin-bottom: 20px; font-weight: 800; font-size: 24px; color: rgba(255,255,255,0.9);'>📊 {category}</h3>", unsafe_allow_html=True)
                
                comparison_data = []
                
                for kpi in category_kpis:
                    # Get own team data
                    own_val = own_data_source.get(selected_team, {}).get(kpi, None)
                    own_rank, _ = calculate_ranking(kpi, selected_team, own_data_source)
                    own_color, own_text_color = get_conditional_color(own_rank, total_teams)
                    
                    # Determine which stat to use for opposition (complementary stat if exists)
                    opp_kpi = STAT_PAIRS.get(kpi, kpi)
                    
                    # Get opposition data (using complementary stat if available)
                    opp_val = opp_data_source.get(opposition_team, {}).get(opp_kpi, None)
                    opp_rank, _ = calculate_ranking(opp_kpi, opposition_team, opp_data_source)
                    opp_color, opp_text_color = get_conditional_color(opp_rank, total_teams)
                    
                    # Calculate difference (own - opposition)
                    diff_val = None
                    advantage = None
                    if own_val is not None and opp_val is not None:
                        try:
                            diff_val = float(own_val) - float(opp_val)
                            
                            is_complementary = (opp_kpi != kpi)
                            is_ag_stat = "Ag" in kpi or kpi in ["Scores from Turnover Ag", "Scores from Stoppage Ag"]
                            
                            if is_complementary:
                                if is_ag_stat:
                                    if diff_val > 0.5:
                                        category_opportunities[category].append({'kpi': kpi, 'opp_kpi': opp_kpi, 'diff': diff_val, 'own_rank': own_rank, 'opp_rank': opp_rank})
                                        advantage = "advantage"
                                    elif diff_val < -0.5:
                                        category_threats[category].append({'kpi': kpi, 'opp_kpi': opp_kpi, 'diff': diff_val, 'own_rank': own_rank, 'opp_rank': opp_rank})
                                        advantage = "disadvantage"
                                    else:
                                        advantage = "neutral"
                                else:
                                    if diff_val > 0.5:
                                        category_threats[category].append({'kpi': kpi, 'opp_kpi': opp_kpi, 'diff': diff_val, 'own_rank': own_rank, 'opp_rank': opp_rank})
                                        advantage = "disadvantage"
                                    elif diff_val < -0.5:
                                        category_opportunities[category].append({'kpi': kpi, 'opp_kpi': opp_kpi, 'diff': diff_val, 'own_rank': own_rank, 'opp_rank': opp_rank})
                                        advantage = "advantage"
                                    else:
                                        advantage = "neutral"
                            else:
                                if diff_val > 0.5:
                                    category_opportunities[category].append({'kpi': kpi, 'opp_kpi': opp_kpi, 'diff': diff_val, 'own_rank': own_rank, 'opp_rank': opp_rank})
                                    advantage = "advantage"
                                elif diff_val < -0.5:
                                    category_threats[category].append({'kpi': kpi, 'opp_kpi': opp_kpi, 'diff': diff_val, 'own_rank': own_rank, 'opp_rank': opp_rank})
                                    advantage = "disadvantage"
                                else:
                                    advantage = "neutral"
                        except:
                            pass
                    
                    comparison_data.append({
                        'kpi': kpi,
                        'opp_kpi': opp_kpi,
                        'own_val': own_val,
                        'own_rank': own_rank,
                        'own_color': own_color,
                        'own_text_color': own_text_color,
                        'opp_val': opp_val,
                        'opp_rank': opp_rank,
                        'opp_color': opp_color,
                        'opp_text_color': opp_text_color,
                        'diff_val': diff_val,
                        'advantage': advantage
                    })
                
                # Display comparison cards
                num_comp_cards = len(comparison_data)
                cols_per_row = 5
                
                for i in range(0, num_comp_cards, cols_per_row):
                    cols = st.columns(cols_per_row)
                    
                    for j in range(cols_per_row):
                        idx = i + j
                        if idx >= num_comp_cards:
                            break
                        
                        data = comparison_data[idx]
                        
                        with cols[j]:
                            # Format values
                            own_val_display = f"{float(data['own_val']):.2f}" if data['own_val'] is not None else "N/A"
                            own_rank_display = format_ordinal(data['own_rank'])
                            opp_val_display = f"{float(data['opp_val']):.2f}" if data['opp_val'] is not None else "N/A"
                            opp_rank_display = format_ordinal(data['opp_rank'])
                            
                            # Show stat names (may be different for complementary pairs)
                            own_stat_label = data['kpi']
                            opp_stat_label = data['opp_kpi'] if data['opp_kpi'] != data['kpi'] else data['kpi']
                            
                            # Calculate advantage display
                            if data['diff_val'] is not None:
                                diff_display = f"{data['diff_val']:+.2f}"
                                if data['advantage'] == "advantage":
                                    adv_color = "#00ff00"
                                    adv_icon = "✓"
                                    adv_bg = "rgba(0, 255, 0, 0.1)"
                                    adv_text = "ADVANTAGE"
                                elif data['advantage'] == "disadvantage":
                                    adv_color = "#ff0000"
                                    adv_icon = "✗"
                                    adv_bg = "rgba(255, 0, 0, 0.1)"
                                    adv_text = "THREAT"
                                else:
                                    adv_color = "rgba(255,255,255,0.5)"
                                    adv_icon = "="
                                    adv_bg = "rgba(255,255,255,0.05)"
                                    adv_text = "NEUTRAL"
                            else:
                                diff_display = "—"
                                adv_color = "rgba(255,255,255,0.3)"
                                adv_icon = ""
                                adv_bg = "rgba(255,255,255,0.05)"
                                adv_text = "N/A"
                            
                            # Build comparison card HTML with smaller sizes
                            comp_card_html = f"<div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 10px; padding: 12px; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 12px rgba(0,0,0,0.3); position: relative; overflow: hidden;'><div style='position: absolute; top: 0; right: 0; width: 80px; height: 80px; background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 70%); border-radius: 50%; transform: translate(30%, -30%);'></div><div style='font-size: 9px; font-weight: 800; color: rgba(255,255,255,0.5); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.8px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{data['kpi']}</div><div style='display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px;'><div style='background: rgba(255,255,255,0.03); border-radius: 8px; padding: 10px; border-left: 3px solid {data['own_color']};'><div style='font-size: 8px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;'>{selected_team}</div><div style='font-size: 7px; font-weight: 600; color: rgba(255,255,255,0.4); margin-bottom: 3px;'>{own_stat_label}</div><div style='font-size: 32px; font-weight: 900; color: #ffffff; margin-bottom: 4px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{own_val_display}</div><div style='display: inline-block; background-color: {data['own_color']}; color: {data['own_text_color']}; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 14px;'>{own_rank_display}</div></div><div style='background: rgba(255,255,255,0.03); border-radius: 8px; padding: 10px; border-left: 3px solid {data['opp_color']};'><div style='font-size: 8px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;'>{opposition_team}</div><div style='font-size: 7px; font-weight: 600; color: rgba(255,255,255,0.4); margin-bottom: 3px;'>{opp_stat_label}</div><div style='font-size: 32px; font-weight: 900; color: #ffffff; margin-bottom: 4px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{opp_val_display}</div><div style='display: inline-block; background-color: {data['opp_color']}; color: {data['opp_text_color']}; padding: 4px 12px; border-radius: 4px; font-weight: 700; font-size: 14px;'>{opp_rank_display}</div></div></div><div style='background: {adv_bg}; border-radius: 6px; padding: 8px; text-align: center; border: 1px solid {adv_color}33;'><div style='font-size: 8px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px;'>{adv_text}</div><div style='font-size: 24px; font-weight: 900; color: {adv_color}; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{diff_display} {adv_icon}</div></div></div>"
                            st.markdown(comp_card_html, unsafe_allow_html=True)
            
            # Opportunities and Threats Analysis by Category
            st.markdown("---")
            st.markdown(f"<h3 style='text-align: center; margin: 30px 0 20px 0; font-weight: 900; font-size: 28px;'>📊 Match Analysis</h3>", unsafe_allow_html=True)
            
            # Display by category
            for category in ["Team", "Offence", "Defence", "Contest"]:
                category_opps = category_opportunities.get(category, [])
                category_thrs = category_threats.get(category, [])
                
                if not category_opps and not category_thrs:
                    continue
                
                st.markdown(f"<h4 style='margin-top: 25px; margin-bottom: 15px; font-weight: 800; font-size: 20px; color: rgba(255,255,255,0.9);'>{category}</h4>", unsafe_allow_html=True)
                
                analysis_col1, analysis_col2 = st.columns(2)
                
                with analysis_col1:
                    st.markdown(f"<div style='background: linear-gradient(135deg, rgba(0, 255, 0, 0.1) 0%, rgba(0, 255, 0, 0.05) 100%); border-radius: 12px; padding: 20px; border-left: 4px solid #00ff00;'><h4 style='color: #00ff00; margin-bottom: 15px; font-size: 18px;'>✓ OPPORTUNITIES</h4>", unsafe_allow_html=True)
                    
                    if category_opps:
                        category_opps.sort(key=lambda x: abs(x['diff']), reverse=True)
                        for opp in category_opps:
                            if opp['kpi'] != opp['opp_kpi']:
                                stat_display = f"{opp['kpi']} vs {opp['opp_kpi']}"
                            else:
                                stat_display = opp['kpi']
                            st.markdown(f"<div style='background: rgba(0,0,0,0.3); border-radius: 8px; padding: 12px; margin-bottom: 10px;'><div style='font-weight: 700; color: #ffffff; margin-bottom: 5px;'>{stat_display}</div><div style='font-size: 14px; color: rgba(255,255,255,0.7);'>Advantage: <span style='color: #00ff00; font-weight: 700;'>+{opp['diff']:.2f}</span> | You: {format_ordinal(opp['own_rank'])} vs Them: {format_ordinal(opp['opp_rank'])}</div></div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<p style='color: rgba(255,255,255,0.5); font-style: italic; font-size: 13px;'>None identified</p>", unsafe_allow_html=True)
                    
                    st.markdown("</div>", unsafe_allow_html=True)
                
                with analysis_col2:
                    st.markdown(f"<div style='background: linear-gradient(135deg, rgba(255, 0, 0, 0.1) 0%, rgba(255, 0, 0, 0.05) 100%); border-radius: 12px; padding: 20px; border-left: 4px solid #ff0000;'><h4 style='color: #ff0000; margin-bottom: 15px; font-size: 18px;'>✗ THREATS</h4>", unsafe_allow_html=True)
                    
                    if category_thrs:
                        category_thrs.sort(key=lambda x: abs(x['diff']), reverse=True)
                        for threat in category_thrs:
                            if threat['kpi'] != threat['opp_kpi']:
                                stat_display = f"{threat['kpi']} vs {threat['opp_kpi']}"
                            else:
                                stat_display = threat['kpi']
                            st.markdown(f"<div style='background: rgba(0,0,0,0.3); border-radius: 8px; padding: 12px; margin-bottom: 10px;'><div style='font-weight: 700; color: #ffffff; margin-bottom: 5px;'>{stat_display}</div><div style='font-size: 14px; color: rgba(255,255,255,0.7);'>Deficit: <span style='color: #ff0000; font-weight: 700;'>{threat['diff']:.2f}</span> | You: {format_ordinal(threat['own_rank'])} vs Them: {format_ordinal(threat['opp_rank'])}</div></div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<p style='color: rgba(255,255,255,0.5); font-style: italic; font-size: 13px;'>None identified</p>", unsafe_allow_html=True)
                    
                    st.markdown("</div>", unsafe_allow_html=True)
        
        # League context footer
        st.markdown("---")
        st.markdown(f"""
        <div style='text-align: center; color: rgba(255,255,255,0.5); font-size: 13px; margin-top: 30px;'>
            Rankings out of {total_teams if 'total_teams' in locals() else 18} teams | 
            Colour coding: <span style='color: #008000;'>■</span> Top 15% | 
            <span style='color: #90EE90;'>■</span> 60-85% | 
            <span style='color: #FFA500;'>■</span> 35-60% | 
            <span style='color: #FF0000;'>■</span> Bottom 35%
        </div>
        """, unsafe_allow_html=True)
        
        # Professional footer
        render_footer()
        
    except Exception as e:
        st.error(f"Error loading data: {e}")
        import traceback
        st.code(traceback.format_exc())
