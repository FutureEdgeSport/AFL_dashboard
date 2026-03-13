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
    TEAM_CODE_MAP, TEAM_CODE_TO_NAME, TEAM_COLOURS, TEAM_COLOUR_PALETTES, ALL_TEAMS,
    DEPTH_POSITIONS, POSITION_ABBREV_TO_FULL, POSITION_COLOURS,
    AGE_BANDS, AGE_BANDS_ALT,
    METRIC_ORDER, RATING_COL_CANDIDATES, TRAIT_COLUMNS,
    UIConfig, get_rating_color, get_rank_color, get_ordinal, safe_float, safe_int, normalize_team_name,
    get_unified_table_css, METRIC_TOOLTIPS, get_tooltip_html,
    PLAYER_NICKNAME_MAP, get_nickname_variants, build_player_name_variants,
)
from config.player_names import get_resolver as _get_name_resolver

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

# ---------------- PASSWORD GATE ----------------
def _check_password() -> bool:
    """Return True if the user has entered the correct password."""
    if st.session_state.get("password_correct"):
        return True
    pwd = st.text_input("Enter password to access the dashboard", type="password", key="_pw_input")
    if pwd:
        correct = st.secrets.get("passwords", {}).get("app_password", "")
        if pwd == correct:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False

# Only enforce the gate when secrets are configured (i.e. on Streamlit Cloud)
try:
    _has_pw = st.secrets.get("passwords", {}).get("app_password")
except Exception:
    _has_pw = None
if _has_pw:
    if not _check_password():
        st.stop()

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
    Render export buttons using components.html() so JavaScript actually executes.
    - Print / Save as PDF: opens the browser print dialog (Ctrl+P → Save as PDF)
    - Export as PNG: uses html2canvas to capture the main content area
    """
    export_html = f"""
    <html>
    <head>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <style>
        body {{ margin: 0; background: transparent; font-family: sans-serif; }}
        .export-bar {{ display: flex; justify-content: center; gap: 12px; padding: 10px 0; }}
        .export-btn {{
            background: linear-gradient(135deg, #00D26A 0%, #00A854 100%);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 14px;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }}
        .export-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 210, 106, 0.4);
        }}
    </style>
    </head>
    <body>
    <div class="export-bar">
        <button class="export-btn" id="printBtn">{_svg_inline('document', 16)}️ Print / Save as PDF</button>
        <button class="export-btn" id="pngBtn">{_svg_inline('chart_bar', 16)} Export as PNG</button>
    </div>
    <script>
        document.getElementById('printBtn').addEventListener('click', function() {{
            window.parent.print();
        }});
        document.getElementById('pngBtn').addEventListener('click', function() {{
            var mainEl = window.parent.document.querySelector('section.main');
            if (mainEl) {{
                html2canvas(mainEl, {{
                    backgroundColor: '#0e1117',
                    scale: 2,
                    useCORS: true
                }}).then(function(canvas) {{
                    var link = document.createElement('a');
                    link.download = '{filename}.png';
                    link.href = canvas.toDataURL('image/png');
                    link.click();
                }});
            }}
        }});
    </script>
    </body>
    </html>
    """
    components.html(export_html, height=60)


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
    .ct-pill {{
        display: inline-block;
        min-width: 60px;
        padding: 5px 16px;
        border-radius: 12px;
        font-weight: 700;
        font-size: 0.85em;
        letter-spacing: 0.02em;
        text-align: center;
        white-space: nowrap;
        box-shadow: 0 1px 4px rgba(0,0,0,0.25);
        line-height: 1.4;
    }}
    .ct-fa {{
        min-width: 50px;
        padding: 5px 14px;
        font-size: 0.78em;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }}
    .ct-cap {{
        font-weight: 700;
        color: #FFD700 !important;
        font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
        font-size: 0.88em;
    }}
    </style>
    </head>
    <body>
    {html_table}
    <script>
    (function() {{
        const table = document.querySelector('.fe-table') || document.querySelector('.ll-table');
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


# ─── SVG Silhouette Icon Infrastructure ───────────────────────────────
# All page/section icons use inline SVG silhouettes instead of emoji.
SVG_ICON_PATHS = {
    "home":          "M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z",
    "chart_bar":     "M3 3v18h18V3H3zm16 16H5V5h14v14zM7 12h2v5H7v-5zm4-3h2v8h-2V9zm4-2h2v10h-2V7z",
    "chart_trend":   "M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z",
    "balance":       "M10 3H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1zm0 10H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zm10-10h-6c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1zm0 10h-6c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1z",
    "list":          "M3 3h18v2H3V3zm0 4h18v2H3V7zm0 4h18v2H3v-2zm0 4h12v2H3v-2zm0 4h8v2H3v-2z",
    "depth_chart":   "M3 3h4v18H3V3zm7 4h4v14h-4V7zm7 4h4v10h-4V11z",
    "person_circle": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z",
    "ladder":        "M3 21h18v-2H3v2zm0-4h14v-2H3v2zm0-4h18v-2H3v2zm0-4h10v-2H3v2zm0-6v2h18V3H3z",
    "document":      "M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM6 20V4h7v5h5v11H6zm2-6h8v2H8v-2zm0-3h8v2H8v-2z",
    "layers":        "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
    "contract":      "M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13zM9.88 15.12l-1.41 1.41L11 19.06l4.24-4.24-1.41-1.41L11 16.24l-1.12-1.12z",
    "gamepad":       "M2 4v16h20V4H2zm18 14H4V6h16v12zM6 12h3v4H6v-4zm5-4h2v8h-2V8zm5 2h3v6h-3v-6z",
    "scorecard":     "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm-1-13h2v6h-2V7zm0 8h2v2h-2v-2z",
    "trophy":        "M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2z",
    "person":        "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
    "star":          "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14l-5-4.87 6.91-1.01L12 2z",
    "trending":      "M16 6l2.29 2.29-4.88 4.88-4-4L2 16.59 3.41 18l6-6 4 4 6.3-6.29L22 12V6h-6z",
    "people":        "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z",
    "search":        "M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
    "runner":        "M13.49 5.48c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm-3.6 13.9l1-4.4 2.1 2v6h2v-7.5l-2.1-2 .6-3c1.3 1.5 3.3 2.5 5.5 2.5v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1l-5.2 2.2v4.7h2v-3.4l1.8-.7-1.6 8.1-4.9-1-.4 2 7 1.4z",
    "calendar":      "M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM9 10H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2z",
    "folder":        "M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z",
    "strength":      "M20.57 14.86L22 13.43 20.57 12 17 15.57 8.43 7 12 3.43 10.57 2 9.14 3.43 7.71 2 5.57 4.14 4.14 2.71 2.71 4.14l1.43 1.43L2.71 7l1.43 1.43L2 10.57 3.43 12 7 8.43 15.57 17 12 20.57 13.43 22l1.43-1.43L16.29 22l2.14-2.14 1.43 1.43 1.43-1.43-1.43-1.43L22 16.29z",
    "shield":        "M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z",
    "swords":        "M6.92 5H5l4 4-1.79 1.79L3 6.58V5l3.22 3.22L6.92 5zM20 5v1.58l-4.21 4.21L14 9l4-4h-1.92l-.7 2.22L20 5zm-9.71 7.71L12 14.42l1.71-1.71 1.41 1.41L12 17.24l-3.12-3.12 1.41-1.41zM3 18.42l4.21-4.21L8.79 15 5 18.79V20h1.92l.7-2.22L3 18.42zm17 0l-4.62.58.7 2.22H18v-1.21L14.21 15l1.58-1.79L20 17.42v1z",
    "tag":           "M21.41 11.58l-9-9C12.05 2.22 11.55 2 11 2H4c-1.1 0-2 .9-2 2v7c0 .55.22 1.05.59 1.42l9 9c.36.36.86.58 1.41.58.55 0 1.05-.22 1.41-.59l7-7c.37-.36.59-.86.59-1.41 0-.55-.23-1.06-.59-1.42zM5.5 7C4.67 7 4 6.33 4 5.5S4.67 4 5.5 4 7 4.67 7 5.5 6.33 7 5.5 7z",
    "soccer":        "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17.93c-3.95.49-7.4-2.04-8.54-5.42L8 13.31l2 1v3l2.62 2.62zM16 16l-1.5-3 1.96-1.97 2.87.73c-.14 1.9-1.04 3.57-2.33 4.74l-1 .5zM5.67 7.42l2.5 1.5L9 12l-2.5 2.5L4.13 13c-.07-.33-.13-.66-.13-1 0-1.76.57-3.39 1.54-4.72l.13.14z",
    "gear":          "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58z",
    "stadium":       "M7 5L3 7V3l4 2zm14-2v4l-4-2 4-2zM3 17l4-2-4-2v4zm18-4l-4 2 4 2v-4zM12 8c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4z",
    "favorite":      "M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z",
}

# Map page names → SVG icon key
PAGE_ICON_MAP = {
    "Home":                     "home",
    "Club List":                "list",
    "Depth Chart":              "depth_chart",
    "Team Age Breakdown":       "person_circle",
    "List Ladder":              "ladder",
    "Team List Summary":        "document",
    "List Breakdown - Traits":  "layers",
    "Contract Status":          "contract",
    "Overview":                 "chart_bar",
    "Team Breakdown":           "chart_trend",
    "Team Compare":             "balance",
    "Game Predictor":             "gamepad",
    "Game Model Scorecard":     "scorecard",
    "Best 23":                  "trophy",
    "Player Profile":           "person",
    "IDP":                      "trending",
    "Custom Player Comparison": "people",
    "Player Rating Matrix":     "chart_bar",
}


def _svg_inline(name, size=20, color=None):
    """Return inline SVG HTML for a named icon."""
    path_d = SVG_ICON_PATHS.get(name, "")
    if not path_d:
        return ""
    col = f'fill="{color}"' if color else 'fill="currentColor"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'{col} width="{size}" height="{size}" '
            f'style="vertical-align:middle;display:inline-block;margin-right:6px;opacity:0.85;">'
            f'<path d="{path_d}"/></svg>')


def _svg_for_page(page_name, size=20, color=None):
    """Return inline SVG HTML for a page by name."""
    icon_key = PAGE_ICON_MAP.get(page_name, "chart_bar")
    return _svg_inline(icon_key, size, color)


def render_page_header(title: str, subtitle: str = None, icon: str = "chart_bar"):
    """Render consistent page header across all pages using SVG silhouette icons."""
    svg_icon = _svg_inline(icon, 36)
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
            {svg_icon} {title.upper()}
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
        <div style="font-size: 48px; margin-bottom: 16px;">{_svg_inline('document', 20)}</div>
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
    Also handles nickname variants (e.g. 'Cameron Rayner' matches 'Cam Rayner').
    Returns matching rows from traits_df.
    """
    if traits_df is None or traits_df.empty or "Player_Full" not in traits_df.columns:
        return pd.DataFrame()
    
    # First try exact match
    exact_match = traits_df[traits_df["Player_Full"] == full_name]
    if not exact_match.empty:
        return exact_match
    
    # Try nickname variants of the full name (e.g. "Cameron Rayner" → try "Cam Rayner")
    for variant in build_player_name_variants(full_name):
        if variant == full_name:
            continue
        variant_match = traits_df[traits_df["Player_Full"] == variant]
        if not variant_match.empty:
            return variant_match
    
    # Parse the full name
    parts = full_name.strip().split()
    if len(parts) < 2:
        return pd.DataFrame()
    
    first_name = parts[0]
    last_name = parts[-1]
    
    # Try matching by last name and first initial
    first_initial = first_name[0].upper() + "."
    
    # Build possible abbreviated patterns from ALL nickname variants
    all_first_variants = get_nickname_variants(first_name)
    patterns = []
    for variant_first in all_first_variants:
        vf = variant_first.capitalize()
        patterns.append(f"{vf[0]}. {last_name}")    # C. Warner
        patterns.append(f"{vf[:2]}. {last_name}")    # Ca. Warner / Ch. Warner
        patterns.append(f"{vf[:3]}. {last_name}")    # Cam. Warner / Cha. Warner
    # Deduplicate while preserving order
    seen = set()
    patterns = [p for p in patterns if not (p in seen or seen.add(p))]
    
    # Also handle middle names if present
    if len(parts) > 2:
        middle_parts = " ".join(parts[1:-1])
        for variant_first in all_first_variants:
            patterns.append(f"{variant_first[0].upper()}. {middle_parts} {last_name}")
    
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
    
    # If multiple last name matches, try to narrow by first initial (any variant)
    if not last_name_matches.empty:
        all_initials = set(v[0].upper() for v in all_first_variants)
        initial_matches = last_name_matches[
            last_name_matches["Player_Full"].str.strip().str[0].str.upper().isin(all_initials)
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
def load_team_ladders_from_excel(season: int, last10: bool = False, block: str | None = None) -> pd.DataFrame:
    """Load team ladder data from Excel sheets (legacy method with formulas).
    
    Args:
        season: Season year
        last10: Legacy flag for Last 10 (use block='L10' instead)
        block: One of 'Season', 'L10', 'L5'. Overrides last10 if provided.
    """
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        # Determine block
        _block = block if block else ("L10" if last10 else "Season")
        if _block == "L10":
            sheet_name = f"{season} Ladders (L10)"
        elif _block == "L5":
            sheet_name = f"{season} Ladders (L5)"
        else:
            sheet_name = f"{season} Ladders"
        raw = xl.parse(sheet_name)
        return _normalise_ladder_df(raw)
    except FileNotFoundError:
        st.error(f"❌ Team ratings file not found: {TEAM_FILE}")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Could not load {season} ladder data: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_team_ladders_computed_wrapper(season: int, last10: bool = False, block: str | None = None) -> pd.DataFrame:
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
        _block = block if block else ("L10" if last10 else "Season")
        
        # First try to load from computed CSV files (new sophisticated system)
        # Use block-specific file if available
        if _block == "L10":
            computed_path = Path(__file__).parent / "data" / "computed" / f"team_summary_{season}_L10.csv"
        elif _block == "L5":
            computed_path = Path(__file__).parent / "data" / "computed" / f"team_summary_{season}_L5.csv"
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

            # Map pillar rank columns to the names expected by METRIC_ORDER.
            # CSV has e.g. "Ball Winning Rank" but the UI builds
            # rank_col = f"{metric_col} Rank" → "Ball Winning Ranking Rank".
            # Bridge the gap so every "{Pillar} Ranking Rank" column exists.
            pillar_rank_map = {
                "Ball Winning Ranking Rank": "Ball Winning Rank",
                "Ball Movement Ranking Rank": "Ball Movement Rank",
                "Scoring Ranking Rank": "Scoring Rank",
                "Defence Ranking Rank": "Defence Rank",
                "Pressure Ranking Rank": "Pressure Rank",
            }
            for expected_col, csv_col in pillar_rank_map.items():
                if expected_col not in df.columns and csv_col in df.columns:
                    df[expected_col] = df[csv_col]

            return df
        
        # Fallback to Excel Ladders sheets (which have the ranking data formatted correctly)
        # Use load_team_ladders_from_excel which handles the Ladders sheets properly
        return load_team_ladders_from_excel(season, last10, block=_block)
    except FileNotFoundError:
        st.error(f"❌ Team ratings file not found: {TEAM_FILE}")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Could not compute {season} ladder data: {e}")
        return pd.DataFrame()


def load_team_ladders(season: int, last10: bool = False, block: str | None = None) -> pd.DataFrame:
    """
    Load team ladder data - automatically chooses data source based on USE_COMPUTED_RATINGS flag.
    
    Args:
        season: Season year
        last10: Legacy flag for Last 10 (use block='L10' instead)
        block: One of 'Season', 'L10', 'L5'. Overrides last10 if provided.
    """
    if USE_COMPUTED_RATINGS:
        return load_team_ladders_computed_wrapper(season, last10, block=block)
    else:
        return load_team_ladders_from_excel(season, last10, block=block)


@st.cache_data(show_spinner=False)
def load_afl_ladder_positions() -> pd.DataFrame:
    """Load historical AFL ladder positions - uses master workbook with fallback.
    
    Always supplements with the legacy ladder file so that freshly-scraped
    seasons (e.g. CURRENT_SEASON) are picked up even if the master workbook
    hasn't been rebuilt yet.
    """
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

    df = pd.DataFrame()

    # Try master workbook first
    if DATA_LOADER_AVAILABLE and master_workbook_available():
        df = load_ladder_positions()

    # Always try the legacy ladder file — it may have fresher data
    try:
        legacy_df = pd.read_excel("afl_ladders_2011_2025.xlsx")
        legacy_df["Team"] = legacy_df["Team"].replace(team_name_mapping)
        if df.empty:
            return legacy_df
        # Merge: add any seasons present in legacy but missing from master
        existing_seasons = set(df["Season"].unique())
        new_rows = legacy_df[~legacy_df["Season"].isin(existing_seasons)]
        if not new_rows.empty:
            df = pd.concat([df, new_rows], ignore_index=True)
    except Exception:
        pass

    if df.empty:
        st.warning("Could not load ladder positions from any source.")
    return df


def get_ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------- DATA LOADERS – TEAM SUMMARY ----------------

def _generate_summary_from_raw(season: int) -> pd.DataFrame:
    """
    Generate a team summary DataFrame from raw team stats CSV,
    matching the layout of the legacy Excel Summary sheets so that
    _extract_attribute_structure() can parse it unchanged.

    Layout (matching Excel header=0 default):
      Row 0 (pandas column header) → "SEASON TOTAL" in col-0, rest NaN
      iloc[0] → empty row
      iloc[1] → group header row (Team, Ball Winning, Ball Movement, …)
      iloc[2] → individual stat labels (Post Clear CP Diff, Rank, …)
      iloc[3:] → team data
    """
    from pathlib import Path
    raw_path = Path(__file__).parent / "data" / "raw" / "team" / f"team_stats_{season}.csv"
    if not raw_path.exists():
        return pd.DataFrame()
    raw = pd.read_csv(raw_path)
    raw = raw[raw["Team"].notna()]
    raw = raw[~raw["Team"].astype(str).str.contains("Total|Average|nan", case=False, na=False)]
    raw = raw[~raw["Team"].astype(str).str.match(r"^\d+$")]
    raw["Team"] = raw["Team"].apply(lambda x: normalize_team_name(str(x)) if pd.notna(x) else x)
    raw = raw.reset_index(drop=True)
    n_teams = len(raw)
    if n_teams == 0:
        return pd.DataFrame()

    # Also load computed pillar ratings if available
    comp_path = Path(__file__).parent / "data" / "computed" / f"team_summary_{season}.csv"
    comp = pd.read_csv(comp_path) if comp_path.exists() else pd.DataFrame()
    if not comp.empty:
        comp["Team"] = comp["Team"].apply(lambda x: normalize_team_name(str(x)) if pd.notna(x) else x)

    # ---- Define the groups and their sub-stats ----
    def _safe(series, col, default=0):
        return series.get(col, default) if col in raw.columns else default

    # Each group: (group_name, [(stat_label, compute_fn, higher_is_better), ...])
    # The compute functions take a row (pd.Series) from raw.
    GROUPS = [
        ("Ball Winning", [
            ("Post Clear CP Diff",
             lambda r: r.get("PostClearanceContestedPossessions", 0)
                       - r.get("PostClearanceContestedPossessions_Opposition", 0), True),
            ("Ground Ball Diff",
             lambda r: r.get("GroundBallGets", 0) - r.get("GroundBallGets_Opposition", 0), True),
            ("1st Poss to Clear %",
             lambda r: r.get("FirstPossessionToClearance", 0), True),
            ("Clearance Diff",
             lambda r: r.get("TotalClearances", 0) - r.get("TotalClearances_Opposition", 0), True),
            ("Ball Winning Ranking", None, True),  # pillar rating
        ]),
        ("Ball Movement", [
            ("Def Half to Score %",
             lambda r: r.get("DefHalfToScore", 0), True),
            ("Chain to Score %",
             lambda r: r.get("ChainToScore", 0), True),
            ("D50 to F50 %",
             lambda r: r.get("D50ToF50", 0), True),
            ("Kick Rating",
             lambda r: r.get("KickingEfficiency", 0), True),
            ("Ball Movement Ranking", None, True),
        ]),
        ("Scoring", [
            ("Scores per I50 %",
             lambda r: r.get("ScoringShotsPerInside50", 0), True),
            ("Goals Per I 50 %",
             lambda r: r.get("GoalsPerInside50", 0), True),
            ("Accuracy %",
             lambda r: r.get("GoalAccuracy", 0), True),
            ("+/- Exp Score",
             lambda r: r.get("xScoreRating", 0), True),
            ("Scoring Ranking", None, True),
        ]),
        ("Defence", [
            ("Def Half to Score Ag %",
             lambda r: r.get("DefHalfToScore_Opposition", 0), False),
            ("Chain to Score Ag %",
             lambda r: r.get("ChainToScore_Opposition", 0), False),
            ("D50 to F50 Ag %",
             lambda r: r.get("D50ToF50_Opposition", 0), False),
            ("Goals Per I50 Ag %",
             lambda r: r.get("GoalsPerInside50_Opposition", 0), False),
            ("Defence Ranking", None, True),
        ]),
        ("Pressure", [
            ("Tackle Diff",
             lambda r: r.get("Tackles", 0) - r.get("Tackles_Opposition", 0), True),
            ("F50 Tackles",
             lambda r: r.get("TacklesInside50", 0), True),
            ("Pressure Acts",
             lambda r: r.get("PressureActs", 0), True),
            ("1%'ers",
             lambda r: r.get("OnePercenters", 0), True),
            ("Pressure Ranking", None, True),
        ]),
        ("Health Check", [
            ("Score from Turnover For",
             lambda r: r.get("PointsFromTurnover", 0), True),
            ("Scores from Turnover Ag",
             lambda r: r.get("PointsFromTurnover_Opposition", 0), False),
            ("Scores from Stoppages For",
             lambda r: r.get("PointsFromStoppage", 0), True),
            ("Scores from Stoppage Ag",
             lambda r: r.get("PointsFromStoppage_Opposition", 0), False),
            ("Territory %",
             lambda r: r.get("ForwardHalf", r.get("TimeInPossession", 0)), True),
            ("Post-Clearance CP Diff",
             lambda r: r.get("PostClearanceContestedPossessions_Diff",
                             r.get("PostClearanceContestedPossessions", 0)
                             - r.get("PostClearanceContestedPossessions_Opposition", 0)), True),
            ("Health Check Ranking", None, True),
        ]),
        ("Wheelo Ratings", [
            ("Attack Rating",
             lambda r: r.get("RatingPoints", 0), True),
            ("Defence Rating",
             lambda r: r.get("RatingPoints_Opposition", 0), False),
            ("Overall Rating", None, True),
        ]),
    ]

    # ---- Build values per team for each stat ----
    # For each stat, compute value and rank across teams.
    # "Ranking" stats come from the computed summary CSV.
    stat_results = {}  # stat_label -> [val_per_team]
    rank_results = {}
    for group_name, stats in GROUPS:
        for stat_label, compute_fn, higher_is_better in stats:
            if compute_fn is not None:
                vals = []
                for _, row in raw.iterrows():
                    try:
                        vals.append(float(compute_fn(row)))
                    except Exception:
                        vals.append(np.nan)
                vals_series = pd.Series(vals)
                if higher_is_better:
                    ranks = vals_series.rank(ascending=False, method="min")
                else:
                    ranks = vals_series.rank(ascending=True, method="min")
                stat_results[stat_label] = vals
                rank_results[stat_label] = ranks.tolist()
            else:
                # Pillar ranking from computed summary
                pillar_col = stat_label  # e.g. "Ball Winning Ranking"
                if stat_label == "Overall Rating" and not comp.empty and "Overall Rating" in comp.columns:
                    pillar_col = "Overall Rating"
                if not comp.empty and pillar_col in comp.columns:
                    # Match by team name
                    val_map = dict(zip(comp["Team"], comp[pillar_col]))
                    rank_col = pillar_col.replace(" Ranking", " Rank")
                    if rank_col == "Overall Rating":
                        rank_col = "Overall Rank"
                    rank_map = dict(zip(comp["Team"], comp.get(rank_col, pd.Series()))) if rank_col in comp.columns else {}
                    vals = [val_map.get(t, np.nan) for t in raw["Team"]]
                    ranks = [rank_map.get(t, np.nan) for t in raw["Team"]]
                else:
                    vals = [np.nan] * n_teams
                    ranks = [np.nan] * n_teams
                stat_results[stat_label] = vals
                rank_results[stat_label] = ranks

    # ---- Build the wide DataFrame matching Excel layout ----
    # Calculate total columns needed
    total_cols = 1  # col 0 = Team
    group_starts = {}
    for group_name, stats in GROUPS:
        group_starts[group_name] = total_cols
        for _ in stats:
            total_cols += 2  # value + rank
        total_cols += 1  # gap column between groups

    # Build rows
    n_rows = 3 + n_teams  # header blank + group header + stat labels + team rows
    grid = [[np.nan] * total_cols for _ in range(n_rows)]

    # Row 0 = empty
    # Row 1 = group headers
    grid[1][0] = "Team"
    for group_name, stats in GROUPS:
        grid[1][group_starts[group_name]] = group_name

    # Row 2 = stat labels
    for group_name, stats in GROUPS:
        col = group_starts[group_name]
        for stat_label, _, _ in stats:
            grid[2][col] = stat_label
            grid[2][col + 1] = "Rank"
            col += 2

    # Rows 3+ = team data
    for t_idx in range(n_teams):
        grid[3 + t_idx][0] = raw.iloc[t_idx]["Team"]
        for group_name, stats in GROUPS:
            col = group_starts[group_name]
            for stat_label, _, _ in stats:
                grid[3 + t_idx][col] = stat_results[stat_label][t_idx]
                grid[3 + t_idx][col + 1] = rank_results[stat_label][t_idx]
                col += 2

    # Create DataFrame with first row as columns (matching xl.parse default)
    header_row = ["SEASON TOTAL"] + [np.nan] * (total_cols - 1)
    df_out = pd.DataFrame(grid, columns=header_row)
    return df_out


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
        if year_sheet in xl.sheet_names:
            df = xl.parse(year_sheet)
            df.columns = df.columns.astype(str)
            return df
    except Exception:
        pass

    # For seasons without an Excel sheet (e.g. 2026), generate from raw data
    df = _generate_summary_from_raw(season)
    if not df.empty:
        return df

    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_team_summary_for_year_l10(season: int) -> pd.DataFrame:
    """Load team Last 10 summary for a season."""
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        year_sheet = f"{season} Last 10 Summary"
        df = xl.parse(year_sheet)
        df.columns = df.columns.astype(str)
        return df
    except Exception:
        # Fall back to regular summary if L10 not available
        return load_team_summary_for_year(season)


@st.cache_data(show_spinner=False)
def load_team_summary_for_year_l5(season: int) -> pd.DataFrame:
    """Load team Last 5 summary for a season."""
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        year_sheet = f"{season} Last 5 Summary"
        df = xl.parse(year_sheet)
        df.columns = df.columns.astype(str)
        return df
    except Exception:
        # Fall back to regular summary if L5 not available
        return load_team_summary_for_year(season)


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
        # Always include CURRENT_SEASON even if not in Excel yet
        if CURRENT_SEASON not in seasons:
            seasons.append(CURRENT_SEASON)
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
        return AVAILABLE_SEASONS  # Fall back to config default


def _normalise_rating_column(df: pd.DataFrame) -> pd.DataFrame:
    for cand in RATING_COL_CANDIDATES:
        if cand in df.columns:
            if cand != "RatingPoints_Avg":
                df = df.rename(columns={cand: "RatingPoints_Avg"})
            break
    return df


def _compute_age_decimal_from_dob(df: pd.DataFrame, season: int = None) -> pd.DataFrame:
    """Compute precise Age_Decimal from DOB column.
    
    Overwrites any existing Age_Decimal with DOB-derived values (existing
    values may be truncated integers like 26.0).  Rows without DOB keep
    their original Age_Decimal.
    
    Uses today's date for current season, or mid-season (July 1) for historical.
    """
    if "DOB" not in df.columns:
        return df
    
    from datetime import date
    
    # Reference date: today for current season, July 1 of that year for historical
    if season and season == CURRENT_SEASON:
        ref_date = date.today()
    elif season:
        ref_date = date(season, 7, 1)  # mid-season for historical
    else:
        ref_date = date.today()
    
    ref_ts = pd.Timestamp(ref_date)
    dob_dt = pd.to_datetime(df["DOB"], errors="coerce")
    has_dob = dob_dt.notna()
    computed_age = ((ref_ts - dob_dt).dt.days / 365.25).round(2)
    
    if "Age_Decimal" not in df.columns:
        df["Age_Decimal"] = computed_age
    else:
        df["Age_Decimal"] = pd.to_numeric(df["Age_Decimal"], errors="coerce")
        # Overwrite with DOB-computed value wherever DOB is available
        # (existing Age_Decimal may be truncated integer like 26.0 instead of 26.4)
        df.loc[has_dob, "Age_Decimal"] = computed_age[has_dob]
        # Keep existing Age_Decimal for rows without DOB
    
    # Also update plain Age with the computed decimal where DOB exists
    if "Age" in df.columns:
        df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
        df.loc[has_dob, "Age"] = computed_age[has_dob]
    else:
        df["Age"] = computed_age
    
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
            "Player", "Team", "Age", "Age_Decimal", "DOB", "Position", "Matches",
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
        
        # Compute Age_Decimal from DOB if DOB is available
        df = _compute_age_decimal_from_dob(df, s)
        
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
                "Player", "Team", "Age", "Age_Decimal", "DOB", "Position", "Matches",
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

            # Compute Age_Decimal from DOB if DOB is available
            df = _compute_age_decimal_from_dob(df, s)

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
            st.info("ℹ️ 2026 game data not yet available. Showing 2025 season ratings.")
    
    if df.empty:
        st.warning(f"⚠️ Could not load player data for {season}")
    
    # Enrich generic positions (e.g. 2026 FootyWire data has "Forward" not "Key Forward")
    # by looking up prior-season positions from player_summary.csv
    if not df.empty and "Position" in df.columns:
        _GENERIC_POSITIONS = {"Forward", "Defender", "Midfield", "Ruck",
                              "DefenderForward", "MidfieldForward", "ForwardRuck",
                              "DefenderMidfield", "DefenderRuck"}
        has_generic = df["Position"].isin(_GENERIC_POSITIONS).any()
        if has_generic:
            try:
                summary_path = Path(__file__).parent / "data" / "computed" / "player_summary.csv"
                if summary_path.exists():
                    sum_df = pd.read_csv(summary_path)
                    # Build lookup: player name → position  (use last-name match as fallback)
                    name_to_pos = {}
                    lastname_to_pos = {}
                    if "Player" in sum_df.columns and "Position" in sum_df.columns:
                        for _, r in sum_df.iterrows():
                            pname = str(r["Player"]).strip()
                            pos = str(r["Position"]).strip()
                            if pname and pos and pos not in ("nan", ""):
                                name_to_pos[pname.lower()] = pos
                                parts = pname.split()
                                if len(parts) >= 2:
                                    lastname_to_pos[parts[-1].lower()] = pos
                    
                    def _enrich_position(row):
                        cur_pos = str(row.get("Position", "")).strip()
                        if cur_pos not in _GENERIC_POSITIONS:
                            return cur_pos
                        player = str(row.get("Player", "")).strip()
                        # Exact name match
                        enriched = name_to_pos.get(player.lower())
                        if enriched:
                            return enriched
                        # Last-name match (handles first-name variations)
                        parts = player.split()
                        if len(parts) >= 2:
                            enriched = lastname_to_pos.get(parts[-1].lower())
                            if enriched:
                                return enriched
                        # Map generic FootyWire positions to closest standard position
                        _FW_MAP = {
                            "Forward": "Gen. Forward", "Defender": "Gen. Defender",
                            "Midfield": "Midfielder", "DefenderForward": "Gen. Defender",
                            "MidfieldForward": "Mid-Forward", "ForwardRuck": "Ruck",
                            "DefenderMidfield": "Gen. Defender", "DefenderRuck": "Gen. Defender",
                        }
                        return _FW_MAP.get(cur_pos, cur_pos)
                    
                    df["Position"] = df.apply(_enrich_position, axis=1)
            except Exception:
                pass
    
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
                "Player", "Team", "Age", "Age_Decimal", "DOB", "Position", "Matches",
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
            
            # Resolve player names to canonical form
            try:
                _resolver = _get_name_resolver()
                df["Player"] = _resolver.resolve_df(df, "Player", "Team")
            except Exception:
                pass
            
            # Compute exact Age_Decimal from DOB
            df = _compute_age_decimal_from_dob(df, season)
            
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
            "Player", "Team", "Age", "Age_Decimal", "DOB", "Position", "Matches",
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

        # Resolve player names to canonical form
        try:
            _resolver = _get_name_resolver()
            df["Player"] = _resolver.resolve_df(df, "Player", "Team")
        except Exception:
            pass

        # Compute exact Age_Decimal from DOB
        df = _compute_age_decimal_from_dob(df, season)

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
    Load cached Traits API data, filtered to AFL-only entries.
    Excludes VFL and other non-AFL competition data.
    Returns empty dict if not available.
    """
    if not TRAITS_API_AVAILABLE:
        return {}
    try:
        cache = load_traits_cache()
        all_players = cache.get('players', {})
        # Filter to AFL-only: exclude entries where Team_API contains 'VFL'
        # or Competition is explicitly 'VFL'
        afl_only = {}
        for name, data in all_players.items():
            team = str(data.get('Team_API', ''))
            comp = str(data.get('Competition', ''))
            if 'VFL' in team.upper() or comp.upper() == 'VFL':
                continue
            afl_only[name] = data
        return afl_only
    except Exception:
        return {}


def _extract_surname(name: str) -> str:
    """Extract the surname (last word) from a player name, handling edge cases."""
    parts = str(name).strip().split()
    if not parts:
        return ""
    # Handle hyphenated names properly (e.g. 'Darcy Byrne-Jones')
    return parts[-1].lower()


def _build_surname_index(names_with_teams: list) -> dict:
    """
    Build a (surname, team) -> full_name index for fuzzy matching.
    Only stores entries where the surname is unique within a team,
    to avoid false positives.
    
    Args:
        names_with_teams: list of (player_name, team_name) tuples
    Returns:
        dict of (surname_lower, team_name) -> player_name
    """
    from collections import defaultdict
    # Group by (surname, team)
    surname_team_groups = defaultdict(list)
    for player_name, team_name in names_with_teams:
        surname = _extract_surname(player_name)
        if surname:
            surname_team_groups[(surname, team_name)].append(player_name)
    
    # Only keep unique surname+team combos (no ambiguity)
    index = {}
    for (surname, team), players in surname_team_groups.items():
        if len(players) == 1:
            index[(surname, team)] = players[0]
    return index


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
    
    # Pre-create any missing target columns so API data can be written
    for excel_col in API_TO_EXCEL.values():
        if excel_col not in df.columns:
            df[excel_col] = np.nan
    
    # Build surname+team index for fuzzy matching (fallback for name variants)
    api_surname_index = _build_surname_index([
        (name, TEAM_CODE_TO_NAME.get(data.get('Team_API', ''), data.get('Team_API', '')))
        for name, data in api_cache.items()
    ])
    
    for idx, row in df.iterrows():
        player_name = row.get('Player_Full') or row.get('Player', '')
        team_name = row.get('Team_Full', '')
        
        # Try exact name match first
        api_data = api_cache.get(player_name)
        
        # Fallback: surname + team match (handles Zachary→Zach, Lachlan→Lachie etc.)
        if not api_data:
            surname = _extract_surname(player_name)
            if surname:
                matched_name = api_surname_index.get((surname, team_name))
                if matched_name:
                    api_data = api_cache.get(matched_name)
        
        if not api_data:
            continue
        
        # Update each trait column from API if available
        for api_col, excel_col in API_TO_EXCEL.items():
            if api_col in api_data:
                api_val = api_data[api_col]
                if api_val is not None and not pd.isna(api_val):
                    df.at[idx, excel_col] = api_val
        
        # Map Position_API abbreviation to Position / Position_Full
        pos_api = api_data.get('Position_API')
        if pos_api and (pd.isna(row.get('Position', np.nan)) or str(row.get('Position', '')).strip() == ''):
            df.at[idx, 'Position'] = str(pos_api).strip()
        
        updated_count += 1
    
    return df


def _backfill_from_prior_season(df: pd.DataFrame, current_season: int) -> pd.DataFrame:
    """
    For players in the current season who are missing trait values,
    backfill from the prior season's data.
    
    Matching strategy (in order):
    1. Exact Player_Full match
    2. Surname + team match (handles abbreviated names like 'C. Mills',
       and name variants like 'Mitch' vs 'Mitchell')
    
    This keeps the dashboard populated with last-known ratings until
    new-season API data arrives. Backfilled values are marked via a
    '_traits_backfilled' boolean column for transparency.
    """
    prior_season = current_season - 1
    
    # All trait columns to backfill
    BACKFILL_COLS = [
        "Rating", "Ball Winning", "Ball Use", "Aerial", "Defence",
        "Stoppage", "Contest", "Power", "Receives",
        "Handballing", "Kicking", "Goal Kicking", "Connecting",
        "Marking", "Contested", "Moks", "Ruck",
        "Pressure", "Tackling", "Intercepting", "Neutralise",
    ]
    
    # Identify players missing core trait data
    if "Rating" not in df.columns:
        return df
    missing_mask = df["Rating"].isna()
    if not missing_mask.any():
        return df  # Everyone already has data
    
    # Load prior season CSV
    prior_csv = Path(__file__).parent / "data" / "raw" / "traits" / f"traits_{prior_season}.csv"
    if not prior_csv.exists():
        return df
    
    try:
        df_prior = pd.read_csv(prior_csv)
        df_prior.columns = [str(c).strip() for c in df_prior.columns]
    except Exception:
        return df
    
    # Normalise Player_Full in prior data
    if "Player_Full" not in df_prior.columns:
        if "Player" in df_prior.columns:
            df_prior["Player_Full"] = df_prior["Player"].astype(str).str.strip()
        else:
            return df
    df_prior["Player_Full"] = df_prior["Player_Full"].astype(str).str.strip()
    
    # Map team codes to full names in prior data
    if "Team" in df_prior.columns:
        df_prior["_team_full"] = (
            df_prior["Team"].astype(str).str.strip()
            .map(TEAM_CODE_TO_NAME)
            .fillna(df_prior["Team"].astype(str).str.strip())
        )
    elif "Team_Full" in df_prior.columns:
        df_prior["_team_full"] = df_prior["Team_Full"].astype(str).str.strip()
    else:
        df_prior["_team_full"] = ""
    
    # Resolve prior player names to canonical form so they match current-season
    # names regardless of format differences (abbreviated, nickname variants, etc.)
    try:
        _resolver = _get_name_resolver()
        df_prior["Player_Full"] = _resolver.resolve_df(df_prior, "Player_Full", "_team_full")
    except Exception:
        pass  # Fall through to surname+team matching as safety net
    
    # Build exact lookup: player_name -> {col: value}
    prior_exact = {}
    for _, row in df_prior.iterrows():
        player = row["Player_Full"]
        vals = {}
        for col in BACKFILL_COLS:
            if col in df_prior.columns and pd.notna(row.get(col)):
                vals[col] = row[col]
        if vals:
            prior_exact[player] = vals
    
    # Build surname+team lookup for fuzzy matching
    # (surname_lower, team_full) -> {col: value}
    prior_surname_team = {}
    from collections import defaultdict
    surname_team_groups = defaultdict(list)
    for _, row in df_prior.iterrows():
        surname = _extract_surname(row["Player_Full"])
        team = row["_team_full"]
        if surname and team:
            vals = {}
            for col in BACKFILL_COLS:
                if col in df_prior.columns and pd.notna(row.get(col)):
                    vals[col] = row[col]
            if vals:
                surname_team_groups[(surname, team)].append(vals)
    
    # Only keep unambiguous surname+team matches
    for key, vals_list in surname_team_groups.items():
        if len(vals_list) == 1:
            prior_surname_team[key] = vals_list[0]
    
    if not prior_exact and not prior_surname_team:
        return df
    
    # Mark backfill column
    if "_traits_backfilled" not in df.columns:
        df["_traits_backfilled"] = False
    
    backfilled = 0
    for idx in df.index[missing_mask]:
        player = df.at[idx, "Player_Full"]
        team = df.at[idx, "Team_Full"] if "Team_Full" in df.columns else ""
        
        # Try exact name match first
        prior_vals = prior_exact.get(player)
        
        # Fallback: surname + team match
        if not prior_vals:
            surname = _extract_surname(player)
            if surname and team:
                prior_vals = prior_surname_team.get((surname, team))
        
        if not prior_vals:
            continue
        for col, val in prior_vals.items():
            if col in df.columns and pd.isna(df.at[idx, col]):
                df.at[idx, col] = val
        df.at[idx, "_traits_backfilled"] = True
        backfilled += 1
    
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

        # Canonical name resolution — handles nickname variants (Zachary↔Zach),
        # abbreviated names (A. Cadman → Aaron Cadman), and team-scoped
        # surname matching.  Applied once here so all downstream merges
        # (API enrichment, backfill, traits↔summary join) match automatically.
        try:
            _resolver = _get_name_resolver()
            df["Player_Full"] = _resolver.resolve_df(df, "Player_Full", "Team_Full")
        except Exception:
            pass  # Graceful degradation if resolver fails

        # Position_Full
        if "Position" in df.columns:
            pos_abbrev = df["Position"].astype(str).str.strip()
            df["Position_Full"] = pos_abbrev.map(POSITION_ABBREV_TO_FULL).fillna(pos_abbrev)
        elif "Position_Full" not in df.columns:
            df["Position_Full"] = ""
        df["Position_Full"] = df["Position_Full"].astype(str).str.strip()

        # Map API-format column names to expected names (2026+ CSVs use different schema)
        if "Overall_Rating" in df.columns and "Rating" not in df.columns:
            df["Rating"] = df["Overall_Rating"]

        # Ensure core trait columns always exist (may be NaN until API data arrives)
        for core_col in ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
            if core_col not in df.columns:
                df[core_col] = np.nan

        # Ensure sub-trait columns exist too (needed for detailed breakdowns)
        for sub_col in ["Stoppage", "Contest", "Power", "Receives",
                        "Handballing", "Kicking", "Goal Kicking", "Connecting",
                        "Marking", "Contested", "Moks", "Ruck",
                        "Pressure", "Tackling", "Intercepting", "Neutralise"]:
            if sub_col not in df.columns:
                df[sub_col] = np.nan

        # clean obvious junk strings
        for c in ["Player_Full", "Team_Full", "Position_Full"]:
            df[c] = df[c].replace({"nan": "", "None": ""})

        # Enhance with Traits API data for recent seasons
        if actual_season >= 2025:
            api_cache = _load_traits_api_cache()
            if api_cache:
                df = _enhance_traits_with_api(df, api_cache)

        # Backfill missing trait values from prior season for current season
        # This ensures players who had ratings last year show data until new
        # season values come through from the API
        if actual_season == CURRENT_SEASON:
            df = _backfill_from_prior_season(df, actual_season)

        return df

    try:
        # Try master workbook first
        if DATA_LOADER_AVAILABLE and master_workbook_available():
            df = load_traits_for_season(season)
            if not df.empty:
                return _process_traits_df(df, season)
        
        # Try CSV fallback (e.g. traits_2026.csv)
        csv_path = Path(__file__).parent / "data" / "raw" / "traits" / f"traits_{season}.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                df.columns = [str(c).strip() for c in df.columns]
                if not df.empty:
                    return _process_traits_df(df, season)
            except Exception:
                pass
        
        # Fallback to legacy Excel method
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


# ---------------- WHEELO SUPPLEMENTARY STATS ----------------
# New Equity + xChainScore metrics from Wheelo data – injected into
# Team Breakdown / Team Compare attribute drill-downs alongside Excel sub-metrics.

# Map: attribute_group → list of (display_name, wheelo_col, higher_is_better)
WHEELO_EXTRA_STATS = {
    "Ball Winning": [
        ("Equity Pre-Clearance Diff", "Equity_PreClearance_Diff", True),
        ("Equity Post-Clearance Diff", "Equity_PostClearance_Diff", True),
    ],
    "Ball Movement": [
        ("Equity Ball Use Diff", "Equity_BallUse_Diff", True),
    ],
    "Defence": [
        ("xScore Against", "xScore_Opposition", False),
    ],
    "Health Check": [
        ("xChain Score Stoppage Diff", "xChainScoreFromStoppage_Diff", True),
        ("xChain Score Turnover Diff", "xChainScoreFromTurnover_Diff", True),
    ],
}


_WHEELO_NON_TEAMS = {"Average", "League Average", "Avg", "Total"}


@st.cache_data(show_spinner=False)
def _load_wheelo_team_stats() -> pd.DataFrame:
    """Load Wheelo team data with new Equity/xChainScore columns."""
    try:
        wheelo_path = BASE_DIR / "Wheelo_Team_Data.xlsx"
        if wheelo_path.exists():
            # Try L10 sheet first (most comprehensive), then first sheet
            xls = pd.ExcelFile(wheelo_path)
            for sheet in xls.sheet_names:
                if "L10" in sheet:
                    df = pd.read_excel(wheelo_path, sheet_name=sheet)
                    df.columns = df.columns.astype(str).str.strip()
                    if "Team" in df.columns:
                        df["Team"] = df["Team"].apply(lambda x: normalize_team_name(str(x)) if pd.notna(x) else x)
                        df = df[~df["Team"].isin(_WHEELO_NON_TEAMS)]
                    return df
            # Fallback to first sheet
            df = pd.read_excel(wheelo_path, sheet_name=0)
            df.columns = df.columns.astype(str).str.strip()
            if "Team" in df.columns:
                df["Team"] = df["Team"].apply(lambda x: normalize_team_name(str(x)) if pd.notna(x) else x)
                df = df[~df["Team"].isin(_WHEELO_NON_TEAMS)]
            return df
    except Exception:
        pass
    return pd.DataFrame()


def _get_wheelo_stat_distribution(stat_display_name: str, wheelo_col: str, higher_is_better: bool = True) -> pd.DataFrame:
    """Get stat distribution from Wheelo data for a supplementary metric."""
    df = _load_wheelo_team_stats()
    if df.empty or wheelo_col not in df.columns:
        return pd.DataFrame(columns=["Team", "Value", "Rank"])

    result = df[["Team", wheelo_col]].copy()
    result.columns = ["Team", "Value"]
    result["Value"] = pd.to_numeric(result["Value"], errors="coerce")
    result = result.dropna(subset=["Value"]).reset_index(drop=True)
    result["Rank"] = result["Value"].rank(ascending=not higher_is_better, method="min").astype(int)
    return result


# ---------------- ATTRIBUTE STRUCTURE HELPERS (TEAM SUMMARY) ----------------
def _extract_attribute_structure(summary_df: pd.DataFrame, attribute_name: str):
    """
    Reads group header row and stat row to find columns for one attribute group.
    Returns list of dicts:
      { "stat_name": ..., "value_col": int, "rank_col": int | None }
    Also appends Wheelo supplementary stats (Equity, xChainScore) if available
    for the requested attribute group.
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

    # ---- Move the pillar Ranking stat to the front (e.g. "Ball Winning Ranking") ----
    ranking_idx = next(
        (i for i, b in enumerate(blocks) if b["stat_name"].endswith("Ranking")),
        None,
    )
    if ranking_idx is not None and ranking_idx > 0:
        blocks.insert(0, blocks.pop(ranking_idx))

    # ---- Append Wheelo supplementary stats for this attribute group ----
    wheelo_extras = WHEELO_EXTRA_STATS.get(attribute_name, [])
    wheelo_df = _load_wheelo_team_stats() if wheelo_extras else pd.DataFrame()
    for display_name, wheelo_col, higher_is_better in wheelo_extras:
        if not wheelo_df.empty and wheelo_col in wheelo_df.columns:
            blocks.append({
                "stat_name": display_name,
                "source": "wheelo",
                "wheelo_col": wheelo_col,
                "higher_is_better": higher_is_better,
            })

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

    # ---- Wheelo-sourced supplementary stat ----
    if block_info.get("source") == "wheelo":
        return _get_wheelo_stat_distribution(
            block_info["stat_name"],
            block_info["wheelo_col"],
            block_info.get("higher_is_better", True),
        )

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
    """Load player photo guide and create mapping from various name formats to full names.
    
    Also registers nickname variants (e.g. 'Cameron Rayner' -> guide entry 'Cam Rayner')
    using the centralized PLAYER_NICKNAME_MAP from config.constants.
    """
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
                
                # ── Nickname variants ──
                # E.g. if guide has "Cam Rayner", also register "Cameron Rayner" → "Cam Rayner"
                for variant_first in get_nickname_variants(first_name):
                    variant_name = f"{variant_first.capitalize()} {surname}"
                    if variant_name != full_name:
                        name_map[variant_name] = full_name
                        name_map[variant_name.lower()] = full_name
                        # Also register variant initial
                        variant_initial = f"{variant_first[0].upper()}. {surname}"
                        if variant_initial not in name_map:
                            name_map[variant_initial] = full_name
                            name_map[variant_initial.lower()] = full_name
                        # Team-specific variant mapping
                        variant_team_key = f"{team}_{variant_name.strip().lower()}"
                        team_player_map[variant_team_key] = full_name
        
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
    
    # Fallback: try nickname variants of the filename directly
    # E.g. "Cameron Rayner" → try "cam_rayner.png" even if not in photo guide
    for variant_name in build_player_name_variants(normalized_name):
        variant_base = variant_name.lower().replace(" ", "_")
        if variant_base == base:
            continue  # already tried
        for ext in (".png", ".jpg", ".jpeg"):
            path = str(BASE_DIR / PLAYER_PHOTO_FOLDER / (variant_base + ext))
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
        container.markdown(f"<div style='width:{size}px;height:{size}px;background:#333;display:flex;align-items:center;justify-content:center;border-radius:8px;'><span style='font-size:48px;opacity:0.3;'>{_svg_inline('person', 20)}</span></div>", unsafe_allow_html=True)
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
    Returns all years that have team summary data available.
    Checks: 1) computed CSV files, 2) '<YEAR> Summary' sheets in TEAM_FILE.
    Falls back to TEAM_SEASONS if nothing found.
    """
    years = set()
    
    # Check for computed CSV files (new pipeline)
    computed_dir = Path(__file__).parent / "data" / "computed"
    if computed_dir.exists():
        for f in computed_dir.glob("team_summary_*.csv"):
            stem = f.stem  # e.g. 'team_summary_2026' or 'team_summary_2025_L10'
            parts = stem.replace("team_summary_", "").split("_")
            if parts[0].isdigit():
                years.add(int(parts[0]))
    
    # Also check Excel sheets (legacy)
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        for sheet in xl.sheet_names:
            s = str(sheet).strip()
            if s.endswith(" Summary"):
                head = s.split()[0]
                if head.isdigit():
                    years.add(int(head))
    except Exception:
        pass
    
    years = sorted(years, reverse=True)
    return years if years else sorted(set(TEAM_SEASONS), reverse=True)


@st.cache_data(show_spinner=False)
def get_l10_available_years() -> set[int]:
    """Return set of years that have Last 10 data (computed CSV or Excel sheet)."""
    l10_years: set[int] = set()
    computed_dir = Path(__file__).parent / "data" / "computed"
    if computed_dir.exists():
        for f in computed_dir.glob("team_summary_*_L10.csv"):
            parts = f.stem.replace("team_summary_", "").split("_")
            if parts[0].isdigit():
                l10_years.add(int(parts[0]))
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        for sheet in xl.sheet_names:
            s = str(sheet).strip()
            if s.endswith(" Last 10 Summary"):
                head = s.split()[0]
                if head.isdigit():
                    l10_years.add(int(head))
    except Exception:
        pass
    return l10_years


@st.cache_data(show_spinner=False)
def get_l5_available_years() -> set[int]:
    """Return set of years that have Last 5 data (computed CSV or Excel sheet)."""
    l5_years: set[int] = set()
    computed_dir = Path(__file__).parent / "data" / "computed"
    if computed_dir.exists():
        for f in computed_dir.glob("team_summary_*_L5.csv"):
            parts = f.stem.replace("team_summary_", "").split("_")
            if parts[0].isdigit():
                l5_years.add(int(parts[0]))
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        for sheet in xl.sheet_names:
            s = str(sheet).strip()
            if s.endswith(" Last 5 Summary"):
                head = s.split()[0]
                if head.isdigit():
                    l5_years.add(int(head))
    except Exception:
        pass
    return l5_years


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

    # Sort by highest rated player first within each grid cell
    # Look for matches column (used later for rankings, not for grid ordering)
    matches_col_display = None
    for col_name in ['Matches', f'{CURRENT_SEASON} Matches', '2025 Matches', 'Total Matches']:
        if col_name in df_team.columns:
            matches_col_display = col_name
            break
    
    # Cap matches at 23 (regular season) to avoid over-rating players who played finals
    MAX_MATCHES_FOR_RATING = 23

    # Sort grid display by raw rating (highest rated player first)
    df_team = df_team.copy()
    if rating_col in df_team.columns:
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
        
        # Find matches column - prefer one with meaningful data (non-zero sum)
        matches_col = None
        _matches_candidates = [f'{CURRENT_SEASON} Matches', '2025 Matches', 'Total Matches', 'Matches']
        for col_name in _matches_candidates:
            if col_name in all_teams_df.columns:
                _m = pd.to_numeric(all_teams_df[col_name], errors="coerce").fillna(0)
                if _m.sum() > 0:
                    matches_col = col_name
                    break
        # If no column had meaningful data, still try any that exists
        if matches_col is None:
            for col_name in _matches_candidates:
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
    1. Position-based age-performance curve (polynomial fit on league data)
    2. Player's historical rating trend
    3. Current rating level relative to the curve

    Returns DataFrame with Year, Predicted_Rating, Upper_Band, Lower_Band
    """
    import numpy as np

    # ---- Sanitise inputs ----
    current_age = float(current_age) if pd.notna(current_age) else 25.0
    current_rating = float(current_rating) if pd.notna(current_rating) else 0.0

    # If current rating is 0 (no games this season) or very low, fall back to
    # the most recent meaningful historical rating so the projection isn't flat.
    effective_rating = current_rating
    hist_nonzero = [r for r in historical_ratings if r and r > 0]
    if effective_rating <= 0 and hist_nonzero:
        # Use the mean of the last 3 meaningful seasons
        effective_rating = float(np.mean(hist_nonzero[-3:]))
    elif effective_rating <= 0:
        effective_rating = 8.0  # league-average fallback

    # ---- Step 1: Build position-specific age-performance curve ----
    normalized_pos = "Midfielder"
    if position and isinstance(position, str):
        normalized_pos = map_position_to_depth(position)
        position_players = all_players_df[
            all_players_df["Position"].apply(
                lambda p: map_position_to_depth(p) if pd.notna(p) else ""
            ) == normalized_pos
        ].copy()
    else:
        position_players = all_players_df.copy()

    if position_players.empty:
        position_players = all_players_df.copy()

    position_players["Age"] = pd.to_numeric(position_players["Age"], errors="coerce")
    position_players["RatingPoints_Avg"] = pd.to_numeric(
        position_players["RatingPoints_Avg"], errors="coerce"
    )
    # Exclude zero-rating rows (players with no games) from the curve
    position_players = position_players[position_players["RatingPoints_Avg"] > 0]
    position_players = position_players.dropna(subset=["Age", "RatingPoints_Avg"])

    # ---- Step 2: Fit age-performance curve ----
    poly = None
    if len(position_players) >= 20:
        age_stats = (
            position_players.groupby(pd.cut(position_players["Age"], bins=20))
            .agg({"RatingPoints_Avg": ["median", "count"]})
            .reset_index()
        )
        age_stats.columns = ["Age_Bin", "Median_Rating", "Count"]
        age_stats["Age"] = age_stats["Age_Bin"].apply(
            lambda x: x.mid if pd.notna(x) else None
        )
        age_stats = age_stats.dropna(subset=["Age", "Median_Rating"])
        age_stats = age_stats[age_stats["Count"] >= 3]

        if len(age_stats) >= 3:
            try:
                coeffs = np.polyfit(
                    age_stats["Age"].astype(float),
                    age_stats["Median_Rating"].astype(float),
                    2,
                )
                poly = np.poly1d(coeffs)
            except Exception:
                poly = None

    # ---- Step 3: Calculate year-on-year change factors from the curve ----
    # The poly curve tells us the *shape* of how performance evolves with age.
    # We use relative change from the curve (not absolute values) to project
    # the player's individual trajectory.
    peak_age_map = {
        "Midfielder": 28, "Wing": 27, "Ruck": 29,
        "Key Forward": 29, "Gen. Forward": 28, "Mid-Forward": 28,
        "Key Defender": 29, "Gen. Defender": 28,
    }
    peak_age = peak_age_map.get(normalized_pos, 28)

    # ---- Step 4: Historical trend (per-season change) ----
    trend_per_year = 0.0
    if len(hist_nonzero) >= 2:
        # Use last 4 seasons max for trend
        recent = hist_nonzero[-4:]
        trend_per_year = (recent[-1] - recent[0]) / (len(recent) - 1)
    # Clamp trend to avoid wild extrapolation (max ±15% of effective rating/year)
    max_trend = effective_rating * 0.15
    trend_per_year = max(-max_trend, min(trend_per_year, max_trend))

    # ---- Step 5: Generate projections ----
    years = []
    predictions = []
    upper_bands = []
    lower_bands = []

    prev_rating = effective_rating

    for year_offset in range(projection_years + 1):
        future_age = current_age + year_offset
        future_year = current_season + year_offset

        if year_offset == 0:
            predicted_rating = effective_rating
        else:
            # --- Age-curve factor ---
            # How much does the curve change from this age to next?
            if poly is not None:
                curve_now = float(poly(future_age - 1))
                curve_next = float(poly(future_age))
                if curve_now > 0:
                    age_factor = curve_next / curve_now  # e.g. 0.97 for decline
                else:
                    age_factor = 1.0
            else:
                # Fallback: use simple peak-age based model
                if future_age <= peak_age:
                    age_factor = 1.0 + 0.02 * (1 - (future_age - peak_age) / 8)
                else:
                    years_past = future_age - peak_age
                    age_factor = 1.0 - 0.02 * years_past - 0.003 * (years_past ** 2)
                age_factor = max(age_factor, 0.90)

            # --- Blend: 70% age curve + 30% individual trend ---
            curve_prediction = prev_rating * age_factor
            trend_prediction = prev_rating + trend_per_year
            predicted_rating = 0.7 * curve_prediction + 0.3 * trend_prediction

            # Decay trend influence over time (less reliable further out)
            trend_per_year *= 0.6

        # Floor — rating can't go below 2
        predicted_rating = max(predicted_rating, 2.0)

        # Confidence bands widen with projection distance + age
        dynamic_confidence = confidence_band * (1 + 0.08 * year_offset)
        if future_age > 30:
            dynamic_confidence *= 1.15
        upper = predicted_rating * (1 + dynamic_confidence)
        lower = max(predicted_rating * (1 - dynamic_confidence), 1.0)

        years.append(future_year)
        predictions.append(round(predicted_rating, 2))
        upper_bands.append(round(upper, 2))
        lower_bands.append(round(lower, 2))
        prev_rating = predicted_rating

    return pd.DataFrame({
        "Year": years,
        "Predicted_Rating": predictions,
        "Upper_Band": upper_bands,
        "Lower_Band": lower_bands,
    })
    


# ---------------- PAGE NAV ----------------

# Define page groups for organized navigation (AMS categories)
PAGE_GROUPS = {
    "Home": ["Home"],
    "List Management & Recruiting": ["Club List", "Depth Chart", "Team Age Breakdown", "List Ladder", "Team List Summary", "List Breakdown - Traits", "Contract Status"],
    "Team Performance": ["Overview", "Team Breakdown", "Team Compare", "Game Predictor", "Game Model Scorecard", "Best 23"],
    "Individual Performance": ["Player Profile", "IDP", "Custom Player Comparison", "Player Rating Matrix"],
}

# AMS category metadata for Home page
AMS_CATEGORIES = {
    "List Management & Recruiting": {
        "icon": _svg_inline("list", 28),
        "description": "Squad composition, depth analysis & recruiting tools",
        "colour": "#1B5E20",
    },
    "Team Performance": {
        "icon": _svg_inline("chart_bar", 28),
        "description": "Team analytics, game models & tactical insights",
        "colour": "#0D47A1",
    },
    "Individual Performance": {
        "icon": _svg_inline("person", 28),
        "description": "Player profiles, traits analysis & comparisons",
        "colour": "#4A148C",
    },
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
if "home_category" not in st.session_state:
    st.session_state.home_category = None

def render_grouped_navigation():
    """Render grouped sidebar navigation with refined monochrome styling."""
    selected = st.session_state.selected_page
    
    # ── Monochrome accent per section ──
    SECTION_STYLES = {
        "List Management & Recruiting": {
            "accent": "#9E9E9E",        # warm grey
            "bg":     "rgba(158,158,158,0.06)",
            "icon":   "list",
        },
        "Team Performance": {
            "accent": "#B0BEC5",        # blue-grey
            "bg":     "rgba(176,190,197,0.06)",
            "icon":   "chart_bar",
        },
        "Individual Performance": {
            "accent": "#BDBDBD",        # light grey
            "bg":     "rgba(189,189,189,0.06)",
            "icon":   "person",
        },
    }

    # ── CSS ── logo container + navigation styling ──
    st.markdown("""
    <style>
    /* Fixed logo container at top of sidebar */
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
        border-top: 1px solid rgba(255,255,255,0.12);
    }
    /* Pad sidebar content below fixed logo */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        padding-top: 260px !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        overflow-y: auto;
        padding-top: 0;
    }

    /* ── Section header ── */
    .nav-section-hdr {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 10px 4px 10px;
        margin: 14px 0 4px 0;
        font-size: 0.7em;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        border-top: 1px solid rgba(255,255,255,0.06);
    }
    .nav-section-hdr svg { flex-shrink: 0; }

    /* ── Page link buttons – override Streamlit defaults ── */
    [data-testid="stSidebar"] button[kind="secondary"] {
        background: transparent !important;
        border: none !important;
        color: rgba(255,255,255,0.55) !important;
        font-size: 0.85em !important;
        font-weight: 500 !important;
        padding: 5px 10px !important;
        justify-content: flex-start !important;
        text-align: left !important;
        border-radius: 6px !important;
        transition: background 0.15s, color 0.15s !important;
        margin: 0 !important;
        min-height: 0 !important;
        line-height: 1.4 !important;
    }
    [data-testid="stSidebar"] button[kind="secondary"] p,
    [data-testid="stSidebar"] button[kind="secondary"] div,
    [data-testid="stSidebar"] button[kind="secondary"] span {
        text-align: left !important;
        width: 100% !important;
    }
    [data-testid="stSidebar"] button[kind="secondary"]:hover {
        background: rgba(255,255,255,0.06) !important;
        color: rgba(255,255,255,0.85) !important;
    }
    [data-testid="stSidebar"] button[kind="primary"] {
        background: rgba(255,255,255,0.08) !important;
        border: none !important;
        border-left: 2px solid rgba(255,255,255,0.5) !important;
        color: #FFFFFF !important;
        font-size: 0.85em !important;
        font-weight: 600 !important;
        padding: 5px 10px !important;
        justify-content: flex-start !important;
        text-align: left !important;
        border-radius: 0 6px 6px 0 !important;
        margin: 0 !important;
        min-height: 0 !important;
        line-height: 1.4 !important;
    }
    [data-testid="stSidebar"] button[kind="primary"] p,
    [data-testid="stSidebar"] button[kind="primary"] div,
    [data-testid="stSidebar"] button[kind="primary"] span {
        text-align: left !important;
        width: 100% !important;
    }

    /* ── Search input ── */
    [data-testid="stSidebar"] .stTextInput input {
        font-size: 0.82em !important;
        padding: 6px 10px !important;
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 8px !important;
    }

    /* ── Hide icon-wrap spacers ── */
    .nav-icon-wrap { display: none !important; }

    /* ── Favourites / Recent labels ── */
    .sidebar-minor-hdr {
        font-size: 0.68em;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: rgba(255,255,255,0.35);
        padding: 8px 10px 2px 10px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # ── Logo ──
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

    new_page = selected
    
    # ── Player Search ──
    st.sidebar.markdown(
        f"<div style='display:flex;align-items:center;gap:6px;padding:0 10px;'>"
        f"{_svg_inline('search', 14, '#888')}"
        f"<span style='font-size:0.72em;font-weight:700;letter-spacing:0.08em;"
        f"text-transform:uppercase;color:rgba(255,255,255,0.4);'>Player Search</span></div>",
        unsafe_allow_html=True,
    )
    
    @st.cache_data(show_spinner=False)
    def get_all_players_for_search(season: int):
        """Get all players for search functionality.
        
        Prefers load_full_squad (includes all listed players) over
        load_players (only those with game stats).  This ensures players
        drafted for the upcoming season are searchable even before games
        are played.
        """
        try:
            # Try full squad first (has all listed players for the season)
            players = load_full_squad(season)
            # Fallback to rated players if squad is empty
            if players is None or players.empty:
                players = load_players(season)
            if players is None or players.empty:
                return []
            player_list = []
            seen = set()
            for _, row in players.iterrows():
                player = str(row.get("Player", "")).strip()
                team = str(row.get("Team", "")).strip()
                if player and team and player != "nan" and team != "nan":
                    key = f"{player}|{team}"
                    if key not in seen:
                        seen.add(key)
                        player_list.append({"player": player, "team": team, "display": f"{player} ({team})"})
            return sorted(player_list, key=lambda x: x["player"])
        except Exception:
            return []

    all_players_search = get_all_players_for_search(CURRENT_SEASON)
    
    search_query = st.sidebar.text_input(
        "Search for a player...",
        key="global_player_search",
        placeholder="Type player name...",
        label_visibility="collapsed",
    )
    
    if search_query and len(search_query) >= 2:
        matches = [p for p in all_players_search if search_query.lower() in p["player"].lower()][:5]
        if matches:
            for match in matches:
                col1, col2 = st.sidebar.columns([4, 1])
                with col1:
                    if st.button(f"{match['player']}", key=f"search_{match['player']}_{match['team']}", use_container_width=True):
                        st.session_state.selected_player_search = match['player']
                        st.session_state.selected_team_search = match['team']
                        st.session_state.default_team = match['team']
                        st.session_state.selected_page = "Player Profile"
                        st.session_state.page_override = True
                        # Clear stale widget keys so selectboxes respect new defaults
                        for _k in ("pp_team", "pp_player"):
                            st.session_state.pop(_k, None)
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
    
    # thin divider
    st.sidebar.markdown("<div style='border-top:1px solid rgba(255,255,255,0.06);margin:8px 0;'></div>", unsafe_allow_html=True)
    
    # ── Home button ──
    home_selected = selected == "Home"
    if st.sidebar.button(
        f"{'◆' if home_selected else '◇'}  Home",
        key="nav_Home",
        use_container_width=True,
        type="primary" if home_selected else "secondary",
    ):
        new_page = "Home"
        st.session_state.selected_page = "Home"
        st.rerun()
    
    # ── Section groups ──
    for group_name, pages in PAGE_GROUPS.items():
        if group_name == "Home":
            continue
            
        style = SECTION_STYLES.get(group_name, {"accent": "#999", "bg": "rgba(153,153,153,0.06)", "icon": "folder"})
        accent = style["accent"]
        section_icon = _svg_inline(style["icon"], 13, accent)
        
        st.sidebar.markdown(
            f"<div class='nav-section-hdr' style='color:{accent};'>"
            f"{section_icon}{group_name}</div>",
            unsafe_allow_html=True,
        )
        
        for page_name in pages:
            is_selected = page_name == selected
            
            if st.sidebar.button(
                page_name,
                key=f"nav_{page_name}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
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
    st.sidebar.markdown("<div style='border-top:1px solid rgba(255,255,255,0.06);margin:10px 0 4px 0;'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(
        f"<div class='sidebar-minor-hdr'>{_svg_inline('favorite', 12, '#888')} Favorites</div>",
        unsafe_allow_html=True,
    )
    
    # Favorite Teams
    if st.session_state.favorite_teams:
        for team in sorted(st.session_state.favorite_teams):
            col1, col2 = st.sidebar.columns([4, 1])
            with col1:
                if st.button(f"{team}", key=f"fav_team_{team}", use_container_width=True):
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
                    if st.button(f"{player}", key=f"fav_player_{player_key}", use_container_width=True):
                        st.session_state.selected_player_search = player
                        st.session_state.selected_team_search = team
                        st.session_state.default_team = team
                        st.session_state.selected_page = "Player Profile"
                        st.session_state.page_override = True
                        # Clear stale widget keys so selectboxes respect new defaults
                        for _k in ("pp_team", "pp_player"):
                            st.session_state.pop(_k, None)
                        add_to_recent_views("player", player, team, "Player Profile")
                        st.rerun()
                with col2:
                    if st.button("✕", key=f"unfav_player_{player_key}"):
                        toggle_favorite_player(player, team)
                        st.rerun()

# --- Recent Activity Section ---
if st.session_state.recent_views:
    st.sidebar.markdown("<div style='border-top:1px solid rgba(255,255,255,0.06);margin:10px 0 4px 0;'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(
        f"<div class='sidebar-minor-hdr'>{_svg_inline('chart_bar', 12, '#888')} Recent</div>",
        unsafe_allow_html=True,
    )
    for item in st.session_state.recent_views[:5]:
        label = item["name"]
        if st.sidebar.button(f"{label}", key=f"recent_{item['type']}_{item['name']}_{item.get('team', '')}", use_container_width=True):
            if item["type"] == "team":
                st.session_state.default_team = item["name"]
                st.session_state.selected_page = item.get("page", "Team Breakdown")
            else:
                st.session_state.selected_player_search = item["name"]
                st.session_state.selected_team_search = item.get("team", "")
                st.session_state.default_team = item.get("team", "")
                st.session_state.selected_page = item.get("page", "Player Profile")
            st.session_state.page_override = True
            # Clear stale widget keys so selectboxes respect new defaults
            for _k in ("pp_team", "pp_player"):
                st.session_state.pop(_k, None)
            st.rerun()

# --- Comparison History ---
if st.session_state.comparison_history:
    st.sidebar.markdown("<div style='border-top:1px solid rgba(255,255,255,0.06);margin:10px 0 4px 0;'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(
        f"<div class='sidebar-minor-hdr'>{_svg_inline('balance', 12, '#888')} Recent Comparisons</div>",
        unsafe_allow_html=True,
    )
    for comp in st.session_state.comparison_history[:3]:
        label = f"{comp['team1']} vs {comp['team2']}"
        page_target = "Team Compare" if comp["type"] == "team" else "Best 23"
        if st.sidebar.button(f"{label}", key=f"comp_{comp['team1']}_{comp['team2']}", use_container_width=True):
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

    # ----- Resolve team branding colours -----
    _branded_team = st.session_state.get("default_team", None)
    _palette = TEAM_COLOUR_PALETTES.get(_branded_team, {}) if _branded_team else {}
    _pri = _palette.get("primary", "#FFFFFF")
    _sec = _palette.get("secondary", "#FFFFFF")
    _ter = _palette.get("tertiary", "#888888")
    _has_brand = bool(_branded_team and _palette)

    # ----- Team watermark logo (subtle background) -----
    _watermark_b64 = ""
    if _has_brand:
        _team_code = TEAM_CODE_MAP.get(_branded_team, _branded_team.lower().replace(" ", ""))
        _wm_path = f"{LOGO_FOLDER}/{_team_code}.png"
        if os.path.exists(_wm_path):
            import base64 as _b64
            with open(_wm_path, "rb") as _wf:
                _watermark_b64 = _b64.b64encode(_wf.read()).decode()

    # ----- Inject dynamic team-branded CSS -----
    _watermark_css = ""
    if _watermark_b64:
        _watermark_css = f"""
        .block-container {{
            position: relative;
        }}
        .block-container::before {{
            content: '';
            position: fixed;
            top: 50%;
            left: 55%;
            transform: translate(-50%, -50%);
            width: 520px;
            height: 520px;
            background-image: url('data:image/png;base64,{_watermark_b64}');
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            opacity: 0.035;
            pointer-events: none;
            z-index: 0;
        }}
        """

    _brand_border = "1px solid rgba(255,255,255,0.12)"
    _brand_glow = "none"
    _accent_gradient = "linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent)"

    st.markdown(f"""
    <style>
    {_watermark_css}
    .ams-card {{
        border: {_brand_border};
        border-radius: 14px;
        padding: 28px 20px 18px 20px;
        text-align: center;
        cursor: pointer;
        transition: all 0.25s ease;
        height: 100%;
        min-height: 160px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        box-shadow: {_brand_glow};
    }}
    .ams-card:hover {{
        transform: translateY(-4px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.35);
        border-color: rgba(255,255,255,0.3);
    }}
    .ams-card-active {{
        border: 2px solid rgba(255,255,255,0.6) !important;
        box-shadow: 0 4px 20px rgba(255,255,255,0.12);
    }}
    .ams-card .ams-icon {{
        font-size: 2.4em;
        margin-bottom: 10px;
    }}
    .ams-card .ams-title {{
        font-size: 1.05em;
        font-weight: 700;
        color: #FFFFFF;
        margin-bottom: 6px;
    }}
    .ams-card .ams-desc {{
        font-size: 0.78em;
        color: rgba(255,255,255,0.55);
        line-height: 1.3;
    }}
    /* Category card container - button follows card visually */
    .ams-cat-select {{
        margin-top: -6px;
    }}
    .ams-cat-select [data-testid="stButton"] > button {{
        background: transparent !important;
        border: none !important;
        border-top: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 0 0 14px 14px !important;
        padding: 8px 12px !important;
        min-height: 36px !important;
        height: 36px !important;
        color: rgba(255,255,255,0.45) !important;
        font-size: 0.72em !important;
        font-weight: 500 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        transition: all 0.2s ease !important;
    }}
    .ams-cat-select [data-testid="stButton"] > button:hover {{
        color: rgba(255,255,255,0.85) !important;
        background: rgba(255,255,255,0.04) !important;
    }}
    .ams-cat-select [data-testid="stButton"] > button:focus {{
        box-shadow: none !important;
    }}
    .ams-dash-card {{
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 12px;
        padding: 18px 18px 14px 18px;
        text-align: left;
        transition: all 0.22s ease;
        margin-bottom: 2px;
        display: flex;
        align-items: center;
        gap: 14px;
        background: linear-gradient(135deg, rgba(255,255,255,0.02), rgba(255,255,255,0.00));
    }}
    .ams-dash-card:hover {{
        background: rgba(255,255,255,0.04);
        border-color: rgba(255,255,255,0.25);
        transform: translateX(3px);
    }}
    .ams-dash-icon {{
        width: 42px;
        height: 42px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.3em;
        flex-shrink: 0;
    }}
    .ams-dash-info .ams-dash-title {{
        font-weight: 700;
        font-size: 0.92em;
        color: #FFFFFF;
        margin-bottom: 2px;
    }}
    .ams-dash-info .ams-dash-desc {{
        font-size: 0.74em;
        color: rgba(255,255,255,0.42);
        line-height: 1.2;
    }}
    .ams-section-divider {{
        height: 1px;
        background: {_accent_gradient};
        margin: 22px 0;
    }}
    .ams-team-banner {{
        text-align: center;
        padding: 6px 0 0 0;
    }}
    .ams-team-banner .team-name {{
        font-weight: 800;
        font-size: 1.15em;
        letter-spacing: 0.04em;
    }}
    </style>
    """, unsafe_allow_html=True)

    # ----- Logo -----
    logo_path = "team_logos/Logo Transparent.png"

    if os.path.exists(logo_path):
        import base64
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        st.markdown(f"""
            <div style='display: flex; justify-content: center; margin-bottom: 0px;'>
                <img src='data:image/png;base64,{logo_b64}' style='width: 280px; filter: drop-shadow(0 0 20px rgba(255,255,255,0.4)) drop-shadow(0 4px 12px rgba(0,0,0,0.5));'>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div style='text-align: center; color: #999;'>{_svg_inline('stadium', 80)}</div>",
            unsafe_allow_html=True
        )

    # ----- Title -----
    _title_colour = "#FFFFFF"
    st.markdown(
        f"""
        <h1 style='text-align: center; font-size: 2.2em; margin-top: 5px; margin-bottom: 0px; letter-spacing: 0.02em; color: {_title_colour};'>
            Athlete Management System
        </h1>
        <p style='text-align: center; color: rgba(255,255,255,0.45); font-size: 0.95em; margin-top: 2px; margin-bottom: 20px;'>
            FutureEdge Performance
        </p>
        """,
        unsafe_allow_html=True
    )

    # ----- Team Selector -----
    all_teams = [
        "Adelaide", "Brisbane", "Carlton", "Collingwood", "Essendon",
        "Fremantle", "Geelong", "Gold Coast", "GWS Giants",
        "Hawthorn", "Melbourne", "North Melbourne", "Port Adelaide",
        "Richmond", "St Kilda", "Sydney", "West Coast", "Western Bulldogs"
    ]

    # Determine current default_team index
    current_default = st.session_state.get("default_team", None)
    team_options = ["Select a team..."] + all_teams
    default_idx = 0
    if current_default and current_default in all_teams:
        default_idx = all_teams.index(current_default) + 1

    col_pad_l, col_sel, col_pad_r = st.columns([1, 2, 1])
    with col_sel:
        selected_team = st.selectbox(
            "Select Your Team",
            options=team_options,
            index=default_idx,
            key="home_team_selector",
            label_visibility="collapsed",
            placeholder="Select a team...",
        )
        if selected_team and selected_team != "Select a team...":
            st.session_state.default_team = selected_team

    # Show selected team name with branded accent line (logo is the watermark)
    if st.session_state.get("default_team"):
        team = st.session_state.default_team
        st.markdown(
            f"""<div class='ams-team-banner'>
                <div class='team-name' style='color: #FFFFFF;'>{team}</div>
                <div style='height: 3px; margin: 6px auto 0 auto; width: 60px; border-radius: 2px;
                     background: linear-gradient(90deg, rgba(255,255,255,0.6), rgba(255,255,255,0.2));'></div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("<div class='ams-section-divider'></div>", unsafe_allow_html=True)

    # ----- AMS Category Buttons -----
    cat_names = list(AMS_CATEGORIES.keys())
    cat_cols = st.columns(3, gap="medium")

    for idx, cat_name in enumerate(cat_names):
        meta = AMS_CATEGORIES[cat_name]
        with cat_cols[idx]:
            is_active = st.session_state.home_category == cat_name
            active_cls = " ams-card-active" if is_active else ""
            cat_bg = meta["colour"]
            card_gradient = f"linear-gradient(135deg, {cat_bg}44, {cat_bg}22)"
            border_extra = ""
            # Visual card + select button below
            st.markdown(f"""
                <div class='ams-card{active_cls}' style='background: {card_gradient}; {border_extra}'>
                    <div class='ams-icon'>{meta["icon"]}</div>
                    <div class='ams-title'>{cat_name}</div>
                    <div class='ams-desc'>{meta["description"]}</div>
                </div>
            """, unsafe_allow_html=True)
            st.markdown("<div class='ams-cat-select'>", unsafe_allow_html=True)
            if st.button(f"Select ›", key=f"ams_cat_{idx}", use_container_width=True):
                if st.session_state.home_category == cat_name:
                    st.session_state.home_category = None
                else:
                    st.session_state.home_category = cat_name
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    # ----- Dashboard Links for Selected Category -----
    if st.session_state.home_category and st.session_state.home_category in PAGE_GROUPS:
        active_cat = st.session_state.home_category
        pages_in_cat = PAGE_GROUPS[active_cat]
        cat_meta = AMS_CATEGORIES[active_cat]

        st.markdown("<div class='ams-section-divider'></div>", unsafe_allow_html=True)
        st.markdown(
            f"<h3 style='text-align: center; margin-bottom: 16px;'>{cat_meta['icon']}  {active_cat}</h3>",
            unsafe_allow_html=True,
        )

        # SVG silhouette icons for each page (rendered as inline SVG)
        def _svg_icon(path_d, vbox="0 0 24 24"):
            return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vbox}" fill="currentColor" width="40" height="40" style="opacity:0.85;"><path d="{path_d}"/></svg>'

        page_svg_icons = {
            # List Management & Recruiting
            "Club List":       _svg_icon("M3 3h18v2H3V3zm0 4h18v2H3V7zm0 4h18v2H3v-2zm0 4h12v2H3v-2zm0 4h8v2H3v-2z"),
            "Depth Chart":     _svg_icon("M3 3h4v18H3V3zm7 4h4v14h-4V7zm7 4h4v10h-4V11z"),
            "Team Age Breakdown": _svg_icon("M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"),
            "List Ladder":     _svg_icon("M3 21h18v-2H3v2zm0-4h14v-2H3v2zm0-4h18v-2H3v2zm0-4h10v-2H3v2zm0-6v2h18V3H3z"),
            "Team List Summary": _svg_icon("M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM6 20V4h7v5h5v11H6zm2-6h8v2H8v-2zm0-3h8v2H8v-2z"),
            "List Breakdown - Traits": _svg_icon("M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"),
            "Contract Status": _svg_icon("M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm-1 7V3.5L18.5 9H13zM9.88 15.12l-1.41 1.41L11 19.06l4.24-4.24-1.41-1.41L11 16.24l-1.12-1.12z"),
            # Team Performance
            "Overview":        _svg_icon("M3 3v18h18V3H3zm16 16H5V5h14v14zM7 12h2v5H7v-5zm4-3h2v8h-2V9zm4-2h2v10h-2V7z"),
            "Team Breakdown":  _svg_icon("M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"),
            "Team Compare":   _svg_icon("M10 3H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1zm0 10H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zm10-10h-6c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1zm0 10h-6c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1z"),
            "Game Predictor": _svg_icon("M2 4v16h20V4H2zm18 14H4V6h16v12zM6 12h3v4H6v-4zm5-4h2v8h-2V8zm5 2h3v6h-3v-6z"),
            "Game Model Scorecard": _svg_icon("M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm-1-13h2v6h-2V7zm0 8h2v2h-2v-2z"),
            "Best 23":         _svg_icon("M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2z"),
            # Individual Performance
            "Player Profile":  _svg_icon("M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"),
            "IDP":             _svg_icon("M16 6l2.29 2.29-4.88 4.88-4-4L2 16.59 3.41 18l6-6 4 4 6.3-6.29L22 12V6h-6z"),
            "Custom Player Comparison": _svg_icon("M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"),
        }

        page_icons = {pg: _svg_for_page(pg, 20) for pg in PAGE_ICON_MAP if pg != "Home"}

        page_descriptions = {
            "Overview": "High-level team performance snapshot",
            "Team Breakdown": "Detailed team statistics and analysis",
            "Team Compare": "Head-to-head team comparison",
            "Game Predictor": "Simulate match-day scenarios",
            "Game Model Scorecard": "Evaluate game model execution",
            "Best 23": "Optimal team selection analysis",
            "Club List": "Full club list with player details",
            "Depth Chart": "Positional depth across the squad",
            "Team Age Breakdown": "Age profile and list demographics",
            "List Ladder": "Salary and list position rankings",
            "Team List Summary": "Summary of squad composition",
            "List Breakdown - Traits": "Trait distribution across the list",
            "Contract Status": "Player contract and free-agency status",
            "Player Profile": "Individual player performance deep-dive",
            "IDP": "Individual Development Plans",
            "Custom Player Comparison": "Side-by-side player comparison tool",
            "Player Rating Matrix": "Round-by-round player rating heat map",
        }

        # Determine dashboard card accent colour
        _dash_accent = _pri if _has_brand else cat_meta["colour"]

        # Short labels for tile buttons
        page_short_labels = {
            "Overview": "Overview", "Team Breakdown": "Breakdown", "Team Compare": "Compare",
            "Game Predictor": "Predictor", "Game Model Scorecard": "Scorecard", "Best 23": "Best 23",
            "Club List": "Club List", "Depth Chart": "Depth Chart",
            "Team Age Breakdown": "Age Profile", "List Ladder": "List Ladder",
            "Team List Summary": "List Summary", "List Breakdown - Traits": "Traits",
            "Contract Status": "Contracts",
            "Player Profile": "Profile",
            "IDP": "IDP", "Custom Player Comparison": "Compare",
            "Player Rating Matrix": "Rating Matrix",
        }

        # CSS to style sub-page tile buttons as large square icon tiles
        st.markdown(f"""
        <style>
        /* Sub-page tile styling */
        .ams-tile-card-wrap {{
            background: linear-gradient(135deg, rgba(255,255,255,0.04), rgba(255,255,255,0.00));
            border: 1px solid {_dash_accent}28;
            border-radius: 14px;
            padding: 22px 8px 16px 8px;
            text-align: center;
            transition: all 0.25s ease;
            cursor: default;
        }}
        .ams-tile-card-wrap:hover {{
            background: {_dash_accent}14;
            border-color: {_dash_accent}55;
            transform: translateY(-3px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }}
        .ams-tile-card-wrap svg {{
            width: 44px;
            height: 44px;
            color: rgba(255,255,255,0.80);
            filter: drop-shadow(0 2px 6px rgba(0,0,0,0.35));
            margin-bottom: 8px;
        }}
        .ams-tile-card-wrap:hover svg {{
            color: rgba(255,255,255,0.95);
        }}
        .ams-tile-card-wrap .tile-label {{
            font-weight: 700;
            font-size: 0.82em;
            color: rgba(255,255,255,0.88);
            letter-spacing: 0.02em;
        }}
        .ams-tile-card-wrap:hover .tile-label {{
            color: #FFFFFF;
        }}
        /* Style the Streamlit button under tiles as a minimal select link */
        .ams-tile-select {{
            margin-top: -4px;
        }}
        .ams-tile-select [data-testid="stButton"] > button {{
            background: transparent !important;
            border: none !important;
            padding: 6px 8px !important;
            min-height: 28px !important;
            height: 28px !important;
            color: {_dash_accent}88 !important;
            font-size: 0.70em !important;
            font-weight: 500 !important;
            letter-spacing: 0.06em !important;
            text-transform: uppercase !important;
            transition: all 0.2s ease !important;
        }}
        .ams-tile-select [data-testid="stButton"] > button:hover {{
            color: {_dash_accent} !important;
            text-decoration: underline !important;
            background: transparent !important;
        }}
        .ams-tile-select [data-testid="stButton"] > button:focus {{
            box-shadow: none !important;
        }}
        </style>
        """, unsafe_allow_html=True)

        # Render square icon tiles in rows of 4
        row_size = 4
        for row_start in range(0, len(pages_in_cat), row_size):
            row_pages = pages_in_cat[row_start:row_start + row_size]
            btn_cols = st.columns(row_size, gap="small")
            for j, pg in enumerate(row_pages):
                with btn_cols[j]:
                    svg_icon = page_svg_icons.get(pg, "")
                    short_label = page_short_labels.get(pg, pg)
                    # Visual tile card
                    st.markdown(f"""<div class='ams-tile-card-wrap'>
                        {svg_icon}
                        <div class='tile-label'>{short_label}</div>
                    </div>""", unsafe_allow_html=True)
                    # Minimal select button
                    st.markdown("<div class='ams-tile-select'>", unsafe_allow_html=True)
                    if st.button(
                        f"Select ›",
                        key=f"ams_page_{pg}",
                        use_container_width=True,
                    ):
                        st.session_state.selected_page = pg
                        st.session_state.page_override = True
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)

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
    _season = CURRENT_SEASON if CURRENT_SEASON in _seasons else (_seasons[0] if _seasons else None)

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
    _gd_icon = _svg_inline('gamepad', 40)
    st.markdown(f"""<div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);padding: 40px 20px;border-radius: 16px;box-shadow: 0 8px 24px rgba(0,0,0,0.4);margin-bottom: 32px;text-align: center;"><h1 style="color: #FFFFFF;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-weight: 900;font-size: 48px;margin: 0 0 12px 0;letter-spacing: 0.02em;text-shadow: 2px 2px 8px rgba(0,0,0,0.5);">{_gd_icon} Game Predictor</h1><p style="color: rgba(255,255,255,0.8);font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-size: 16px;margin: 0;font-weight: 600;letter-spacing: 0.03em;">Select two teams and compare their 5 phases of the game side-by-side.</p></div>""", unsafe_allow_html=True)

    # -------------------------------------------------
    # SAFETY: build teams if global list is empty
    # -------------------------------------------------
    if not teams:
        try:
            df = load_player_summary()
            if "Team" in df.columns:
                teams = sorted(df["Team"].dropna().unique())
        except Exception as e:
            st.error("Unable to load teams for Game Predictor")
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
    st.markdown("<div style='text-align:center;font-weight:900;font-size:18px;margin-bottom:16px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.05em;'>⏱️ Data Filter</div>", unsafe_allow_html=True)

    # --- Time filter (single widget, single key)
    time_filter = st.radio(
        "Data Filter",
        ["Season", "Last 10 Games"],
        horizontal=True,
        key="gdp_time_filter",
        label_visibility="collapsed",
    )



    # =====================================================
    # LOAD REAL DATA
    # =====================================================
    _block = "L10" if time_filter == "Last 10 Games" else "Season"
    _season = CURRENT_SEASON

    # Load team ladder data (phase ratings 50-99 scale)
    ladders = load_team_ladders(_season, block=_block)
    if ladders.empty:
        # Try previous season as fallback
        _season = CURRENT_SEASON - 1
        ladders = load_team_ladders(_season, block=_block)

    if ladders.empty:
        st.warning("No team rating data available yet.")
        return

    # Normalise team names
    if "Team" in ladders.columns:
        ladders["Team"] = ladders["Team"].apply(lambda x: normalize_team_name(str(x)) if pd.notna(x) else x)

    # Load raw team stats for component data
    from pathlib import Path as _Path
    _raw_path = _Path(__file__).parent / "data" / "raw" / "team" / f"team_stats_{_season}.csv"
    if _raw_path.exists():
        raw_stats = pd.read_csv(_raw_path)
        raw_stats = raw_stats[raw_stats["Team"].notna()]
        raw_stats = raw_stats[~raw_stats["Team"].astype(str).str.contains("Total|Average|nan", case=False, na=False)]
        raw_stats["Team"] = raw_stats["Team"].apply(lambda x: normalize_team_name(str(x)) if pd.notna(x) else x)
    else:
        raw_stats = pd.DataFrame()

    # Phase column mapping
    PHASE_COLS = {
        "Ball Winning": ("Ball Winning Ranking", "Ball Winning Rank"),
        "Ball Movement": ("Ball Movement Ranking", "Ball Movement Rank"),
        "Scoring": ("Scoring Ranking", "Scoring Rank"),
        "Defence": ("Defence Ranking", "Defence Rank"),
        "Pressure": ("Pressure Ranking", "Pressure Rank"),
    }

    # Component stats per phase (from raw team stats)
    PHASE_COMPONENT_STATS = {
        "Ball Winning": [
            ("Post Clear CP Diff", lambda r: r.get("PostClearanceContestedPossessions", 0) - r.get("PostClearanceContestedPossessions_Opposition", 0), "higher better"),
            ("Ground Ball Diff", lambda r: r.get("GroundBallGets", 0) - r.get("GroundBallGets_Opposition", 0), "higher better"),
            ("1st Poss to Clear %", lambda r: r.get("FirstPossessionToClearance", 0), "higher better"),
            ("Clearance Diff", lambda r: r.get("TotalClearances", 0) - r.get("TotalClearances_Opposition", 0), "higher better"),
        ],
        "Ball Movement": [
            ("Def Half to Score %", lambda r: r.get("DefHalfToScore", 0), "higher better"),
            ("Chain to Score %", lambda r: r.get("ChainToScore", 0), "higher better"),
            ("D50 to F50 %", lambda r: r.get("D50ToF50", 0), "higher better"),
            ("Kick Rating", lambda r: r.get("KickingEfficiency", 0), "higher better"),
        ],
        "Scoring": [
            ("Scores per I50 %", lambda r: r.get("ScoringShotsPerInside50", 0), "higher better"),
            ("Goals per I50 %", lambda r: r.get("GoalsPerInside50", 0), "higher better"),
            ("Accuracy %", lambda r: r.get("GoalAccuracy", 0), "higher better"),
            ("+/- Exp Score", lambda r: r.get("xScoreRating", 0), "higher better"),
        ],
        "Defence": [
            ("Def Half to Score Ag %", lambda r: r.get("DefHalfToScore_Opposition", 0), "lower better"),
            ("Chain to Score Ag %", lambda r: r.get("ChainToScore_Opposition", 0), "lower better"),
            ("D50 to F50 Ag %", lambda r: r.get("D50ToF50_Opposition", 0), "lower better"),
            ("Goals per I50 Ag %", lambda r: r.get("GoalsPerInside50_Opposition", 0), "lower better"),
        ],
        "Pressure": [
            ("Tackle Diff", lambda r: r.get("Tackles", 0) - r.get("Tackles_Opposition", 0), "higher better"),
            ("F50 Tackles", lambda r: r.get("TacklesInside50", 0), "higher better"),
            ("Pressure Acts", lambda r: r.get("PressureActs", 0), "higher better"),
            ("1%'ers", lambda r: r.get("OnePercenters", 0), "higher better"),
        ],
    }

    def _get_team_phase_rating(team_name: str, phase: str):
        """Get team's phase rating and rank from ladder data."""
        rating_col, rank_col = PHASE_COLS[phase]
        row = ladders[ladders["Team"] == team_name]
        if row.empty:
            return None, None
        rating = pd.to_numeric(row.iloc[0].get(rating_col), errors="coerce")
        rank = pd.to_numeric(row.iloc[0].get(rank_col), errors="coerce")
        return (float(rating) if pd.notna(rating) else None,
                int(rank) if pd.notna(rank) else None)

    def _get_team_overall_rating(team_name: str):
        """Get team's overall rating and rank."""
        row = ladders[ladders["Team"] == team_name]
        if row.empty:
            return None, None
        rating = pd.to_numeric(row.iloc[0].get("Overall Rating", row.iloc[0].get("Team Rating")), errors="coerce")
        rank = pd.to_numeric(row.iloc[0].get("Overall Rank", row.iloc[0].get("Team Rating Rank")), errors="coerce")
        return (float(rating) if pd.notna(rating) else None,
                int(rank) if pd.notna(rank) else None)

    def _get_team_component_stats(team_name: str, phase: str):
        """Get component stats for a team's phase from raw data."""
        if raw_stats.empty:
            return []
        row = raw_stats[raw_stats["Team"] == team_name]
        if row.empty:
            return []
        row_dict = row.iloc[0].to_dict()
        results = []
        for stat_name, compute_fn, direction in PHASE_COMPONENT_STATS.get(phase, []):
            try:
                val = float(compute_fn(row_dict))
                results.append((stat_name, val, direction))
            except Exception:
                results.append((stat_name, None, direction))
        return results

    # =====================================================
    # Overall Rating comparison banner
    # =====================================================
    st.markdown("<div style='margin:40px 0 24px 0;'></div>", unsafe_allow_html=True)

    overall_a, rank_a = _get_team_overall_rating(team_a)
    overall_b, rank_b = _get_team_overall_rating(team_b)

    def _ordinal(n):
        if n is None:
            return "—"
        n = int(n)
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    col_a = _gdp_colour(overall_a) if overall_a else "#888"
    col_b = _gdp_colour(overall_b) if overall_b else "#888"

    st.markdown(f"""<div class="gdp-card" style="padding:28px;margin-bottom:32px;"><div style="text-align:center;font-weight:900;font-size:16px;color:#FFD700;margin-bottom:20px;letter-spacing:0.08em;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">OVERALL TEAM RATING — {_season} {time_filter}</div><div style="display:flex;justify-content:center;align-items:center;gap:48px;"><div style="text-align:center;"><div style="font-size:14px;font-weight:800;color:rgba(255,255,255,0.8);margin-bottom:8px;">{team_a}</div><div style="font-size:48px;font-weight:900;color:{col_a};text-shadow:0 2px 12px {col_a}50;">{int(overall_a) if overall_a else '—'}</div><div style="font-size:13px;color:rgba(255,255,255,0.6);margin-top:4px;font-weight:700;">Ranked {_ordinal(rank_a)}</div></div><div style="font-size:28px;font-weight:900;color:rgba(255,255,255,0.3);">VS</div><div style="text-align:center;"><div style="font-size:14px;font-weight:800;color:rgba(255,255,255,0.8);margin-bottom:8px;">{team_b}</div><div style="font-size:48px;font-weight:900;color:{col_b};text-shadow:0 2px 12px {col_b}50;">{int(overall_b) if overall_b else '—'}</div><div style="font-size:13px;color:rgba(255,255,255,0.6);margin-top:4px;font-weight:700;">Ranked {_ordinal(rank_b)}</div></div></div></div>""", unsafe_allow_html=True)

    # =====================================================
    # 5 Phases side-by-side comparison
    # =====================================================
    st.markdown(f"<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:12px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;'>{_svg_inline('chart_bar', 20)} 5 Phases of the Game</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center;color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:24px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Side-by-side phase ratings ({_season} {time_filter}) — expand each to see contributing stats</div>", unsafe_allow_html=True)

    phase_colours = {
        "Ball Winning": "#0066CC",
        "Ball Movement": "#009933",
        "Scoring": "#FFD700",
        "Defence": "#CC0000",
        "Pressure": "#800080",
    }

    for phase_name in ["Ball Winning", "Ball Movement", "Scoring", "Defence", "Pressure"]:
        rating_a, rank_phase_a = _get_team_phase_rating(team_a, phase_name)
        rating_b, rank_phase_b = _get_team_phase_rating(team_b, phase_name)

        p_col = phase_colours[phase_name]
        col_ra = _gdp_colour(rating_a) if rating_a else "#888"
        col_rb = _gdp_colour(rating_b) if rating_b else "#888"
        val_a = int(rating_a) if rating_a else "—"
        val_b = int(rating_b) if rating_b else "—"
        bar_a = max(0, min(100, int(rating_a))) if rating_a else 0
        bar_b = max(0, min(100, int(rating_b))) if rating_b else 0

        # Determine winner
        winner_html = ""
        if rating_a and rating_b:
            if rating_a > rating_b:
                winner_html = f"<span style='font-size:11px;font-weight:800;color:#00CC00;'>▲ {team_a}</span>"
            elif rating_b > rating_a:
                winner_html = f"<span style='font-size:11px;font-weight:800;color:#00CC00;'>▲ {team_b}</span>"
            else:
                winner_html = "<span style='font-size:11px;font-weight:800;color:#888;'>EVEN</span>"

        st.markdown(f"""<div class="gdp-card" style="padding:20px 24px;margin-bottom:16px;border-left:5px solid {p_col};"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;"><div style="font-weight:900;font-size:18px;color:{p_col};font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;letter-spacing:0.03em;">{phase_name}</div>{winner_html}</div><div style="display:flex;gap:24px;align-items:stretch;"><div style="flex:1;background:rgba(255,255,255,0.04);border-radius:10px;padding:14px 16px;"><div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;"><span style="font-size:13px;font-weight:800;color:rgba(255,255,255,0.85);">{team_a}</span><span style="font-size:11px;color:rgba(255,255,255,0.5);font-weight:700;">Ranked {_ordinal(rank_phase_a)}</span></div><div style="font-size:32px;font-weight:900;color:{col_ra};text-shadow:0 2px 8px {col_ra}50;">{val_a}</div><div class="gdp-bar-bg" style="margin-top:10px;"><div class="gdp-bar-fill" style="width:{bar_a}%;background:{col_ra};box-shadow:0 0 16px {col_ra};"></div></div></div><div style="flex:1;background:rgba(255,255,255,0.04);border-radius:10px;padding:14px 16px;"><div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;"><span style="font-size:13px;font-weight:800;color:rgba(255,255,255,0.85);">{team_b}</span><span style="font-size:11px;color:rgba(255,255,255,0.5);font-weight:700;">Ranked {_ordinal(rank_phase_b)}</span></div><div style="font-size:32px;font-weight:900;color:{col_rb};text-shadow:0 2px 8px {col_rb}50;">{val_b}</div><div class="gdp-bar-bg" style="margin-top:10px;"><div class="gdp-bar-fill" style="width:{bar_b}%;background:{col_rb};box-shadow:0 0 16px {col_rb};"></div></div></div></div></div>""", unsafe_allow_html=True)

        # Expandable component stats
        with st.expander(f"📊 {phase_name} — Contributing Stats", expanded=False):
            stats_a = _get_team_component_stats(team_a, phase_name)
            stats_b = _get_team_component_stats(team_b, phase_name)

            if stats_a and stats_b:
                # Compare stats side-by-side in a table
                comp_rows = []
                for (sn_a, sv_a, dir_a), (sn_b, sv_b, _) in zip(stats_a, stats_b):
                    # Determine who is better
                    better = ""
                    if sv_a is not None and sv_b is not None:
                        higher_better = dir_a == "higher better"
                        if (higher_better and sv_a > sv_b) or (not higher_better and sv_a < sv_b):
                            better = "A"
                        elif (higher_better and sv_b > sv_a) or (not higher_better and sv_b < sv_a):
                            better = "B"

                    def _fmt(v):
                        if v is None:
                            return "—"
                        if abs(v) >= 100:
                            return f"{v:.0f}"
                        return f"{v:.1f}"

                    dot_a = "🟢" if better == "A" else ("🔴" if better == "B" else "⚪")
                    dot_b = "🟢" if better == "B" else ("🔴" if better == "A" else "⚪")

                    comp_rows.append({
                        f"{team_a}": f"{dot_a} {_fmt(sv_a)}",
                        "Stat": sn_a,
                        f"{team_b}": f"{dot_b} {_fmt(sv_b)}",
                    })

                comp_df = pd.DataFrame(comp_rows)
                st.dataframe(comp_df, hide_index=True, use_container_width=True)
            else:
                st.info("Raw component stats not available for this filter/season.")

    # =====================================================
    # Summary Comparison Table
    # =====================================================
    st.markdown("<div style='margin:40px 0;border-top:1px solid rgba(255,255,255,0.15);'></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:8px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;'>{_svg_inline('trophy', 20)} Head-to-Head Summary</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:24px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Phase-by-phase advantage breakdown</div>", unsafe_allow_html=True)

    summary_rows = []
    team_a_wins = 0
    team_b_wins = 0
    for phase_name in ["Ball Winning", "Ball Movement", "Scoring", "Defence", "Pressure"]:
        ra, rk_a = _get_team_phase_rating(team_a, phase_name)
        rb, rk_b = _get_team_phase_rating(team_b, phase_name)
        adv = ""
        if ra and rb:
            diff = ra - rb
            if diff > 0:
                adv = f"▲ {team_a} (+{diff:.0f})"
                team_a_wins += 1
            elif diff < 0:
                adv = f"▲ {team_b} (+{abs(diff):.0f})"
                team_b_wins += 1
            else:
                adv = "Even"
        summary_rows.append({
            "Phase": phase_name,
            f"{team_a} Rating": int(ra) if ra else "—",
            f"{team_a} Rank": _ordinal(rk_a),
            f"{team_b} Rating": int(rb) if rb else "—",
            f"{team_b} Rank": _ordinal(rk_b),
            "Advantage": adv,
        })

    summary_df = pd.DataFrame(summary_rows)

    # Build a styled HTML table
    sum_html = ["<table class='fe-table'><thead><tr>"]
    for col in summary_df.columns:
        bg = "#1a1a1a"
        fg = "#FFFFFF"
        if col == "Phase":
            pass
        elif team_a in col:
            bg = "#FF6B35"
        elif team_b in col:
            bg = "#4A90E2"
        elif col == "Advantage":
            bg = "#2a2a2a"
        sum_html.append(f"<th style='background:{bg};color:{fg};padding:10px 14px;font-size:12px;'>{col}</th>")
    sum_html.append("</tr></thead><tbody>")

    for _, row in summary_df.iterrows():
        sum_html.append("<tr>")
        for col in summary_df.columns:
            val = row[col]
            style = "padding:8px 14px;font-size:13px;"
            if col == "Phase":
                p_c = phase_colours.get(val, "#FFF")
                style += f"font-weight:900;color:{p_c};"
            elif "Rating" in col:
                try:
                    c = _gdp_colour(float(val))
                    style += f"font-weight:900;color:{c};"
                except (ValueError, TypeError):
                    pass
            elif col == "Advantage":
                if f"▲ {team_a}" in str(val):
                    style += "color:#FF6B35;font-weight:800;"
                elif f"▲ {team_b}" in str(val):
                    style += "color:#4A90E2;font-weight:800;"
                else:
                    style += "color:#888;"
            sum_html.append(f"<td style='{style}'>{val}</td>")
        sum_html.append("</tr>")
    sum_html.append("</tbody></table>")
    st.markdown("\n".join(sum_html), unsafe_allow_html=True)

    # Verdict banner
    if team_a_wins > team_b_wins:
        verdict_team = team_a
        verdict_col = "#FF6B35"
    elif team_b_wins > team_a_wins:
        verdict_team = team_b
        verdict_col = "#4A90E2"
    else:
        verdict_team = "EVEN"
        verdict_col = "#FFD700"

    st.markdown(f"""<div class="gdp-card" style="margin-top:24px;padding:20px;text-align:center;border:2px solid {verdict_col}40;"><div style="font-size:13px;color:rgba(255,255,255,0.6);font-weight:800;letter-spacing:0.08em;margin-bottom:8px;">PHASE ADVANTAGE</div><div style="font-size:28px;font-weight:900;color:{verdict_col};font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">{verdict_team}</div><div style="font-size:13px;color:rgba(255,255,255,0.5);margin-top:8px;font-weight:700;">{team_a_wins} – {team_b_wins} phase wins</div></div>""", unsafe_allow_html=True)

    # =====================================================
    # Predicted Margin
    # =====================================================
    st.markdown("<div style='margin:40px 0;border-top:1px solid rgba(255,255,255,0.15);'></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center;font-weight:900;font-size:24px;margin-bottom:8px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;letter-spacing:0.03em;'>{_svg_inline('chart_bar', 20)} Predicted Scoreline</div>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center;color:rgba(255,255,255,0.7);font-size:14px;margin-bottom:24px;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;font-weight:600;'>Based on phase ratings against a baseline 85-85 scoreline</div>", unsafe_allow_html=True)

    # Calculate predicted scores: baseline 85 each, adjust by rating difference
    # Ratings are on 50-99 scale, midpoint ~75. Each point above/below midpoint
    # shifts predicted score. The h2h gap further amplifies the margin.
    _midpoint = 75.0
    _scale = 1.2
    score_a = 85.0
    score_b = 85.0
    if overall_a is not None:
        score_a += (overall_a - _midpoint) * _scale
    if overall_b is not None:
        score_b += (overall_b - _midpoint) * _scale

    # Head-to-head adjustment: the rating gap between teams also shifts the margin
    if overall_a is not None and overall_b is not None:
        gap = (overall_a - overall_b) * 0.6
        score_a += gap
        score_b -= gap

    pred_a = max(30, round(score_a))
    pred_b = max(30, round(score_b))
    margin = abs(pred_a - pred_b)
    if pred_a > pred_b:
        fav_team = team_a
        fav_col = "#FF6B35"
    elif pred_b > pred_a:
        fav_team = team_b
        fav_col = "#4A90E2"
    else:
        fav_team = "DRAW"
        fav_col = "#FFD700"

    margin_label = f"{fav_team} by {margin} pts" if margin > 0 else "DRAW"

    st.markdown(f"""<div class="gdp-card" style="padding:28px;text-align:center;border:2px solid {fav_col}40;"><div style="display:flex;justify-content:center;align-items:center;gap:48px;margin-bottom:20px;"><div style="text-align:center;"><div style="font-size:14px;font-weight:800;color:rgba(255,255,255,0.8);margin-bottom:8px;">{team_a}</div><div style="font-size:48px;font-weight:900;color:{'#FF6B35' if pred_a >= pred_b else 'rgba(255,255,255,0.5)'};text-shadow:0 2px 12px {'#FF6B35' if pred_a >= pred_b else 'rgba(0,0,0,0)'}50;">{pred_a}</div></div><div style="font-size:28px;font-weight:900;color:rgba(255,255,255,0.3);">–</div><div style="text-align:center;"><div style="font-size:14px;font-weight:800;color:rgba(255,255,255,0.8);margin-bottom:8px;">{team_b}</div><div style="font-size:48px;font-weight:900;color:{'#4A90E2' if pred_b >= pred_a else 'rgba(255,255,255,0.5)'};text-shadow:0 2px 12px {'#4A90E2' if pred_b >= pred_a else 'rgba(0,0,0,0)'}50;">{pred_b}</div></div></div><div style="font-size:13px;color:rgba(255,255,255,0.6);font-weight:800;letter-spacing:0.08em;margin-bottom:6px;">PREDICTED MARGIN</div><div style="font-size:24px;font-weight:900;color:{fav_col};font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">{margin_label}</div></div>""", unsafe_allow_html=True)

    st.markdown("<div style='margin:24px 0;'></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center;color:rgba(255,255,255,0.5);font-size:12px;font-style:italic;font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif;'>Data: {_season} {time_filter} · Ratings on 50-99 scale · Predicted scoreline is indicative only</div>", unsafe_allow_html=True)

    # Professional footer
    render_footer()



# ================= OVERVIEW =================
if page == "Overview":
    import textwrap
    import pandas as pd
    import streamlit as st

    render_page_header("FutureEdge AFL Dashboard", "Overview & Performance Analysis", "chart_bar")

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

    _l10_years = get_l10_available_years()
    _l5_years = get_l5_available_years()
    year_options = []
    for y in available_years:
        year_options.append(f"{y} - Season")
        if int(y) in _l10_years:
            year_options.append(f"{y} - Last 10 Games")
        if int(y) in _l5_years:
            year_options.append(f"{y} - Last 5 Games")

    # Primary period selector
    col_primary, col_compare_toggle = st.columns([3, 1])
    with col_primary:
        selected_option = st.selectbox(
            "Select Year & Data Window",
            year_options,
            index=0,
            help="Choose which year to view. Last 10 / Last 5 Games available where data exists.",
        )
    with col_compare_toggle:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)  # Spacer to align
        compare_mode = st.checkbox("Compare Periods", value=False, help="Compare two time periods side by side")

    # Parse primary selection into season, window, and block
    _sel_parts = selected_option.split(" - ", 1)
    selected_season = int(_sel_parts[0])
    window = _sel_parts[1] if len(_sel_parts) > 1 else "Season"
    if window == "Last 10 Games":
        _block = "L10"
    elif window == "Last 5 Games":
        _block = "L5"
    else:
        _block = "Season"

    last10 = _block == "L10"
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
            
            _cmp_parts = compare_option.split(" - ", 1)
            compare_season = int(_cmp_parts[0])
            compare_window = _cmp_parts[1] if len(_cmp_parts) > 1 else "Season"
            if compare_window == "Last 10 Games":
                _cmp_block = "L10"
            elif compare_window == "Last 5 Games":
                _cmp_block = "L5"
            else:
                _cmp_block = "Season"
            
            period_label2 = f"{compare_window} ({compare_season})"
            
            # Load comparison data
            try:
                ladders2 = load_team_ladders(compare_season, block=_cmp_block)
            except Exception as e:
                st.warning(f"Could not load comparison data for {period_label2}: {e}")
                ladders2 = None

    # ----------------------------
    # Load ladder
    # ----------------------------
    try:
        ladders = load_team_ladders(selected_season, block=_block)
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
        "Team Rating": ("#DAA520", "white"),
        "Ball Winning Ranking": ("#0066CC", "white"),
        "Ball Movement Ranking": ("#009933", "white"),
        "Scoring Ranking": ("#FFEB3B", "black"),
        "Defence Ranking": ("#CC0000", "white"),
        "Pressure Ranking": ("#800080", "white"),
    }

    render_html(st, f"<hr><h2 style='text-align:center;color:#FFFFFF;margin-bottom:25px;'>{_svg_inline('trophy', 24)} Team Leaders – {period_label}</h2>")

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
                prefix = f"{_svg_inline('trophy', 16)} {team}"
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
    render_html(st, f"<hr><h2 style='text-align:center;color:#FFFFFF;margin-top:30px;margin-bottom:25px;'>{_svg_inline('chart_bar', 24)} Team Ladder – {period_label}</h2>")

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
        "Team\nRating": ("#DAA520", "white"),
        "Ball Winning\nRanking": ("#0066CC", "white"),
        "Ball Movement\nRanking": ("#009933", "white"),
        "Scoring\nRanking": ("#FFEB3B", "black"),
        "Defence\nRanking": ("#CC0000", "white"),
        "Pressure\nRanking": ("#800080", "white"),
    }
    rank_header_colors = {
        "Team Rating\nRank": ("#8B6914", "white"),
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

    # Build HTML table using unified .fe-table CSS (dark background, matching Club List)
    html = []
    html.append("<table class='fe-table fe-sortable'><thead><tr>")

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
            if c == "Team Rating\nRank":
                bg, fg = rank_header_colors.get("Team Rating\nRank", ("#8B6914", "white"))
            elif c.replace("\nRank", "\nRanking") in metric_colors:
                parent = c.replace("\nRank", "\nRanking")
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

            # metric value cell — pill with opacity-based coloring
            if c in metric_colors:
                bg, fg = metric_colors[c]
                opacity = 1.0
                if c in column_rankings:
                    r = column_rankings[c].loc[ridx]
                    if pd.notna(r):
                        opacity = 1.0 - (float(r) - 1.0) / denom * 0.7  # 1.0 -> 0.3
                r_, g_, b_ = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
                html.append(f"<td><span class='ct-pill' style='background:rgba({r_},{g_},{b_},{opacity:.3f});color:{fg};'>{v}</span></td>")
                continue

            # rank cell — pill
            if c.endswith("\nRank"):
                if c == "Team Rating\nRank":
                    bg = darken_color("#DAA520", 0.75)
                    fg = "white"
                    parent_metric = "Team\nRating"
                elif c.replace("\nRank", "\nRanking") in metric_colors:
                    parent = c.replace("\nRank", "\nRanking")
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
                html.append(f"<td><span class='ct-pill' style='background:rgba({r_},{g_},{b_},{opacity:.3f});color:{fg};'>{v}</span></td>")
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
        render_html(st, f"<hr><h2 style='text-align:center;color:#FFFFFF;margin-top:40px;margin-bottom:25px;'>{_svg_inline('chart_trend', 24)} Period Comparison – {period_label} vs {period_label2}</h2>")
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
                "Team Rating": ("#DAA520", "white"),
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
    render_page_header("Team Breakdown", "Detailed Team Performance Analysis", "chart_trend")
    
    # Breadcrumb navigation
    render_breadcrumb([("Home", "Home"), ("Team Breakdown", None)])

    # Get available years for top-level selection
    available_years = get_available_summary_years()
    if not available_years:
        st.error("No summary years available.")
        st.stop()
    
    # Create options: years with Season, plus Last 10 / Last 5 where data exists
    _l10_years = get_l10_available_years()
    _l5_years = get_l5_available_years()
    year_options = []
    for year in available_years:
        year_options.append(f"{year} - Season")
        if year in _l10_years:
            year_options.append(f"{year} - Last 10 Games")
        if year in _l5_years:
            year_options.append(f"{year} - Last 5 Games")
    
    # Year and data window selection combined
    selected_option = st.selectbox(
        "Select Year & Data Window",
        year_options,
        index=0 if year_options else None,
        help="Choose which year to view. Last 10 / Last 5 Games available where data exists.",
    )
    
    # Parse the selection
    _sel_parts = selected_option.split(" - ", 1)
    selected_year = int(_sel_parts[0])
    window = _sel_parts[1] if len(_sel_parts) > 1 else "Season"
    if window == "Last 10 Games":
        _block = "L10"
    elif window == "Last 5 Games":
        _block = "L5"
    else:
        _block = "Season"
    
    last10 = _block == "L10"
    period_label = f"{window} ({selected_year})"

    try:
        ladders = load_team_ladders(selected_year, block=_block)
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
    st.markdown(f"<h2 style='text-align: center; color: #FFFFFF; margin-bottom: 20px;'>{_svg_inline('chart_bar', 24)} Team Ratings Snapshot</h2>", unsafe_allow_html=True)

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
            rating_str = f"{int(round(float(rating_val)))}"
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
    st.markdown(f"<h2 style='text-align: center; color: #FFFFFF; margin-bottom: 20px;'>{_svg_inline('chart_trend', 24)} Detailed Attribute Analysis</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #AAAAAA; margin-bottom: 25px;'>Team Performance vs League Competition</p>", unsafe_allow_html=True)

    # Load summary data for the selected year and window
    if _block == "L10":
        summary_year = load_team_summary_for_year_l10(selected_year)
    elif _block == "L5":
        summary_year = load_team_summary_for_year_l5(selected_year)
    else:
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
        which_block = "Last10" if window == "Last 10 Games" else ("Last5" if window == "Last 5 Games" else "Season")
        
        # Dynamic layout: 3 columns per row, as many rows as needed
        num_cols = 3
        
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
                st.markdown(f"<h4 style='color: #FFFFFF; margin-top: 20px; margin-bottom: 10px;'>{_svg_inline('trophy', 24)} Top 4 Teams</h4>", unsafe_allow_html=True)
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
                    
                    _trophy_svg = _svg_inline('trophy', 20)
                    _chart_svg = _svg_inline('chart_bar', 20)
                    _top4_val = f"{top4_avg:.1f}" if top4_avg is not None else "–"
                    _league_val = f"{league_avg:.1f}" if league_avg is not None else "–"
                    
                    avg_html = f"""
                    <div style='display: flex; gap: 12px;'>
                        <div style='flex: 1; background: linear-gradient(135deg, rgba(255,215,0,0.15) 0%, rgba(255,215,0,0.05) 100%); 
                                    border: 1px solid rgba(255,215,0,0.3); border-radius: 10px; padding: 14px; text-align: center;'>
                            <div style='color: #FFD700; font-size: 0.75em; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;'>{_trophy_svg} Top 4 Avg</div>
                            <div style='font-size: 1.6em; font-weight: 900; color: #FFD700;'>{_top4_val}</div>
                        </div>
                        <div style='flex: 1; background: linear-gradient(135deg, rgba(100,149,237,0.15) 0%, rgba(100,149,237,0.05) 100%); 
                                    border: 1px solid rgba(100,149,237,0.3); border-radius: 10px; padding: 14px; text-align: center;'>
                            <div style='color: #6495ED; font-size: 0.75em; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px;'>{_chart_svg} League Avg</div>
                            <div style='font-size: 1.6em; font-weight: 900; color: #6495ED;'>{_league_val}</div>
                        </div>
                    </div>
                    """
                    st.markdown(avg_html, unsafe_allow_html=True)
            # close the bordered div
            st.markdown("</div>", unsafe_allow_html=True)
        
        # Render stats in rows of 3
        for row_start in range(0, len(stat_names), num_cols):
            if row_start > 0:
                st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
            row_stats = stat_names[row_start:row_start + num_cols]
            stat_cols = st.columns(num_cols)
            for idx, sn in enumerate(row_stats):
                with stat_cols[idx]:
                    render_stat_column(sn, idx, num_cols)


# ================= TEAM COMPARE =================

elif page == "Team Compare":
    render_page_header("Team Compare", "Head-to-Head Team Analysis", "balance")
    
    # Breadcrumb navigation
    render_breadcrumb([("Home", "Home"), ("Team Compare", None)])
    
    # Using global get_ordinal from config

    # Get available years for top-level selection (same as Team Breakdown)
    available_years = get_available_summary_years()
    if not available_years:
        st.error("No summary years available.")
        st.stop()
    
    # Create options: years with Season, plus Last 10 / Last 5 where data exists
    _l10_years = get_l10_available_years()
    _l5_years = get_l5_available_years()
    year_options = []
    for year in available_years:
        year_options.append(f"{year} - Season")
        if year in _l10_years:
            year_options.append(f"{year} - Last 10 Games")
        if year in _l5_years:
            year_options.append(f"{year} - Last 5 Games")
    
    # Helper function to parse year/window selection and load data
    def load_team_data_for_selection(selected_option):
        """Parse selection and load ladder data."""
        _parts = selected_option.split(" - ", 1)
        sel_year = int(_parts[0])
        sel_window = _parts[1] if len(_parts) > 1 else "Season"
        if sel_window == "Last 10 Games":
            sel_block = "L10"
        elif sel_window == "Last 5 Games":
            sel_block = "L5"
        else:
            sel_block = "Season"
        
        sel_label = f"{sel_window} ({sel_year})"
        
        try:
            sel_ladders = load_team_ladders(sel_year, block=sel_block)
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
        
        st.caption(f"{period_label1}")
    
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
        
        st.caption(f"{period_label2}")
    
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
        except Exception:
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
            except Exception:
                pass
    
    if available_pillars:
        st.markdown("""
        <div style='text-align: center; margin-bottom: 20px;'>
            <div style='font-size: 24px; font-weight: 900; color: #FFFFFF;
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        letter-spacing: 0.02em;'>
                Team Favoured Indicator
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
        with st.expander("Adjust Pillar Weightings", expanded=False):
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
                except Exception:
                    continue
            
            # Calculate favour percentage with AMPLIFIED differences
            # FIFA-style ratings range from ~62-82, so typical score differences are small
            # We amplify the differences to create more extreme results on the continuum
            
            # Calculate the raw difference in weighted scores
            score_diff = team2_weighted_score - team1_weighted_score
            
            # In practice, with ratings in 62-82 range and weights summing to 100:
            # - Team scores range roughly from 62 to 82 (if all pillars equal)
            # - Max realistic difference between teams is about 15-20 points total
            # We want small differences (2-5 points) to still show meaningful separation
            
            # Use a steeper amplification factor (3x) to spread out results
            # A 5-point difference should push the marker significantly off center
            amplification_factor = 3.0
            
            # Expected max realistic difference is ~20 points, amplified = ~60
            # This maps to 0-100 scale where 50 is center
            max_realistic_diff = 25.0  # Realistic max diff between best and worst teams
            
            # Apply amplification and normalize to -50 to +50 range, then shift to 0-100
            amplified_diff = score_diff * amplification_factor
            normalized_diff = amplified_diff / max_realistic_diff * 50  # Scale to ±50
            
            favour_position = 50 + normalized_diff
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
            with st.expander("View Pillar Breakdown", expanded=False):
                if pillar_breakdown:
                    breakdown_data = []
                    for pb in pillar_breakdown:
                        winner_icon = "" if pb["winner"] != "Tie" else ""
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
    # Use ladders1 as the base dataset for radar chart metrics
    spider_metrics = []
    team1_values = []
    team2_values = []
    top4_averages = []
    
    for metric_col in METRIC_ORDER:
        if metric_col not in ladders1.columns:
            continue
        
        # Get team values
        try:
            team1_val = float(team1_row[metric_col])
            team2_val = float(team2_row[metric_col]) if metric_col in ladders2.columns else None
            if team2_val is None:
                continue
        except Exception:
            continue
        
        # Calculate Top 4 average from ladders1 (base dataset)
        top4_vals = ladders1.nlargest(4, metric_col)[metric_col]
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
            
            # Get team colours from palettes — ensure high contrast on dark backgrounds
            _pal1 = TEAM_COLOUR_PALETTES.get(team1, {"primary": "#6496FF", "secondary": "#FFFFFF"})
            _pal2 = TEAM_COLOUR_PALETTES.get(team2, {"primary": "#FF6464", "secondary": "#FFFFFF"})

            def _brighten_hex(hex_col, factor=1.6):
                """Lighten a hex colour to improve visibility on dark backgrounds."""
                r = min(255, int(int(hex_col[1:3], 16) * factor))
                g = min(255, int(int(hex_col[3:5], 16) * factor))
                b = min(255, int(int(hex_col[5:7], 16) * factor))
                # Ensure minimum brightness so very dark colours are visible
                brightness = (r * 299 + g * 587 + b * 114) / 1000
                if brightness < 100:
                    boost = int((100 - brightness) * 1.8)
                    r, g, b = min(255, r + boost), min(255, g + boost), min(255, b + boost)
                return f'#{r:02X}{g:02X}{b:02X}'

            def _colour_distance(c1, c2):
                """Simple perceptual distance between two hex colours."""
                r1, g1, b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
                r2, g2, b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
                return ((r1-r2)**2 + (g1-g2)**2 + (b1-b2)**2) ** 0.5

            # Brighten primaries for radar line visibility
            _c1 = _brighten_hex(_pal1["primary"], 1.7)
            _c2 = _brighten_hex(_pal2["primary"], 1.7)

            # If colours are too similar, try secondary, then tertiary, then defaults
            if _colour_distance(_c1, _c2) < 120:
                # Try secondary colour (skip pure black/white which don't help)
                _alt = _pal2.get("secondary", "")
                if _alt and _alt not in ("#000000", "#FFFFFF", "#ffffff"):
                    _c2_alt = _brighten_hex(_alt, 1.4)
                    if _colour_distance(_c1, _c2_alt) >= 100:
                        _c2 = _c2_alt
                # Try tertiary
                if _colour_distance(_c1, _c2) < 120:
                    _alt = _pal2.get("tertiary", "")
                    if _alt and _alt not in ("#000000", "#FFFFFF", "#ffffff"):
                        _c2_alt = _brighten_hex(_alt, 1.3)
                        if _colour_distance(_c1, _c2_alt) >= 100:
                            _c2 = _c2_alt
                # Final fallback to guaranteed high-contrast pair
                if _colour_distance(_c1, _c2) < 100:
                    _c1 = "#6496FF"
                    _c2 = "#FF6464"

            # Bar chart uses same colours
            _bar1 = _c1
            _bar2 = _c2

            # === RADAR 1: HEAD-TO-HEAD (Team 1 vs Team 2) ===
            fig.add_trace(
                go.Scatterpolar(
                    r=team1_values_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor=f'rgba({int(_c1[1:3],16)},{int(_c1[3:5],16)},{int(_c1[5:7],16)},0.15)',
                    line=dict(color=_c1, width=3),
                    name=team1,
                    legendgroup='team1',
                    showlegend=True
                ),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatterpolar(
                    r=team2_values_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor=f'rgba({int(_c2[1:3],16)},{int(_c2[3:5],16)},{int(_c2[5:7],16)},0.12)',
                    line=dict(color=_c2, width=3, dash='dot'),
                    name=team2,
                    legendgroup='team2',
                    showlegend=True
                ),
                row=1, col=1
            )
            
            # === RADAR 2: TEAM 1 vs TOP 4 AVERAGE ===
            fig.add_trace(
                go.Scatterpolar(
                    r=team1_values_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor=f'rgba({int(_c1[1:3],16)},{int(_c1[3:5],16)},{int(_c1[5:7],16)},0.15)',
                    line=dict(color=_c1, width=3),
                    name=team1,
                    legendgroup='team1',
                    showlegend=False
                ),
                row=1, col=2
            )
            
            fig.add_trace(
                go.Scatterpolar(
                    r=top4_averages_closed,
                    theta=clean_metrics_closed,
                    fill='toself',
                    fillcolor='rgba(255, 215, 0, 0.1)',
                    line=dict(color='#FFD700', width=3),
                    name='Top 4 Avg',
                    legendgroup='top4',
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
                    marker=dict(color=_bar1),
                    legendgroup='team1',
                    showlegend=False
                ),
                row=1, col=3
            )
            
            fig.add_trace(
                go.Bar(
                    x=x_positions,
                    y=team2_values,
                    name=team2,
                    marker=dict(color=_bar2),
                    legendgroup='team2',
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
            
            # Build title with period info
            if period_label1 == period_label2:
                chart_period = period_label1
            else:
                chart_period = f"{period_label1} vs {period_label2}"
            
            # Update layout
            fig.update_layout(
                title_text=f"<b>{team1} vs {team2}</b> – Head-to-Head  |  <b>{team1}</b> vs Top 4 Avg  ({chart_period})",
                title_font_size=16,
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
    
    # Determine if this is a same-team cross-period comparison
    is_same_team_comparison = (team1 == team2)
    
    if is_same_team_comparison:
        st.subheader(f"Period Comparison: {team1} ({period_label1} vs {period_label2})")
    else:
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
        except Exception:
            return str(rank_val)
    
    # Load summary data for attributes (use team1's year)
    try:
        summary_year = load_team_summary_for_year(year1)
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
    
    # Separate strengths and weaknesses
    metric_df = pd.DataFrame(metric_analysis)
    
    if is_same_team_comparison:
        # For same-team cross-period comparison, compare VALUES (higher = better for ratings)
        # "Improved" = period1 value > period2 value (higher rating in first period)
        # "Declined" = period1 value < period2 value (lower rating in first period)
        team1_strengths = metric_df[
            (metric_df["team1_val"].notna()) & 
            (metric_df["team2_val"].notna()) & 
            (metric_df["team1_val"] > metric_df["team2_val"])
        ].sort_values("team1_val", ascending=False)[["metric", "team1_val", "team2_val", "team1_rank", "team2_rank"]].reset_index(drop=True)
        
        team1_weaknesses = metric_df[
            (metric_df["team1_val"].notna()) & 
            (metric_df["team2_val"].notna()) & 
            (metric_df["team1_val"] < metric_df["team2_val"])
        ].sort_values("team2_val", ascending=False)[["metric", "team1_val", "team2_val", "team1_rank", "team2_rank"]].reset_index(drop=True)
    else:
        # For different teams, compare RANKINGS (lower rank = better)
        team1_strengths = metric_df[
            (metric_df["team1_rank"].notna()) & 
            (metric_df["team2_rank"].notna()) & 
            (metric_df["team1_rank"] < metric_df["team2_rank"])
        ].sort_values("team1_rank", ascending=True)[["metric", "team1_val", "team2_val", "team1_rank", "team2_rank"]].reset_index(drop=True)
        
        team1_weaknesses = metric_df[
            (metric_df["team1_rank"].notna()) & 
            (metric_df["team2_rank"].notna()) & 
            (metric_df["team1_rank"] > metric_df["team2_rank"])
        ].sort_values("team2_rank", ascending=True)[["metric", "team1_val", "team2_val", "team1_rank", "team2_rank"]].reset_index(drop=True)
    
    # Display analysis with enhanced styling
    st.markdown("---")
    if is_same_team_comparison:
        st.subheader(f"Performance Changes: {team1}")
    else:
        st.subheader(f"Strengths & Weaknesses Analysis: {team1} vs {team2}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if is_same_team_comparison:
            st.markdown(f"<h3 style='color: #00CC00;'>{_svg_inline('chart_trend', 24)} Higher in {period_label1}</h3>", unsafe_allow_html=True)
        else:
            st.markdown(f"<h3 style='color: #00CC00;'>{_svg_inline('chart_trend', 20)} {team1} – Strengths</h3>", unsafe_allow_html=True)
        if len(team1_strengths) > 0:
            for idx, row in team1_strengths.iterrows():
                metric = row["metric"]
                t1_val = row["team1_val"]
                t2_val = row["team2_val"]
                t1_rank = row["team1_rank"]
                t2_rank = row["team2_rank"]
                t1_rank_str = format_rank(t1_rank)
                t2_rank_str = format_rank(t2_rank)
                
                if is_same_team_comparison:
                    # Calculate value difference for same-team comparison
                    val_diff = t1_val - t2_val
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(90deg, rgba(0,204,0,0.1) 0%, rgba(0,204,0,0.05) 100%); 
                                    border-left: 4px solid #00CC00; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                            <div style='font-weight: bold; color: #00CC00;'>{idx + 1}. {metric}</div>
                            <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                {period_label1}: <span style='font-weight: bold; color: #00FF00;'>{t1_val:.1f}</span> {t1_rank_str} 
                                <span style='color: #888;'>vs</span> 
                                {period_label2}: <span style='font-weight: bold;'>{t2_val:.1f}</span> {t2_rank_str}
                            </div>
                            <div style='font-size: 0.85em; color: #00DD00; margin-top: 4px;'>
                                +{val_diff:.1f} rating points higher
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                else:
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
            if is_same_team_comparison:
                st.info(f"No metrics higher in {period_label1}")
            else:
                st.info("No statistics where Team 1 ranks higher")
    
    with col2:
        if is_same_team_comparison:
            st.markdown(f"<h3 style='color: #FF4444;'>{_svg_inline('chart_trend', 24)} Higher in {period_label2}</h3>", unsafe_allow_html=True)
        else:
            st.markdown(f"<h3 style='color: #FF4444;'>{_svg_inline('chart_trend', 20)} {team1} – Weaknesses</h3>", unsafe_allow_html=True)
        if len(team1_weaknesses) > 0:
            for idx, row in team1_weaknesses.iterrows():
                metric = row["metric"]
                t1_val = row["team1_val"]
                t2_val = row["team2_val"]
                t1_rank = row["team1_rank"]
                t2_rank = row["team2_rank"]
                t1_rank_str = format_rank(t1_rank)
                t2_rank_str = format_rank(t2_rank)
                
                if is_same_team_comparison:
                    # Calculate value difference for same-team comparison
                    val_diff = t2_val - t1_val
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(90deg, rgba(255,68,68,0.1) 0%, rgba(255,68,68,0.05) 100%); 
                                    border-left: 4px solid #FF4444; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                            <div style='font-weight: bold; color: #FF4444;'>{idx + 1}. {metric}</div>
                            <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                {period_label1}: <span style='font-weight: bold;'>{t1_val:.1f}</span> {t1_rank_str} 
                                <span style='color: #888;'>vs</span> 
                                {period_label2}: <span style='font-weight: bold; color: #FF6666;'>{t2_val:.1f}</span> {t2_rank_str}
                            </div>
                            <div style='font-size: 0.85em; color: #FF6666; margin-top: 4px;'>
                                +{val_diff:.1f} rating points higher in {period_label2}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                else:
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
            if is_same_team_comparison:
                st.info(f"No metrics higher in {period_label2}")
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
        def _window_to_attr_block(w):
            if w == "Last 10 Games": return "Last10"
            if w == "Last 5 Games": return "Last5"
            return "Season"
        which_block1 = _window_to_attr_block(window1)
        which_block2 = _window_to_attr_block(window2)
        
        # For same-team cross-period comparison, we need summary data from DIFFERENT sheets
        # Load the correct summary sheet based on the window
        if window1 == "Last 10 Games":
            summary_year1 = load_team_summary_for_year_l10(year1)
        elif window1 == "Last 5 Games":
            summary_year1 = load_team_summary_for_year_l5(year1)
        else:
            summary_year1 = load_team_summary_for_year(year1)
        
        summary_year2 = None
        if is_same_team_comparison:
            # Load from the appropriate sheet for period 2
            if window2 == "Last 10 Games":
                summary_year2 = load_team_summary_for_year_l10(year2)
            elif window2 == "Last 5 Games":
                summary_year2 = load_team_summary_for_year_l5(year2)
            else:
                summary_year2 = load_team_summary_for_year(year2)
        
        for attribute_group in attribute_groups:
            try:
                blocks = _extract_attribute_structure(summary_year1, attribute_group)
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
            if is_same_team_comparison:
                st.subheader(f"Detailed Attribute Stats: {team1} ({period_label1} vs {period_label2})")
            else:
                st.subheader(f"Detailed Attribute Stats Breakdown: {team1} vs {team2}")
            
            if is_same_team_comparison:
                st.markdown(f"""<div style='background: rgba(255,215,0,0.1); padding: 18px; border-radius: 10px; border-left: 5px solid #FFD700; margin-bottom: 25px;'><p style='color: #DDDDDD; margin: 0; font-size: 1.05em; line-height: 1.6;'><strong style='color: #FFFFFF; font-size: 1.2em;'>About This Section</strong><br><span style='color: #CCCCCC; font-size: 0.95em;'>Deep-dive comparison of {team1}'s performance across two time periods. Stats are compared by VALUE (higher = better for most metrics).</span></p></div>""", unsafe_allow_html=True)
            else:
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
                    if is_same_team_comparison:
                        # For same-team cross-period comparison, get data from BOTH periods
                        dist_df1 = get_attribute_stat_distribution(
                            summary_year1,
                            attribute_group,
                            stat_name,
                            block=which_block1,

                        )
                        dist_df2 = get_attribute_stat_distribution(
                            summary_year2 if summary_year2 is not None else summary_year1,
                            attribute_group,
                            stat_name,
                            block=which_block2,
                        )
                        
                        if dist_df1.empty or dist_df2.empty:
                            continue
                        
                        dist_df1 = dist_df1.copy()
                        dist_df1["Value"] = pd.to_numeric(dist_df1["Value"], errors="coerce")
                        dist_df1["Rank"] = pd.to_numeric(dist_df1["Rank"], errors="coerce")
                        dist_df1 = dist_df1.dropna(subset=["Team", "Value"]).reset_index(drop=True)
                        
                        dist_df2 = dist_df2.copy()
                        dist_df2["Value"] = pd.to_numeric(dist_df2["Value"], errors="coerce")
                        dist_df2["Rank"] = pd.to_numeric(dist_df2["Rank"], errors="coerce")
                        dist_df2 = dist_df2.dropna(subset=["Team", "Value"]).reset_index(drop=True)
                        
                        # Get team data from each period's distribution
                        team1_row_stat = dist_df1[dist_df1["Team"] == team1]
                        team2_row_stat = dist_df2[dist_df2["Team"] == team2]  # Same team, different period
                        
                        if not team1_row_stat.empty and not team2_row_stat.empty:
                            t1_val = team1_row_stat.iloc[0]["Value"]
                            t1_rank = int(team1_row_stat.iloc[0]["Rank"]) if pd.notna(team1_row_stat.iloc[0]["Rank"]) else 0
                            t2_val = team2_row_stat.iloc[0]["Value"]
                            t2_rank = int(team2_row_stat.iloc[0]["Rank"]) if pd.notna(team2_row_stat.iloc[0]["Rank"]) else 0
                            
                            # For same-team, compare VALUES (higher = better for most stats)
                            if t1_val > t2_val:
                                team1_strengths_attr.append({
                                    "stat": stat_name,
                                    "t1_val": t1_val,
                                    "t1_rank": t1_rank,
                                    "t2_val": t2_val,
                                    "t2_rank": t2_rank
                                })
                            elif t1_val < t2_val:
                                team1_weaknesses_attr.append({
                                    "stat": stat_name,
                                    "t1_val": t1_val,
                                    "t1_rank": t1_rank,
                                    "t2_val": t2_val,
                                    "t2_rank": t2_rank
                                })
                    else:
                        # Different teams - use original rank comparison logic
                        dist_df = get_attribute_stat_distribution(
                            summary_year,
                            attribute_group,
                            stat_name,
                            block=which_block1,
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
                            
                            # Compare by RANK for different teams
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
                    if is_same_team_comparison:
                        st.markdown(f"<h4 style='color: #00CC00;'>{_svg_inline('chart_trend', 24)} Higher in {period_label1}</h4>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<h4 style='color: #00CC00;'>{_svg_inline('chart_trend', 20)} {team1} – Strengths</h4>", unsafe_allow_html=True)
                    if len(team1_strengths_attr) > 0:
                        for idx, item in enumerate(team1_strengths_attr):
                            stat = item["stat"]
                            t1_val = item["t1_val"]
                            t1_rank = item["t1_rank"]
                            t2_val = item["t2_val"]
                            t2_rank = item["t2_rank"]
                            
                            try:
                                t1_val_str = f"{float(t1_val):.1f}"
                                t2_val_str = f"{float(t2_val):.1f}"
                            except Exception:
                                t1_val_str = str(t1_val)
                                t2_val_str = str(t2_val)
                            
                            if is_same_team_comparison:
                                # Show value difference for same-team comparison
                                val_diff = float(t1_val) - float(t2_val)
                                t1_ord = f"({t1_rank}{get_ordinal_suffix(t1_rank)})" if t1_rank > 0 else ""
                                t2_ord = f"({t2_rank}{get_ordinal_suffix(t2_rank)})" if t2_rank > 0 else ""
                                st.markdown(
                                    f"""
                                    <div style='background: linear-gradient(90deg, rgba(0,204,0,0.1) 0%, rgba(0,204,0,0.05) 100%); 
                                                border-left: 4px solid #00CC00; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                                        <div style='font-weight: bold; color: #00CC00;'>{idx + 1}. {stat}</div>
                                        <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                            {period_label1}: <span style='font-weight: bold; color: #00FF00;'>{t1_val_str}</span> {t1_ord}
                                            <span style='color: #888;'>vs</span> 
                                            {period_label2}: <span style='font-weight: bold;'>{t2_val_str}</span> {t2_ord}
                                        </div>
                                        <div style='font-size: 0.85em; color: #00DD00; margin-top: 4px;'>
                                            +{val_diff:.1f} higher
                                        </div>
                                    </div>
                                    """,
                                    unsafe_allow_html=True
                                )
                            else:
                                # Show rank difference for different teams
                                rank_diff = int(t2_rank - t1_rank)
                                t1_ord = f"{t1_rank}{get_ordinal_suffix(t1_rank)}"
                                t2_ord = f"{t2_rank}{get_ordinal_suffix(t2_rank)}"
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
                        if is_same_team_comparison:
                            st.info(f"No {attribute_group} stats higher in {period_label1}")
                        else:
                            st.info(f"No {attribute_group} stats where {team1} ranks higher")
                
                with col2:
                    if is_same_team_comparison:
                        st.markdown(f"<h4 style='color: #FF4444;'>{_svg_inline('chart_trend', 24)} Higher in {period_label2}</h4>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<h4 style='color: #FF4444;'>{_svg_inline('chart_trend', 20)} {team1} – Weaknesses</h4>", unsafe_allow_html=True)
                    if len(team1_weaknesses_attr) > 0:
                        for idx, item in enumerate(team1_weaknesses_attr):
                            stat = item["stat"]
                            t1_val = item["t1_val"]
                            t1_rank = item["t1_rank"]
                            t2_val = item["t2_val"]
                            t2_rank = item["t2_rank"]
                            
                            try:
                                t1_val_str = f"{float(t1_val):.1f}"
                                t2_val_str = f"{float(t2_val):.1f}"

                            except Exception:
                                t1_val_str = str(t1_val)
                                t2_val_str = str(t2_val)
                            
                            if is_same_team_comparison:
                                # Show value difference for same-team comparison
                                val_diff = float(t2_val) - float(t1_val)
                                t1_ord = f"({t1_rank}{get_ordinal_suffix(t1_rank)})" if t1_rank > 0 else ""
                                t2_ord = f"({t2_rank}{get_ordinal_suffix(t2_rank)})" if t2_rank > 0 else ""
                                st.markdown(
                                    f"""
                                    <div style='background: linear-gradient(90deg, rgba(255,68,68,0.1) 0%, rgba(255,68,68,0.05) 100%); 
                                                border-left: 4px solid #FF4444; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                                        <div style='font-weight: bold; color: #FF4444;'>{idx + 1}. {stat}</div>
                                        <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                            {period_label1}: <span style='font-weight: bold;'>{t1_val_str}</span> {t1_ord}
                                            <span style='color: #888;'>vs</span> 
                                            {period_label2}: <span style='font-weight: bold; color: #FF6666;'>{t2_val_str}</span> {t2_ord}
                                        </div>
                                        <div style='font-size: 0.85em; color: #FF6666; margin-top: 4px;'>+{val_diff:.1f} higher in {period_label2}</div>
                                    </div>
                                    """,
                                    unsafe_allow_html=True
                                )
                            else:
                                # Show rank difference for different teams
                                rank_diff = int(t1_rank - t2_rank)
                                t1_ord = f"{t1_rank}{get_ordinal_suffix(t1_rank)}"
                                t2_ord = f"{t2_rank}{get_ordinal_suffix(t2_rank)}"
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
                        if is_same_team_comparison:
                            st.info(f"No {attribute_group} stats higher in {period_label2}")
                        else:
                            st.info(f"No {attribute_group} stats where {team2} ranks higher")
    
    # Export section
    st.markdown("---")
    render_export_button("team-compare", f"TeamCompare_{team1}_vs_{team2}")


# ================= CLUB LIST =================
elif page == "Club List":
    render_page_header("Club List", "Complete Team Roster", "list")

    # ---------- Season selector ----------
    seasons = sorted(get_player_seasons(), reverse=True)
    if not seasons:
        st.error("No player seasons found.")
        st.stop()

    default_season_idx = seasons.index(CURRENT_SEASON) if CURRENT_SEASON in seasons else 0
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
            fc_mode = st.toggle("FC Rating Mode", key="club_list_fc_mode", help="Convert trait ratings to FIFA/FC style 50-99 scale")
    
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
        st.session_state.club_list_full = True

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

    # Calculate TPP OUTPUT (% of Team * TPP value, minimum $110,000 per player)
    MIN_PLAYER_PAYMENT = 110_000
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
    # Use the appropriate rating column for color scaling (league-wide, exclude 0-match players)
    played_mask = pd.to_numeric(season_df["Matches"], errors="coerce").fillna(0) > 0
    league_ratings = season_df.loc[played_mask, display_rating_col].dropna() if display_rating_col in season_df.columns else season_df.loc[played_mask, "RatingPoints_Avg"].dropna()
    
    # Convert league ratings to FC mode for proper color scaling
    if rating_type == "Trait Rating" and fc_mode:
        league_ratings = league_ratings.apply(convert_trait_to_fc_rating).dropna()

    # League-wide coaches votes for percentile colour bands (exclude 0-match and 0-vote players)
    if "CoachesVotes_Avg" in season_df.columns:
        _cv_vals = pd.to_numeric(season_df.loc[played_mask, "CoachesVotes_Avg"], errors="coerce")
        league_coaches = _cv_vals[_cv_vals > 0].dropna()
    else:
        league_coaches = pd.Series(dtype=float)
    
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
        matches_val_raw = r["MATCHES"]
        has_played = not pd.isna(matches_val_raw) and int(matches_val_raw) > 0
        if has_played:
            bg, fg = rating_colour_for_value(rating_val, league_ratings)
        else:
            bg, fg = "#444444", "#999999"  # Grey pill for unplayed

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
        if has_played and not pd.isna(coaches_val) and float(coaches_val) > 0:
            cv_bg, cv_fg = rating_colour_for_value(float(coaches_val), league_coaches)
        elif has_played:
            cv_bg, cv_fg = "#FF0000", "white"  # Red pill for played but 0 votes
        else:
            cv_bg, cv_fg = "#444444", "#999999"

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
<td><span class="ct-pill" style="background:{bg}; color:{fg};">{rating_str}</span></td>
<td>{r['COMP RANK']}</td>
<td>{r['POS RANK']}</td>
<td><span class="ct-pill" style="background:{cv_bg}; color:{cv_fg};">{coaches_str}</span></td>
<td>{tog_str}</td>
<td>{ratings_total_str}</td>
<td>{pct_team_str}</td>
<td class="ct-cap">{tpp_output_str}</td>
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

    render_page_header("Player Profile", "Individual Player Analysis", "person")
    
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

    # Fill Age_Decimal gaps from Age (e.g. 2026 CSV has Age but not Age_Decimal)
    if "Age_Decimal" in players_full.columns and "Age" in players_full.columns:
        players_full["Age_Decimal"] = pd.to_numeric(players_full["Age_Decimal"], errors="coerce")
        players_full["Age"] = pd.to_numeric(players_full["Age"], errors="coerce")
        players_full["Age_Decimal"] = players_full["Age_Decimal"].fillna(players_full["Age"])

    # -----------------------------------
    # Season filter - default to current season
    # -----------------------------------
    seasons_available = sorted(players_full["Season"].dropna().unique().tolist(), reverse=True)
    if not seasons_available:
        st.error("No valid seasons available.")
        st.stop()

    default_season_idx = seasons_available.index(CURRENT_SEASON) if CURRENT_SEASON in seasons_available else 0
    
    # Season and FC Mode controls in columns
    ctrl_col1, ctrl_col2 = st.columns([2, 1])
    with ctrl_col1:
        selected_season = st.selectbox("Select Season", seasons_available, index=default_season_idx, key="pp_season")
    with ctrl_col2:
        fc_mode = st.toggle("FC Rating Mode (50-99)", key="pp_fc_mode", help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")

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

    # Get all seasons for this player (including nickname variants like Cam/Cameron)
    player_name_variants = build_player_name_variants(selected_player)
    player_data_all = players_full[players_full["Player"].isin(player_name_variants)].copy()
    if player_data_all.empty:
        st.info("No data found for this player.")
        st.stop()
    
    # Normalize the Player name to the selected variant for consistency
    player_data_all["Player"] = selected_player

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

    display_player_photo(selected_player, col_photo, use_container_width=True, team_name=selected_team)

    # Summary meta
    summary_df = load_player_summary()
    if summary_df is None or summary_df.empty or "Player" not in summary_df.columns:
        summary_match = pd.DataFrame()
    else:
        summary_match = summary_df[summary_df["Player"].isin(player_name_variants)]

    summary_row = summary_match.iloc[0] if not summary_match.empty else None

    latest_position = latest_record.get("Position", "")
    latest_matches = latest_record.get("Matches", None)

    # Age: prefer season data (more current), fall back to summary
    age_summary = None
    _season_age = latest_record.get("Age", None)
    if _season_age is not None and not (isinstance(_season_age, float) and pd.isna(_season_age)):
        age_summary = _season_age
    if age_summary is None and summary_row is not None:
        age_summary = summary_row.get("Age")

    draft_year = None
    if summary_row is not None:
        draft_year = summary_row.get("Draft Year") if "Draft Year" in summary_row.index else summary_row.get("Draft")

    draft_no = summary_row.get("Draft #") if summary_row is not None else None
    height_summary = summary_row.get("Height") if summary_row is not None else None
    total_matches = summary_row.get("Total Matches") if summary_row is not None else None
    rating_pct_2025 = None
    cap_value_2025 = None
    _rating_pct_label = f"{CURRENT_SEASON} RATING %"
    _cap_val_label = f"{CURRENT_SEASON} CAP VALUE"
    if summary_row is not None:
        # Try current season columns first, fall back to 2025
        for _yr in [CURRENT_SEASON, 2025]:
            if rating_pct_2025 is None:
                rating_pct_2025 = summary_row.get(f"{_yr} Rating %")
                if rating_pct_2025 is not None and pd.notna(rating_pct_2025):
                    _rating_pct_label = f"{_yr} RATING %"
                    _rating_pct_col = f"{_yr} Rating %"
                else:
                    rating_pct_2025 = None
            if cap_value_2025 is None:
                cap_value_2025 = summary_row.get(f"{_yr} Cap Value")
                if cap_value_2025 is not None and pd.notna(cap_value_2025):
                    _cap_val_label = f"{_yr} CAP VALUE"
                else:
                    cap_value_2025 = None

    # Load Contract Expiry and FA Status from Footywire data
    contract_expiry = None
    fa_status = None
    footywire_path = Path(__file__).parent / "data" / "raw" / "player" / "footywire_2026_complete.csv"
    if footywire_path.exists():
        try:
            fw_df = pd.read_csv(footywire_path)
            fw_df["Player"] = fw_df["Player"].astype(str).str.strip()
            fw_df["Team"] = fw_df["Team"].astype(str).str.strip()
            fw_match = fw_df[(fw_df["Player"].isin(player_name_variants)) & (fw_df["Team"] == latest_team)]
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

    # RATING %
    if rating_pct_2025 not in [None, ""] and pd.notna(rating_pct_2025):
        try:
            rating_pct_val = float(rating_pct_2025)
            _rp_col = _rating_pct_col if '_rating_pct_col' in dir() else f"{CURRENT_SEASON} Rating %"
            rating_pct_values = summary_df[_rp_col].dropna() if summary_df is not None and _rp_col in summary_df.columns else pd.Series(dtype=float)
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
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>{_rating_pct_label}</div>
                <div style='color: {pct_fg}; font-size: 1.4em; font-weight: 700;'>{rating_pct_val:.1f}%</div>
            </div>
            """)
        except Exception:
            stats_grid.append(f"""
            <div style='background: rgba(0,0,0,0.3); padding: 10px; border-radius: 6px; text-align: center;
                        border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>{_rating_pct_label}</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{rating_pct_2025}%</div>
            </div>
            """)

    # CAP VALUE
    if cap_value_2025 not in [None, ""] and pd.notna(cap_value_2025):
        try:
            cap_val = float(cap_value_2025)
            stats_grid.append(f"""
            <div style='background: rgba(100,100,100,0.2); padding: 10px; border-radius: 6px; text-align: center;
                        border: 1px solid rgba(100,100,100,0.5);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>{_cap_val_label}</div>
                <div style='color: rgba(255, 255, 255, 0.95); font-size: 1.4em; font-weight: 700;'>${cap_val:,.0f}</div>
            </div>
            """)
        except Exception:
            stats_grid.append(f"""
            <div style='background: rgba(100,100,100,0.2); padding: 10px; border-radius: 6px; text-align: center;
                        border: 1px solid rgba(100,100,100,0.5);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>{_cap_val_label}</div>
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
    st.markdown(f"<h3 style='color: #FFFFFF; margin-bottom: 15px;'>{_svg_inline('chart_bar', 24)} Rating by Season</h3>", unsafe_allow_html=True)

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
    st.markdown(f"<h3 style='color: #FFFFFF; margin-bottom: 15px;'>{_svg_inline('scorecard', 24)} Performance Projection (Next 5 Years)</h3>", unsafe_allow_html=True)

    try:
        latest_rating_val = float(latest_record.get("RatingPoints_Avg", 0)) if pd.notna(latest_record.get("RatingPoints_Avg")) else 0
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
                        alt.Tooltip("Lower_Band:Q", format=".1f", title="Lower"),
                        alt.Tooltip("Upper_Band:Q", format=".1f", title="Upper"),
                    ],
                )
            )

            line = (
                alt.Chart(pred)
                .mark_line(point=True, color="steelblue", size=3)
                .encode(
                    x=alt.X("Year:O"),
                    y=alt.Y("Predicted_Rating:Q", title="Rating", scale=alt.Scale(zero=False)),
                    tooltip=["Year", alt.Tooltip("Predicted_Rating:Q", format=".1f")],
                )
            )

            # Overlay historical ratings — rename Season→Year so both layers
            # share the same ordinal x-axis and align properly.
            hist_chart = None
            if not plot_df.empty:
                hist_df = plot_df.reset_index(drop=True).copy()
                hist_df["Year"] = hist_df["Season"]
                hist_chart = (
                    alt.Chart(hist_df)
                    .mark_circle(color="gray", size=100, opacity=0.6)
                    .encode(
                        x=alt.X("Year:O", title="Year"),
                        y=alt.Y("RatingPoints_Avg:Q", title="Rating"),
                        tooltip=[alt.Tooltip("Year:O", title="Season"), alt.Tooltip("RatingPoints_Avg:Q", format=".1f", title="Historical Rating")],
                    )
                )

            combined = band + line
            if hist_chart is not None:
                combined = combined + hist_chart

            st.altair_chart(combined.properties(height=300).interactive(), width="stretch")

            with st.expander("View Detailed Predictions", expanded=False):
                pred_table = pred.copy()
                for c in ["Predicted_Rating", "Upper_Band", "Lower_Band"]:
                    if c in pred_table.columns:
                        pred_table[c] = pd.to_numeric(pred_table[c], errors="coerce").round(1)
                # Build fe-table styled HTML to match Contract Status
                pred_html = "<table class='fe-table fe-sortable'><thead><tr>"
                for col in pred_table.columns:
                    pred_html += f"<th>{col}</th>"
                pred_html += "</tr></thead><tbody>"
                for _, row in pred_table.iterrows():
                    pred_html += "<tr>"
                    for col in pred_table.columns:
                        val = row[col]
                        if pd.isna(val):
                            pred_html += "<td>—</td>"
                        elif col in ('Predicted_Rating', 'Upper_Band', 'Lower_Band') and isinstance(val, (int, float)):
                            bg_color, text_color = rating_colour_for_value(float(val), all_ratings)
                            pred_html += f"<td><span class='ct-pill' style='background:{bg_color};color:{text_color};'>{val:.1f}</span></td>"
                        elif isinstance(val, float):
                            pred_html += f"<td>{val:.1f}</td>"
                        else:
                            pred_html += f"<td>{val}</td>"
                    pred_html += "</tr>"
                pred_html += "</tbody></table>"
                render_sortable_table(pred_html)
        else:
            st.info("Unable to generate performance projection with available data.")
    except Exception as e:
        st.warning(f"Could not generate performance projection: {str(e)}")

    # -----------------------------------
    # Player Season Data (HTML table)
    # -----------------------------------
    st.markdown("---")
    st.markdown(f"<h3 style='color: #CCCCCC; margin-bottom: 15px;'>{_svg_inline('list', 24)} Player Season Data</h3>", unsafe_allow_html=True)

    player_table = plot_df.copy()
    if player_table.empty:
        st.info("No season rows to show.")
    else:
        # Prefer Age_Decimal but fill gaps from Age (e.g. 2026 data has Age but not Age_Decimal)
        if "Age_Decimal" in player_table.columns and "Age" in player_table.columns:
            player_table["Age_Decimal"] = pd.to_numeric(player_table["Age_Decimal"], errors="coerce")
            player_table["Age"] = pd.to_numeric(player_table["Age"], errors="coerce")
            player_table["Age_Decimal"] = player_table["Age_Decimal"].fillna(player_table["Age"])
        age_col = "Age_Decimal" if "Age_Decimal" in player_table.columns else ("Age" if "Age" in player_table.columns else None)
        if age_col:
            player_table[age_col] = pd.to_numeric(player_table[age_col], errors="coerce").round(1)

        player_table["RatingPoints_Avg"] = pd.to_numeric(player_table["RatingPoints_Avg"], errors="coerce").round(1)

        # Include CoachesVotes_Avg if available
        if "CoachesVotes_Avg" in player_table.columns:
            player_table["CoachesVotes_Avg"] = pd.to_numeric(player_table["CoachesVotes_Avg"], errors="coerce").round(2)
        else:
            player_table["CoachesVotes_Avg"] = np.nan

        # Merge Trait Rating per season (traits data only exists from 2021 onwards)
        trait_ratings = []
        for _, row in player_table.iterrows():
            s = int(row["Season"])
            if s < 2021:
                trait_ratings.append(np.nan)
                continue
            try:
                t_df = load_traits(s)
                if t_df is not None and not t_df.empty and "Player_Full" in t_df.columns:
                    t_match = match_player_name_to_traits(selected_player, t_df, row.get("Team", ""))
                    if not t_match.empty and "Rating" in t_match.columns:
                        trait_ratings.append(safe_float(t_match.iloc[0]["Rating"]))
                    else:
                        trait_ratings.append(np.nan)
                else:
                    trait_ratings.append(np.nan)
            except Exception:
                trait_ratings.append(np.nan)
        player_table["Trait_Rating"] = trait_ratings

        cols = [c for c in ["Season", "Team", "Position", age_col, "Matches", "RatingPoints_Avg", "CoachesVotes_Avg", "Trait_Rating"] if c and c in player_table.columns]
        player_table = player_table[cols].drop_duplicates().reset_index(drop=True)

        # Fill NaN positions from nearest adjacent season (forward then backward)
        if "Position" in player_table.columns:
            player_table = player_table.sort_values("Season").reset_index(drop=True)
            pos_series = player_table["Position"].copy()
            pos_series = pos_series.replace({"nan": np.nan, "": np.nan})
            pos_series = pos_series.where(pos_series.notna() & (pos_series != "nan"), other=np.nan)
            # Forward fill first (use earlier season), then back fill (use later season)
            pos_series = pos_series.ffill().bfill()
            player_table["Position"] = pos_series
            player_table = player_table.sort_values("Season", ascending=False).reset_index(drop=True)

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
        rename_map["Trait_Rating"] = "Trait Rating"
        rename_map["CoachesVotes_Avg"] = "Coaches Votes"
        player_table = player_table.rename(columns=rename_map)

        # Final column order: Season, Team, Position, Age, Matches, Rating, Comp Rank, Pos Rank, Trait Rating, Coaches Votes
        ordered_cols = ["Season", "Team", "Position", "Age", "Matches", "Rating", "Comp Rank", "Pos Rank", "Trait Rating", "Coaches Votes"]
        ordered_cols = [c for c in ordered_cols if c in player_table.columns]
        player_table = player_table[ordered_cols]

        # Uses unified .fe-table CSS
        html_season_table = """
        <table class='fe-table fe-table-striped fe-sortable'>
        <thead><tr>
        """
        for col in player_table.columns:
            html_season_table += f"<th>{col}</th>"
        html_season_table += "</tr></thead><tbody>"

        all_comp_ratings = players_full["RatingPoints_Avg"].dropna()

        # League-wide coaches votes for percentile-based colouring (only players with votes > 0)
        if "CoachesVotes_Avg" in players_full.columns:
            _cv = pd.to_numeric(players_full["CoachesVotes_Avg"], errors="coerce")
            all_coaches_votes = _cv[_cv > 0].dropna()
        else:
            all_coaches_votes = pd.Series(dtype=float)

        # Gather all trait ratings across seasons for percentile-based colouring
        all_trait_ratings_list = []
        for s in player_table["Season"].unique():
            try:
                _t_df = load_traits(int(s))
                if _t_df is not None and not _t_df.empty and "Rating" in _t_df.columns:
                    all_trait_ratings_list.append(pd.to_numeric(_t_df["Rating"], errors="coerce"))
            except Exception:
                pass
        all_trait_ratings = pd.concat(all_trait_ratings_list).dropna() if all_trait_ratings_list else pd.Series(dtype=float)

        for _, row in player_table.iterrows():
            html_season_table += "<tr>"
            for col in player_table.columns:
                val = row[col]
                if col == "Rating":
                    if pd.notna(val):
                        bg_color, text_color = rating_colour_for_value(float(val), all_comp_ratings)
                        html_season_table += f"<td><span class='ct-pill' style='background:{bg_color};color:{text_color};'>{float(val):.1f}</span></td>"
                    else:
                        html_season_table += "<td>–</td>"
                elif col == "Trait Rating":
                    if pd.notna(val):
                        bg_color, text_color = rating_colour_for_value(float(val), all_trait_ratings)
                        html_season_table += f"<td><span class='ct-pill' style='background:{bg_color};color:{text_color};'>{float(val):.2f}</span></td>"
                    else:
                        html_season_table += "<td>–</td>"
                elif col == "Coaches Votes":
                    if pd.notna(val) and float(val) > 0:
                        cv_bg, cv_fg = rating_colour_for_value(float(val), all_coaches_votes)
                        html_season_table += f"<td><span class='ct-pill' style='background:{cv_bg};color:{cv_fg};'>{float(val):.2f}</span></td>"
                    else:
                        html_season_table += "<td>–</td>"
                elif col == "Age":
                    if pd.notna(val):
                        html_season_table += f"<td>{float(val):.1f}</td>"
                    else:
                        html_season_table += "<td>–</td>"
                else:
                    html_season_table += f"<td>{val}</td>"
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
                    except Exception:
                        return "#9E9E9E", "—"
                
                # Header
                st.markdown(f"""
                <div style='display: flex; align-items: center; margin-bottom: 20px; margin-top: 20px;'>
                    <span style='font-size: 1.5em; margin-right: 12px;'>{_svg_inline('star', 20)}</span>
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
    # Full Player Traits section - big card UI
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

        _traits_season = int(selected_season)
        traits_sel = load_traits(_traits_season)
        if traits_sel is not None and not traits_sel.empty and "Player_Full" in traits_sel.columns:
            # Use smart matching function to handle abbreviated names
            player_traits_sel = match_player_name_to_traits(selected_player, traits_sel, latest_team)

            if "Season" in player_traits_sel.columns:
                player_traits_sel["Season"] = pd.to_numeric(player_traits_sel["Season"], errors="coerce")
                player_traits_sel = player_traits_sel[player_traits_sel["Season"] == _traits_season]

            if not player_traits_sel.empty:
                player_trait = player_traits_sel.iloc[0]

                rating = player_trait.get("Rating", None)
                ball_winning = player_trait.get("Ball Winning", None)
                ball_use = player_trait.get("Ball Use", None)
                aerial = player_trait.get("Aerial", None)
                defence = player_trait.get("Defence", None)
                _pos_raw = player_trait.get("Position_Full", None)
                if _pos_raw is None or (isinstance(_pos_raw, float) and pd.isna(_pos_raw)):
                    _pos_raw = player_trait.get("Position", None)
                if _pos_raw is None or (isinstance(_pos_raw, float) and pd.isna(_pos_raw)):
                    _pos_raw = latest_position
                position = _pos_raw

                # ---------------------------
                # KPI CARDS (FIXED POSITION RANK)
                # ---------------------------

                all_traits_sorted = traits_sel.copy()

                # Ensure we only use selected season rows if Season exists
                if "Season" in all_traits_sorted.columns:
                    all_traits_sorted["Season"] = pd.to_numeric(all_traits_sorted["Season"], errors="coerce")
                    all_traits_sorted = all_traits_sorted[all_traits_sorted["Season"] == _traits_season]

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
                        overall_rank = int(all_traits_sorted[all_traits_sorted["Player_Full"].isin(player_name_variants)].index[0] + 1)
                    except Exception:
                        overall_rank = int((all_traits_sorted["Rating"] >= rv).sum())

                # ---- Position rank (WITHIN position group) ----
                pos_df = pd.DataFrame()
                pos_col = "Position_Full" if "Position_Full" in all_traits_sorted.columns else ("Position" if "Position" in all_traits_sorted.columns else None)

                if rv is not None and pos_col and position not in [None, ""] and not pd.isna(position) and not all_traits_sorted.empty:
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
                            position_rank = int(pos_df[pos_df["Player_Full"].isin(player_name_variants)].index[0] + 1)
                        except Exception:
                            position_rank = int((pos_df["Rating"] >= rv).sum())

                # ---------------------------
                # Render Professional KPI Dashboard
                # ---------------------------
                
                st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
                
                # Header
                st.markdown(f"""
                <div style='display: flex; align-items: center; justify-content: center; margin-bottom: 20px;'>
                    <span style='font-size: 1.5em; margin-right: 12px;'>⭐</span>
                    <h3 style='color: #FFFFFF; margin: 0; font-size: 1.4em; font-weight: 700;'>Performance Rankings</h3>
                    <span style='margin-left: 12px; background: rgba(255,215,0,0.2); padding: 4px 12px; border-radius: 20px; font-size: 0.85em; color: #FFD700;'>{_traits_season}</span>
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
                st.markdown(f"""
                <div style='display: flex; align-items: center; justify-content: center; margin-bottom: 24px;'>
                    <span style='font-size: 1.5em; margin-right: 12px;'>{_svg_inline('chart_bar', 20)}</span>
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

    # -----------------------------------
    # Traits History (by season) - adapted from Player Traits page
    # -----------------------------------
    try:
        traits_history_seasons = sorted(get_traits_seasons(), reverse=True)
        # Also include CSV-based seasons (2026+)
        for _ts_year in range(CURRENT_SEASON, 2020, -1):
            _ts_csv = Path(__file__).parent / "data" / "raw" / "traits" / f"traits_{_ts_year}.csv"
            if _ts_csv.exists() and _ts_year not in traits_history_seasons:
                traits_history_seasons.append(_ts_year)
        traits_history_seasons = sorted(set(traits_history_seasons), reverse=True)

        if traits_history_seasons:
            traits_hist_parts = []
            for _thy in traits_history_seasons:
                _th_df = load_traits(int(_thy))
                if _th_df is None or _th_df.empty:
                    continue
                _th_df = _th_df.copy()
                if "Season" not in _th_df.columns:
                    _th_df["Season"] = int(_thy)
                _th_df["Season"] = pd.to_numeric(_th_df["Season"], errors="coerce").fillna(int(_thy)).astype(int)
                _th_variants = build_player_name_variants(selected_player)
                if "Player_Full" in _th_df.columns:
                    _th_df = _th_df[_th_df["Player_Full"].astype(str).isin(_th_variants)]
                elif "Player" in _th_df.columns:
                    _th_df = _th_df[_th_df["Player"].astype(str).isin(_th_variants)]
                else:
                    continue
                if not _th_df.empty:
                    traits_hist_parts.append(_th_df)

            traits_hist_df = pd.concat(traits_hist_parts, ignore_index=True) if traits_hist_parts else pd.DataFrame()

            if not traits_hist_df.empty:
                st.markdown("<div style='margin-top: 40px;'></div>", unsafe_allow_html=True)
                st.markdown("""
                <div style='display: flex; align-items: center; margin-bottom: 20px;'>
                    <span style='font-size: 1.5em; margin-right: 12px;'>📊</span>
                    <h3 style='color: #FFFFFF; margin: 0; font-size: 1.4em; font-weight: 700;'>Traits History</h3>
                </div>
                """, unsafe_allow_html=True)

                _th_cols = ["Season", "Team_Full", "Position_Full", "Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
                _th_cols = [c for c in _th_cols if c in traits_hist_df.columns]
                _th_view = traits_hist_df[_th_cols].copy()

                for _thc in ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
                    if _thc in _th_view.columns:
                        _th_view[_thc] = pd.to_numeric(_th_view[_thc], errors="coerce")

                _th_view = _th_view.sort_values("Season", ascending=False).reset_index(drop=True)

                # Get league ratings for conditional formatting
                try:
                    _th_league_df = load_traits(CURRENT_SEASON)
                    if _th_league_df is not None and not _th_league_df.empty and "Rating" in _th_league_df.columns:
                        _th_league_ratings = pd.to_numeric(_th_league_df["Rating"], errors="coerce").dropna()
                    else:
                        _th_league_ratings = pd.to_numeric(_th_view["Rating"], errors="coerce").dropna() if "Rating" in _th_view.columns else pd.Series(dtype=float)
                except Exception:
                    _th_league_ratings = pd.to_numeric(_th_view["Rating"], errors="coerce").dropna() if "Rating" in _th_view.columns else pd.Series(dtype=float)

                # League-wide sub-trait distributions for pill colouring
                _th_subtrait_series = {}
                for _st_col in ["Ball Winning", "Ball Use", "Aerial", "Defence"]:
                    try:
                        if _th_league_df is not None and _st_col in _th_league_df.columns:
                            _th_subtrait_series[_st_col] = pd.to_numeric(_th_league_df[_st_col], errors="coerce").dropna()
                        else:
                            _th_subtrait_series[_st_col] = pd.to_numeric(_th_view[_st_col], errors="coerce").dropna() if _st_col in _th_view.columns else pd.Series(dtype=float)
                    except Exception:
                        _th_subtrait_series[_st_col] = pd.Series(dtype=float)

                def _th_fmt(x):
                    if pd.isna(x):
                        return "—"
                    if fc_mode:
                        fc_val = convert_trait_to_fc_rating(x)
                        return str(fc_val) if fc_val is not None else "—"
                    return f"{float(x):.2f}"

                _th_html = '<table class="fe-table fe-table-striped fe-sortable"><thead><tr>'
                for c in _th_view.columns:
                    _th_html += f"<th>{str(c).replace('_', ' ')}</th>"
                _th_html += "</tr></thead><tbody>"

                for _, _th_row in _th_view.iterrows():
                    _th_html += "<tr>"
                    for c in _th_view.columns:
                        if c == "Rating":
                            v = _th_row.get(c, np.nan)
                            if pd.notna(v) and len(_th_league_ratings) > 0:
                                bg, fg = rating_colour_for_value(float(v), _th_league_ratings)
                                _th_html += f"<td><span class='ct-pill' style='background:{bg};color:{fg};'>{_th_fmt(v)}</span></td>"
                            else:
                                _th_html += "<td>—</td>"
                        elif c in ["Ball Winning", "Ball Use", "Aerial", "Defence"]:
                            v = _th_row.get(c, np.nan)
                            if pd.notna(v) and c in _th_subtrait_series and len(_th_subtrait_series[c]) > 0:
                                bg, fg = rating_colour_for_value(float(v), _th_subtrait_series[c])
                                _th_html += f"<td><span class='ct-pill' style='background:{bg};color:{fg};'>{_th_fmt(v)}</span></td>"
                            else:
                                _th_html += f"<td>{_th_fmt(v)}</td>"
                        else:
                            _th_html += f"<td>{_th_row.get(c, '—')}</td>"
                    _th_html += "</tr>"

                _th_html += "</tbody></table>"
                render_sortable_table(_th_html)
    except Exception:
        pass

    # Professional footer
    render_footer()


# ================= DEPTH CHART =================

elif page == "Depth Chart":
    render_page_header("Depth Chart", "Positional Player Rankings", "depth_chart")

    # Depth Chart needs FULL roster data including Wings and players who didn't play
    # Always load from Excel Summary sheet (not computed CSV which only has players who played)
    summary_df = _load_player_summary_excel()
    if summary_df.empty:
        st.error("Could not load Summary sheet from AFL Player Ratings.")
        st.stop()
    
    # ------------------------------------------------------------------
    # 2026+ SQUAD OVERLAY: Use current-season squad list, merge 2025 ratings
    # ------------------------------------------------------------------
    _depth_using_2026_squad = False
    if CURRENT_SEASON >= 2026:
        try:
            from pathlib import Path as _P
            _squad_csv = _P(__file__).parent / "data" / "raw" / "player" / f"squads_{CURRENT_SEASON}.csv"
            if _squad_csv.exists():
                _sq = pd.read_csv(_squad_csv)
                _sq.columns = _sq.columns.astype(str).str.strip()
                # Compute exact Age_Decimal from DOB before rename
                _sq = _compute_age_decimal_from_dob(_sq, CURRENT_SEASON)
                # Rename columns to match Summary schema
                _matches_col = f"{CURRENT_SEASON} Matches"
                _rn = {"Matches_Career": "Total Matches", "Age_Decimal": "Age_Dec",
                       "Matches_Current": _matches_col}
                _sq = _sq.rename(columns={k: v for k, v in _rn.items() if k in _sq.columns})
                if "Jumper" not in _sq.columns and "JumperNumber" in _sq.columns:
                    _sq = _sq.rename(columns={"JumperNumber": "Jumper"})
                # Convert string Age like "24yr, 152d" to numeric
                if "Age_Dec" in _sq.columns:
                    _sq["Age"] = pd.to_numeric(_sq["Age_Dec"], errors="coerce")
                elif "Age" in _sq.columns:
                    _sq["Age"] = _sq["Age"].apply(
                        lambda x: float(str(x).split("yr")[0].strip())
                        if pd.notna(x) and "yr" in str(x)
                        else pd.to_numeric(x, errors="coerce")
                    )
                # Normalise team names
                _sq["Team"] = _sq["Team"].astype(str).str.strip().replace({
                    "GWS": "GWS Giants", "Greater Western Sydney": "GWS Giants"
                })
                _sq["Player"] = _sq["Player"].astype(str).str.strip()
                
                # Merge rating columns AND detailed Position from Summary (ratings as fallback)
                _rating_cols_to_merge = []
                for _rc in [str(CURRENT_SEASON), CURRENT_SEASON, "2025", 2025, "Last 2 Average", "Career", f"{CURRENT_SEASON} Matches", "2025 Matches", "Total Matches"]:
                    if _rc in summary_df.columns and _rc not in _rating_cols_to_merge:
                        _rating_cols_to_merge.append(_rc)
                
                # Also grab detailed Position from Summary (Key Defender, Wing, etc.)
                _merge_cols = list(_rating_cols_to_merge)
                if "Position" in summary_df.columns:
                    _merge_cols.append("Position")
                
                if _merge_cols:
                    _sum_subset = summary_df[["Player", "Team"] + _merge_cols].copy()
                    _sum_subset["Player"] = _sum_subset["Player"].astype(str).str.strip()
                    _sum_subset["Team"] = _sum_subset["Team"].astype(str).str.strip().replace({
                        "GWS": "GWS Giants", "Greater Western Sydney": "GWS Giants"
                    })
                    # Rename Position to avoid collision during merge
                    if "Position" in _sum_subset.columns:
                        _sum_subset = _sum_subset.rename(columns={"Position": "Position_Detail"})
                        _merge_cols = [c if c != "Position" else "Position_Detail" for c in _merge_cols]
                    
                    # First try matching by Player+Team, then by Player only (for traded players)
                    _sq = _sq.merge(_sum_subset, on=["Player", "Team"], how="left", suffixes=("", "_sum"))
                    # For players who moved teams, try matching by name only
                    _first_rating = _rating_cols_to_merge[0] if _rating_cols_to_merge else None
                    _unmatched = _sq[_sq[_first_rating].isna()]["Player"].tolist() if _first_rating else []
                    if _unmatched:
                        _sum_name_only = _sum_subset.drop_duplicates(subset=["Player"], keep="first")
                        _sum_name_only = _sum_name_only.set_index("Player")[_merge_cols]
                        for _um_player in _unmatched:
                            if _um_player in _sum_name_only.index:
                                for _col in _merge_cols:
                                    _sq.loc[_sq["Player"] == _um_player, _col] = _sum_name_only.loc[_um_player, _col]
                    
                    # ── Fuzzy name matching for remaining unmatched ──
                    # Catches case differences (Van Rooyen vs van Rooyen)
                    # and nickname variants (Lachlan ↔ Lachie, Matt ↔ Matthew, etc.)
                    _still_na = _sq[_sq[_first_rating].isna()]["Player"].tolist() if _first_rating else []
                    if _still_na:
                        # Use centralized PLAYER_NICKNAME_MAP from config.constants
                        # Build case-insensitive + nickname lookup from summary
                        # Key: (normalised_name, team_lower) → row index in _sum_subset
                        _fuzzy_lookup = {}
                        for _si, _sr in _sum_subset.iterrows():
                            _sp = str(_sr["Player"]).strip()
                            _st = str(_sr["Team"]).strip().lower()
                            # Exact name (case-insensitive)
                            _fuzzy_lookup[(_sp.lower(), _st)] = _si
                            # Also register all nickname variants of first name
                            _parts = _sp.split()
                            if len(_parts) >= 2:
                                _surname = " ".join(_parts[1:])
                                for _variant in get_nickname_variants(_parts[0]):
                                    _variant_name = _variant + " " + _surname
                                    _fuzzy_lookup[(_variant_name.lower(), _st)] = _si

                        for _um_player in _still_na:
                            _um_team = _sq.loc[_sq["Player"] == _um_player, "Team"]
                            if _um_team.empty:
                                continue
                            _um_team_val = str(_um_team.iloc[0]).strip().lower()
                            _key = (_um_player.strip().lower(), _um_team_val)
                            if _key in _fuzzy_lookup:
                                _match_idx = _fuzzy_lookup[_key]
                                for _col in _merge_cols:
                                    _sq.loc[_sq["Player"] == _um_player, _col] = _sum_subset.loc[_match_idx, _col]
                    # ─────────────────────────────────────────────
                    
                    # Use detailed position from Summary where available
                    if "Position_Detail" in _sq.columns:
                        _has_detail = _sq["Position_Detail"].notna()
                        _sq.loc[_has_detail, "Position"] = _sq.loc[_has_detail, "Position_Detail"]
                        _sq.drop(columns=["Position_Detail"], inplace=True)
                
                # Clean up any suffix columns
                for _c in list(_sq.columns):
                    if _c.endswith("_sum"):
                        _sq.drop(columns=[_c], inplace=True)
                
                summary_df = _sq
                _depth_using_2026_squad = True
        except Exception as _e:
            pass  # Fall back to regular Summary sheet
    
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
        f"{CURRENT_SEASON} (latest)": str(CURRENT_SEASON),
        "Last 2 Seasons Average": "Last 2 Average",
        "Career": "Career",
    }
    # The column key may be int or str depending on how the data was loaded
    _rating_key_current = CURRENT_SEASON if CURRENT_SEASON in summary_df.columns else str(CURRENT_SEASON)
    # Also try previous season as fallback
    if _rating_key_current not in summary_df.columns:
        _rating_key_current = 2025 if 2025 in summary_df.columns else "2025"
    rating_options_internal = {
        f"{CURRENT_SEASON} (latest)": _rating_key_current,
        "Last 2 Seasons Average": "Last 2 Average",
        "Career": "Career",
    }
    rating_label = st.selectbox(
        "Which rating to use?",
        list(rating_options.keys()),
        index=0,
    )
    rating_col_name = rating_options_internal[rating_label]

    df_team = summary_df[summary_df["Team"] == selected_team].copy()
    if df_team.empty:
        st.warning("No data for this team in Summary sheet.")
        st.stop()

    if rating_col_name not in df_team.columns:
        # Try alternative key format (int vs str for year columns)
        _alt_key = str(rating_col_name) if isinstance(rating_col_name, int) else rating_col_name
        if _alt_key in df_team.columns:
            rating_col_name = _alt_key
        elif "Career" in df_team.columns:
            st.info(f"Rating column '{rating_col_name}' not found. Using Career ratings.")
            rating_col_name = "Career"
        else:
            st.error(
                f"Column '{rating_col_name}' not found in Summary sheet. "
                "Check the exact header names in the Excel file."
            )
            st.stop()

    df_team["RatingPoints_Avg"] = pd.to_numeric(
        df_team[rating_col_name], errors="coerce"
    )

    # Load player data for ranking calculations
    # Determine which season's data to use based on the actual rating column
    _ranking_season = CURRENT_SEASON
    try:
        _rcn = str(rating_col_name)
        _rating_year = int(_rcn) if _rcn.isdigit() else None
        if _rating_year and 2012 <= _rating_year <= CURRENT_SEASON:
            _ranking_season = _rating_year
    except (ValueError, TypeError):
        pass
    players_ranking_df = load_players(_ranking_season)
    # If the ranking season data is sparse (e.g. early in a new season), fall back to previous season
    if not players_ranking_df.empty and "Matches" in players_ranking_df.columns:
        _avg_matches = pd.to_numeric(players_ranking_df["Matches"], errors="coerce").mean()
        if _avg_matches < 2 and _ranking_season > 2012:
            _fallback = load_players(_ranking_season - 1)
            if not _fallback.empty:
                players_ranking_df = _fallback
    
    # IMPORTANT: df_team (from Summary) is used for DISPLAY - shows ALL squad players
    # This includes players who didn't play (they'll have NaN ratings but still appear)
    # Ensure all players appear even without ratings
    
    # For RANKING calculations: use per-season player data when a specific year is selected
    # Detect if rating_col_name is a year
    _is_year_rating = False
    try:
        _yr = int(rating_col_name) if isinstance(rating_col_name, str) and rating_col_name.isdigit() else (rating_col_name if isinstance(rating_col_name, int) else None)
        _is_year_rating = _yr is not None and 2012 <= _yr <= CURRENT_SEASON
    except (ValueError, TypeError):
        pass

    if _is_year_rating and not players_ranking_df.empty:
        # Use per-season players data for ranking (same data source as List Ladder)
        # Only players who actually played will affect rankings
        ranking_df = players_ranking_df.copy()
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
        # Get matches from Summary - prefer most recent season with meaningful data
        # Check for matches columns in order, preferring ones with actual games played
        _matches_found = False
        for _mc in ['2025 Matches', f'{CURRENT_SEASON} Matches', 'Total Matches']:
            if _mc in ranking_df.columns:
                _m_vals = pd.to_numeric(ranking_df[_mc], errors="coerce").fillna(0)
                if _m_vals.sum() > 0:
                    ranking_df["Matches"] = _m_vals
                    _matches_found = True
                    break
        if not _matches_found:
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

    render_page_header("AFL Team Age Breakdown", "Age Group Performance Analysis")

    # Season filter
    _tab_seasons = sorted(get_player_seasons(), reverse=True)
    selected_season = st.selectbox("Season", _tab_seasons, index=0, key="team_age_breakdown_season")

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
        age_breakdown_table[f"{band}_Rank"] = age_breakdown_table[band].rank(ascending=False, method='min').astype(int)
    
    # Sort by team name
    age_breakdown_table = age_breakdown_table.sort_values("Team").reset_index(drop=True)

    # Compact ranking legend
    st.markdown("""<div style='display:flex; align-items:center; gap:14px; padding:8px 14px; background:rgba(255,255,255,0.03); border-radius:8px; margin-bottom:16px; flex-wrap:wrap;'><span style='color:#888; font-size:0.75em; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>Ranking</span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#008000; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>1-4 Elite</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#90EE90; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>5-7 Good</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#FFD700; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>8-11 Average</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#FFA500; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>12-15 Below Avg</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#FF0000; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>16-18 Poor</span></span></div>""", unsafe_allow_html=True)
    
    # Helper function to get rank color - 5 tier system (returns single color string)
    def get_rank_color_age(rank_val):
        """5-tier system: Elite (1-4), Good (5-7), Average (8-11), Below Avg (12-15), Poor (16-18)"""
        if rank_val <= 4:
            return "#008000"   # Elite - Dark Green
        elif rank_val <= 7:
            return "#90EE90"   # Good - Light Green
        elif rank_val <= 11:
            return "#FFD700"   # Average - Gold
        elif rank_val <= 15:
            return "#FFA500"   # Below Average - Orange
        else:
            return "#FF0000"   # Poor - Red
    
    # Build display columns: Team + age bands
    display_cols = ["Team"] + AGE_BANDS
    
    # Build age breakdown HTML table
    html_table = """<table class='fe-table fe-sortable'>
<thead>
<tr>
"""
    
    # Add column headers
    for col in display_cols:
        html_table += f"<th>{col}</th>"
    html_table += "</tr>\n</thead>\n<tbody>\n"
    
    # Add data rows with stacked percentage + ranking badge (List Ladder style)
    for _, row in age_breakdown_table.iterrows():
        html_table += "<tr>\n"
        for col in display_cols:
            if col == "Team":
                html_table += f"<td>{row['Team']}</td>\n"
            else:
                # Age band columns — stacked percentage + ranking badge
                band = col
                pct = row[band]
                rank_val = int(row[f"{band}_Rank"])
                bg_color = get_rank_color_age(rank_val)
                text_color = "black" if bg_color in ("#90EE90", "#FFD700") else "white"
                html_table += (
                    f"<td>"
                    f"<div style='font-weight:700;font-size:1.05em;color:#E0E0E0;margin-bottom:3px;'>{pct:.1f}%</div>"
                    f"<span class='ct-pill' style='background-color:{bg_color};color:{text_color};'>{get_ordinal_suffix(rank_val)}</span>"
                    f"</td>\n"
                )
        html_table += "</tr>\n"
    
    html_table += "</tbody>\n</table>"
    render_sortable_table(html_table)
    
    # Professional footer
    render_footer()


# ================= LIST LADDER =================

elif page == "List Ladder":

    render_page_header("AFL List Ladder", "Positional Depth Rankings")

    # Season filter
    _ll_seasons = sorted(get_player_seasons(), reverse=True)
    selected_season = st.selectbox("Season", _ll_seasons, index=0, key="list_ladder_season")

    # Load player data
    try:
        players_df = load_players(selected_season)
    except Exception as e:
        st.error(f"Error loading player data: {e}")
        st.stop()

    if players_df.empty:
        st.warning(f"No player data found for {selected_season}.")
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
    
    # Compact ranking legend
    st.markdown("""<div style='display:flex; align-items:center; gap:14px; padding:8px 14px; background:rgba(255,255,255,0.03); border-radius:8px; margin-bottom:16px; flex-wrap:wrap;'><span style='color:#888; font-size:0.75em; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>Ranking</span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#008000; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>1-4 Elite</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#90EE90; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>5-7 Good</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#FFD700; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>8-11 Average</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#FFA500; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>12-15 Below Avg</span></span><span style='display:inline-flex; align-items:center; gap:4px;'><span style='width:8px; height:8px; border-radius:50%; background:#FF0000; display:inline-block;'></span><span style='color:#AAA; font-size:0.75em;'>16-18 Poor</span></span></div>""", unsafe_allow_html=True)
    st.markdown("<p style='color:#666; font-size:0.75em; margin:-8px 0 16px 14px;'>Points = Rating × Matches (capped at 23 regular season games). Total Points = overall list strength.</p>", unsafe_allow_html=True)
    
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
    
    # Build list ladder HTML table
    html_table = """<table class='fe-table fe-sortable'>
<thead>
<tr>
"""

    # Add column headers
    for col in display_df.columns:
        if col == "Total Points":
            html_table += f"<th style='background:linear-gradient(135deg,#f0f0f0 0%,#ffffff 100%);color:#1a1a1a;border-left:3px solid rgba(255,215,0,0.6);'>{col}</th>"
        else:
            html_table += f"<th>{col}</th>"
    html_table += "</tr>\n</thead>\n<tbody>\n"

    # Add data rows with Depth-Chart-style ranking badges
    for row_idx, row in display_df.iterrows():
        html_table += "<tr>\n"
        for col_idx, col in enumerate(display_df.columns):
            if col in ["Rank", "Team"]:
                html_table += f"<td>{row[col]}</td>\n"
            elif col == "Total Points":
                overall_rank = int(row["Rank"])
                tp_bg = get_rank_color(overall_rank)
                tp_text = "black" if tp_bg in ("#90EE90", "#FFD700") else "white"
                html_table += (
                    f"<td style='background:rgba(255,255,255,0.95);border-left:3px solid rgba(255,215,0,0.6);'>"
                    f"<div style='font-weight:800;font-size:1.1em;color:#1a1a1a;margin-bottom:3px;'>{row[col]}</div>"
                    f"<span class='ct-pill' style='background-color:{tp_bg};color:{tp_text};'>{get_ordinal_suffix(overall_rank)}</span>"
                    f"</td>\n"
                )
            else:
                # Position columns - stacked points + ranking badge
                val_str = row[col]
                if "(" in val_str and ")" in val_str:
                    pts_part = val_str.split("(")[0].strip()
                    rank_part = val_str.split("(")[1].split(")")[0]

                    rank_val = int(ladder_df.iloc[row_idx][f"{col}_Rank"])
                    bg_color = get_rank_color(rank_val)
                    text_color = "black" if bg_color in ("#90EE90", "#FFD700") else "white"

                    html_table += (
                        f"<td>"
                        f"<div style='font-weight:700;font-size:1.05em;color:#E0E0E0;margin-bottom:3px;'>{pts_part}</div>"
                        f"<span class='ct-pill' style='background-color:{bg_color};color:{text_color};'>{rank_part}</span>"
                        f"</td>\n"
                    )
                else:
                    html_table += f"<td>{val_str}</td>\n"
        html_table += "</tr>\n"

    html_table += "</tbody>\n</table>"
    render_sortable_table(html_table)
    
    # ---- Team Selector for Positional Breakdown ----
    st.markdown("<div style='border-top:1px solid rgba(255,255,255,0.1); margin:40px 0 24px 0;'></div>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='color:#FFFFFF; font-weight:800; font-size:1.6em; margin:0 0 4px 0;'>{_svg_inline('list', 24)} Team Player Breakdown</h2><p style='color:#999; font-size:0.85em; margin:0 0 16px 0;'>Positional depth analysis by player contributions</p>", unsafe_allow_html=True)
    
    # Team selector
    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        default_idx = teams.index(st.session_state.default_team)
    selected_team = st.selectbox("Select a team to view contributing players", teams, index=default_idx, key="list_ladder_team_select")
    
    # Player contribution info
    st.markdown("<p style='color:#888; font-size:0.8em; margin-bottom:16px;'>Players color-coded by percentile ranking across the competition.</p>", unsafe_allow_html=True)
    
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
                        html_player_table = """<table class='fe-table fe-table-compact' style='table-layout:fixed;width:100%;'>
<colgroup>
<col style='width:55%;'>
<col style='width:25%;'>
<col style='width:20%;'>
</colgroup>
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
<td><span class="ct-pill" style="background:{bg_color}; color:{text_color};">{row['Rating']}</span></td>
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

    render_page_header("Team List Summary", "Complete Team Overview", "document")

    # Season filter
    _tls_seasons = sorted(get_player_seasons(), reverse=True)
    selected_season = st.selectbox("Season", _tls_seasons, index=0, key="team_list_summary_season")
    
    # Team selection
    # Get teams from player data
    try:
        players_df = load_players(selected_season)
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
            st.markdown(f"<p style='color: #CCCCCC; font-size: 1.1em;'>{selected_season} Season List Analysis</p>", unsafe_allow_html=True)
    else:
        st.markdown(f"<h2 style='text-align: center; color: #FFFFFF;'>{selected_team}</h2>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ================= AGE BREAKDOWN SECTION =================
    st.markdown(f"<h2 style='color: #FFFFFF; margin: 30px 0 20px 0;'>{_svg_inline('people', 24)} Age Breakdown</h2>", unsafe_allow_html=True)
    
    # Calculate age breakdown data (same logic as Team Age Breakdown page)
    required_cols = ["Player", "Team", "Age", "Matches", "RatingPoints_Avg"]
    missing_cols = [c for c in required_cols if c not in players_df.columns]
    if missing_cols:
        st.error(f"Missing required columns: {', '.join(missing_cols)}")
        st.stop()
    
    players_df["Age"] = pd.to_numeric(players_df["Age"], errors="coerce")
    players_df["Matches"] = pd.to_numeric(players_df["Matches"], errors="coerce")
    players_df["RatingPoints_Avg"] = pd.to_numeric(players_df["RatingPoints_Avg"], errors="coerce")
    
    # Filter to players with at least 1 match (fall back to all players if none have matches yet)
    players_filtered = players_df[players_df["Matches"] >= 1].copy()
    if players_filtered.empty:
        players_filtered = players_df.copy()
    
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
    
    ladder_df = pd.DataFrame(ladder_data)
    if ladder_df.empty or "Total Points" not in ladder_df.columns:
        ladder_df = pd.DataFrame({"Team": all_teams if all_teams else [], "Total Points": [0]*len(all_teams)})
    ladder_df = ladder_df.sort_values("Total Points", ascending=False).reset_index(drop=True)
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
<td><span class='ct-pill' style='background: {bg_color}; color: {text_color};'>{rank_display}</span></td>
</tr>
"""
    
    html_age_table += "</tbody>\n</table>"
    render_sortable_table(html_age_table)
    
    # Age breakdown analysis
    st.markdown(f"<h3 style='color: #FFFFFF; margin: 30px 0 15px 0;'>{_svg_inline('chart_trend', 24)} Age Breakdown Analysis</h3>", unsafe_allow_html=True)
    
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
        analysis_points.append(f"{_svg_inline('chart_bar', 20)} <strong>Overall:</strong> Team is performing above league average across age groups (+{avg_diff_league:.1f} average)")
    elif avg_diff_league < -1.0:
        analysis_points.append(f"{_svg_inline('chart_bar', 20)} <strong>Overall:</strong> Team is performing below league average across age groups ({avg_diff_league:.1f} average)")
    else:
        analysis_points.append(f"{_svg_inline('chart_bar', 20)} <strong>Overall:</strong> Team is performing at league average across age groups")
    
    if analysis_points:
        analysis_html = "<div style='background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,215,0,0.2);'>"
        for point in analysis_points:
            analysis_html += f"<p style='color: #DDDDDD; line-height: 1.8; margin: 10px 0;'>{point}</p>"
        analysis_html += "</div>"
        st.markdown(analysis_html, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ================= POSITIONAL DEPTH SECTION =================
    st.markdown(f"<h2 style='color: #FFFFFF; margin: 30px 0 20px 0;'>{_svg_inline('trending', 24)} Positional Depth</h2>", unsafe_allow_html=True)
    
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
    
    # Get selected team's data (guard against team missing from filtered data)
    _team_pos_match = position_ladder_df[position_ladder_df["Team"] == selected_team]
    if _team_pos_match.empty:
        st.info(f"No positional depth data available for {selected_team} (no qualifying matches yet).")
        render_footer()
    else:
        team_pos_data = _team_pos_match.iloc[0]
    
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
<td><span class='ct-pill' style='background: {bg_color}; color: {text_color};'>{rank_display}</span></td>
</tr>
"""
        
        html_pos_table += "</tbody>\n</table>"
        render_sortable_table(html_pos_table)
        
        # Positional depth analysis
        st.markdown(f"<h3 style='color: #FFFFFF; margin: 30px 0 15px 0;'>{_svg_inline('chart_trend', 24)} Positional Depth Analysis</h3>", unsafe_allow_html=True)
        
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
            pos_analysis_points.append(f"{_svg_inline('trophy', 20)} <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Elite list depth ({total_points:.1f} total points)")
        elif team_overall_rank <= 7:
            pos_analysis_points.append(f"{_svg_inline('chart_bar', 20)} <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Good list depth ({total_points:.1f} total points)")
        elif team_overall_rank <= 11:
            pos_analysis_points.append(f"{_svg_inline('chart_bar', 20)} <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Average list depth ({total_points:.1f} total points)")
        elif team_overall_rank <= 15:
            pos_analysis_points.append(f"{_svg_inline('chart_bar', 20)} <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Below average list depth ({total_points:.1f} total points)")
        else:
            pos_analysis_points.append(f"{_svg_inline('chart_bar', 20)} <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Poor list depth ({total_points:.1f} total points)")
        
        if pos_analysis_points:
            pos_analysis_html = "<div style='background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,215,0,0.2);'>"
            for point in pos_analysis_points:
                pos_analysis_html += f"<p style='color: #DDDDDD; line-height: 1.8; margin: 10px 0;'>{point}</p>"
            pos_analysis_html += "</div>"
            st.markdown(pos_analysis_html, unsafe_allow_html=True)
        
        # Summary section
        st.markdown("---")
        st.markdown(f"<h2 style='color: #FFFFFF; margin: 30px 0 20px 0;'>{_svg_inline('list', 24)} Summary</h2>", unsafe_allow_html=True)
        
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


    render_page_header("Best 23", "Model, Compare & Select Your Team", "trophy")
    
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
    seasons = sorted(get_player_seasons(), reverse=True)

    season = st.selectbox("Season", seasons, index=0, key="best23_season")

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

    # ── Reclassify Wing players ──────────────────────────
    # The computed player_summary.csv has no "Wing" position —
    # all Wing players are labelled "Midfielder".  Load the Wings
    # sheet from AFL_Historical and patch the Position column so
    # that build_best23() can fill Wing slots correctly.
    try:
        _wings_df = pd.read_excel(
            "data/AFL_Historical_2012_2025.xlsx", sheet_name="Wings"
        )
        _wing_keys = set()
        for _, _wr in _wings_df.iterrows():
            _pn = _wr.get("Player", "")
            _tm = _wr.get("Team", "")
            if pd.notna(_pn) and pd.notna(_tm):
                _wing_keys.add(
                    (str(_pn).strip().lower(), str(_tm).strip().lower())
                )

        def _is_wing(row):
            pn = str(row.get("Player", "")).strip().lower()
            tm = str(row.get("Team", "")).strip().lower()
            return (pn, tm) in _wing_keys

        _mask = merged_all.apply(_is_wing, axis=1)
        merged_all.loc[_mask, "Position"] = "Wing"
    except Exception:
        pass  # If Wings sheet unavailable, fall through
    # ─────────────────────────────────────────────────────

    teams = sorted(merged_all["Team"].dropna().unique())

    # =====================================================
    # BEST 23 ENGINE
    # =====================================================
    def build_best23(team):
        df = merged_all[merged_all["Team"] == team].sort_values("Rating", ascending=False)
        used = set()
        slots = []

        # Position compatibility: ordered list of acceptable fallback positions
        # for each slot type. First entry is exact match, rest are compatible alternatives.
        POSITION_COMPAT = {
            "Key Defender":  ["Key Defender"],
            "Gen. Defender": ["Gen. Defender"],
            "Wing":          ["Wing", "Midfielder"],
            "Ruck":          ["Ruck"],
            "Midfielder":    ["Midfielder", "Mid-Forward"],
            "Key Forward":   ["Key Forward"],
            "Gen. Forward":  ["Gen. Forward", "Mid-Forward"],
            "Mid-Forward":   ["Mid-Forward", "Gen. Forward"],
        }

        def pick(position):
            """Pick best available player for a position using compatibility list.
            
            1. Try exact position match first
            2. Try compatible positions in order
            3. Never fall back to a completely unrelated position
            """
            compat = POSITION_COMPAT.get(position, [position])
            
            # Try each compatible position in priority order
            for compat_pos in compat:
                candidates = df[df["Position"] == compat_pos].sort_values("Rating", ascending=False)
                for _, r in candidates.iterrows():
                    if r["Player"] not in used:
                        used.add(r["Player"])
                        return r
            
            return None

        # ------------------------------
        # On-field 18
        # ------------------------------
        for pos, x, y in ONFIELD_SLOTS:
            slots.append((x, y, pos, pick(pos), False))

        # Fill any empty on-field slots with best remaining players
        # (only if no position-matched player was available at all)
        for i, (x, y, pos, r, bench) in enumerate(slots):
            if r is None:
                for _, candidate in df.iterrows():
                    if candidate["Player"] not in used:
                        used.add(candidate["Player"])
                        slots[i] = (x, y, pos, candidate, False)
                        break

        # ------------------------------
        # Bench: 1 defender, then best remaining 4 non-defenders
        # ------------------------------
        bench_df = df[~df["Player"].isin(used)]
        def_pick_df = bench_df[bench_df["Position"].str.contains("Defend", case=False, na=False)].head(1)

        if not def_pick_df.empty:
            r = def_pick_df.iloc[0]
            used.add(r["Player"])
            slots.append((BENCH_X, BENCH_YS[0], "Bench", r, True))

        # now next best 4 non-defenders
        for y in BENCH_YS[1:]:
            bench_df = df[~df["Player"].isin(used)]
            bench_df = bench_df[~bench_df["Position"].str.contains("Defend", case=False, na=False)]
            if bench_df.empty:
                break
            r = bench_df.iloc[0]
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
    st.caption("Fill every position on the oval using the dropdowns below. Once a player is picked they cannot be selected again.")

    # Position layout that mirrors the oval —
    # each tuple: (slot_label, position_category, group_tag)
    MANUAL_FIELD_ROWS = [
        # --- Back 6 ---
        [("Key Def 1", "Key Defender", "Back 6"),
         ("Key Def 2", "Key Defender", "Back 6")],
        [("Gen Def 1", "Gen. Defender", "Back 6"),
         ("Gen Def 2", "Gen. Defender", "Back 6")],
        [("Gen Def 3", "Gen. Defender", "Back 6"),
         ("Gen Def 4", "Gen. Defender", "Back 6")],
        # --- Midfield ---
        [("Wing 1", "Wing", "Midfield"),
         ("Ruck", "Ruck", "Midfield"),
         ("Wing 2", "Wing", "Midfield")],
        [("Mid 1", "Midfielder", "Midfield"),
         ("Mid 2", "Midfielder", "Midfield"),
         ("Mid 3", "Midfielder", "Midfield")],
        # --- Forward 6 ---
        [("Gen Fwd 1", "Gen. Forward", "Forward 6"),
         ("Gen Fwd 2", "Gen. Forward", "Forward 6")],
        [("Mid-Fwd", "Mid-Forward", "Forward 6"),
         ("Gen Fwd 3", "Gen. Forward", "Forward 6")],
        [("Key Fwd 1", "Key Forward", "Forward 6"),
         ("Key Fwd 2", "Key Forward", "Forward 6")],
        # --- Bench ---
        [("Bench 1", "Bench", "Bench"),
         ("Bench 2", "Bench", "Bench"),
         ("Bench 3", "Bench", "Bench"),
         ("Bench 4", "Bench", "Bench"),
         ("Bench 5", "Bench", "Bench")],
    ]

    # Map slot_label → (x%, y%) for oval rendering
    MANUAL_SLOT_XY = {
        "Key Def 1": (32, 15), "Key Def 2": (63, 15),
        "Gen Def 1": (32, 24), "Gen Def 2": (63, 24),
        "Gen Def 3": (32, 33), "Gen Def 4": (63, 33),
        "Wing 1": (20, 55), "Ruck": (48, 46), "Wing 2": (76, 55),
        "Mid 1": (48, 52), "Mid 2": (48, 58), "Mid 3": (48, 64),
        "Gen Fwd 1": (32, 75), "Gen Fwd 2": (63, 75),
        "Mid-Fwd": (32, 84), "Gen Fwd 3": (63, 84),
        "Key Fwd 1": (32, 93), "Key Fwd 2": (63, 93),
    }
    MANUAL_BENCH_XY = {
        "Bench 1": (BENCH_X, BENCH_YS[0]),
        "Bench 2": (BENCH_X, BENCH_YS[1]),
        "Bench 3": (BENCH_X, BENCH_YS[2]),
        "Bench 4": (BENCH_X, BENCH_YS[3]),
        "Bench 5": (BENCH_X, BENCH_YS[4]),
    }

    def _manual_oval_picker(team_key, team_name, merged_all):
        """Render position-by-position dropdowns and return (picked_df, selections_dict)."""
        df = merged_all[merged_all["Team"] == team_name].copy()
        df = df.sort_values("Rating", ascending=False)

        used = set()
        selections = {}  # slot_label → row dict

        section_labels = {
            0: "🛡️ **Back 6**", 3: "🏃 **Midfield**",
            5: "🎯 **Forward 6**", 8: "🪑 **Bench**",
        }

        for row_idx, row_slots in enumerate(MANUAL_FIELD_ROWS):
            if row_idx in section_labels:
                st.markdown(section_labels[row_idx])

            cols = st.columns(len(row_slots))
            for col, (slot_label, pos_cat, grp) in zip(cols, row_slots):
                with col:
                    avail = df[~df["Player"].isin(used)]
                    options = ["— empty —"] + [
                        f"{r.Player} ({r.Position}) – {float(r.Rating):.1f}"
                        for r in avail.itertuples()
                    ]
                    choice = st.selectbox(
                        slot_label,
                        options,
                        index=0,
                        key=f"ms_{team_key}_{slot_label}",
                    )
                    if choice != "— empty —":
                        # Parse player name from label
                        p_name = choice.split(" (")[0]
                        match = avail[avail["Player"] == p_name]
                        if not match.empty:
                            r = match.iloc[0]
                            used.add(r["Player"])
                            selections[slot_label] = {
                                "Player": r["Player"],
                                "Position": r["Position"],
                                "Rating": float(r["Rating"]),
                                "Jumper": r.get("Jumper", ""),
                                "Team": team_name,
                                "Group": grp,
                            }

        if not selections:
            return pd.DataFrame(), selections

        out = pd.DataFrame(list(selections.values()))
        out["Rating"] = pd.to_numeric(out["Rating"], errors="coerce")
        return out, selections

    def _render_manual_oval(team_name, selections, team_ratings_series):
        """Render the filled oval for manual selections."""
        magnets_html = ""
        for slot_label, sel in selections.items():
            xy = MANUAL_SLOT_XY.get(slot_label) or MANUAL_BENCH_XY.get(slot_label)
            if xy is None:
                continue
            x, y = xy
            first, last = split_name(sel["Player"])
            grp = pos_group(sel["Position"])
            num = ""
            try:
                j = sel.get("Jumper", "")
                if j and not pd.isna(j):
                    num = str(j)
            except Exception:
                pass
            rat = f"{sel['Rating']:.1f}"
            is_bench = slot_label.startswith("Bench")
            fade = "opacity:0.55;" if is_bench else ""
            bgc, fgc, bri = rating_style(sel["Rating"], team_ratings_series)

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

        # Empty slots for unfilled positions
        all_slots = {**MANUAL_SLOT_XY, **MANUAL_BENCH_XY}
        for slot_label, (x, y) in all_slots.items():
            if slot_label not in selections:
                is_bench = slot_label.startswith("Bench")
                fade = "opacity:0.35;" if is_bench else "opacity:0.45;"
                magnets_html += f"""
                <div class="wrap" style="left:{x}%; top:{y}%; {fade}">
                <div class="magnet other">
                    <div class="num"></div>
                    <div class="name">
                    <div class="first">&nbsp;</div>
                    <div class="last">{slot_label}</div>
                    </div>
                    <div class="rating" style="background:rgba(255,255,255,0.15);color:#999;">—</div>
                </div>
                </div>
                """

        manual_html = f"""
        <style>
        .field-container {{ width: 100%; max-width: {FIELD_WIDTH_PX}px; margin: 0 auto; }}
        .field {{ position: relative; width: 100%; padding-bottom: {(FIELD_HEIGHT_PX / FIELD_WIDTH_PX) * 100}%;
                  background: url("data:image/png;base64,{bg}") center/contain no-repeat; margin: auto; }}
        .wrap {{ position: absolute; transform: translate(-50%, -50%); }}
        .magnet {{ width: clamp(140px, 18vw, 235px); height: clamp(32px, 4vw, 44px);
                   display: flex; align-items: center; gap: clamp(4px, 0.6vw, 8px);
                   padding: clamp(4px, 0.5vw, 6px) clamp(6px, 0.8vw, 10px);
                   border-radius: 16px; color: #fff;
                   font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
                   font-weight: 800; box-shadow: 0 8px 18px rgba(0,0,0,.35); }}
        .num {{ min-width: clamp(20px, 2.5vw, 30px); text-align: center;
                font-size: clamp(10px, 1.2vw, 13px); opacity: 0.95; }}
        .name {{ display: flex; flex-direction: column; line-height: 1.05; }}
        .first {{ font-size: clamp(7px, 0.8vw, 9px); opacity: 0.9; }}
        .last {{ font-size: clamp(10px, 1.2vw, 13px); }}
        .rating {{ margin-left: auto; width: clamp(28px, 3.5vw, 40px); height: clamp(20px, 2.5vw, 28px);
                   border-radius: 10px; display: flex; align-items: center; justify-content: center;
                   font-size: clamp(9px, 1.1vw, 12px); font-weight: 900; background: #fff; color: #000; }}
        .def {{ background: #c62828; }}
        .mid {{ background: #2e7d32; }}
        .wingfwd {{ background: #ef6c00; }}
        .ruckkf {{ background: #1565c0; }}
        .other {{ background: #555; }}
        </style>
        <div class="field-container"><div class="field">{magnets_html}</div></div>
        """
        components.html(manual_html.strip(), height=int(min(FIELD_HEIGHT_PX + 20, 900)), scrolling=True)

    # --- Team A manual selection ---
    st.markdown("---")
    ms_team_a = st.selectbox(
        "Team A", teams,
        index=teams.index(st.session_state.default_team) if "default_team" in st.session_state and st.session_state.default_team in teams else 0,
        key="ms_team_a_sel",
    )
    st.subheader(f"{ms_team_a} – Pick Your Best 23")
    ms_sel_a_df, ms_sel_a_dict = _manual_oval_picker("A", ms_team_a, merged_all)
    ms_a_series = merged_all.loc[merged_all["Team"] == ms_team_a, "Rating"]
    if ms_sel_a_dict:
        _render_manual_oval(ms_team_a, ms_sel_a_dict, ms_a_series)

    # --- Team B manual selection ---
    st.markdown("---")
    ms_b_teams = [t for t in teams if t != ms_team_a]
    ms_team_b = st.selectbox("Team B", ms_b_teams, key="ms_team_b_sel")
    st.subheader(f"{ms_team_b} – Pick Your Best 23")
    ms_sel_b_df, ms_sel_b_dict = _manual_oval_picker("B", ms_team_b, merged_all)
    ms_b_series = merged_all.loc[merged_all["Team"] == ms_team_b, "Rating"]
    if ms_sel_b_dict:
        _render_manual_oval(ms_team_b, ms_sel_b_dict, ms_b_series)

    # =====================================================
    # Manual Selection Comparison (mirrors Best 23 Comparison)
    # =====================================================
    ms_count_a = len(ms_sel_a_dict) if ms_sel_a_dict else 0
    ms_count_b = len(ms_sel_b_dict) if ms_sel_b_dict else 0
    ms_expected = 23

    if ms_count_a == ms_expected and ms_count_b == ms_expected:
        st.markdown("---")
        st.header("Manual Selection Comparison")

        # --- Header with logos ---
        ms_overall_a = avg_rating(ms_sel_a_df)
        ms_overall_b = avg_rating(ms_sel_b_df)
        ms_net = None
        if ms_overall_a is not None and ms_overall_b is not None:
            ms_net = ms_overall_a - ms_overall_b

        ms_logo_a_b64 = _team_logo_b64(ms_team_a)
        ms_logo_b_b64 = _team_logo_b64(ms_team_b)
        ms_oa_str = "" if ms_overall_a is None else f"{ms_overall_a:.2f}"
        ms_ob_str = "" if ms_overall_b is None else f"{ms_overall_b:.2f}"

        ms_hdr = f"""
        <div class="b23Header">
        <div class="teamCol">
            {"<img class='logo' src='data:image/png;base64," + ms_logo_a_b64 + "' />" if ms_logo_a_b64 else "<div class='logoFallback'></div>"}
            <div class="teamName">{ms_team_a}</div>
            <div class="label">YOUR SELECTED RATING</div>
            {_pill(ms_oa_str if ms_oa_str else "—", big=True)}
        </div>
        <div class="midCol">
            <div class="vsPill">VS</div>
            <div class="netLabel">NET (A − B)</div>
            {_diff_pill(ms_net)}
            <div class="subNote">Positive = Team A higher</div>
        </div>
        <div class="teamCol">
            {"<img class='logo' src='data:image/png;base64," + ms_logo_b_b64 + "' />" if ms_logo_b_b64 else "<div class='logoFallback'></div>"}
            <div class="teamName">{ms_team_b}</div>
            <div class="label">YOUR SELECTED RATING</div>
            {_pill(ms_ob_str if ms_ob_str else "—", big=True)}
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
        min-height: 340px;
        }}
        .logo {{
        width: 420px;
        max-width: 90%;
        height: 220px;
        object-fit: contain;
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
        min-height: 340px;
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
        components.html(ms_hdr.strip(), height=400, scrolling=False)

        # --- Position-by-position comparison ---
        MS_CAT_MAP = {
            "Key Defender": ["Key Defender"],
            "Gen. Defender": ["Gen. Defender"],
            "Wing": ["Wing"],
            "Midfielder": ["Midfielder"],
            "Ruck": ["Ruck"],
            "Key Forward": ["Key Forward"],
            "Gen. Forward": ["Gen. Forward", "Mid-Forward"],
        }

        def ms_cat_df(df, cat_name):
            pos_list = MS_CAT_MAP[cat_name]
            if df.empty:
                return df
            return df[df["Position"].isin(pos_list)].copy()

        def _ms_render_position(cat_name):
            left_df = ms_cat_df(ms_sel_a_df, cat_name).sort_values("Rating", ascending=False)
            right_df = ms_cat_df(ms_sel_b_df, cat_name).sort_values("Rating", ascending=False)
            lcol, ccol, rcol = st.columns([4.5, 3.0, 4.5], gap="large")
            with lcol:
                st.markdown(f"**{cat_name}**")
                if left_df.empty:
                    st.caption("—")
                else:
                    for _, row in left_df.iterrows():
                        st.markdown(_magnet_html(row, ms_a_series), unsafe_allow_html=True)
            with ccol:
                _centre_stats(left_df, right_df, cat_name)
            with rcol:
                st.markdown(f"**{cat_name}**")
                if right_df.empty:
                    st.caption("—")
                else:
                    for _, row in right_df.iterrows():
                        st.markdown(_magnet_html(row, ms_b_series), unsafe_allow_html=True)

        st.markdown("---")
        _ms_render_position("Key Defender")
        st.markdown("---")
        _ms_render_position("Gen. Defender")
        st.markdown("---")
        _ms_render_position("Midfielder")
        st.markdown("---")
        _ms_render_position("Wing")
        st.markdown("---")
        _ms_render_position("Ruck")
        st.markdown("---")
        _ms_render_position("Key Forward")
        st.markdown("---")
        _ms_render_position("Gen. Forward")

        # --- Bench comparison ---
        st.markdown("---")
        bench_a = ms_sel_a_df[ms_sel_a_df["Group"] == "Bench"].sort_values("Rating", ascending=False) if not ms_sel_a_df.empty else pd.DataFrame()
        bench_b = ms_sel_b_df[ms_sel_b_df["Group"] == "Bench"].sort_values("Rating", ascending=False) if not ms_sel_b_df.empty else pd.DataFrame()
        lcol, ccol, rcol = st.columns([4.5, 3.0, 4.5], gap="large")
        with lcol:
            st.markdown("**Bench**")
            if bench_a.empty:
                st.caption("—")
            else:
                for _, row in bench_a.iterrows():
                    st.markdown(_magnet_html(row, ms_a_series, dim=True), unsafe_allow_html=True)
        with ccol:
            _centre_stats(bench_a, bench_b, "Bench")
        with rcol:
            st.markdown("**Bench**")
            if bench_b.empty:
                st.caption("—")
            else:
                for _, row in bench_b.iterrows():
                    st.markdown(_magnet_html(row, ms_b_series, dim=True), unsafe_allow_html=True)

    else:
        st.markdown("---")
        st.info(f"Select **{ms_expected} players** for both teams to see the comparison. (Team A: {ms_count_a}/23, Team B: {ms_count_b}/23)")

    # Professional footer
    render_footer()


# ================= LIST BREAKDOWN - TRAITS =================

elif page == "List Breakdown - Traits":

    render_page_header("List Breakdown - Traits", "Squad Trait Analysis & Player Profiles", "chart_bar")

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
    
    default_season_idx = available_seasons.index(CURRENT_SEASON) if CURRENT_SEASON in available_seasons else 0
    
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
        fc_mode = st.toggle("FC Rating Mode (50-99)", key="traits_breakdown_fc_mode", help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")

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
        traits_df["Age"] = np.nan

    # Backfill missing Age/Position/Height/Jumper from season player data
    # Summary sheet may not cover all players (e.g. 2026 has 668 summary vs 788 squad players)
    _backfill_cols = ["Age", "Position", "Height", "Jumper"]
    _missing_mask = traits_df["Age"].isna()
    if _missing_mask.any():
        try:
            _season_players = load_players(int(selected_season))
            if _season_players.empty:
                # Try full squad data as fallback
                _season_players = load_full_squad_data(int(selected_season))
            if not _season_players.empty and "Player" in _season_players.columns:
                _season_players["Player"] = _season_players["Player"].astype(str).str.strip()
                _sp_cols = ["Player"] + [c for c in _backfill_cols if c in _season_players.columns]
                _sp_lookup = _season_players[_sp_cols].drop_duplicates(subset=["Player"], keep="first")
                _sp_lookup = _sp_lookup.set_index("Player")
                for col in _backfill_cols:
                    if col in _sp_lookup.columns and col in traits_df.columns:
                        # Only fill where currently NaN
                        null_mask = traits_df[col].isna()
                        if null_mask.any():
                            mapped = traits_df.loc[null_mask, "Player_Full"].map(_sp_lookup[col])
                            traits_df.loc[null_mask, col] = mapped
                    elif col in _sp_lookup.columns and col not in traits_df.columns:
                        traits_df[col] = traits_df["Player_Full"].map(_sp_lookup[col])
                # Re-coerce Age to numeric after backfill
                traits_df["Age"] = pd.to_numeric(traits_df["Age"], errors="coerce")
        except Exception:
            pass  # Continue with whatever data we have

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
        stats = team_stats.get(trait_name)
        if stats:
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
        else:
            card_html = f"""<div style='background-color: #555555; color: white; padding: 25px 20px; border-radius: 12px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border: 2px solid rgba(255,255,255,0.15);'>
<div style='font-size: 0.85em; font-weight: 600; letter-spacing: 0.12em; opacity: 0.9; margin-bottom: 8px; text-transform: uppercase; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{trait_name}</div>
<div style='font-size: 2.5em; font-weight: 900; line-height: 1; margin: 8px 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>N/A</div>
<div style='font-size: 0.95em; font-weight: 700; letter-spacing: 0.08em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>No data</div>
</div>"""
        trait_cards.append(card_html)
    
    trait_grid = "".join(trait_cards)
    
    overall_stats = team_stats.get("Overall Rating")
    if not overall_stats:
        overall_stats = {"avg": 0, "rank": "—", "total": "—", "color": "#555555", "text_color": "white"}
    # Format overall value based on FC mode
    if fc_mode:
        overall_display_val = str(convert_trait_to_fc_rating(overall_stats["avg"]))
    else:
        overall_display_val = f'{overall_stats["avg"]:.2f}' if isinstance(overall_stats["avg"], (int, float)) else 'N/A'
    
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
    section_header = f"""<div style='background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 12px; margin: 30px 0 20px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border-left: 5px solid #e94560;'><h3 style='color: #FFFFFF; margin: 0; font-weight: 900; letter-spacing: 0.05em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{_svg_inline('list', 24)} SQUAD DEPTH GRID — {trait_label.upper()}</h3><p style='color: #CCCCCC; margin: 8px 0 0 0; font-size: 0.95em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{selected_season} Season | {squad_size_text} | Coloured by team percentile</p></div>"""
    
    st.markdown(section_header, unsafe_allow_html=True)

    html = build_depth_chart_html(df_team, traits_df_renamed, fc_mode=fc_mode)
    st.markdown(html, unsafe_allow_html=True)
    
    # ============= TRAITS-BASED LIST LADDER =============
    st.markdown(f"""<div style='background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 12px; margin: 50px 0 20px 0; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border-left: 5px solid #e94560;'><h3 style='color: #FFFFFF; margin: 0; font-weight: 900; letter-spacing: 0.05em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{_svg_inline('trophy', 24)} TRAITS LIST LADDER — AFL RANKINGS</h3><p style='color: #CCCCCC; margin: 8px 0 0 0; font-size: 0.95em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{selected_season} Season | {squad_size_text} | Sorted by Overall Trait Rating</p></div>""", unsafe_allow_html=True)
    
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
    
    # Add ranking for each trait column (handle NaN gracefully)
    for col in ["Overall", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
        ranks = ladder_df[col].rank(ascending=False, method="min")
        ladder_df[f"{col}_Rank"] = ranks.fillna(len(ladder_df)).astype(int)
    
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
            # Format value based on FC mode (handle NaN gracefully)
            if pd.isna(val):
                display_val = "N/A"
                bg, fg = "#555555", "white"
            elif fc_mode:
                display_val = str(convert_trait_to_fc_rating(val))
            else:
                display_val = f'{val:.2f}'
            
            ladder_html.append(f"<td style='{row_bg}padding:14px 12px;border-right:2px solid #e0e0e0;border-top:2px solid #e0e0e0;text-align:center;'><div style='display:inline-block;background:{bg};color:{fg};padding:10px 16px;border-radius:10px;font-weight:900;font-size:1.15em;box-shadow:0 3px 10px rgba(0,0,0,0.2);min-width:70px;'>{display_val}<div style='font-size:0.7em;opacity:0.8;margin-top:2px;'>#{trait_rank}</div></div></td>")
        
        ladder_html.append("</tr>")
    
    ladder_html.append("</table>")
    
    st.markdown("".join(ladder_html), unsafe_allow_html=True)
    
    # ========== TEAM TRAIT COMPARISON SECTION ==========
    st.markdown("---")
    st.markdown(f"<h2 style='color:#FFFFFF;margin-top:40px;'>{_svg_inline('balance', 24)} Team Trait Comparison</h2>", unsafe_allow_html=True)
    
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
            team1_val = float(team1_data[metric]) if pd.notna(team1_data[metric]) else 0.0
            team2_val = float(team2_data[metric]) if pd.notna(team2_data[metric]) else 0.0
            
            # Calculate Top 4 average
            top4_avg = ladder_df.nlargest(4, metric)[metric].mean()
            if pd.isna(top4_avg):
                top4_avg = 0.0
            
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
            except Exception:
                return str(rank_val)
        
        # Analyze each trait
        trait_analysis = []
        for i, metric in enumerate(trait_metrics):
            team1_val = team1_values[i]
            team2_val = team2_values[i]
            try:
                team1_rank = int(team1_data[f"{metric}_Rank"])
            except (ValueError, TypeError):
                team1_rank = len(ladder_df)
            try:
                team2_rank = int(team2_data[f"{metric}_Rank"])
            except (ValueError, TypeError):
                team2_rank = len(ladder_df)
            
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
            st.markdown(f"<h3 style='color: #00CC00;'>{_svg_inline('chart_trend', 20)} {team1_trait} – Strengths</h3>", unsafe_allow_html=True)
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
            st.markdown(f"<h3 style='color: #FF4444;'>{_svg_inline('chart_trend', 20)} {team1_trait} – Weaknesses</h3>", unsafe_allow_html=True)
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
                    _person_svg = _svg_inline("person", 20)
                    photo_html = f'<div style="width:100%;height:280px;background:linear-gradient(135deg, {color_start}40 0%, {color_end}40 100%);display:flex;align-items:center;justify-content:center;"><span style="font-size:72px;opacity:0.3;">{_person_svg}</span></div>'
                
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
            with st.expander(f"View Full {pillar_name} Table", expanded=False):
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
    render_page_header("Contract Status", "Player Contract & Free Agency Overview", "contract")

    # ---------- Season selector ----------
    seasons = sorted(get_player_seasons(), reverse=True)
    if not seasons:
        st.error("No player seasons found.")
        st.stop()

    default_season_idx = seasons.index(CURRENT_SEASON) if CURRENT_SEASON in seasons else 0
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
    
    MIN_PLAYER_PAYMENT = 110_000
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
<th>POS</th>
<th>AGE</th>
<th>GP</th>
<th>RATING</th>
<th>CAP VALUE</th>
<th>% CAP</th>
<th>EXPIRY</th>
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

        # Shortened FA label for pill
        fa_short = fa_status
        if "Unrestricted" in str(fa_status):
            fa_short = "UFA"
        elif "Restricted" in str(fa_status) and "Unrestricted" not in str(fa_status):
            fa_short = "RFA"
        elif "Non-Free" in str(fa_status):
            fa_short = "Non-FA"
        elif "Delisted" in str(fa_status):
            fa_short = "DFA"
        elif "Out of Contract" in str(fa_status):
            fa_short = "OOC"

        position_str = r["POSITION"] if pd.notna(r["POSITION"]) else "—"

        html += f"""
<tr>
<td>{r['PLAYER']}</td>
<td>{r['TEAM']}</td>
<td>{position_str}</td>
<td>{age_str}</td>
<td>{games_str}</td>
<td><span class="ct-pill" style="background:{bg_rating}; color:{fg_rating};">{rating_str}</span></td>
<td class="ct-cap">{cap_str}</td>
<td>{pct_cap_str}</td>
<td><span class="ct-pill" style="background:{bg_expiry}; color:{fg_expiry};">{expiry_str}</span></td>
<td><span class="ct-pill ct-fa" style="background:{bg_fa}; color:{fg_fa};" title="{fa_status}">{fa_short}</span></td>
</tr>
"""

    html += "</tbody></table>"

    render_sortable_table(html)

    # ---------- Contract Summary Section ----------
    import plotly.graph_objects as go
    
    st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
    
    # Professional header for summary section
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%);
        padding: 16px 20px;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.08);
        margin-bottom: 20px;
        text-align: center;
    ">
        <h3 style="
            color: #FFFFFF;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            font-weight: 700;
            font-size: 20px;
            margin: 0;
            letter-spacing: 0.03em;
        ">Contract Summary</h3>
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
        border-radius: 10px;
        padding: 16px 12px;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.08);
        box-shadow: 0 2px 8px rgba(0,0,0,0.25);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .contract-metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.35);
    }
    .contract-metric-value {
        font-size: 28px;
        font-weight: 900;
        margin: 0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
    .contract-metric-label {
        font-size: 11px;
        font-weight: 600;
        color: rgba(255,255,255,0.6);
        margin-top: 6px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
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
    
    # Pie Charts Section
    chart_cols = st.columns(2)
    
    # Contract Expiry Pie Chart
    with chart_cols[0]:
        st.markdown('<p style="text-align:center; color:rgba(255,255,255,0.75); font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; margin-bottom:4px;">Contract Expiry Distribution</p>', unsafe_allow_html=True)
        
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
        st.markdown('<p style="text-align:center; color:rgba(255,255,255,0.75); font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; margin-bottom:4px;">Free Agency Status</p>', unsafe_allow_html=True)
        
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
    detail_cols = st.columns(2)
    
    with detail_cols[0]:
        with st.expander("Contract Expiry Details", expanded=False):
            if not expiry_counts.empty:
                expiry_df = pd.DataFrame({
                    "Year": [int(y) for y in expiry_counts.index],
                    "Players": expiry_counts.values,
                    "% of Squad": [f"{v/total_players*100:.1f}%" for v in expiry_counts.values]
                })
                st.dataframe(expiry_df, hide_index=True, use_container_width=True)
    
    with detail_cols[1]:
        with st.expander("Free Agency Status Details", expanded=False):
            if not fa_counts.empty:
                fa_df = pd.DataFrame({
                    "Status": fa_counts.index,
                    "Players": fa_counts.values,
                    "% of Squad": [f"{v/total_players*100:.1f}%" for v in fa_counts.values]
                })
                st.dataframe(fa_df, hide_index=True, use_container_width=True)

    render_footer()


#### GAME DAY PLAYEGROUND

elif page == "Game Predictor":
   

   

    render_game_day_playground(teams)


# ================= IDP (INDIVIDUAL DEVELOPMENT PLAN) =================
elif page == "IDP":
    st.markdown(f"""<div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);padding: 40px 20px;border-radius: 16px;box-shadow: 0 8px 24px rgba(0,0,0,0.4);margin-bottom: 32px;text-align: center;"><h1 style="color: #FFFFFF;font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-weight: 900;font-size: 48px;margin: 0 0 12px 0;letter-spacing: 0.02em;text-shadow: 2px 2px 8px rgba(0,0,0,0.5);">{_svg_inline('list', 24)} Individual Development Plan</h1><p style="color: rgba(255,255,255,0.8);font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;font-size: 16px;margin: 0;font-weight: 600;letter-spacing: 0.03em;">Comprehensive player analysis with position benchmarking and comparison tools</p></div>""", unsafe_allow_html=True)
    
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
        except Exception:
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
        seasons_available = AVAILABLE_SEASONS
    
    # Season and FC Mode controls
    ctrl_col1, ctrl_col2 = st.columns([2, 1])
    with ctrl_col1:
        selected_season = st.selectbox("Select Season", seasons_available, index=0, key="idp_season")
    with ctrl_col2:
        fc_mode = st.toggle("FC Rating Mode (50-99)", key="idp_fc_mode", help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")
    
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
    st.markdown(f"<div class='idp-section-header'>{_svg_inline('chart_bar', 24)} Trait Overview</div>", unsafe_allow_html=True)
    
    # Define trait pillars and their sub-stats (updated to use correct column names)
    trait_pillars = {
        "Ball Winning": {
            "color": "#1B4D3E",  # Dark green
            "icon": _svg_inline('runner', 16),
            "substats": ["Stoppage", "Contest", "Power", "Receives"]
        },
        "Ball Use": {
            "color": "#1B3D5D",  # Dark blue
            "icon": _svg_inline('star', 20),
            "substats": ["Handballing", "Kicking", "Goal Kicking", "Connecting"]
        },
        "Aerial": {
            "color": "#4A4A2A",  # Olive
            "icon": _svg_inline('trending', 20),
            "substats": ["Marking", "Contested", "Moks", "Ruck"]
        },
        "Defence": {
            "color": "#5D1B1B",  # Dark red/maroon
            "icon": _svg_inline('shield', 20),
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
        except Exception:
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
            with st.expander(f"View {pillar_name} Details", expanded=False):
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
    st.markdown(f"<div class='idp-section-header'>{_svg_inline('star', 24)} Position Benchmarking (Top 10)</div>", unsafe_allow_html=True)
    
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
    
    st.markdown(f"<div class='idp-card'><h3 style='color:#FFFFFF;margin:0 0 24px 0;font-weight:900;font-size:22px;'>{_svg_inline('chart_bar', 24)} {selected_trait} Analysis vs Top 10 {player_position}s</h3>", unsafe_allow_html=True)
    
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
            pillar_icon = pillar_info.get('icon', _svg_inline('chart_bar', 20))
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
            with st.expander(f"View {pillar_name} Sub-Traits", expanded=False):
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
    st.markdown(f"<div class='idp-section-header'>{_svg_inline('strength', 24)} Strengths & Focus Areas</div>", unsafe_allow_html=True)
    
    col_strength, col_focus = st.columns(2)
    
    with col_strength:
        st.markdown(f"<div class='idp-card' style='border-left:6px solid #00FF00;'><h3 style='color:#00FF00;margin:0 0 16px 0;font-weight:900;font-size:20px;'>{_svg_inline('contract', 24)} Key Strengths</h3>", unsafe_allow_html=True)
        
        if strengths:
            strengths.sort(key=lambda x: x[1], reverse=True)
            for stat, pct in strengths[:5]:
                st.markdown(f"<div style='padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.1);'><span style='color:#FFFFFF;font-weight:700;font-size:14px;'>{stat}</span><span style='color:#00FF00;font-weight:900;float:right;font-size:14px;'>+{pct:.1f}% above avg</span></div>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='color:rgba(255,255,255,0.6);font-style:italic;'>Performing at or near Top 10 average across all metrics</p>", unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    with col_focus:
        st.markdown(f"<div class='idp-card' style='border-left:6px solid #FF6B6B;'><h3 style='color:#FF6B6B;margin:0 0 16px 0;font-weight:900;font-size:20px;'>{_svg_inline('star', 24)} Focus Areas</h3>", unsafe_allow_html=True)
        
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
    
    st.markdown(f"<div class='idp-section-header'>{_svg_inline('people', 24)} 5 Most Similar Players</div>", unsafe_allow_html=True)
    
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
    st.markdown(f"<div class='idp-section-header'>{_svg_inline('balance', 24)} Player Comparison Tool</div>", unsafe_allow_html=True)
    
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
                pillar_icon = pillar_info.get('icon', _svg_inline('chart_bar', 20))
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
                with st.expander(f"View {pillar_name} Sub-Trait Comparison", expanded=False):
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
                    <td><span class='ct-pill' style='background:{tier1_color};color:#fff;'>{p1_str}</span></td>
                    <td><span class='ct-pill' style='background:{tier2_color};color:#fff;'>{p2_str}</span></td>
                    <td><span class='ct-pill' style='background:{delta_color};color:#fff;'>{delta_display}</span></td>
                </tr>""")
            
            if comparison_rows:
                _comp_table_html = f"<table class='fe-table fe-sortable'><thead><tr><th style='text-align:left;'>Statistic</th><th>{selected_player}</th><th>{comparison_player}</th><th>Difference</th></tr></thead><tbody>{''.join(comparison_rows)}</tbody></table>"
                render_sortable_table(_comp_table_html)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Development recommendations
    st.markdown(f"<div class='idp-section-header'>{_svg_inline('chart_trend', 24)} Development Recommendations</div>", unsafe_allow_html=True)
    
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
        st.markdown(f"<h4 style='color:#FF6B6B;font-weight:900;font-size:18px;margin-top:16px;'>{_svg_inline('star', 24)} Priority Focus Areas:</h4>", unsafe_allow_html=True)
        
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
                
                with st.expander(f"View {pillar_name} Sub-Trait Analysis", expanded=False):
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
        st.markdown(f"<h4 style='color:#00FF00;font-weight:900;margin-top:28px;font-size:18px;'>{_svg_inline('strength', 24)} Key Strengths to Maintain:</h4>", unsafe_allow_html=True)
        
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
                
                with st.expander(f"View {pillar_name} Sub-Trait Analysis", expanded=False):
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
    render_page_header("Custom Player Comparison", "Build & Compare Custom Player Profiles", "people")
    
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
                    with st.expander("View Subcategories", expanded=False):
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
    fc_mode = st.toggle("FC Rating Mode (50-99)", key="cpc_fc_mode", 
                        help="Convert trait ratings from 1-4 scale to FIFA/FC style 50-99 scale")
    
    st.divider()
    
    # -------------------------
    # Build Your Player Section
    # -------------------------
    st.markdown("""
    <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                border-radius: 16px; padding: 25px; margin-bottom: 25px;
                border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 8px 32px rgba(0,0,0,0.4);'>
        <h3 style='color: #FFFFFF; margin: 0 0 5px 0; font-size: 1.4em;'>Build Your Player</h3>
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
            with st.expander(f"Adjust Subcategories", expanded=False):
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
    
    if st.button("Find Similar Players", type="primary", use_container_width=True):
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
                        st.markdown(f"""<div style='width: 180px; height: 180px; background: linear-gradient(135deg, #9333EA 0%, #6B21A8 100%); border-radius: 16px; display: flex; align-items: center; justify-content: center; margin: 0 auto; box-shadow: 0 4px 16px rgba(147,51,234,0.4);'><span style='font-size: 5em;'>{_svg_inline('person', 20)}</span></div>""", unsafe_allow_html=True)
                    else:
                        display_player_photo(player_name, st, size=180, team_name=team)
                
                with col_info:
                    # Compact info card in center
                    pos_color = "#9333EA" if is_custom else "rgba(255,255,255,0.7)"
                    team_text = "Custom Build" if is_custom else team
                    
                    if is_custom:
                        st.markdown(f"""<div style='background: rgba(147,51,234,0.15); border-radius: 12px; padding: 15px; text-align: center; border: 1px solid rgba(147,51,234,0.3);'><h3 style='color: #FFFFFF; margin: 0 0 8px 0; font-size: 1.3em; font-weight: 900;'>{player_name}</h3><p style='color: {pos_color}; margin: 0 0 4px 0; font-size: 0.85em; font-weight: 600;'>{position}</p><p style='color: rgba(255,255,255,0.5); margin: 0 0 8px 0; font-size: 0.75em;'>{team_text}</p><p style='color: rgba(255,255,255,0.4); margin: 0 0 10px 0; font-size: 0.7em;'>{age_str}</p><div style='font-size: 1.5em;'>{_svg_inline('people', 24)}</div><div style='color: rgba(255,255,255,0.5); font-size: 0.65em; margin-top: 4px;'>CUSTOM BUILD</div></div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""<div style='background: rgba(255,255,255,0.05); border-radius: 12px; padding: 15px; text-align: center; border: 1px solid rgba(255,255,255,0.1);'><h3 style='color: #FFFFFF; margin: 0 0 8px 0; font-size: 1.3em; font-weight: 900;'>{player_name}</h3><p style='color: {pos_color}; margin: 0 0 4px 0; font-size: 0.85em; font-weight: 500;'>{position}</p><p style='color: rgba(255,255,255,0.5); margin: 0 0 4px 0; font-size: 0.75em;'>{team_text}</p><p style='color: rgba(255,255,255,0.4); margin: 0 0 10px 0; font-size: 0.7em;'>{age_str}</p><div style='font-size: 2em; font-weight: 900; color: {border_color}; line-height: 1;'>{similarity:.1f}%</div><div style='color: rgba(255,255,255,0.5); font-size: 0.65em; margin-top: 4px;'>MATCH</div></div>""", unsafe_allow_html=True)
                
                with col_logo:
                    if is_custom:
                        st.markdown(f"""<div style='width: 180px; height: 180px; background: rgba(147, 51, 234, 0.15); border-radius: 16px; display: flex; align-items: center; justify-content: center; border: 2px solid rgba(147, 51, 234, 0.3); margin: 0 auto;'><span style='font-size: 5em;'>{_svg_inline('star', 20)}</span></div>""", unsafe_allow_html=True)
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
        st.markdown(f"### {_svg_inline('star', 20)} Comparison", unsafe_allow_html=True)
        
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
        with st.expander("View All Results", expanded=False):
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
    render_page_header("Game Model Scorecard", "Match Analysis & KPI Tracking", "scorecard")
    
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
        "Overall Rating",
        # Wheelo supplementary metrics
        "Equity Pre-Clearance Diff",
        "Equity Post-Clearance Diff",
        "Equity Ball Use Diff",
        "xChain Score Stoppage Diff",
        "xChain Score Turnover Diff",
        "xScore Against",
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
        available_years = AVAILABLE_SEASONS
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
    
    # Define which metrics should use the computed FIFA-style ratings (50-99 scale)
    COMPUTED_METRICS = {
        "Ball Winning Ranking", "Ball Movement Ranking", "Scoring Ranking", 
        "Defence Ranking", "Pressure Ranking", "Health Check Ranking",
        "Attack Rating", "Defence Rating", "Overall Rating", "Team Rating"
    }
    
    # Load data
    try:
        # Load computed FIFA-style ratings for pillar metrics
        computed_ladders_season = load_team_ladders(selected_year, last10=False)
        computed_ladders_l10 = load_team_ladders(selected_year, block="L10")
        computed_ladders_l5 = load_team_ladders(selected_year, block="L5")
        
        # Also load raw Excel data for individual KPIs (not pillar-level)
        xl = pd.ExcelFile(TEAM_FILE)
        sheet_name = f"{selected_year} Summary"
        raw_df = None
        if sheet_name in xl.sheet_names:
            raw_df = xl.parse(sheet_name, header=None)
            # Structure: Row 3 has metric names, Row 4 onwards has teams
            metric_row_idx = 3
            first_team_row_idx = 4
        else:
            # Fall back to generated summary from raw CSV data
            gen_df = _generate_summary_from_raw(selected_year)
            if not gen_df.empty:
                raw_df = gen_df
                # _generate_summary_from_raw uses default header, so indices shift
                metric_row_idx = 2
                first_team_row_idx = 3
        
        if raw_df is None or raw_df.empty:
            st.warning(f"No team summary data available for {selected_year}.")
            st.stop()
        
        # Get metric names from row 3 and create column index mapping
        metric_to_col = {}
        for col_idx in range(len(raw_df.columns)):
            metric = raw_df.iloc[metric_row_idx, col_idx]
            if pd.notna(metric) and str(metric).strip() != 'Rank':
                metric_to_col[str(metric).strip()] = col_idx
        
        # Build data dictionary by reading team rows (raw data)
        team_data_raw = {}
        for row_idx in range(first_team_row_idx, len(raw_df)):
            team_name = raw_df.iloc[row_idx, 0]
            if pd.notna(team_name):
                team_name = str(team_name).strip()
                if team_name == "GWS":
                    team_name = "GWS Giants"
                
                if team_name in all_teams:
                    team_data_raw[team_name] = {}
                    for metric_name, col_idx in metric_to_col.items():
                        value = raw_df.iloc[row_idx, col_idx]
                        if pd.notna(value):
                            try:
                                team_data_raw[team_name][metric_name] = float(value)
                            except Exception:
                                pass
        
        # Merge computed ratings with raw data (computed takes priority for pillar metrics)
        team_data = {}
        for team_name in all_teams:
            team_data[team_name] = team_data_raw.get(team_name, {}).copy()
            # Override pillar metrics with computed FIFA-style ratings
            if not computed_ladders_season.empty:
                team_row = computed_ladders_season[computed_ladders_season["Team"] == team_name]
                if not team_row.empty:
                    for metric in COMPUTED_METRICS:
                        if metric in team_row.columns:
                            val = team_row[metric].iloc[0]
                            if pd.notna(val):
                                try:
                                    team_data[team_name][metric] = float(val)
                                except Exception:
                                    pass
        
        # ---- Inject Wheelo supplementary metrics into team_data ----
        WHEELO_SCORECARD_MAP = {
            "Equity Pre-Clearance Diff": "Equity_PreClearance_Diff",
            "Equity Post-Clearance Diff": "Equity_PostClearance_Diff",
            "Equity Ball Use Diff": "Equity_BallUse_Diff",
            "xChain Score Stoppage Diff": "xChainScoreFromStoppage_Diff",
            "xChain Score Turnover Diff": "xChainScoreFromTurnover_Diff",
            "xScore Against": "xScore_Opposition",
        }
        wheelo_df_sc = _load_wheelo_team_stats()
        if not wheelo_df_sc.empty and "Team" in wheelo_df_sc.columns:
            for team_name in all_teams:
                wrow = wheelo_df_sc[wheelo_df_sc["Team"] == team_name]
                if not wrow.empty:
                    for display, col in WHEELO_SCORECARD_MAP.items():
                        if col in wheelo_df_sc.columns:
                            val = wrow[col].iloc[0]
                            if pd.notna(val):
                                try:
                                    team_data.setdefault(team_name, {})[display] = float(val)
                                except Exception:
                                    pass
        
        # Load Last 10 if available
        last10_data_raw = {}
        l10_metric_row_idx = metric_row_idx  # default same as season
        l10_first_team_row_idx = first_team_row_idx
        has_l10 = False
        try:
            sheet_name_l10 = f"{selected_year} Last 10 Summary"
            if sheet_name_l10 in xl.sheet_names:
                raw_df_l10 = xl.parse(sheet_name_l10, header=None)
                l10_metric_row_idx = 3
                l10_first_team_row_idx = 4
                has_l10 = True
            
            if has_l10:
                metric_to_col_l10 = {}
                for col_idx in range(len(raw_df_l10.columns)):
                    metric = raw_df_l10.iloc[l10_metric_row_idx, col_idx]
                    if pd.notna(metric) and str(metric).strip() != 'Rank':
                        metric_to_col_l10[str(metric).strip()] = col_idx
                
                for row_idx in range(l10_first_team_row_idx, len(raw_df_l10)):
                    team_name = raw_df_l10.iloc[row_idx, 0]
                    if pd.notna(team_name):
                        team_name = str(team_name).strip()
                        if team_name == "GWS":
                            team_name = "GWS Giants"
                        
                        if team_name in all_teams:
                            last10_data_raw[team_name] = {}
                            for metric_name, col_idx in metric_to_col_l10.items():
                                value = raw_df_l10.iloc[row_idx, col_idx]
                                if pd.notna(value):
                                    try:
                                        last10_data_raw[team_name][metric_name] = float(value)
                                    except Exception:
                                        pass
        except Exception:
            last10_data_raw = {}
        
        # Merge computed ratings with L10 raw data
        last10_data = {}
        if has_l10 or (computed_ladders_l10 is not None and not computed_ladders_l10.empty):
            for team_name in all_teams:
                last10_data[team_name] = last10_data_raw.get(team_name, {}).copy()
                # Override pillar metrics with computed FIFA-style ratings
                if computed_ladders_l10 is not None and not computed_ladders_l10.empty:
                    team_row = computed_ladders_l10[computed_ladders_l10["Team"] == team_name]
                    if not team_row.empty:
                        for metric in COMPUTED_METRICS:
                            if metric in team_row.columns:
                                val = team_row[metric].iloc[0]
                                if pd.notna(val):
                                    try:
                                        last10_data[team_name][metric] = float(val)
                                    except Exception:
                                        pass
            
            # ---- Inject Wheelo supplementary metrics into last10_data ----
            if not wheelo_df_sc.empty and "Team" in wheelo_df_sc.columns:
                for team_name in all_teams:
                    wrow = wheelo_df_sc[wheelo_df_sc["Team"] == team_name]
                    if not wrow.empty:
                        for display, col in WHEELO_SCORECARD_MAP.items():
                            if col in wheelo_df_sc.columns:
                                val = wrow[col].iloc[0]
                                if pd.notna(val):
                                    try:
                                        last10_data.setdefault(team_name, {})[display] = float(val)
                                    except Exception:
                                        pass
        
        # Load Last 5 if available
        last5_data_raw = {}
        has_l5 = False
        try:
            sheet_name_l5 = f"{selected_year} Last 5 Summary"
            if sheet_name_l5 in xl.sheet_names:
                raw_df_l5 = xl.parse(sheet_name_l5, header=None)
                l5_metric_row_idx = 3
                l5_first_team_row_idx = 4
                has_l5 = True
            
            if has_l5:
                metric_to_col_l5 = {}
                for col_idx in range(len(raw_df_l5.columns)):
                    metric = raw_df_l5.iloc[l5_metric_row_idx, col_idx]
                    if pd.notna(metric) and str(metric).strip() != 'Rank':
                        metric_to_col_l5[str(metric).strip()] = col_idx
                
                for row_idx in range(l5_first_team_row_idx, len(raw_df_l5)):
                    team_name = raw_df_l5.iloc[row_idx, 0]
                    if pd.notna(team_name):
                        team_name = str(team_name).strip()
                        if team_name == "GWS":
                            team_name = "GWS Giants"
                        
                        if team_name in all_teams:
                            last5_data_raw[team_name] = {}
                            for metric_name, col_idx in metric_to_col_l5.items():
                                value = raw_df_l5.iloc[row_idx, col_idx]
                                if pd.notna(value):
                                    try:
                                        last5_data_raw[team_name][metric_name] = float(value)
                                    except Exception:
                                        pass
        except Exception:
            last5_data_raw = {}
        
        # Merge computed ratings with L5 raw data
        last5_data = {}
        if has_l5 or (computed_ladders_l5 is not None and not computed_ladders_l5.empty):
            for team_name in all_teams:
                last5_data[team_name] = last5_data_raw.get(team_name, {}).copy()
                if computed_ladders_l5 is not None and not computed_ladders_l5.empty:
                    team_row = computed_ladders_l5[computed_ladders_l5["Team"] == team_name]
                    if not team_row.empty:
                        for metric in COMPUTED_METRICS:
                            if metric in team_row.columns:
                                val = team_row[metric].iloc[0]
                                if pd.notna(val):
                                    try:
                                        last5_data[team_name][metric] = float(val)
                                    except Exception:
                                        pass
            
            # ---- Inject Wheelo supplementary metrics into last5_data ----
            if not wheelo_df_sc.empty and "Team" in wheelo_df_sc.columns:
                for team_name in all_teams:
                    wrow = wheelo_df_sc[wheelo_df_sc["Team"] == team_name]
                    if not wrow.empty:
                        for display, col in WHEELO_SCORECARD_MAP.items():
                            if col in wheelo_df_sc.columns:
                                val = wrow[col].iloc[0]
                                if pd.notna(val):
                                    try:
                                        last5_data.setdefault(team_name, {})[display] = float(val)
                                    except Exception:
                                        pass
        
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
                    except Exception:
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
                
                st.markdown(f"<h3 style='margin-top: 30px; margin-bottom: 20px; font-weight: 800; font-size: 24px; color: rgba(255,255,255,0.9);'>{_svg_inline('chart_bar', 24)} {category}</h3>", unsafe_allow_html=True)
                
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
                    
                    # Get Last 5 value if applicable
                    l5_val = None
                    l5_rank = None
                    l5_color = "#666666"
                    l5_text_color = "white"
                    
                    if last5_data:
                        l5_val = last5_data.get(selected_team, {}).get(kpi, None)
                        l5_rank, _ = calculate_ranking(kpi, selected_team, last5_data)
                        l5_color, l5_text_color = get_conditional_color(l5_rank, total_teams)
                    
                    # Calculate trend (L5 vs Season if L5 available, else L10 vs Season)
                    diff_val = None
                    trend_source = None
                    if l5_val is not None and season_val is not None:
                        try:
                            diff_val = float(l5_val) - float(season_val)
                            trend_source = "L5"
                        except Exception:
                            pass
                    elif l10_val is not None and season_val is not None:
                        try:
                            diff_val = float(l10_val) - float(season_val)
                            trend_source = "L10"
                        except Exception:
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
                        'l5_val': l5_val,
                        'l5_rank': l5_rank,
                        'l5_color': l5_color,
                        'l5_text_color': l5_text_color,
                        'diff_val': diff_val,
                        'trend_source': trend_source,
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
                            l5_val_display = f"{float(data['l5_val']):.2f}" if data['l5_val'] is not None else "—"
                            l5_rank_display = format_ordinal(data['l5_rank']) if data['l5_rank'] is not None else "—"
                        
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
                                trend_label = f"TREND ({data.get('trend_source', 'L10')} vs Season)"
                            else:
                                diff_display = "—"
                                trend_color = "rgba(255,255,255,0.3)"
                                trend_icon = ""
                                trend_bg = "rgba(255,255,255,0.05)"
                                trend_label = "TREND"
                            
                            # Build card HTML with 3 columns: Season / L10 / L5
                            card_html = f"<div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border-radius: 10px; padding: 12px; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 12px rgba(0,0,0,0.3); position: relative; overflow: hidden;'><div style='position: absolute; top: 0; right: 0; width: 80px; height: 80px; background: radial-gradient(circle, rgba(255,255,255,0.05) 0%, transparent 70%); border-radius: 50%; transform: translate(30%, -30%);'></div><div style='font-size: 9px; font-weight: 800; color: rgba(255,255,255,0.5); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.8px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{data['kpi']}</div><div style='display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin-bottom: 12px;'><div style='background: rgba(255,255,255,0.03); border-radius: 8px; padding: 8px; border-left: 3px solid {data['season_color']};'><div style='font-size: 7px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px;'>SEASON</div><div style='font-size: 24px; font-weight: 900; color: #ffffff; margin-bottom: 3px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{season_val_display}</div><div style='display: inline-block; background-color: {data['season_color']}; color: {data['season_text_color']}; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 12px;'>{season_rank_display}</div></div><div style='background: rgba(255,255,255,0.03); border-radius: 8px; padding: 8px; border-left: 3px solid {data['l10_color']};'><div style='font-size: 7px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px;'>LAST 10</div><div style='font-size: 24px; font-weight: 900; color: #ffffff; margin-bottom: 3px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{l10_val_display}</div><div style='display: inline-block; background-color: {data['l10_color']}; color: {data['l10_text_color']}; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 12px;'>{l10_rank_display}</div></div><div style='background: rgba(255,255,255,0.03); border-radius: 8px; padding: 8px; border-left: 3px solid {data['l5_color']};'><div style='font-size: 7px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px;'>LAST 5</div><div style='font-size: 24px; font-weight: 900; color: #ffffff; margin-bottom: 3px; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{l5_val_display}</div><div style='display: inline-block; background-color: {data['l5_color']}; color: {data['l5_text_color']}; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 12px;'>{l5_rank_display}</div></div></div><div style='background: {trend_bg}; border-radius: 6px; padding: 8px; text-align: center; border: 1px solid {trend_color}33;'><div style='font-size: 7px; font-weight: 700; color: rgba(255,255,255,0.5); margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.5px;'>{trend_label}</div><div style='font-size: 24px; font-weight: 900; color: {trend_color}; font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;'>{diff_display} {trend_icon}</div></div></div>"
                            st.markdown(card_html, unsafe_allow_html=True)
            
            # Opposition Snapshot Section
            st.markdown("---")
            st.markdown(f"<h2 style='text-align: center; margin: 40px 0 30px 0; font-weight: 900; font-size: 36px;'>{_svg_inline('swords', 24)} Opposition Snapshot</h2>", unsafe_allow_html=True)
            
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
                _compare_options = ["Season"]
                if last10_data:
                    _compare_options.append("Last 10")
                if last5_data:
                    _compare_options.append("Last 5")
                comparison_window = st.selectbox(
                    "Compare Using",
                    options=_compare_options,
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
            if comparison_window == "Last 5" and last5_data:
                opp_data_source = last5_data
                own_data_source = last5_data
            elif comparison_window == "Last 10" and last10_data:
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
                
                st.markdown(f"<h3 style='margin-top: 30px; margin-bottom: 20px; font-weight: 800; font-size: 24px; color: rgba(255,255,255,0.9);'>{_svg_inline('chart_bar', 24)} {category}</h3>", unsafe_allow_html=True)
                
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
                        except Exception:
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
            st.markdown(f"<h3 style='text-align: center; margin: 30px 0 20px 0; font-weight: 900; font-size: 28px;'>{_svg_inline('chart_bar', 24)} Match Analysis</h3>", unsafe_allow_html=True)
            
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

# ================= PLAYER RATING MATRIX =================
elif page == "Player Rating Matrix":
    render_page_header("Player Rating Matrix", "Round-by-Round Player Ratings", "chart_bar")
    render_breadcrumb([("Home", "Home"), ("Player Rating Matrix", None)])

    from data_loader import load_match_ratings
    import re as _mr_re

    # Discover available seasons from match_ratings_*.csv files
    _mr_data_dir = Path(__file__).parent / "data" / "raw" / "player"
    _mr_seasons = sorted(
        [int(m.group(1)) for f in _mr_data_dir.glob("match_ratings_*.csv")
         if (m := _mr_re.search(r"match_ratings_(\d{4})\.csv$", f.name))],
        reverse=True,
    )
    if not _mr_seasons:
        _mr_seasons = [CURRENT_SEASON]

    # Season filter
    selected_season = st.selectbox("Season", _mr_seasons, index=0, key="mr_season")

    df_mr = load_match_ratings(selected_season)

    if df_mr.empty:
        st.warning("No match rating data available for this season. Run the Wheelo Match Stats scraper first:\n\n```\npython scrape_wheelo_match_stats.py --season " + str(selected_season) + "\n```")
    else:
        # Metric toggle
        _mr_metric = st.toggle("Show Coaches Votes", value=False, key="mr_metric_toggle")
        _mr_use_votes = _mr_metric

        # Determine rating column
        rating_col = None
        votes_col = None
        for candidate in ["RatingPoints", "RatingPoints_Avg", "Rating Points", "Rating", "Player Rating"]:
            if candidate in df_mr.columns:
                rating_col = candidate
                break
        for candidate in ["CoachesVotes", "Coaches Votes", "CoachesVotes_Avg"]:
            if candidate in df_mr.columns:
                votes_col = candidate
                break
        if rating_col is None:
            numeric_cols = [c for c in df_mr.select_dtypes(include="number").columns if c != "Round"]
            if numeric_cols:
                rating_col = numeric_cols[0]

        # Pick active column based on toggle
        if _mr_use_votes and votes_col:
            active_col = votes_col
            _mr_fv = lambda v: f"{v:.0f}"
            _mr_fv_avg = lambda v: f"{v:.1f}"
        else:
            active_col = rating_col
            _mr_fv = lambda v: f"{v:.1f}"
            _mr_fv_avg = _mr_fv

        if active_col is None:
            st.error("Could not identify a rating column in the match data.")
        else:
            # Filters
            teams_available = sorted(df_mr["Team"].dropna().unique()) if "Team" in df_mr.columns else []
            rounds_available = sorted(df_mr["Round"].dropna().unique()) if "Round" in df_mr.columns else []

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                selected_team = st.selectbox("Team", teams_available, index=0) if teams_available else None
            with col_f2:
                round_range = st.slider("Rounds", int(min(rounds_available)), int(max(rounds_available)),
                                        (int(min(rounds_available)), int(max(rounds_available)))) if len(rounds_available) > 1 else (int(rounds_available[0]), int(rounds_available[0]))

            # Filter data
            mask = pd.Series(True, index=df_mr.index)
            if selected_team:
                mask &= df_mr["Team"] == selected_team
            mask &= df_mr["Round"].between(round_range[0], round_range[1])
            df_filt = df_mr[mask].copy()

            if df_filt.empty:
                st.info("No data for the selected filters.")
            else:
                # Build pivot: players as rows, rounds as columns
                player_col = "Player" if "Player" in df_filt.columns else df_filt.columns[0]
                pivot = df_filt.pivot_table(index=player_col, columns="Round",
                                            values=active_col, aggfunc="first")
                pivot.columns = [("OR" if int(c) == 0 else f"R{int(c)}") for c in pivot.columns]

                # Add season average
                pivot["Avg"] = pivot.mean(axis=1).round(1)
                pivot.sort_values("Avg", ascending=False, inplace=True)

                # Determine colour thresholds from the data
                all_vals = df_filt[active_col].dropna()
                q80 = all_vals.quantile(0.80)
                q60 = all_vals.quantile(0.60)
                q40 = all_vals.quantile(0.40)
                q20 = all_vals.quantile(0.20)

                # Coaches-votes colour bands: 9+, 7-8, 5-6, 3-4, 1-2, 0
                def _cv_colour(v):
                    """Coaches-votes colour: 9+=darkest, 7-8, 5-6, 3-4, 1-2, 0=grey."""
                    if pd.isna(v):
                        return "#555555", "#aaa"
                    n = float(v)
                    if n >= 9:
                        return "#006400", "#fff"
                    if n >= 7:
                        return "#228B22", "#fff"
                    if n >= 5:
                        return "#3CB371", "#000"
                    if n >= 3:
                        return "#66CDAA", "#000"
                    if n >= 1:
                        return "#90EE90", "#000"
                    return "#555555", "#aaa"

                # Build a "played" lookup so we can tell 0-votes-but-played from didn't-play
                if _mr_use_votes and votes_col:
                    _played_pivot = df_filt.pivot_table(
                        index=player_col, columns="Round",
                        values="RatingPoints" if "RatingPoints" in df_filt.columns else active_col,
                        aggfunc="first",
                    )
                    _played_pivot.columns = [("OR" if int(c) == 0 else f"R{int(c)}") for c in _played_pivot.columns]
                else:
                    _played_pivot = None

                def _matrix_colour(v, is_votes=False):
                    if pd.isna(v):
                        return "rgba(255,255,255,0.05)"
                    if is_votes:
                        return _cv_colour(v)[0]
                    if v >= q80:
                        return "#008000"
                    if v >= q60:
                        return "#90EE90"
                    if v >= q40:
                        return "#FFD700"
                    if v >= q20:
                        return "#FFA500"
                    return "#FF0000"

                def _text_colour(bg, v=None, is_votes=False):
                    if is_votes and v is not None and not pd.isna(v):
                        return _cv_colour(v)[1]
                    return "#000" if bg in ("#90EE90", "#FFD700", "#FFA500", "#66CDAA", "#3CB371") else "#fff"

                # Build HTML table
                round_cols = [c for c in pivot.columns if c != "Avg"]
                header_cells = "".join(f"<th style='padding:8px 10px;text-align:center;font-size:12px;color:rgba(255,255,255,0.7);border-bottom:1px solid rgba(255,255,255,0.15);'>{c}</th>" for c in round_cols)
                header_cells += "<th style='padding:8px 10px;text-align:center;font-size:12px;font-weight:700;color:#fff;border-bottom:1px solid rgba(255,255,255,0.15);border-left:2px solid rgba(255,255,255,0.2);'>Avg</th>"

                rows_html = ""
                for player, row in pivot.iterrows():
                    cells = ""
                    for rc in round_cols:
                        val = row[rc]
                        if _mr_use_votes and pd.isna(val):
                            # Check if player actually played this round
                            played = _played_pivot is not None and rc in _played_pivot.columns and pd.notna(_played_pivot.loc[player, rc]) if _played_pivot is not None and player in _played_pivot.index else False
                            if played:
                                # Played but 0 votes — show as 0 grey
                                val = 0
                                bg = _matrix_colour(val, is_votes=True)
                                tc = _text_colour(bg, v=val, is_votes=True)
                                display = "0"
                            else:
                                bg = "rgba(255,255,255,0.05)"
                                tc = "#555"
                                display = "—"
                        elif _mr_use_votes and pd.notna(val):
                            bg = _matrix_colour(val, is_votes=True)
                            tc = _text_colour(bg, v=val, is_votes=True)
                            display = _mr_fv(val)
                        else:
                            bg = _matrix_colour(val)
                            tc = _text_colour(bg)
                            display = _mr_fv(val) if pd.notna(val) else "—"
                        cells += f"<td style='padding:4px 6px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.06);'><span class='ct-pill' style='background:{bg};color:{tc};'>{display}</span></td>"
                    avg_val = row["Avg"]
                    avg_bg = _matrix_colour(avg_val, is_votes=_mr_use_votes)
                    avg_tc = _text_colour(avg_bg, v=avg_val, is_votes=_mr_use_votes)
                    cells += f"<td style='padding:4px 6px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.06);border-left:2px solid rgba(255,255,255,0.2);'><span class='ct-pill' style='background:{avg_bg};color:{avg_tc};font-weight:800;'>{_mr_fv_avg(avg_val)}</span></td>"
                    rows_html += f"<tr><td style='padding:6px 12px;white-space:nowrap;font-size:13px;color:#fff;border-bottom:1px solid rgba(255,255,255,0.08);position:sticky;left:0;background:#1a1a2e;z-index:1;'>{player}</td>{cells}</tr>"

                matrix_html = f"<div style='overflow-x:auto;border-radius:12px;border:1px solid rgba(255,255,255,0.1);'><table style='border-collapse:collapse;width:100%;'><thead><tr><th style='padding:8px 12px;text-align:left;font-size:12px;color:rgba(255,255,255,0.7);border-bottom:1px solid rgba(255,255,255,0.15);position:sticky;left:0;background:#1a1a2e;z-index:2;'>Player</th>{header_cells}</tr></thead><tbody>{rows_html}</tbody></table></div>"

                st.markdown(matrix_html, unsafe_allow_html=True)

                # Legend
                if _mr_use_votes:
                    st.markdown("""
<div style='text-align:center;color:rgba(255,255,255,0.5);font-size:12px;margin-top:16px;'>
<span style='color:#006400;'>■</span> 9+ votes |
<span style='color:#228B22;'>■</span> 7-8 votes |
<span style='color:#3CB371;'>■</span> 5-6 votes |
<span style='color:#66CDAA;'>■</span> 3-4 votes |
<span style='color:#90EE90;'>■</span> 1-2 votes |
<span style='color:#555555;'>■</span> 0 votes |
— Didn't play
</div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
<div style='text-align:center;color:rgba(255,255,255,0.5);font-size:12px;margin-top:16px;'>
<span style='color:#008000;'>■</span> Top 20% |
<span style='color:#90EE90;'>■</span> 60-80th |
<span style='color:#FFD700;'>■</span> 40-60th |
<span style='color:#FFA500;'>■</span> 20-40th |
<span style='color:#FF0000;'>■</span> Bottom 20%
</div>""", unsafe_allow_html=True)

                # Summary stats
                st.markdown("---")
                top5 = pivot.nlargest(5, "Avg")
                bot5 = pivot.nsmallest(5, "Avg")

                def _leaderboard_card(title, icon_colour, data, ascending=False):
                    rows = ""
                    for rank, (player, row) in enumerate(data.iterrows(), 1):
                        avg = row["Avg"]
                        bg = _matrix_colour(avg, is_votes=_mr_use_votes)
                        tc = _text_colour(bg, v=avg, is_votes=_mr_use_votes)
                        bar_w = max(10, min(100, avg / (data["Avg"].max() or 1) * 100)) if not ascending else max(10, min(100, (data["Avg"].max() - avg + data["Avg"].min()) / (data["Avg"].max() or 1) * 100))
                        rows += (
                            f"<tr>"
                            f"<td style='padding:10px 12px;font-size:18px;font-weight:900;color:{icon_colour};text-align:center;width:36px;'>{rank}</td>"
                            f"<td style='padding:10px 8px;'>"
                            f"<div style='font-size:14px;font-weight:700;color:#fff;letter-spacing:0.01em;'>{player}</div>"
                            f"<div style='margin-top:6px;height:4px;border-radius:2px;background:rgba(255,255,255,0.1);'>"
                            f"<div style='height:100%;width:{bar_w:.0f}%;border-radius:2px;background:{bg};'></div></div>"
                            f"</td>"
                            f"<td style='padding:10px 8px;text-align:right;'><span class='ct-pill' style='background:{bg};color:{tc};'>{_mr_fv_avg(avg)}</span></td>"
                            f"</tr>"
                        )
                    return (
                        f"<div style='background:linear-gradient(145deg,rgba(20,20,30,0.95),rgba(30,30,45,0.95));"
                        f"border-radius:14px;border:1px solid rgba(255,255,255,0.08);overflow:hidden;'>"
                        f"<div style='padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.08);"
                        f"background:linear-gradient(90deg,{icon_colour}18,transparent);'>"
                        f"<h3 style='margin:0;color:#fff;font-size:16px;font-weight:800;letter-spacing:0.03em;'>"
                        f"<span style='color:{icon_colour};'>●</span>&ensp;{title}</h3></div>"
                        f"<table style='width:100%;border-collapse:collapse;'>{rows}</table></div>"
                    )

                _mr_label = "AVG COACHES VOTES" if _mr_use_votes else "AVG RATING"
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(_leaderboard_card(f"TOP 5 — {_mr_label}", "#008000", top5), unsafe_allow_html=True)
                with c2:
                    st.markdown(_leaderboard_card(f"BOTTOM 5 — {_mr_label}", "#FF0000", bot5, ascending=True), unsafe_allow_html=True)

    render_footer()
