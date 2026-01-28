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
from PIL import Image

# Import centralized configuration
from config.constants import (
    CURRENT_SEASON, AVAILABLE_SEASONS, DEFAULT_SEASON,
    TEAM_FILE, PLAYER_FILE, TRAITS_FILE, LADDERS_FILE,
    LOGO_FOLDER, PLAYER_PHOTO_FOLDER,
    TEAM_CODE_MAP, TEAM_CODE_TO_NAME, TEAM_COLOURS, ALL_TEAMS,
    DEPTH_POSITIONS, POSITION_ABBREV_TO_FULL, POSITION_COLOURS,
    AGE_BANDS, AGE_BANDS_ALT,
    METRIC_ORDER, RATING_COL_CANDIDATES, TRAIT_COLUMNS,
    UIConfig, get_rating_color, get_rank_color, get_ordinal, safe_float, normalize_team_name
)

# ---------------- STREAMLIT CONFIG ----------------
st.set_page_config(
    page_title="FutureEdge AFL Dashboard",
    page_icon="🏉",
    layout="wide",
)

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

BASE_DIR = Path(__file__).resolve().parent


# ============================================================================
# UNIFIED HELPER FUNCTIONS
# ============================================================================
def render_html(container, html_str: str):
    """Render HTML safely without code block artifacts."""
    container.markdown(textwrap.dedent(html_str).strip(), unsafe_allow_html=True)


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
def load_team_ladders(season: int, last10: bool = False) -> pd.DataFrame:
    """Load team ladder data for a specific season with error handling."""
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
def load_afl_ladder_positions() -> pd.DataFrame:
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
def load_player_summary() -> pd.DataFrame:
    """Load player summary data with error handling."""
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
    Player Ratings loader (AFL Player Ratings.xlsx per-season sheets).
    This should NOT enforce traits columns.
    """
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        df = xl.parse(str(season))
        df.columns = df.columns.astype(str).str.strip()
        df = _normalise_rating_column(df)

        cols = [
            "Player",
            "Team",
            "Age",
            "Age_Decimal",
            "Position",
            "Matches",
            "RatingPoints_Avg",
            "Height",
            "Height_cm",
            "Jumper",
            "Jersey",
            "Number",
            "Guernsey",
            "No",
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
        st.warning(f"⚠️ Could not load player data for {season}: {e}")
        return pd.DataFrame()


# ---------------- DATA LOADERS – TRAITS (ENRICHED source of truth) ----------------
@st.cache_data(show_spinner=False)
def load_traits(season: int = CURRENT_SEASON) -> pd.DataFrame:
    """
    Load ENRICHED traits for a season.

    Assumes ENRICHED is the source of truth:
    - does NOT use player_registry / player_uid
    - guarantees: Player_Full, Team_Full, Position_Full, Season exist
    """
    TEAM_CODE_TO_NAME = {
        "AFC": "Adelaide","BFC": "Brisbane","CFC": "Carlton","COFC": "Collingwood","EFC": "Essendon",
        "FRFC": "Fremantle","GFC": "Geelong","GCFC": "Gold Coast","GWS": "GWS Giants","HFC": "Hawthorn",
        "MFC": "Melbourne","NMFC": "North Melbourne","PAFC": "Port Adelaide","RFC": "Richmond","SKFC": "St Kilda",
        "SFC": "Sydney","WCFC": "West Coast","WBFC": "Western Bulldogs",
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

    try:
        df = pd.read_excel("2025 Traits ENRICHED.xlsx", sheet_name=str(season))
        df.columns = [str(c).strip() for c in df.columns]

        # Season
        if "Season" not in df.columns:
            df["Season"] = season
        df["Season"] = pd.to_numeric(df["Season"], errors="coerce").fillna(season).astype(int)

        # Team_Full
        if "Team_Full" not in df.columns:
            if "Team" in df.columns:
                df["Team_Full"] = (
                    df["Team"].astype(str).str.strip()
                    .map(TEAM_CODE_TO_NAME)
                    .fillna(df["Team"].astype(str).str.strip())
                )
            else:
                df["Team_Full"] = ""
        df["Team_Full"] = df["Team_Full"].astype(str).str.strip()

        # Player_Full
        if "Player_Full" not in df.columns:
            if "Player" in df.columns:
                df["Player_Full"] = df["Player"].astype(str).str.strip()
            else:
                st.error(f"ENRICHED traits sheet '{season}' is missing Player/Player_Full.")
                return pd.DataFrame()
        df["Player_Full"] = df["Player_Full"].astype(str).str.strip()

        # Position_Full
        if "Position_Full" not in df.columns:
            if "Position" in df.columns:
                pos_abbrev = df["Position"].astype(str).str.strip()
                df["Position_Full"] = pos_abbrev.map(POSITION_ABBREV_TO_FULL).fillna(pos_abbrev)
            else:
                df["Position_Full"] = ""
        df["Position_Full"] = df["Position_Full"].astype(str).str.strip()

        # clean obvious junk strings
        for c in ["Player_Full", "Team_Full", "Position_Full"]:
            df[c] = df[c].replace({"nan": "", "None": ""})

        return df

    except Exception as e:
        st.error(f"Error loading ENRICHED traits for {season}: {e}")
        return pd.DataFrame()


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
            parts = full_name.split()
            if len(parts) >= 2:
                initial_surname = f"{parts[0][0]}. {parts[-1]}"
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
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if len(vals) == 0 or pd.isna(v):
        return "#333333", "white"

    perc = (vals <= v).mean()
    if perc >= 0.85:
        return "#008000", "white"
    elif perc >= 0.60:
        return "#90EE90", "black"
    elif perc >= 0.35:
        return "#FFA500", "white"
    else:
        return "#FF0000", "white"


# ---------------- PLAYER TRAITS HISTORY TABLE HELPERS ----------------
def _opacity_from_pct(pct: float) -> float:
    if pd.isna(pct):
        return 0.25
    if pct >= 0.85:
        return 1.0
    if pct >= 0.65:
        return 0.75
    if pct >= 0.45:
        return 0.50
    return 0.25


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
        if pos_int <= 4:
            color = "#006400"   # dark green
        elif pos_int <= 9:
            color = "#90EE90"   # light green
        elif pos_int <= 14:
            color = "#FFA500"   # orange
        else:
            color = "#FF0000"   # red
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
        if pct_rank <= 4:
            color = "#006400"
        elif pct_rank <= 9:
            color = "#90EE90"
        elif pct_rank <= 14:
            color = "#FFA500"
        else:
            color = "#FF0000"
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
    """Return colour based on percentile of rating_value within df_team[rating_col]."""
    try:
        ratings = pd.to_numeric(df_team[rating_col], errors="coerce").dropna()
        if len(ratings) == 0 or pd.isna(rating_value):
            return "#333333", "white"

        percentile = (ratings <= rating_value).mean()

        if percentile >= 0.85:
            return "#008000", "white"
        elif percentile >= 0.60:
            return "#90EE90", "black"
        elif percentile >= 0.35:
            return "#FFA500", "white"
        else:
            return "#FF0000", "white"
    except Exception:
        return "#333333", "white"


def build_depth_chart_html(df_team: pd.DataFrame, all_teams_df: pd.DataFrame = None) -> str:
    """
    df_team is the Summary subset for one team, with:
    Player, Jumper, Age, Height, Position, RatingPoints_Avg.
    all_teams_df is the full Summary DataFrame for all teams (for ranking calculations).
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

    if rating_col in df_team.columns:
        df_sorted = df_team.sort_values(rating_col, ascending=False)
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
        
        # Right side: rating box (if exists)
        rating_box_html = ""
        if rating_col in df_team.columns and pd.notna(rating) and str(rating).strip() != "":
            try:
                rating_float = float(rating)
                bg_color, text_color = get_rating_color_team_context(
                    rating_float, df_team, rating_col
                )

                rating_box_html = f"<span style='display:inline-block;padding:8px 16px;border-radius:10px;background:{bg_color};color:{text_color};font-weight:900;font-size:1.5em;box-shadow:0 3px 10px rgba(0,0,0,0.3);border:2px solid rgba(255,255,255,0.2);min-width:50px;text-align:center;'>{rating_float:.2f}</span>"
            except Exception:
                rating_box_html = f"<span>{rating}</span>"
        
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
        
        # Get all ratings for percentile calculation (same as List Ladder)
        all_ratings = pd.to_numeric(all_teams_df[rating_col], errors="coerce").dropna()
        
        def get_rating_points(rating_val, all_ratings_clean):
            """Convert rating to points based on percentile (same as List Ladder)."""
            if pd.isna(rating_val):
                return 0
            
            percentile = (all_ratings_clean <= rating_val).mean()
            
            if percentile >= 0.85:
                return 3  # dark green - top 15%
            elif percentile >= 0.60:
                return 1  # light green - top 40%
            elif percentile >= 0.35:
                return 0.5  # orange - top 65%
            else:
                return 0  # red - bottom group
        
        # Get unique teams
        teams = all_teams_df["Team"].dropna().unique()
        
        # Calculate age band rankings (column rankings) - TOTAL POINTS not average
        age_band_points = {team: {band: 0 for band in AGE_BANDS} for team in teams}
        
        for team in teams:
            team_df = all_teams_df[all_teams_df["Team"] == team]
            for _, row in team_df.iterrows():
                player_age = row.get(age_col, None)
                player_rating = row.get(rating_col, None)
                
                if pd.notna(player_age) and pd.notna(player_rating):
                    age_band = map_age_to_band(player_age)
                    try:
                        points = get_rating_points(float(player_rating), all_ratings)
                        age_band_points[team][age_band] += points
                    except Exception:
                        pass
        
        # Rank teams for each age band based on TOTAL POINTS
        for band in AGE_BANDS:
            team_totals = []
            for team in teams:
                total_pts = age_band_points[team][band]
                team_totals.append((team, total_pts))
            
            # Sort by total points (descending) and assign ranks
            team_totals.sort(key=lambda x: x[1], reverse=True)
            for rank, (team, pts) in enumerate(team_totals, 1):
                if team == df_team["Team"].iloc[0]:
                    age_band_rankings[band] = (rank, len(teams), pts)
                    break
        
        # Calculate position rankings (row rankings) - TOTAL POINTS not average
        position_points = {team: {pos: 0 for pos in DEPTH_POSITIONS} for team in teams}
        
        for team in teams:
            team_df = all_teams_df[all_teams_df["Team"] == team]
            for _, row in team_df.iterrows():
                player_pos_raw = row.get(pos_col, None)
                player_rating = row.get(rating_col, None)
                
                if pd.notna(player_pos_raw) and pd.notna(player_rating):
                    depth_pos = map_position_to_depth(player_pos_raw)
                    try:
                        points = get_rating_points(float(player_rating), all_ratings)
                        position_points[team][depth_pos] += points
                    except Exception:
                        pass
        
        # Rank teams for each position based on TOTAL POINTS
        for pos in DEPTH_POSITIONS:
            team_totals = []
            for team in teams:
                total_pts = position_points[team][pos]
                team_totals.append((team, total_pts))
            
            # Sort by total points (descending) and assign ranks
            team_totals.sort(key=lambda x: x[1], reverse=True)
            for rank, (team, pts) in enumerate(team_totals, 1):
                if team == df_team["Team"].iloc[0]:
                    position_rankings[pos] = (rank, len(teams), pts)
                    break

    # Helper function to get ordinal suffix
    def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    
    # Helper function to get ranking color (same as Team Breakdown)
    def get_ranking_color(rank, total=18):
        if rank <= 4:
            return "#006400"  # dark green
        elif rank <= 9:
            return "#90EE90"  # light green
        elif rank <= 14:
            return "#FFA500"  # orange
        else:
            return "#FF0000"  # red

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
            text_color = "black" if color == "#90EE90" else "white"
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
            text_color = "black" if color == "#90EE90" else "white"
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

PAGES = ["Home", "Overview", "Team Breakdown", "Team Compare", "Club List", "Player Profile", "Player Traits", "Depth Chart", "Team Age Breakdown", "List Ladder", "Team List Summary", "Best 23", "List Breakdown - Traits", "Game Day Playground", "IDP", "Game Model Scorecard"]

# Initialize session state for page navigation
if "selected_page" not in st.session_state:
    st.session_state.selected_page = "Home"
if "page_override" not in st.session_state:
    st.session_state.page_override = False

# Check if there's a page override from a button click
if st.session_state.page_override:
    page = st.session_state.selected_page
    # Show sidebar with the current page selected
    st.sidebar.radio("Navigate", PAGES, index=PAGES.index(page) if page in PAGES else 0, key="page_nav")
    # Clear the override flag for next rerun
    st.session_state.page_override = False
else:
    # Normal sidebar navigation
    page = st.sidebar.radio("Navigate", PAGES, index=PAGES.index(st.session_state.selected_page) if st.session_state.selected_page in PAGES else 0, key="page_nav")
    # Update session state with the current page selection
    st.session_state.selected_page = page


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
    # Center content with columns
    col1, col2, col3 = st.columns([1, 3, 1])
    
    with col2:
        # Display main logo image
        logo_path = "team_logos/Logo Transparent.png"
        
        if os.path.exists(logo_path):
            st.markdown("<style>.home-logo img { filter: drop-shadow(0 0 20px rgba(255,255,255,0.4)) drop-shadow(0 4px 12px rgba(0,0,0,0.5)); }</style><div class='home-logo'>", unsafe_allow_html=True)
            st.image(logo_path)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            # Fallback if logo not found - show placeholder
            st.markdown(
                "<div style='text-align: center; font-size: 100px; color: #999;'>🏉</div>",
                unsafe_allow_html=True
            )
        
        # Heading
        st.markdown(
            """
            <h1 style='text-align: center; font-size: 2.5em; margin-top: 40px;'>
                AFL Dashboards
            </h1>
            """,
            unsafe_allow_html=True
        )
        
        # Team selection instruction
        st.markdown(
            """
            <h3 style='text-align: center; color: #FFFFFF; margin-top: 30px; margin-bottom: 30px;'>
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
                        # Display logo
                        img = Image.open(team_logo_path)
                        # Resize image to fixed dimensions for consistency
                        img_resized = img.resize((120, 120), Image.Resampling.LANCZOS)
                        st.image(img_resized, width="content")
                        
                        # Add small spacer before button
                        st.markdown('<div style="height: 5px;"></div>', unsafe_allow_html=True)
                        # Create clickable button
                        if st.button("Select", key=f"home_team_{team}_{idx}", width="stretch", help=f"Select {team}"):
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
                        # Display logo
                        img = Image.open(team_logo_path)
                        # Resize image to fixed dimensions for consistency
                        img_resized = img.resize((120, 120), Image.Resampling.LANCZOS)
                        st.image(img_resized, width="content")
                        
                        # Add small spacer before button
                        st.markdown('<div style="height: 5px;"></div>', unsafe_allow_html=True)
                        # Create clickable button
                        if st.button("Select", key=f"home_team_{team}_{idx+9}", width="stretch", help=f"Select {team}"):
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
        st.dataframe(df, use_container_width=True, hide_index=True)


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
        # Dark green, light green, orange, red
        if score >= 85: return "#0B6E4F"
        if score >= 70: return "#3FB984"
        if score >= 55: return "#F4A261"
        return "#C44536"

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
        team_a = st.selectbox("Team A", teams, key="gdp_team_a")
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
    
    # Professional footer
    render_footer()


# ================= OVERVIEW =================
if page == "Overview":
    import textwrap
    import pandas as pd
    import streamlit as st

    st.title("🏉 FutureEdge AFL Dashboard – Overview")

    # ----------------------------
    # Helpers (render_html is imported from top of file)
    # ----------------------------
    def to_ordinal(n):
        if pd.isna(n) or n == "":
            return ""
        try:
            n = int(float(n))
        except Exception:
            return ""
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

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

    selected_option = st.selectbox(
        "Select Year & Data Window",
        year_options,
        index=0,
        help="Choose which year to view. Last 10 Games only available for 2025.",
    )

    if " - Last 10 Games" in selected_option:
        selected_season = 2025
        window = "Last 10 Games"
    else:
        selected_season = int(selected_option.split(" - ")[0])
        window = "Season"

    last10 = window == "Last 10 Games"
    period_label = f"{window} ({selected_season})"

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
            ladder_view[c] = pd.to_numeric(ladder_view[c], errors="coerce").apply(to_ordinal)

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

    # Build HTML with NO leading indentation + dedent at the end
    html = []
    html.append("""
    <style>
    .overview-ladder-table{
        width:100%;
        border-collapse:separate;
        border-spacing:0;
        margin:20px 0;
        border-radius:12px;
        overflow:hidden;
        background:#ffffff;
        font-size:0.90em;
        box-shadow:0 4px 20px rgba(0,0,0,0.15);
    }
    .overview-ladder-table th{
        padding:14px 8px;
        text-align:center;
        font-weight:900;
        font-size:0.85em;
        letter-spacing:0.5px;
        border-right:1px solid rgba(255,255,255,0.15);
        white-space:pre-line;
        line-height:1.25;
        border-bottom:2px solid rgba(0,0,0,0.10);
    }
    .overview-ladder-table th:first-child{
        text-align:left;
        padding-left:18px;
    }
    .overview-ladder-table td{
        padding:12px 8px;
        text-align:center;
        font-weight:800;
        border-bottom:1px solid rgba(0,0,0,0.06);
        border-right:1px solid rgba(0,0,0,0.04);
    }
    .overview-ladder-table td:first-child{
        text-align:left;
        padding-left:18px;
        font-weight:900;
        background:#fafafa !important;
        border-right:2px solid rgba(0,0,0,0.08);
        color:#1a1a1a;
    }
    .overview-ladder-table tr:hover{
        background:#f6f6f6;
    }
    </style>
    """)

    html.append("<table class='overview-ladder-table'><thead><tr>")

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

    # CRITICAL: dedent/strip to avoid Streamlit showing HTML as a string
    render_html(st, "\n".join(html))

    st.caption(f"Teams shown: {ladder_view['Team'].nunique()} (should be 18)")



# ================= TEAM BREAKDOWN =================

elif page == "Team Breakdown":
    st.title("📊 Team Breakdown")

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
    team_name = st.selectbox("Select a team", team_list, index=default_idx)

    team_row = ladders[ladders["Team"] == team_name].iloc[0]
    
    # Display team logo with centered positioning
    st.markdown("---")
    st.markdown(f"<h2 style='text-align: center; color: #FFFFFF; margin-bottom: 20px;'>{team_name}</h2>", unsafe_allow_html=True)
    
    team_code = TEAM_CODE_MAP.get(team_name, team_name.lower().replace(" ", ""))
    team_logo_path = f"{LOGO_FOLDER}/{team_code}.png"
    
    # Get ladder position and percentage for this team and season with colors
    ladder_position_str, ladder_position_rank, position_color = get_ladder_position(team_name, selected_year)
    ladder_percentage_str, percentage_rank, percentage_color = get_ladder_percentage(team_name, selected_year)
    
    # Determine text color based on background color
    def get_text_color(bg_color):
        if bg_color in ["#006400", "#FF0000"]:  # dark colors
            return "white"
        else:  # light colors
            return "black"
    
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
            
            st.plotly_chart(fig, use_container_width=True)
            
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
            if rank_int <= 4:
                color = "#006400"
                bg_gradient = "linear-gradient(135deg, rgba(0,100,0,0.2) 0%, rgba(0,100,0,0.1) 100%)"
                border_color = "#00AA00"
            elif rank_int <= 9:
                color = "#90EE90"
                bg_gradient = "linear-gradient(135deg, rgba(144,238,144,0.2) 0%, rgba(144,238,144,0.1) 100%)"
                border_color = "#90EE90"
            elif rank_int <= 14:
                color = "#FFA500"
                bg_gradient = "linear-gradient(135deg, rgba(255,165,0,0.2) 0%, rgba(255,165,0,0.1) 100%)"
                border_color = "#FFA500"
            else:
                color = "#FF0000"
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
        # Show first 4 stats in 4 columns
        stat_cols = st.columns(4)
        for idx, stat_name in enumerate(stat_names[:4]):
            dist_df = get_attribute_stat_distribution(
                summary_year,
                selected_attribute,
                stat_name,
                block=which_block,
            )
            with stat_cols[idx]:
                # add a subtle right border between columns for visual separation
                col_border = (
                    "border-right:2px solid rgba(255,215,0,0.2);padding-right:12px;margin-right:8px;"
                    if idx < 3
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
                            main_color = "#006400"
                            bg_gradient = "linear-gradient(135deg, rgba(0,100,0,0.3) 0%, rgba(0,100,0,0.1) 100%)"
                            border_color = "#00AA00"
                        elif rank <= 9:
                            main_color = "#90EE90"
                            bg_gradient = "linear-gradient(135deg, rgba(144,238,144,0.3) 0%, rgba(144,238,144,0.1) 100%)"
                            border_color = "#90EE90"
                        elif rank <= 14:
                            main_color = "#FFA500"
                            bg_gradient = "linear-gradient(135deg, rgba(255,165,0,0.3) 0%, rgba(255,165,0,0.1) 100%)"
                            border_color = "#FFA500"
                        else:
                            main_color = "#FF0000"
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
                        # Averages
                        st.markdown("<hr style='border:0;border-top:2px solid rgba(255,215,0,0.3);margin:16px 0;'>", unsafe_allow_html=True)
                        st.markdown("<h4 style='color: #FFFFFF; margin-bottom: 10px;'>📊 Averages</h4>", unsafe_allow_html=True)
                        if not top4.empty and top4["Value"].notna().any():
                            avg_top4 = top4["Value"].dropna().mean()
                            st.metric("Top 4", f"{avg_top4:.1f}")
                        else:
                            st.metric("Top 4", "–")
                    # close the bordered div
                    st.markdown("</div>", unsafe_allow_html=True)



# ================= TEAM COMPARE =================

elif page == "Team Compare":
    st.title("⚖️ Team Compare")
    
    # Helper function for ordinal formatting
    def get_ordinal(n):
        """Convert number to ordinal string (1st, 2nd, 3rd, etc.)"""
        try:
            n = int(n)
            if 10 <= n % 100 <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
            return f"{n}{suffix}"
        except:
            return str(n)

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
    
    # Year and data window selection combined
    selected_option = st.selectbox(
        "Select Year & Data Window",
        year_options,
        index=0 if year_options else None,
        help="Choose which year to view. Last 10 Games only available for 2025.",
        key="team_compare_period"
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

    st.caption(f"Comparing: {period_label}")

    # Normalize team names in ladders DataFrame
    ladders["Team"] = ladders["Team"].replace({
        "GWS": "GWS Giants",
        "Greater Western Sydney": "GWS Giants"
    })
    
    team_list = sorted(ladders["Team"].unique())
    
    # Team selection columns
    col1, col2 = st.columns(2)
    with col1:
        # Set default index for team1 based on session state
        default_idx1 = 0
        if "default_team" in st.session_state and st.session_state.default_team in team_list:
            default_idx1 = team_list.index(st.session_state.default_team)
        team1 = st.selectbox("Team 1 (Base)", team_list, index=default_idx1, key="team_compare_team1")
    with col2:
        # Default to different team if available
        default_idx = 1 if len(team_list) > 1 else 0
        team2 = st.selectbox("Team 2 (Comparison)", team_list, index=default_idx, key="team_compare_team2")
    
    if team1 == team2:
        st.warning("Please select two different teams to compare.")
        st.stop()
    
    # Display team logos with reflection effect
    st.markdown("---")
    logo_col1, logo_col2 = st.columns(2)
    
    with logo_col1:
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
    
    # Get team rows
    team1_row = ladders[ladders["Team"] == team1].iloc[0]
    team2_row = ladders[ladders["Team"] == team2].iloc[0]
    
    # ========== SIMILARITY SCORE CALCULATION ==========
    # Calculate similarity score between the two teams based on all available metrics
    similarity_metrics = []
    for col in ladders.columns:
        if col == "Team" or col not in team1_row.index or col not in team2_row.index:
            continue
        try:
            val1 = float(team1_row[col])
            val2 = float(team2_row[col])
            # Skip if either value is NaN
            if pd.isna(val1) or pd.isna(val2):
                continue
            # Get column range for normalization
            col_min = ladders[col].min()
            col_max = ladders[col].max()
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
            
            st.plotly_chart(fig, use_container_width=True)
            
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

# ================= CLUB LIST =================
elif page == "Club List":
    st.title("📋 Club List")

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
        df = load_players(int(season))
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

    # Remove unrated rows
    df = df.dropna(subset=["RatingPoints_Avg"]).copy()
    if df.empty:
        st.warning(f"No rated players found for {season}.")
        st.stop()

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

    # ---------- Toggle ----------
    if "club_list_full" not in st.session_state:
        st.session_state.club_list_full = False

    c1, c2, _ = st.columns([1, 1, 6])
    with c1:
        if st.button("Show full list", use_container_width=True):
            st.session_state.club_list_full = True
    with c2:
        if st.button("Top 5 only", use_container_width=True):
            st.session_state.club_list_full = False

    # ---------- Team slice ----------
    if not selected_teams:
        st.info("Select at least one team to display.")
        st.stop()

    team_df = df[df["Team"].isin(selected_teams)].copy()

    if team_df.empty:
        st.info("No players found for this team.")
        st.stop()

    team_df = team_df.sort_values("RatingPoints_Avg", ascending=False).reset_index(drop=True)

    # ---------- Rankings (season-wide) ----------
    season_df = df.sort_values("RatingPoints_Avg", ascending=False).reset_index(drop=True)

    season_df["CompRank"] = season_df["RatingPoints_Avg"].rank(method="min", ascending=False).astype(int)

    season_df["DepthPos"] = season_df["Position"].apply(
        lambda x: map_position_to_depth(x) if pd.notna(x) and str(x).strip() != "" else "—"
    )

    season_df["PosRank"] = (
        season_df.groupby("DepthPos")["RatingPoints_Avg"]
        .rank(method="min", ascending=False)
        .astype(int)
    )

    # Merge ranks by Player (within-season unique enough)
    rank_map = season_df.set_index("Player")[["CompRank", "PosRank", "DepthPos"]]
    team_df = team_df.join(rank_map, on="Player")

    def ordinal(n):
        if pd.isna(n):
            return "—"
        n = int(n)
        if 10 <= n % 100 <= 20:
            return f"{n}th"
        return f"{n}{ {1:'st',2:'nd',3:'rd'}.get(n%10,'th') }"

    # ---------- Build output ----------
    out = pd.DataFrame({
        "PLAYER": team_df["Player"].fillna("—"),
        "COMP RANK": team_df["CompRank"].apply(ordinal),
        "POS RANK": team_df["PosRank"].apply(ordinal),
        "SEASON": int(season),
        "TEAM": team_df["Team"].fillna("—"),
        "POSITION": team_df["DepthPos"].fillna("—"),
        "AGE": pd.to_numeric(team_df["Age"], errors="coerce").round(1),
        "MATCHES": pd.to_numeric(team_df["Matches"], errors="coerce").fillna(0).astype(int),
        "RATING": pd.to_numeric(team_df["RatingPoints_Avg"], errors="coerce").round(1),
    })


    if not st.session_state.club_list_full:
        out = out.head(5).copy()

    # ---------- Render in Player Profile style (IMPORTANT: use render_html) ----------
    league_ratings = season_df["RatingPoints_Avg"].dropna()

    html = """
<style>
.player-season-table {
    width: 100%;
    border-collapse: collapse;
    background: #2a2a2a;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.player-season-table th {
    background: linear-gradient(135deg, #1a1a1a, #3a3a3a);
    color: white;
    padding: 14px;
    text-align: center;
    font-weight: 900;
    font-size: 0.85em;
}
.player-season-table td {
    padding: 10px;
    text-align: center;
    font-weight: 600;
    color: #ccc;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}
.player-season-table tbody tr:nth-child(even) { background: #333333; }
.player-season-table tbody tr:hover { background: #4a4a4a; }
.player-season-table td:first-child { text-align: left; padding-left: 14px; }
.player-season-table th:first-child { text-align: left; padding-left: 14px; }

</style>

<table class="player-season-table">
<thead>
<tr>
<th>PLAYER</th>
<th>COMP RANK</th>
<th>POS RANK</th>
<th>SEASON</th>
<th>TEAM</th>
<th>POSITION</th>
<th>AGE</th>
<th>MATCHES</th>
<th>RATING</th>
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

        rating_str = "—" if pd.isna(rating_val) else f"{float(rating_val):.1f}"

        html += f"""
<tr>
<td>{r['PLAYER']}</td>
<td>{r['COMP RANK']}</td>
<td>{r['POS RANK']}</td>
<td>{r['SEASON']}</td>
<td>{r['TEAM']}</td>
<td>{r['POSITION']}</td>
<td>{age_str}</td>
<td>{matches_str}</td>
<td style="background-color:{bg}; color:{fg}; font-weight:900;">{rating_str}</td>
</tr>
"""


    html += "</tbody></table>"

    # CRITICAL: render_html prevents HTML appearing as a code block
    render_html(st, html)
    
    # Professional footer
    render_footer()


# ================= PLAYER PROFILE =================
elif page == "Player Profile":
    import textwrap

    st.title("👤 Player Profile")

    # (render_html is imported from top of file)

    # Helper: ordinal
    def get_ordinal(n):
        try:
            n = int(n)
        except Exception:
            return "N/A"
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def safe_float(x):
        try:
            return float(x)
        except Exception:
            return None

    def safe_int(x):
        try:
            return int(float(x))
        except Exception:
            return None

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
    selected_season = st.selectbox("Select Season", seasons_available, index=default_season_idx, key="pp_season")

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

    # Player selection
    team_players = players_season[players_season["Team"] == selected_team].copy()
    player_names = sorted([p for p in team_players["Player"].dropna().unique().tolist() if str(p).strip() != ""])
    if not player_names:
        st.warning("No players found for this team.")
        st.stop()

    selected_player = st.selectbox("Select Player", player_names, key="pp_player")

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
    contract_expiry = summary_row.get("Contract Expiry") if summary_row is not None else None
    rating_pct_2025 = summary_row.get("2025 Rating %") if summary_row is not None else None
    cap_value_2025 = summary_row.get("2025 Cap Value") if summary_row is not None else None

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
        st.altair_chart(chart, use_container_width=True)

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
            current_season=2025,
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

            st.altair_chart(combined.properties(height=300).interactive(), use_container_width=True)

            with st.expander("📊 View Detailed Predictions", expanded=False):
                pred_table = pred.copy()
                for c in ["Predicted_Rating", "Upper_Band", "Lower_Band"]:
                    if c in pred_table.columns:
                        pred_table[c] = pd.to_numeric(pred_table[c], errors="coerce").round(1)
                st.dataframe(pred_table, hide_index=True, use_container_width=True)
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

        html_season_table = """
        <style>
        .player-season-table {
            width: 100%;
            border-collapse: collapse;
            background: #2a2a2a;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            margin-bottom: 40px;
        }
        .player-season-table th {
            background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
            color: #FFFFFF;
            padding: 14px 10px;
            text-align: center;
            font-weight: 900;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-right: 1px solid rgba(255,255,255,0.1);
        }
        .player-season-table th:nth-child(3) { text-align: left; }
        .player-season-table th:last-child { border-right: none; }
        .player-season-table td {
            padding: 10px;
            text-align: center;
            font-size: 0.9em;
            font-weight: 600;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            border-right: 1px solid rgba(255,255,255,0.05);
            color: #CCCCCC;
        }
        .player-season-table td:nth-child(3) { text-align: left; }
        .player-season-table td:last-child { border-right: none; }
        .player-season-table tbody tr { background: #3a3a3a; transition: all 0.3s ease; }
        .player-season-table tbody tr:hover {
            background: #4a4a4a;
            transform: scale(1.002);
            box-shadow: 0 4px 12px rgba(200,200,200,0.2);
        }
        .player-season-table tbody tr:nth-child(even) { background: #333333; }
        .player-season-table tbody tr:nth-child(even):hover { background: #4a4a4a; }
        </style>
        <table class='player-season-table'>
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
        st.markdown(textwrap.dedent(html_season_table).strip(), unsafe_allow_html=True)

    # -----------------------------------
    # Traits Snapshot (ENRICHED, selected season)
    # -----------------------------------
    st.markdown("---")
    st.markdown("<h3 style='color: #FFFFFF; margin-bottom: 15px;'>🎯 Traits Snapshot (ENRICHED)</h3>", unsafe_allow_html=True)

    try:
        traits_selected = load_traits(int(selected_season))
        if traits_selected is not None and not traits_selected.empty and "Player_Full" in traits_selected.columns:
            t = traits_selected[traits_selected["Player_Full"] == selected_player].copy()
            if not t.empty:
                row = t.iloc[0]
                cols = st.columns(5)
                metrics = [
                    ("Rating", row.get("Rating")),
                    ("Ball Winning", row.get("Ball Winning")),
                    ("Ball Use", row.get("Ball Use")),
                    ("Aerial", row.get("Aerial")),
                    ("Defence", row.get("Defence")),
                ]
                for i, (label, val) in enumerate(metrics):
                    with cols[i]:
                        v = safe_float(val)
                        st.metric(label, "—" if v is None else f"{v:.2f}")
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
            player_traits_2025 = traits_2025[traits_2025["Player_Full"] == selected_player].copy()

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
                # Render KPI cards
                # ---------------------------
                

                st.markdown("---")
                st.markdown("<h3 style='text-align: center; color: #FFFFFF; margin-top: 30px; margin-bottom: 25px;'>⭐ Key Performance Metrics (2025 Traits)</h3>", unsafe_allow_html=True)

                key_metrics = []

                if rv is not None:
                    all_ratings_traits = pd.to_numeric(all_traits_sorted["Rating"], errors="coerce").dropna()
                    bg_color, _ = rating_colour_for_value(rv, all_ratings_traits)
                    rating_label = get_trait_label(rv)

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
                        <div style='color: {rating_text_color}; font-size: 4em; font-weight: 900; line-height: 1;'>{rv:.2f}</div>
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
                    c1, c2, c3 = st.columns(3)
                    if len(key_metrics) > 0:
                        render_html(c1, key_metrics[0])
                    if len(key_metrics) > 1:
                        render_html(c2, key_metrics[1])
                    if len(key_metrics) > 2:
                        render_html(c3, key_metrics[2])

                st.markdown("---")
                st.markdown("<h3 style='text-align: center; color: #FFFFFF; margin-top: 30px; margin-bottom: 25px;'>📊 Trait Analysis</h3>", unsafe_allow_html=True)

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
                            trait_label = get_trait_label(trait_val)
                            r, g, b = int(trait_color.lstrip('#')[:2], 16), int(trait_color.lstrip('#')[2:4], 16), int(trait_color.lstrip('#')[4:], 16)

                            substats_html = ""
                            for substat_name, substat_value in substats.items():
                                if substat_value not in [None, ""] and pd.notna(substat_value):
                                    try:
                                        substat_val = float(substat_value)
                                        substat_label = get_trait_label(substat_val)
                                        substats_html += textwrap.dedent(f"""
                                        <div style='background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-bottom: 6px;'>
                                            <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>{substat_name}</div>
                                            <div style='color: #FFFFFF; font-size: 1.2em; font-weight: 800;'>
                                                {substat_val:.2f} <span style='font-size: 0.7em; font-weight: 600;'>{substat_label}</span>
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
                                <div style='color: #FFFFFF; font-size: 2.5em; font-weight: 900;'>{trait_val:.2f}</div>
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
    st.title("🎯 Player Traits")

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

    def get_ordinal(n):
        try:
            n = int(n)
        except Exception:
            return "N/A"
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

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
    # Season selection
    # -------------------------
    seasons_available = sorted(get_player_seasons(), reverse=True)
    if not seasons_available:
        seasons_available = [2025, 2024, 2023]

    primary_season = st.selectbox("Select Season", seasons_available, index=0, key="traits_primary_season")

    default_history = [s for s in seasons_available if s >= (int(primary_season) - 2)]
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

        # ---- Styled HTML table (matches your other tables) ----
        traits_html = """
    <style>
    .traits-history-table {
        width: 100%;
        border-collapse: collapse;
        background: #2a2a2a;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        margin-bottom: 40px;
    }
    .traits-history-table th {
        background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
        color: #FFFFFF;
        padding: 14px 10px;
        text-align: center;
        font-weight: 900;
        font-size: 0.9em;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-right: 1px solid rgba(255,255,255,0.1);
    }
    .traits-history-table th:nth-child(2),
    .traits-history-table td:nth-child(2),
    .traits-history-table th:nth-child(3),
    .traits-history-table td:nth-child(3) {
        text-align: left;
    }
    .traits-history-table th:last-child,
    .traits-history-table td:last-child { border-right: none; }

    .traits-history-table td {
        padding: 10px;
        text-align: center;
        font-size: 0.9em;
        font-weight: 600;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        border-right: 1px solid rgba(255,255,255,0.05);
        color: #CCCCCC;
    }

    .traits-history-table tbody tr { background: #3a3a3a; transition: all 0.3s ease; }
    .traits-history-table tbody tr:nth-child(even) { background: #333333; }
    .traits-history-table tbody tr:hover {
        background: #4a4a4a;
        transform: scale(1.002);
        box-shadow: 0 4px 12px rgba(200,200,200,0.2);
    }
    </style>

    <table class="traits-history-table">
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

        def fmt2(x):
            return "—" if pd.isna(x) else f"{float(x):.2f}"

        for _, r in view.iterrows():
            traits_html += "<tr>"
            for c in view.columns:
                if c == "Rating":
                    v = r.get(c, np.nan)
                    if pd.notna(v) and len(league_ratings) > 0:
                        bg, fg = rating_colour_for_value(float(v), league_ratings)
                        traits_html += f"<td style='background-color:{bg}; color:{fg}; font-weight:900;'>{fmt2(v)}</td>"
                    else:
                        traits_html += "<td>—</td>"
                else:
                    # numeric trait formatting
                    if c in ["Ball Winning", "Ball Use", "Aerial", "Defence"]:
                        traits_html += f"<td>{fmt2(r.get(c, np.nan))}</td>"
                    else:
                        traits_html += f"<td>{r.get(c, '—')}</td>"
            traits_html += "</tr>"

        traits_html += """
    </tbody>
    </table>
    """

    render_html(st, traits_html)


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
            <div style='color: {rating_text_color}; font-size: 4em; font-weight: 900; line-height: 1;'>{rating_val:.2f}</div>
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
            sub_label = get_trait_label(sub_val)

            substats_html_parts.append(
                f"<div style='background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-bottom: 6px;'>"
                f"  <div style='color: rgba(255,255,255,0.7); font-size: 0.75em; margin-bottom: 4px;'>{sanitize_text(substat_name)}</div>"
                f"  <div style='color: #FFFFFF; font-size: 1.2em; font-weight: 800;'>"
                f"    {sub_val:.2f} <span style='font-size: 0.7em; font-weight: 600;'> {sanitize_text(sub_label)}</span>"
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
            <div style='color: #FFFFFF; font-size: 2.5em; font-weight: 900;'>{trait_val:.2f}</div>
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
    st.title("📋 Depth Chart")

    summary_df = load_player_summary()
    if summary_df.empty:
        st.error("Could not load Summary sheet from AFL Player Ratings.")
        st.stop()

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
    
    # Also add RatingPoints_Avg to the full summary_df for ranking calculations
    summary_df_with_ratings = summary_df.copy()
    summary_df_with_ratings["RatingPoints_Avg"] = pd.to_numeric(
        summary_df_with_ratings[rating_col_name], errors="coerce"
    )

    st.markdown(
        f"#### Squad Depth Grid – {selected_team} "
        f"({rating_label}, coloured by team percentile)"
    )

    html = build_depth_chart_html(df_team, summary_df_with_ratings)
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
    players_df["Total_Rating_Points"] = players_df["RatingPoints_Avg"] * players_df["Matches"]

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
    
    # Helper function to get rank color
    def get_rank_color_age(rank_val):
        if rank_val <= 4:
            return "#006400", "white"  # dark green
        elif rank_val <= 9:
            return "#90EE90", "black"  # light green
        elif rank_val <= 14:
            return "#FFA500", "white"  # orange
        else:
            return "#FF0000", "white"  # red
    
    # Create professional HTML table with color-coded rankings
    html_table = """<style>
.age-breakdown-table {
    width: 100%;
    border-collapse: collapse;
    background: #2a2a2a;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    margin-bottom: 40px;
}
.age-breakdown-table th {
    background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
    color: #FFFFFF;
    padding: 16px 12px;
    text-align: center;
    font-weight: 900;
    font-size: 0.95em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-right: 1px solid rgba(255,255,255,0.1);
}
.age-breakdown-table th:first-child {
    text-align: left;
    padding-left: 20px;
}
.age-breakdown-table th:last-child {
    border-right: none;
}
.age-breakdown-table td {
    padding: 12px;
    text-align: center;
    font-size: 0.95em;
    font-weight: 600;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    border-right: 1px solid rgba(255,255,255,0.05);
    color: #CCCCCC;
}
.age-breakdown-table td:first-child {
    text-align: left;
    padding-left: 20px;
    font-weight: 700;
    color: #FFFFFF;
}
.age-breakdown-table td:last-child {
    border-right: none;
}
.age-breakdown-table tbody tr {
    background: #3a3a3a;
    transition: all 0.3s ease;
}
.age-breakdown-table tbody tr:hover {
    background: #4a4a4a;
    transform: scale(1.002);
    box-shadow: 0 4px 12px rgba(200,200,200,0.2);
}
.age-breakdown-table tbody tr:nth-child(even) {
    background: #333333;
}
.age-breakdown-table tbody tr:nth-child(even):hover {
    background: #4a4a4a;
}
.age-breakdown-table .league-avg-row {
    background: linear-gradient(135deg, #2d2d2d 0%, #1a1a1a 100%) !important;
    border-top: 3px solid #CCCCCC !important;
}
.age-breakdown-table .league-avg-row td {
    font-weight: 800 !important;
    color: #FFFFFF !important;
    font-size: 1.05em !important;
}
.age-breakdown-table .league-avg-row:hover {
    background: linear-gradient(135deg, #2d2d2d 0%, #1a1a1a 100%) !important;
    transform: none !important;
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
<table class='age-breakdown-table'>
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
    st.markdown(html_table, unsafe_allow_html=True)
    
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
    required_cols = ["Player", "Team", "Position", "RatingPoints_Avg"]
    missing_cols = [c for c in required_cols if c not in players_df.columns]
    if missing_cols:
        st.error(f"Missing required columns: {', '.join(missing_cols)}")
        st.stop()

    # Get all ratings for percentile calculation
    all_ratings = players_df["RatingPoints_Avg"].dropna()
    
    # Define get_rating_points function
    def get_rating_points(rating_val, all_ratings_clean):
        """Convert rating to points based on percentile."""
        if pd.isna(rating_val):
            return 0
        
        percentile = (all_ratings_clean <= rating_val).mean()
        
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
    
    # Map players to depth positions, using Summary tab positions when available
    def get_depth_position(player_name, fallback_position):
        # First check if player has position in Summary tab
        if pd.notna(player_name) and str(player_name).strip() in summary_positions:
            summary_pos = summary_positions[str(player_name).strip()]
            return map_position_to_depth(summary_pos)
        # Otherwise use the position from player data
        return map_position_to_depth(fallback_position) if pd.notna(fallback_position) else "Midfielder"
    
    players_df["Depth_Position"] = players_df.apply(
        lambda row: get_depth_position(row.get("Player"), row.get("Position")), axis=1
    )
    
    # Calculate points for each player
    players_df["Points"] = players_df["RatingPoints_Avg"].apply(
        lambda r: get_rating_points(r, all_ratings)
    )
    
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
    
    # Professional explanation
    st.markdown("""<div style='background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; border: 1px solid rgba(255,215,0,0.2); margin-bottom: 25px;'><h4 style='color: #FFFFFF; margin-top: 0; font-size: 1.3em;'>Ranking Guide</h4><div style='display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px;'><div style='text-align: center; padding: 15px; background: #006400; border-radius: 8px;'><strong style='color: white; font-size: 1.1em;'>1st - 4th</strong><br><span style='color: #CCCCCC; font-size: 0.9em;'>Elite</span></div><div style='text-align: center; padding: 15px; background: #90EE90; border-radius: 8px;'><strong style='color: black; font-size: 1.1em;'>5th - 9th</strong><br><span style='color: #333333; font-size: 0.9em;'>Strong</span></div><div style='text-align: center; padding: 15px; background: #FFA500; border-radius: 8px;'><strong style='color: white; font-size: 1.1em;'>10th - 14th</strong><br><span style='color: #EEEEEE; font-size: 0.9em;'>Average</span></div><div style='text-align: center; padding: 15px; background: #FF0000; border-radius: 8px;'><strong style='color: white; font-size: 1.1em;'>15th - 18th</strong><br><span style='color: #EEEEEE; font-size: 0.9em;'>Needs Work</span></div></div><p style='color: #DDDDDD; line-height: 1.8; margin: 0;'><strong style='color: #FFFFFF;'>How to Read:</strong> Each position shows the team's rank (1st-18th) and total points accumulated by players in that position. Higher ranks and points indicate stronger depth. <strong style='color: #90EE90;'>Total Points</strong> column shows overall list strength.</p></div>""", unsafe_allow_html=True)
    
    # Helper function to get ordinal suffix
    def get_ordinal_suffix(n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    
    # Helper function to get color based on rank
    def get_rank_color(rank):
        if rank <= 4:
            return "#006400"  # Dark green
        elif rank <= 9:
            return "#90EE90"  # Light green
        elif rank <= 14:
            return "#FFA500"  # Orange
        else:
            return "#FF0000"  # Red
    
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
    
    # Create professional HTML table with color-coded rankings
    html_table = """<style>
.list-ladder-table {
    width: 100%;
    border-collapse: collapse;
    background: #2a2a2a;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    margin-bottom: 40px;
}
.list-ladder-table th {
    background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
    color: #FFFFFF;
    padding: 16px 12px;
    text-align: center;
    font-weight: 900;
    font-size: 0.95em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-right: 1px solid rgba(255,255,255,0.1);
}
.list-ladder-table th:first-child {
    text-align: center;
    width: 60px;
}
.list-ladder-table th:nth-child(2) {
    text-align: left;
    padding-left: 20px;
}
.list-ladder-table th:last-child {
    border-right: none;
    background: linear-gradient(135deg, #2a2a2a 0%, #1a1a1a 100%);
    color: white;
}
.list-ladder-table td {
    padding: 12px;
    text-align: center;
    font-size: 0.9em;
    font-weight: 600;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    border-right: 1px solid rgba(255,255,255,0.05);
    color: #CCCCCC;
}
.list-ladder-table td:first-child {
    text-align: center;
    font-weight: 800;
    color: #FFFFFF;
    font-size: 1em;
}
.list-ladder-table td:nth-child(2) {
    text-align: left;
    padding-left: 20px;
    font-weight: 700;
    color: #FFFFFF;
}
.list-ladder-table td:last-child {
    border-right: none;
    background: rgba(100,100,100,0.2);
    font-weight: 800;
    color: #FFFFFF;
    font-size: 1em;
}
.list-ladder-table tbody tr {
    background: #3a3a3a;
    transition: all 0.3s ease;
}
.list-ladder-table tbody tr:hover {
    background: #4a4a4a;
    transform: scale(1.002);
    box-shadow: 0 4px 12px rgba(200,200,200,0.2);
}
.list-ladder-table tbody tr:nth-child(even) {
    background: #333333;
}
.list-ladder-table tbody tr:nth-child(even):hover {
    background: #4a4a4a;
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
<table class='list-ladder-table'>
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
    st.markdown(html_table, unsafe_allow_html=True)
    
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
                        
                        # Create HTML table with color coding
                        html_player_table = """<style>
.player-breakdown-table {
    width: 100%;
    border-collapse: collapse;
    background: rgba(255,255,255,0.05);
    border-radius: 0 0 8px 8px;
    overflow: hidden;
}
.player-breakdown-table th {
    background: rgba(255,215,0,0.2);
    color: #FFFFFF;
    padding: 10px;
    text-align: left;
    font-weight: 800;
    font-size: 0.9em;
}
.player-breakdown-table td {
    padding: 8px 10px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    color: #FFFFFF;
}
.player-breakdown-table tr:hover {
    background: rgba(255,215,0,0.1);
}
</style>
<table class='player-breakdown-table'>
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
    st.title("📊 Team List Summary")
    
    # Team selection
    # Get teams from player data
    try:
        players_df = load_players(CURRENT_SEASON)
    except Exception as e:
        st.error(f"Error loading player data: {e}")
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
    ladder_data = []
    all_ratings = players_filtered["RatingPoints_Avg"].dropna()
    
    def get_rating_points(rating_val, all_ratings_clean):
        if pd.isna(rating_val):
            return 0
        percentile = (all_ratings_clean <= rating_val).mean()
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
    
    # Map players to depth positions, using Summary tab positions when available
    def get_depth_position(player_name, fallback_position):
        # First check if player has position in Summary tab
        if pd.notna(player_name) and str(player_name).strip() in summary_positions:
            summary_pos = summary_positions[str(player_name).strip()]
            return map_position_to_depth(summary_pos)
        # Otherwise use the position from player data
        return map_position_to_depth(fallback_position) if pd.notna(fallback_position) else "Midfielder"
    
    players_filtered["Depth_Position"] = players_filtered.apply(
        lambda row: get_depth_position(row.get("Player"), row.get("Position")), axis=1
    )
    players_filtered["Points"] = players_filtered["RatingPoints_Avg"].apply(
        lambda r: get_rating_points(r, all_ratings)
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
    
    # Helper function for rank color
    def get_rank_color_age(rank):
        if rank <= 4:
            return "#006400", "white"
        elif rank <= 9:
            return "#90EE90", "black"
        elif rank <= 14:
            return "#FFA500", "white"
        else:
            return "#FF0000", "white"
    
    # Create HTML table for age breakdown
    html_age_table = """<style>
.age-comparison-table {
    width: 100%;
    border-collapse: collapse;
    background: #2a2a2a;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    margin-bottom: 40px;
}
.age-comparison-table th {
    background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
    color: #FFFFFF;
    padding: 14px 10px;
    text-align: center;
    font-weight: 900;
    font-size: 0.9em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-right: 1px solid rgba(255,255,255,0.1);
}
.age-comparison-table th:last-child {
    border-right: none;
}
.age-comparison-table td {
    padding: 12px 10px;
    text-align: center;
    font-size: 0.95em;
    font-weight: 600;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    border-right: 1px solid rgba(255,255,255,0.05);
    color: #CCCCCC;
}
.age-comparison-table td:last-child {
    border-right: none;
}
.age-comparison-table tbody tr {
    background: #3a3a3a;
    transition: all 0.3s ease;
}
.age-comparison-table tbody tr:hover {
    background: #4a4a4a;
    transform: scale(1.002);
    box-shadow: 0 4px 12px rgba(200,200,200,0.2);
}
.age-comparison-table tbody tr:nth-child(even) {
    background: #333333;
}
.age-comparison-table tbody tr:nth-child(even):hover {
    background: #4a4a4a;
}
.rank-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 0.85em;
}
</style>
<table class='age-comparison-table'>
<thead>
<tr>
<th>Age Band</th>
<th>""" + selected_team + """</th>
<th>League Avg</th>
<th>Top 4 Avg</th>
<th>Diff vs League</th>
<th>Diff vs Top 4</th>
<th>Rank</th>
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
    st.markdown(html_age_table, unsafe_allow_html=True)
    
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
    
    # Create HTML table for positional depth
    html_pos_table = """<style>
.pos-comparison-table {
    width: 100%;
    border-collapse: collapse;
    background: #0a0e27;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    margin-bottom: 40px;
}
.pos-comparison-table th {
    background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
    color: #FFFFFF;
    padding: 14px 10px;
    text-align: center;
    font-weight: 900;
    font-size: 0.9em;
    letter-spacing: 0.5px;
    border-right: 1px solid rgba(255,255,255,0.1);
}
.pos-comparison-table th:first-child {
    text-align: left;
    padding-left: 20px;
}
.pos-comparison-table th:last-child {
    border-right: none;
}
.pos-comparison-table td {
    padding: 12px 10px;
    text-align: center;
    font-size: 0.95em;
    font-weight: 600;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    border-right: 1px solid rgba(255,255,255,0.05);
    color: #CCCCCC;
}
.pos-comparison-table td:first-child {
    text-align: left;
    padding-left: 20px;
}
.pos-comparison-table td:last-child {
    border-right: none;
}
.pos-comparison-table tbody tr {
    background: #1a1a1a;
    transition: all 0.3s ease;
}
.pos-comparison-table tbody tr:hover {
    background: #2a2a2a;
    transform: scale(1.002);
    box-shadow: 0 4px 12px rgba(255,255,255,0.1);
}
.pos-comparison-table tbody tr:nth-child(even) {
    background: #222222;
}
.pos-comparison-table tbody tr:nth-child(even):hover {
    background: #2a2a2a;
}
</style>
<table class='pos-comparison-table'>
<thead>
<tr>
<th>Position</th>
<th>""" + selected_team + """</th>
<th>League Avg</th>
<th>Top 4 Avg</th>
<th>Diff vs League</th>
<th>Diff vs Top 4</th>
<th>Rank</th>
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
    st.markdown(html_pos_table, unsafe_allow_html=True)
    
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
    
    # Overall ladder position
    team_overall_rank = position_ladder_df[position_ladder_df["Team"] == selected_team].index[0] + 1
    total_points = team_pos_data["Total Points"]
    league_avg_points = position_ladder_df["Total Points"].mean()
    
    if team_overall_rank <= 4:
        pos_analysis_points.append(f"🏆 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Elite list depth ({total_points:.1f} total points)")
    elif team_overall_rank <= 9:
        pos_analysis_points.append(f"📊 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Strong list depth ({total_points:.1f} total points)")
    elif team_overall_rank <= 14:
        pos_analysis_points.append(f"📊 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Average list depth ({total_points:.1f} total points)")
    else:
        pos_analysis_points.append(f"📊 <strong>Overall List Ranking:</strong> {get_ordinal_suffix(team_overall_rank)} - Below average list depth ({total_points:.1f} total points)")
    
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


    st.title("🏉 Best 23 – Model, Compare & Select")

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
    team = st.selectbox("Select Team", teams)
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
    .field {{
    position: relative;
    width: {FIELD_WIDTH_PX}px;
    height: {FIELD_HEIGHT_PX}px;
    background: url("data:image/png;base64,{bg}") center/contain no-repeat;
    margin: auto;
    }}

    .wrap {{
    position: absolute;
    transform: translate(-50%, -50%);
    }}

    .magnet {{
    width: 235px;                 /* ⬅ narrower */
    height: 44px;                 /* ⬅ shorter */
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    border-radius: 16px;
    color: #fff;
    font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
    font-weight: 800;
    box-shadow: 0 8px 18px rgba(0,0,0,.35);
    }}

    .num {{
    min-width: 30px;
    text-align: center;
    font-size: 13px;
    opacity: 0.95;
    }}

    .name {{
    display: flex;
    flex-direction: column;
    line-height: 1.05;
    }}

    .first {{
    font-size: 9px;
    opacity: 0.9;
    }}

    .last {{
    font-size: 13px;
    }}

    .rating {{
    margin-left: auto;            /* ⬅ right aligned */
    width: 40px;
    height: 28px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
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

    <div class="field">
    {magnets_html}
    </div>
    """

    import streamlit.components.v1 as components
    components.html(
        textwrap.dedent(html).strip(),
        height=FIELD_HEIGHT_PX + 20,
        scrolling=False
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
        team_a = st.selectbox("Team A", teams, key="best23_team_a")
    with c2:
        team_b = st.selectbox(
            "Team B",
            [t for t in teams if t != team_a],
            key="best23_team_b"
        )

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
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

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
    selected_season = st.selectbox(
        "Season",
        available_seasons,
        index=default_season_idx,
        key="traits_breakdown_season"
    )

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
        card_html = f"""<div style='background-color: {stats["color"]}; color: {stats["text_color"]}; padding: 25px 20px; border-radius: 12px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border: 2px solid rgba(255,255,255,0.15);'>
<div style='font-size: 0.85em; font-weight: 600; letter-spacing: 0.12em; opacity: 0.9; margin-bottom: 8px; text-transform: uppercase; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{trait_name}</div>
<div style='font-size: 2.5em; font-weight: 900; line-height: 1; margin: 8px 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{stats["avg"]:.2f}</div>
<div style='font-size: 0.95em; font-weight: 700; letter-spacing: 0.08em; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>#{stats["rank"]} of {stats["total"]}</div>
</div>"""
        trait_cards.append(card_html)
    
    trait_grid = "".join(trait_cards)
    
    overall_stats = team_stats["Overall Rating"]
    
    header_html = f"""<div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); padding: 40px 20px; border-radius: 20px; margin-bottom: 30px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); border: 2px solid #e94560;'>
<div style='text-align: center; margin-bottom: 20px;'>{logo_html}</div>
<h1 style='text-align: center; color: #FFFFFF; margin: 10px 0 30px 0; font-size: 3em; font-weight: 900; text-transform: uppercase; letter-spacing: 0.1em; text-shadow: 3px 3px 6px rgba(0,0,0,0.7); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{selected_team}</h1>
<div style='text-align: center; margin-bottom: 30px;'>
<div style='display: inline-block; background-color: {overall_stats["color"]}; color: {overall_stats["text_color"]}; padding: 20px 40px; border-radius: 15px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); border: 3px solid rgba(255,255,255,0.2);'>
<div style='font-size: 0.9em; font-weight: 600; letter-spacing: 0.15em; opacity: 0.9; margin-bottom: 5px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>OVERALL TRAIT RATING</div>
<div style='font-size: 3.5em; font-weight: 900; line-height: 1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;'>{overall_stats["avg"]:.2f}</div>
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

    html = build_depth_chart_html(df_team, traits_df_renamed)
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
    
    # Helper function to get color based on rank
    def get_ladder_rank_color(rank, total=18):
        if rank <= 4:
            return "#006400", "white"  # Dark green
        elif rank <= 9:
            return "#90EE90", "black"  # Light green
        elif rank <= 14:
            return "#FFA500", "white"  # Orange
        else:
            return "#FF0000", "white"  # Red
    
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
            
            ladder_html.append(f"<td style='{row_bg}padding:14px 12px;border-right:2px solid #e0e0e0;border-top:2px solid #e0e0e0;text-align:center;'><div style='display:inline-block;background:{bg};color:{fg};padding:10px 16px;border-radius:10px;font-weight:900;font-size:1.15em;box-shadow:0 3px 10px rgba(0,0,0,0.2);min-width:70px;'>{val:.2f}<div style='font-size:0.7em;opacity:0.8;margin-top:2px;'>#{trait_rank}</div></div></td>")
        
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
            
            st.plotly_chart(fig, use_container_width=True)
            
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
                    
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(90deg, rgba(0,204,0,0.1) 0%, rgba(0,204,0,0.05) 100%); 
                                    border-left: 4px solid #00CC00; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                            <div style='font-weight: bold; color: #00CC00;'>{metric}</div>
                            <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                {team1_trait}: <span style='font-weight: bold; color: #00FF00;'>{t1_val:.2f}</span> {t1_rank_str} 
                                <span style='color: #888;'>vs</span> 
                                {team2_trait}: <span style='font-weight: bold;'>{t2_val:.2f}</span> {t2_rank_str}
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
                    
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(90deg, rgba(255,68,68,0.1) 0%, rgba(255,68,68,0.05) 100%); 
                                    border-left: 4px solid #FF4444; padding: 12px; border-radius: 8px; margin-bottom: 10px;'>
                            <div style='font-weight: bold; color: #FF4444;'>{metric}</div>
                            <div style='font-size: 0.9em; color: #CCCCCC; margin-top: 6px;'>
                                {team1_trait}: <span style='font-weight: bold;'>{t1_val:.2f}</span> {t1_rank_str} 
                                <span style='color: #888;'>vs</span> 
                                {team2_trait}: <span style='font-weight: bold; color: #FF6666;'>{t2_val:.2f}</span> {t2_rank_str}
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
                                    {value:.2f}
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
                
                # Format value based on pillar type
                if pillar_name in ["DISPOSALS", "MARKS", "GOALS"]:
                    formatted_value = f"{value:.2f}"
                else:
                    formatted_value = f"{value:.2f}"
                
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
                    
                    # Format value
                    formatted_value = f"{value:.2f}"
                    
                    # Create rank badge using the same color as the rating with contrasting text
                    rank_badge = f'<div style="background: {rating_color};border-radius: 6px;padding: 4px 10px;margin-right: 10px;min-width: 32px;text-align: center;box-shadow: 0 2px 4px rgba(0,0,0,0.2);"><span style="font-size: 12px;font-weight: 900;color: {rating_text_color};font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;">#{rank}</span></div>'
                    
                    # Render card with rank badge
                    st.markdown(f'<div style="background: rgba(20,20,30,0.6);border: 1px solid rgba(255,255,255,0.1);border-radius: 8px;padding: 12px 14px;margin-bottom: 8px;display: flex;align-items: center;justify-content: space-between;"><div style="display: flex;align-items: center;flex: 1;min-width: 0;">{rank_badge}{logo_html}<div style="overflow: hidden;text-overflow: ellipsis;white-space: nowrap;"><span style="font-size: 14px;font-weight: 700;color: #FFFFFF;font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;">{full_name}</span></div></div><div style="font-size: 20px;font-weight: 900;color: {rating_color};font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif;margin-left: 12px;white-space: nowrap;">{formatted_value}</div></div>', unsafe_allow_html=True)

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
    .idp-comparison-table {
        width: 100%;
        border-collapse: collapse;
        background: rgba(255,255,255,0.05);
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    }
    .idp-comparison-table th {
        background: rgba(255,255,255,0.12);
        color: #FFFFFF;
        font-weight: 900;
        padding: 14px 12px;
        text-align: center;
        border-bottom: 2px solid rgba(255,255,255,0.2);
    }
    .idp-comparison-table td {
        padding: 12px;
        text-align: center;
        font-weight: 700;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        color: #FFFFFF;
    }
    .idp-comparison-table tbody tr:hover {
        background: rgba(255,255,255,0.08);
    }
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
    
    selected_season = st.selectbox("Select Season", seasons_available, index=0, key="idp_season")
    
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
    
    # ========== SECTION 1: TOP 10 POSITION BENCHMARKING ==========
    st.markdown("<div class='idp-section-header'>🎯 Position Benchmarking (Top 10)</div>", unsafe_allow_html=True)
    
    # Trait selection
    trait_options = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    selected_trait = st.selectbox("Select Trait to Analyze", trait_options, key="idp_trait_select")
    
    # Define sub-stats for each trait
    trait_substats = {
        "Rating": ["Ball Winning", "Ball Use", "Aerial", "Defence"],
        "Ball Winning": ["Stoppage", "Contest", "Power", "Receives"],
        "Ball Use": ["Handballing", "Kicking", "Goal Kicking", "Connecting"],
        "Aerial": ["Marking", "Contested", "Moks", "Ruck"],
        "Defence": ["Pressure", "Tackling", "Intercepting", "1v1"]
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
        
        # Create visually appealing metric cards
        st.markdown(f"""
        <div style='display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:24px;'>
            <div style='background:linear-gradient(135deg,{player_bg}25 0%,{player_bg}15 100%);border:2px solid {player_bg};border-radius:16px;padding:24px;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,0.3);'>
                <div style='color:rgba(255,255,255,0.8);font-size:13px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;'>Your Rating</div>
                <div style='color:{player_text};background:{player_bg};font-size:48px;font-weight:900;line-height:1;padding:16px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);'>{player_trait_val:.2f}</div>
            </div>
            <div style='background:linear-gradient(135deg,rgba(100,149,237,0.25) 0%,rgba(100,149,237,0.15) 100%);border:2px solid #6495ED;border-radius:16px;padding:24px;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,0.3);'>
                <div style='color:rgba(255,255,255,0.8);font-size:13px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;'>Top 10 Average</div>
                <div style='color:#FFFFFF;background:#6495ED;font-size:48px;font-weight:900;line-height:1;padding:16px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);'>{top10_trait_avg:.2f}</div>
            </div>
            <div style='background:linear-gradient(135deg,{delta_bg}25 0%,{delta_bg}15 100%);border:2px solid {delta_bg};border-radius:16px;padding:24px;text-align:center;box-shadow:0 6px 20px rgba(0,0,0,0.3);'>
                <div style='color:rgba(255,255,255,0.8);font-size:13px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;'>Difference</div>
                <div style='color:{delta_text};background:{delta_bg};font-size:48px;font-weight:900;line-height:1;padding:16px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);'>{delta:+.2f}</div>
                <div style='color:{delta_text};background:rgba(0,0,0,0.3);font-size:14px;font-weight:700;margin-top:10px;padding:6px 12px;border-radius:8px;'>{delta_pct:+.1f}%</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Spider graph comparing player to Top 10 average
    st.markdown("<h4 style='color:#FFFFFF;margin:28px 0 16px 0;font-weight:900;font-size:18px;'>Visual Comparison</h4>", unsafe_allow_html=True)
    
    import plotly.graph_objects as go
    
    # Get player values for the 5 main traits
    trait_categories = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
    player_values = [safe_float(player_data.get(trait, 0)) or 0 for trait in trait_categories]
    
    # Calculate Top 10 averages for each trait
    top10_values = []
    for trait in trait_categories:
        trait_avg = pd.to_numeric(top_10_position[trait], errors="coerce").mean()
        top10_values.append(trait_avg if pd.notna(trait_avg) else 0)
    
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
                range=[0, max(max(player_values), max(top10_values)) * 1.1],
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
    
    st.plotly_chart(fig, use_container_width=True, key="player_spider")
    
    # Sub-stats breakdown
    st.markdown("<h4 style='color:#FFFFFF;margin:24px 0 16px 0;font-weight:900;font-size:18px;'>Contributing Statistics</h4>", unsafe_allow_html=True)
    
    strengths = []
    focus_areas = []
    
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
        
        st.markdown(f"""<div class="idp-stat-row {category}" style="border-left-color:{border_color};"><div style="flex:1;"><span style="font-weight:900;font-size:15px;color:#FFFFFF;">{substat}</span></div><div style="display:flex;gap:24px;align-items:center;"><div style="text-align:center;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">You</div><div style="font-size:18px;font-weight:900;color:#FFFFFF;">{player_val:.2f}</div></div><div style="text-align:center;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">Top 10 Avg</div><div style="font-size:18px;font-weight:900;color:#FFFFFF;">{top10_avg:.2f}</div></div><div style="text-align:center;min-width:90px;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">+/-</div><div style="font-size:20px;font-weight:900;color:{border_color};">{delta:+.2f}</div></div><div style="text-align:center;min-width:80px;"><div style="font-size:11px;opacity:0.7;color:#CCCCCC;">%</div><div style="font-size:18px;font-weight:900;color:{border_color};">{delta_pct:+.1f}%</div></div></div></div>""", unsafe_allow_html=True)
    
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
    
    # ========== SECTION 2: PLAYER COMPARISON TOOL ==========
    st.markdown("<div class='idp-section-header'>⚖️ Player Comparison Tool</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='idp-card'><h3 style='color:#FFFFFF;margin:0 0 20px 0;font-weight:900;font-size:22px;'>Compare Against Specific Player</h3>", unsafe_allow_html=True)
    
    # Team filter for comparison
    comparison_teams = sorted(traits_df["Team_Full"].dropna().unique().tolist())
    comparison_team = st.selectbox(
        "Select Team",
        comparison_teams,
        key="idp_comparison_team"
    )
    
    # Filter players by selected team
    team_players_df = traits_df[traits_df["Team_Full"] == comparison_team]
    team_players = sorted(team_players_df["Player_Full"].dropna().unique().tolist())
    
    # Select comparison player from filtered team
    comparison_player = st.selectbox(
        "Select Player to Compare",
        team_players,
        key="idp_comparison_player"
    )
    
    if comparison_player:
        comp_data = traits_df[traits_df["Player_Full"] == comparison_player].iloc[0]
        comp_position = str(comp_data.get("Position_Full", ""))
        comp_team = str(comp_data.get("Team_Full", ""))
        comp_age = comp_data.get("Age", "N/A")
        
        # Normalize names for display
        comparison_player_display = get_full_player_name(comparison_player, comp_team)
        comp_team_display = normalize_team_display(comp_team)
        
        # Comparison header with photos
        col_p1, col_vs, col_p2 = st.columns([2, 1, 2])
        
        with col_p1:
            # Center the photo
            _, photo_col, _ = st.columns([0.5, 1, 0.5])
            with photo_col:
                display_player_photo(selected_player_display, st, size=200, team_name=selected_team_display)
            st.markdown(f"<div style='text-align:center;margin-top:12px;'><h4 style='color:#FFFFFF;margin:0;font-size:20px;font-weight:900;'>{selected_player_display}</h4><p style='color:rgba(255,255,255,0.7);margin:4px 0;font-size:14px;font-weight:600;'>{selected_team_display}</p><p style='color:rgba(255,255,255,0.6);margin:4px 0;font-size:13px;'>{player_position} • Age {player_age}</p></div>", unsafe_allow_html=True)
        
        with col_vs:
            st.markdown("<div style='display:flex;align-items:center;justify-content:center;height:100%;'><div style='font-size:48px;font-weight:900;color:rgba(255,255,255,0.5);text-shadow:2px 2px 6px rgba(0,0,0,0.5);'>VS</div></div>", unsafe_allow_html=True)
        
        with col_p2:
            # Center the photo
            _, photo_col, _ = st.columns([0.5, 1, 0.5])
            with photo_col:
                display_player_photo(comparison_player_display, st, size=200, team_name=comp_team_display)
            st.markdown(f"<div style='text-align:center;margin-top:12px;'><h4 style='color:#FFFFFF;margin:0;font-size:20px;font-weight:900;'>{comparison_player_display}</h4><p style='color:rgba(255,255,255,0.7);margin:4px 0;font-size:14px;font-weight:600;'>{comp_team_display}</p><p style='color:rgba(255,255,255,0.6);margin:4px 0;font-size:13px;'>{comp_position} • Age {comp_age}</p></div>", unsafe_allow_html=True)
        
        st.markdown("<div style='margin:24px 0;'></div>", unsafe_allow_html=True)
        
        # Spider graph comparing the two players
        import plotly.graph_objects as go
        
        # Get values for both players
        trait_categories = ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
        player1_values = [safe_float(player_data.get(trait, 0)) or 0 for trait in trait_categories]
        player2_values = [safe_float(comp_data.get(trait, 0)) or 0 for trait in trait_categories]
        
        # Create spider chart
        fig_comp = go.Figure()
        
        # Add player 1 trace
        fig_comp.add_trace(go.Scatterpolar(
            r=player1_values + [player1_values[0]],
            theta=trait_categories + [trait_categories[0]],
            fill='toself',
            name=selected_player_display.split()[0],
            line=dict(color='#00FF00', width=3),
            fillcolor='rgba(0, 255, 0, 0.2)'
        ))
        
        # Add player 2 trace
        fig_comp.add_trace(go.Scatterpolar(
            r=player2_values + [player2_values[0]],
            theta=trait_categories + [trait_categories[0]],
            fill='toself',
            name=comparison_player_display.split()[0],
            line=dict(color='#FF6B6B', width=3),
            fillcolor='rgba(255, 107, 107, 0.2)'
        ))
        
        fig_comp.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, max(max(player1_values), max(player2_values)) * 1.1],
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
        
        st.plotly_chart(fig_comp, use_container_width=True, key="comparison_spider")
        
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
                st.markdown(f"<div style='background:linear-gradient(135deg, {p1_color}25 0%, {p1_color}15 100%);border:2px solid {p1_color};border-radius:16px;padding:28px 24px;box-shadow:0 6px 20px rgba(0,0,0,0.4);text-align:center;'><div style='color:rgba(255,255,255,0.75);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;'>{p1_display}</div><div style='background:rgba(0,0,0,0.3);border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:48px;font-weight:900;color:{p1_color};line-height:1;text-shadow:2px 2px 8px rgba(0,0,0,0.5);'>{player_comp_val:.2f}</div></div></div>", unsafe_allow_html=True)
            with col2:
                p2_display = comparison_player_display.split()[-1] if ' ' in comparison_player_display else comparison_player_display
                st.markdown(f"<div style='background:linear-gradient(135deg, {p2_color}25 0%, {p2_color}15 100%);border:2px solid {p2_color};border-radius:16px;padding:28px 24px;box-shadow:0 6px 20px rgba(0,0,0,0.4);text-align:center;'><div style='color:rgba(255,255,255,0.75);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;'>{p2_display}</div><div style='background:rgba(0,0,0,0.3);border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:48px;font-weight:900;color:{p2_color};line-height:1;text-shadow:2px 2px 8px rgba(0,0,0,0.5);'>{comp_player_val:.2f}</div></div></div>", unsafe_allow_html=True)
            with col3:
                st.markdown(f"<div style='background:linear-gradient(135deg, {advantage_color}25 0%, {advantage_color}15 100%);border:2px solid {advantage_color};border-radius:16px;padding:28px 24px;box-shadow:0 6px 20px rgba(0,0,0,0.4);text-align:center;'><div style='color:rgba(255,255,255,0.75);font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;'>Advantage</div><div style='background:rgba(0,0,0,0.3);border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:48px;font-weight:900;color:{advantage_color};line-height:1;text-shadow:2px 2px 8px rgba(0,0,0,0.5);'>{advantage_text}</div><div style='margin-top:12px;font-size:14px;font-weight:700;color:rgba(255,255,255,0.7);background:rgba(0,0,0,0.25);padding:8px 16px;border-radius:20px;display:inline-block;'>{delta:+.2f} ({delta_pct:+.1f}%)</div></div></div>", unsafe_allow_html=True)
        
        # Sub-stats comparison table
        st.markdown("<h4 style='color:#FFFFFF;margin:28px 0 16px 0;font-weight:900;font-size:18px;'>Detailed Comparison</h4>", unsafe_allow_html=True)
        
        # Build table rows
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
            
            comparison_rows.append(f"<tr><td style='text-align:left;'>{substat}</td><td style='background:{p1_bg};'>{p1_val:.2f}</td><td style='background:{p2_bg};'>{p2_val:.2f}</td><td style='color:{delta_color};'>{delta:+.2f}</td></tr>")
        
        if comparison_rows:
            st.markdown(f"<table class='idp-comparison-table'><thead><tr><th style='text-align:left;'>Statistic</th><th>{selected_player}</th><th>{comparison_player}</th><th>Difference</th></tr></thead><tbody>{''.join(comparison_rows)}</tbody></table>", unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Development recommendations
    st.markdown("<div class='idp-section-header'>📈 Development Recommendations</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='idp-card'><h3 style='color:#FFFFFF;margin:0 0 20px 0;font-weight:900;font-size:22px;'>Personalized Development Path</h3>", unsafe_allow_html=True)
    
    if focus_areas:
        st.markdown("<h4 style='color:#FF6B6B;font-weight:900;font-size:18px;margin-top:16px;'>Priority Focus Areas:</h4>", unsafe_allow_html=True)
        for i, (stat, pct) in enumerate(focus_areas[:3], 1):
            st.markdown(f"<div style='margin:12px 0;padding:18px;background:rgba(255,107,107,0.1);border-left:5px solid #FF6B6B;border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:20px;font-weight:900;color:#FF6B6B;margin-bottom:10px;'>{i}. {stat}</div><div style='color:rgba(255,255,255,0.85);font-size:14px;line-height:1.6;'>Currently <strong style='color:#FF6B6B;'>{abs(pct):.1f}%</strong> below top 10 average. Focus training on improving this metric to reach elite {player_position} standards.</div></div>", unsafe_allow_html=True)
    
    if strengths:
        st.markdown("<h4 style='color:#00FF00;font-weight:900;margin-top:28px;font-size:18px;'>Continue Developing Strengths:</h4>", unsafe_allow_html=True)
        for stat, pct in strengths[:3]:
            st.markdown(f"<div style='margin:12px 0;padding:18px;background:rgba(0,255,0,0.1);border-left:5px solid #00FF00;border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,0.3);'><div style='font-size:18px;font-weight:900;color:#00FF00;margin-bottom:10px;'>✓ {stat}</div><div style='color:rgba(255,255,255,0.85);font-size:14px;line-height:1.6;'>Performing <strong style='color:#00FF00;'>{pct:.1f}%</strong> above average. Maintain this advantage through consistent application.</div></div>", unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Professional footer
    render_footer()

# ================= GAME MODEL SCORECARD =================
elif page == "Game Model Scorecard":
    st.title("📊 Game Model Scorecard")
    
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
