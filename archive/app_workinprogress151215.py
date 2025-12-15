from pathlib import Path
import os
import warnings
import math
import string
from collections import defaultdict

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image


# ---------------- STREAMLIT CONFIG ----------------
st.set_page_config(
    page_title="FutureEdge AFL Dashboard",
    page_icon="🏉",
    layout="wide",
)

import streamlit.components.v1 as components

def inject_app_css():
    st.markdown(
        """
        <style>
        .fe-card{
            background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.05));
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 16px;
            padding: 18px 18px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }
        .fe-title{
            font-size: 34px;
            font-weight: 800;
            margin: 0 0 14px 0;
            color: #FFFFFF;
        }
        .fe-kv-label{
            font-size: 11px;
            letter-spacing: .08em;
            text-transform: uppercase;
            color: rgba(255,255,255,0.65);
            margin-bottom: 6px;
        }
        .fe-kv-value{
            font-size: 16px;
            font-weight: 700;
            color: #FFFFFF;
        }
        .fe-pill{
            border-radius: 12px;
            padding: 14px 16px;
            border: 1px solid rgba(255,255,255,0.10);
            font-weight: 800;
            color: #FFFFFF;
            margin-top: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

inject_app_css()

def render_player_profile_card(player_name: str, team: str, position: str):
    # Position colour fallback
    bg, fg = POSITION_COLOURS.get(position, ("#444444", "white"))

    st.markdown(
        f"""
        <div class="fe-card">
            <div class="fe-title">{player_name}</div>

            <div class="fe-card" style="padding:14px 16px; margin-bottom:10px;">
                <div class="fe-kv-label">Team</div>
                <div class="fe-kv-value">{team}</div>
            </div>

            <div class="fe-pill" style="background:{bg}; color:{fg};">
                <div class="fe-kv-label" style="color: rgba(255,255,255,0.85);">Position</div>
                <div style="font-size:16px; font-weight:900;">{position}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )



warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

BASE_DIR = Path(__file__).resolve().parent


# -------------------------
# Global season defaults (safe)
# -------------------------
TEAM_SEASONS = [2025, 2024, 2023]

def get_default_season() -> int:
    try:
        vals = [int(x) for x in TEAM_SEASONS]
        return max(vals) if vals else 2025
    except Exception:
        return 2025

if "selected_season" not in st.session_state:
    st.session_state["selected_season"] = get_default_season()

if "primary_season" not in st.session_state:
    st.session_state["primary_season"] = st.session_state["selected_season"]


# ---------------- PATHS & CONSTANTS ----------------
TEAM_FILE = "AFL Team Ratings.xlsx"
PLAYER_FILE = "AFL Player Ratings.xlsx"

LOGO_FOLDER = "team_logos"
PLAYER_PHOTO_FOLDER = "player_photos"

TEAM_CODE_MAP = {
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

TEAM_COLOURS = {
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

METRIC_ORDER = [
    "Team Rating",
    "Ball Winning Ranking",
    "Ball Movement Ranking",
    "Scoring Ranking",
    "Defence Ranking",
    "Pressure Ranking",
]

# Rating column candidates in per-season sheets
RATING_COL_CANDIDATES = [
    "RatingPoints_Avg",
    "RatingPoints_Ave",
    "RatingPoint_Ave",
    "RatingPoint_Avg",
]

# Depth chart layout (you were missing these)
DEPTH_POSITIONS = [
    "Key Defender",
    "Gen. Defender",
    "Midfielder",
    "Mid-Forward",
    "Wing",
    "Gen. Forward",
    "Ruck",
    "Key Forward",
]

AGE_BANDS = [
    "Under 22",
    "22 to 26 Year Old",
    "26 to 30 Year Old",
    "30+ Year Old",
]

POSITION_COLOURS = {
    "Key Defender": ("#ff0000", "white"),
    "Gen. Defender": ("#ff9900", "white"),
    "Midfielder": ("#00aa00", "white"),
    "Mid-Forward": ("#00aa00", "white"),
    "Wing": ("#ffff00", "black"),
    "Gen. Forward": ("#ffff00", "black"),
    "Ruck": ("#0099ff", "white"),
    "Key Forward": ("#0099ff", "white"),
}


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
    xl = pd.ExcelFile(TEAM_FILE)
    sheet_name = f"{season} Ladders (L10)" if last10 else f"{season} Ladders"
    raw = xl.parse(sheet_name)
    return _normalise_ladder_df(raw)


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
    xl = pd.ExcelFile(PLAYER_FILE)
    df = xl.parse("Summary")
    df.columns = df.columns.astype(str).str.strip()
    return df


@st.cache_data(show_spinner=False)
def get_player_seasons() -> list[int]:
    xl = pd.ExcelFile(PLAYER_FILE)
    seasons = []
    for s in xl.sheet_names:
        if str(s).isdigit():
            seasons.append(int(s))
    return sorted(seasons, reverse=True)


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


# ---------------- DATA LOADERS – TRAITS (ENRICHED source of truth) ----------------
@st.cache_data(show_spinner=False)
def load_traits(season: int = 2025) -> pd.DataFrame:
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
        path = os.path.join(LOGO_FOLDER, code + ext)
        if os.path.exists(path):
            return path
    return None


def get_player_photo_path(player_name: str):
    if not isinstance(player_name, str):
        return None
    base = player_name.strip().lower().replace(" ", "_")
    for ext in (".png", ".jpg", ".jpeg"):
        path = os.path.join(PLAYER_PHOTO_FOLDER, base + ext)
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


def display_player_photo(player_name: str, container, size: int = 160, use_container_width: bool = False):
    path = get_player_photo_path(player_name)
    if not path:
        return
    try:
        if use_container_width:
            container.image(path, use_container_width=True)
        else:
            img = _resize_image(path, size)
            container.image(img if img is not None else path, width=size)
    except Exception:
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


def render_traits_html_table(table_html: str, height: int = 520):
    # This renders HTML properly (no raw tags showing)
    components.html(table_html, height=height, scrolling=True)


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
                line1_parts.append(str(int(num)))
            except Exception:
                line1_parts.append(str(num))
        line1_parts.append(player_name)
        left_parts.append(f"<span style='font-size:1.1em;font-weight:bold;'>{' '.join(line1_parts)}</span>")
        
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
            left_parts.append(", ".join(line2_parts))
        
        left_html = "<br>".join(left_parts)
        
        # Right side: rating box (if exists)
        rating_box_html = ""
        if rating_col in df_team.columns and pd.notna(rating) and str(rating).strip() != "":
            try:
                rating_float = float(rating)
                bg_color, text_color = get_rating_color_team_context(
                    rating_float, df_team, rating_col
                )

                rating_box_html = (
                    f"<span style='display:inline-block;"
                    f"padding:4px 12px;border-radius:6px;"
                    f"background-color:{bg_color};color:{text_color};"
                    f"border:2px solid #000;font-weight:bold;font-size:1.4em;'>"
                    f"{rating_float:.1f}</span>"
                )
            except Exception:
                rating_box_html = f"<span>{rating}</span>"
        
        # Combine left and right with flexbox, top-aligned
        if rating_box_html:
            player_html = (
                f"<div style='display:flex;justify-content:space-between;align-items:flex-start;gap:8px;'>"
                f"<div>{left_html}</div>"
                f"<div>{rating_box_html}</div>"
                f"</div>"
            )
        else:
            player_html = left_html

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

    # build HTML table with rankings
    html = []
    html.append(
        "<table style='width:100%;border-collapse:collapse;font-size:0.8em;'>"
    )
    # Header row with column names and rankings
    html.append("<tr>")
    html.append(
        "<th style='background-color:black;color:white;padding:6px;"
        "border:2px solid #000;width:12%;'>Position</th>"
    )
    for band in AGE_BANDS:
        # Get ranking info for this age band
        ranking_html = ""
        if band in age_band_rankings:
            rank, total, avg = age_band_rankings[band]
            ordinal = get_ordinal(rank)
            color = get_ranking_color(rank, total)
            # Determine text color based on background
            text_color = "black" if color == "lightgreen" else "white"
            ranking_html = (
                f"<div style='margin-top:8px;'>"
                f"<span style='display:inline-block;background-color:{color};color:{text_color};"
                f"padding:8px 16px;border-radius:8px;font-weight:bold;"
                f"font-size:1.4em;border:3px solid #000;'>{ordinal}</span>"
                f"</div>"
            )
        
        html.append(
            f"<th style='background-color:#8BC34A;color:black;padding:6px;"
            f"border:2px solid #000;text-align:center;vertical-align:top;'>"
            f"<div style='font-weight:bold;'>{band}</div>"
            f"{ranking_html}"
            f"</th>"
        )
    html.append("</tr>")

    for pos in DEPTH_POSITIONS:
        bg, fg = POSITION_COLOURS.get(pos, ("#dddddd", "black"))
        html.append("<tr>")
        
        # Position cell with ranking
        pos_cell_html = f"<div>{pos}</div>"
        if pos in position_rankings:
            rank, total, avg = position_rankings[pos]
            ordinal = get_ordinal(rank)
            color = get_ranking_color(rank, total)
            # Determine text color based on background
            text_color = "black" if color == "lightgreen" else "white"
            pos_cell_html += (
                f"<div style='margin-top:8px;'>"
                f"<span style='display:inline-block;background-color:{color};color:{text_color};"
                f"padding:8px 16px;border-radius:8px;font-weight:bold;"
                f"font-size:1.4em;border:3px solid #000;'>{ordinal}</span>"
                f"</div>"
            )
        
        html.append(
            f"<td style='background-color:{bg};color:{fg};padding:6px;"
            f"border:2px solid #000;font-weight:bold;width:10%;"
            f"white-space:nowrap;vertical-align:top;text-align:center;'>{pos_cell_html}</td>"
        )
        
        for band in AGE_BANDS:
            players = grid[pos][band]
            if players:
                sep = "<hr style='margin:4px 0;border:0;border-top:1px solid #cccccc;' />"
                cell_html = sep.join(players)
            else:
                cell_html = ""
            html.append(
                "<td style='background-color:white;color:black;padding:6px;"
                "border:2px solid #000;vertical-align:top;text-align:left;'>"
                f"{cell_html}</td>"
            )
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
    current_season: int = 2025,
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


# Define table_view as a placeholder DataFrame for demonstration purposes
table_view = pd.DataFrame({
    "Player": ["Player1", "Player2"],
    "Age": [25, 30],
    "Rating": [85.5, 90.0]
})

# Define df_view as a placeholder DataFrame for demonstration purposes
df_view = pd.DataFrame({
    "Player": ["Player1", "Player2"],
    "Team": ["Team1", "Team2"],
    "Position": ["Forward", "Midfield"],
    "Age": [25, 30]
})

# ---------------- PAGE NAV ----------------

PAGES = ["Home", "Overview", "Team Breakdown", "Team Compare", "Club List", "Player Profile", "Player Traits", "Depth Chart", "Team Age Breakdown", "List Ladder", "Team List Summary"]

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
            st.image(logo_path)
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
                        st.image(img_resized, use_container_width=False)
                        
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
                        # Display logo
                        img = Image.open(team_logo_path)
                        # Resize image to fixed dimensions for consistency
                        img_resized = img.resize((120, 120), Image.Resampling.LANCZOS)
                        st.image(img_resized, use_container_width=False)
                        
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


# ================= OVERVIEW =================

if page == "Overview":
    st.title("🏉 FutureEdge AFL Dashboard – Overview")

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
    )
    
    # Parse the selection
    if " - Last 10 Games" in selected_option:
        selected_season = 2025
        window = "Last 10 Games"
    else:
        selected_season = int(selected_option.split(" - ")[0])
        window = "Season"
    
    last10 = window == "Last 10 Games"
    period_label = f"{window} ({selected_season})"

    try:
        ladders = load_team_ladders(selected_season, last10=last10)
    except Exception as e:
        st.error(f"Error loading data for {selected_season} – {window}: {e}")
        st.stop()

    if ladders.empty:
        st.warning(f"No ladder data found for {period_label}.")
        st.stop()

    top4_colour_map = {
        "Team Rating": ("#000000", "white"),
        "Ball Winning Ranking": ("#0066CC", "white"),
        "Ball Movement Ranking": ("#009933", "white"),
        "Scoring Ranking": ("#FFEB3B", "black"),
        "Defence Ranking": ("#CC0000", "white"),
        "Pressure Ranking": ("#800080", "white"),
    }

    st.markdown("---")
    st.markdown(f"<h2 style='text-align: center; color: #FFFFFF; margin-bottom: 25px;'>🏆 Team Leaders – {period_label}</h2>", unsafe_allow_html=True)

    metric_configs = [
        {"label": "Team Rating", "metric_col": "Team Rating"},
        {"label": "Ball Winning Ranking", "metric_col": "Ball Winning Ranking"},
        {"label": "Ball Movement Ranking", "metric_col": "Ball Movement Ranking"},
        {"label": "Scoring Ranking", "metric_col": "Scoring Ranking"},
        {"label": "Defence Ranking", "metric_col": "Defence Ranking"},
        {"label": "Pressure Ranking", "metric_col": "Pressure Ranking"},
    ]

    # First row of 3 stats
    cols_row1 = st.columns(3)
    
    for idx, cfg in enumerate(metric_configs[:3]):
        metric_col = cfg["metric_col"]
        if metric_col not in ladders.columns:
            continue

        top4 = (
            ladders[["Team", metric_col]]
            .dropna(subset=[metric_col])
            .sort_values(metric_col, ascending=False)
            .head(4)
        )
        if top4.empty:
            continue

        bg, fg = top4_colour_map.get(metric_col, ("#333333", "white"))
        lines = []

        for j, (_, row) in enumerate(top4.iterrows()):
            team = row["Team"]
            val = row[metric_col]
            try:
                val_str = f"{int(round(float(val)))}"
            except Exception:
                val_str = str(val)

            if j == 0:
                # Leader styling with gradient background
                bg_gradient = f"linear-gradient(135deg, {bg} 0%, rgba(0,0,0,0.3) 100%)"
                border_style = f"border: 2px solid {bg}; box-shadow: 0 4px 6px rgba(0,0,0,0.3);"
                font_size = "1.15em"
                font_weight = "900"
                padding = "12px 14px"
                prefix = f"👑 {team}"
                value_display = f"<span style='float: right; font-size: 1.2em;'>{val_str}</span>"
            else:
                # Other teams with subtle background
                bg_gradient = f"linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%)"
                border_style = f"border: 1px solid rgba(255,255,255,0.2);"
                font_size = "0.95em"
                font_weight = "700"
                padding = "10px 12px"
                prefix = f"{j+1}. {team}"
                value_display = f"<span style='float: right; color: rgba(255,255,255,0.8);'>{val_str}</span>"

            line_html = (
                f"<div style='background: {bg_gradient}; color: {fg if j == 0 else 'white'}; "
                f"border-radius: 10px; padding: {padding}; margin-bottom: 8px; "
                f"{border_style} font-size: {font_size}; font-weight: {font_weight};'>"
                f"{prefix}{value_display}</div>"
            )
            lines.append(line_html)
        
        container = cols_row1[idx]

        # Enhanced header with color matching the benchmark team
        header_html = (
            f"<div style='background: linear-gradient(135deg, {bg} 0%, rgba(0,0,0,0.4) 100%); "
            f"border-left: 4px solid {bg}; padding: 12px; border-radius: 8px; margin-bottom: 15px;"
            f"box-shadow: 0 2px 4px rgba(0,0,0,0.3);'>"
            f"<div style='font-size: 1.1em; font-weight: 900; color: {fg};'>{cfg['label']}</div></div>"
        )
        container.markdown(header_html, unsafe_allow_html=True)

        leader_team = top4.iloc[0]["Team"]
        
        # Center the logo
        logo_col1, logo_col2, logo_col3 = container.columns([0.5, 1, 0.5])
        with logo_col2:
            display_logo(leader_team, st, size=100)
        
        container.markdown("".join(lines), unsafe_allow_html=True)
    
    # Add visual divider between rows
    st.markdown("<div style='margin-top: 30px; margin-bottom: 30px;'><hr style='border: 0; border-top: 2px solid rgba(255,215,0,0.3);'></div>", unsafe_allow_html=True)
    
    # Second row of 3 stats
    cols_row2 = st.columns(3)
    
    for idx, cfg in enumerate(metric_configs[3:]):
        metric_col = cfg["metric_col"]
        if metric_col not in ladders.columns:
            continue

        top4 = (
            ladders[["Team", metric_col]]
            .dropna(subset=[metric_col])
            .sort_values(metric_col, ascending=False)
            .head(4)
        )
        if top4.empty:
            continue

        bg, fg = top4_colour_map.get(metric_col, ("#333333", "white"))
        lines = []

        for j, (_, row) in enumerate(top4.iterrows()):
            team = row["Team"]
            val = row[metric_col]
            try:
                val_str = f"{int(round(float(val)))}"
            except Exception:
                val_str = str(val)

            if j == 0:
                # Leader styling with gradient background
                bg_gradient = f"linear-gradient(135deg, {bg} 0%, rgba(0,0,0,0.3) 100%)"
                border_style = f"border: 2px solid {bg}; box-shadow: 0 4px 6px rgba(0,0,0,0.3);"
                font_size = "1.15em"
                font_weight = "900"
                padding = "12px 14px"
                prefix = f"👑 {team}"
                value_display = f"<span style='float: right; font-size: 1.2em;'>{val_str}</span>"
            else:
                # Other teams with subtle background
                bg_gradient = f"linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%)"
                border_style = f"border: 1px solid rgba(255,255,255,0.2);"
                font_size = "0.95em"
                font_weight = "700"
                padding = "10px 12px"
                prefix = f"{j+1}. {team}"
                value_display = f"<span style='float: right; color: rgba(255,255,255,0.8);'>{val_str}</span>"

            line_html = (
                f"<div style='background: {bg_gradient}; color: {fg if j == 0 else 'white'}; "
                f"border-radius: 10px; padding: {padding}; margin-bottom: 8px; "
                f"{border_style} font-size: {font_size}; font-weight: {font_weight};'>"
                f"{prefix}{value_display}</div>"
            )
            lines.append(line_html)
        
        container = cols_row2[idx]

        # Enhanced header with color matching the benchmark team
        header_html = (
            f"<div style='background: linear-gradient(135deg, {bg} 0%, rgba(0,0,0,0.4) 100%); "
            f"border-left: 4px solid {bg}; padding: 12px; border-radius: 8px; margin-bottom: 15px;"
            f"box-shadow: 0 2px 4px rgba(0,0,0,0.3);'>"
            f"<div style='font-size: 1.1em; font-weight: 900; color: {fg};'>{cfg['label']}</div></div>"
        )
        container.markdown(header_html, unsafe_allow_html=True)

        leader_team = top4.iloc[0]["Team"]
        
        # Center the logo
        logo_col1, logo_col2, logo_col3 = container.columns([0.5, 1, 0.5])
        with logo_col2:
            display_logo(leader_team, st, size=100)
        
        container.markdown("".join(lines), unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"<h2 style='text-align: center; color: #FFFFFF; margin-top: 30px; margin-bottom: 25px;'>📊 Team Ladder – {period_label}</h2>", unsafe_allow_html=True)

    ladder_cols = ["Team"]
    # Add both value and rank columns for each metric
    for metric_col in METRIC_ORDER:
        if metric_col in ladders.columns:
            ladder_cols.append(metric_col)
            # Also add rank column if it exists
            rank_col = f"{metric_col} Rank"
            if rank_col in ladders.columns:
                ladder_cols.append(rank_col)
    ladder_cols = list(dict.fromkeys(ladder_cols))
    existing = [c for c in ladder_cols if c in ladders.columns]

    if existing:
        ladder_view = ladders[existing].copy()

        sort_col = "Team Rating" if "Team Rating" in ladder_view.columns else None
        if sort_col:
            ladder_view = ladder_view.sort_values(sort_col, ascending=False)

        # Convert all Ranking columns (not Rank columns) to integers with no decimals
        for col in ladder_view.columns:
            if col not in ["Team"] and "Rank" not in col:
                ladder_view[col] = pd.to_numeric(ladder_view[col], errors="coerce").round(0).astype("Int64")

        # Rename columns to wrap over 2 lines
        column_renames = {
            "Team Rating": "Team\nRating",
            "Team Rating Rank": "Team Rating\nRank",
            "Ball Winning Ranking": "Ball Winning\nRanking",
            "Ball Winning Ranking Rank": "Ball Winning\nRank",
            "Ball Movement Ranking": "Ball Movement\nRanking",
            "Ball Movement Ranking Rank": "Ball Movement\nRank",
            "Scoring Ranking": "Scoring\nRanking",
            "Scoring Ranking Rank": "Scoring\nRank",
            "Defence Ranking": "Defence\nRanking",
            "Defence Ranking Rank": "Defence\nRank",
            "Pressure Ranking": "Pressure\nRanking",
            "Pressure Ranking Rank": "Pressure\nRank",
        }
        ladder_view = ladder_view.rename(columns=column_renames)

        # Convert only Rank columns to ordinal format
        def to_ordinal(n):
            if pd.isna(n):
                return ""
            n = int(n)
            if 10 <= n % 100 <= 20:
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
            return f"{n}{suffix}"
        
        for col in ladder_view.columns:
            if "Rank" in col and "Ranking" not in col:
                ladder_view[col] = ladder_view[col].apply(to_ordinal)
        
        # Build professional HTML table
        metric_colors = {
            "Team\nRating": ("#000000", "white"),
            "Ball Winning\nRanking": ("#0066CC", "white"),
            "Ball Movement\nRanking": ("#009933", "white"),
            "Scoring\nRanking": ("#FFEB3B", "black"),
            "Defence\nRanking": ("#CC0000", "white"),
            "Pressure\nRanking": ("#800080", "white"),
        }
        
        rank_colors = {
            "Team Rating\nRank": ("#404040", "white"),
            "Team\nRating": ("#404040", "white"),
            "Ball Winning\nRanking": ("#3399FF", "white"),
            "Ball Movement\nRanking": ("#33CC66", "white"),
            "Scoring\nRanking": ("#FFF176", "black"),
            "Defence\nRanking": ("#FF3333", "white"),
            "Pressure\nRanking": ("#B366CC", "white"),
        }
        
        html_table = """<style>
        overview-ladder-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        margin: 20px 0;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        border-radius: 12px;
        overflow: hidden;
        background: #ffffff;
        font-size: 0.9em;
        }
        .overview-ladder-table thead {
        background: #f8f9fa;
        }
        .overview-ladder-table th {
        padding: 14px 8px;
        text-align: center;
        font-weight: 900;
        font-size: 0.85em;
        color: #FFFFFF;
        letter-spacing: 0.5px;
        border-right: 1px solid #e0e0e0;
        white-space: pre-line;
        line-height: 1.3;
        border-bottom: 2px solid #dee2e6;
        }
        .overview-ladder-table th:first-child {
        text-align: left;
        padding-left: 20px;
        background: #f8f9fa;
        }
        .overview-ladder-table th:last-child {
        border-right: none;
        }
        .overview-ladder-table td {
        padding: 12px 8px;
        text-align: center;
        font-size: 0.95em;
        font-weight: 700;
        border-bottom: 1px solid #f0f0f0;
        border-right: 1px solid #f5f5f5;
        }
        .overview-ladder-table td:first-child {
        text-align: left;
        padding-left: 20px;
        font-weight: 700;
        color: #1a1a1a;
        background: #fafafa !important;
        border-right: 2px solid #e0e0e0;
        }
        .overview-ladder-table td:last-child {
        border-right: none;
        }
        .overview-ladder-table tbody tr {
        background: #ffffff;
        transition: all 0.2s ease;
        }
        .overview-ladder-table tbody tr:hover {
        transform: scale(1.002);
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        background: #fafafa;
        }
        .rank-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 800;
        font-size: 0.85em;
        margin-right: 6px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        }
        .league-avg-row {
        background: linear-gradient(135deg, #2d3561 0%, #1a1f3a 100%) !important;
        border-top: 3px solid #FFD700 !important;
        }
        .league-avg-row td {
        font-weight: 800 !important;
        color: #FFFFFF !important;
        font-size: 1.05em !important;
        }
        .league-avg-row:hover {
        background: linear-gradient(135deg, #2d3561 0%, #1a1f3a 100%) !important;
        transform: none !important;
        }
        </style>
        <table class='overview-ladder-table'>
        <thead>
        <tr>
        """
        
        # Helper function to darken a hex color by a percentage
        def darken_color(hex_color, factor=0.4):
            """Darken a hex color by reducing RGB values by factor (0-1)"""
            hex_color = hex_color.lstrip('#')
            r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:], 16)
            r, g, b = int(r * factor), int(g * factor), int(b * factor)
            return f"#{r:02x}{g:02x}{b:02x}"
        
        # Add headers with gradient backgrounds
        for col in ladder_view.columns:
            # Determine header styling based on column type
            if col == "Team":
                bg = "#1a1a1a"
                bg_dark = darken_color(bg, 0.5)
                gradient = f"linear-gradient(135deg, {bg} 0%, {bg_dark} 100%)"
                html_table += f"<th style='background: {gradient}; color: #FFFFFF;'>{col}</th>"
            elif col in metric_colors:
                bg, fg = metric_colors[col]
                bg_dark = darken_color(bg, 0.6)
                gradient = f"linear-gradient(135deg, {bg} 0%, {bg_dark} 100%)"
                html_table += f"<th style='background: {gradient}; color: {fg};'>{col}</th>"
            elif "Rank" in col and "Ranking" not in col:
                # Check if this specific rank column has its own color definition
                if col in rank_colors:
                    bg, fg = rank_colors[col]
                    bg_dark = darken_color(bg, 0.6)
                    gradient = f"linear-gradient(135deg, {bg} 0%, {bg_dark} 100%)"
                    html_table += f"<th style='background: {gradient}; color: {fg};'>{col}</th>"
                else:
                    # Try to find parent metric by replacing Rank with Ranking
                    parent_metric = col.replace("\nRank", "\nRanking")
                    if parent_metric in rank_colors:
                        bg, fg = rank_colors[parent_metric]
                        bg_dark = darken_color(bg, 0.6)
                        gradient = f"linear-gradient(135deg, {bg} 0%, {bg_dark} 100%)"
                        html_table += f"<th style='background: {gradient}; color: {fg};'>{col}</th>"
                    else:
                        bg = "#1a1a1a"
                        bg_dark = darken_color(bg, 0.5)
                        gradient = f"linear-gradient(135deg, {bg} 0%, {bg_dark} 100%)"
                        html_table += f"<th style='background: {gradient}; color: #FFFFFF;'>{col}</th>"
            else:
                bg = "#1a1a1a"
                bg_dark = darken_color(bg, 0.5)
                gradient = f"linear-gradient(135deg, {bg} 0%, {bg_dark} 100%)"
                html_table += f"<th style='background: {gradient}; color: #FFFFFF;'>{col}</th>"
        html_table += "</tr>\n</thead>\n<tbody>\n"
        
        # Calculate rankings for opacity (higher value = better = higher opacity)
        column_rankings = {}
        for col in ladder_view.columns:
            # Skip Team column and Rank columns (but NOT Ranking columns)
            if col != "Team" and not col.endswith("\nRank"):
                # For metric columns, rank by value (higher is better)
                try:
                    numeric_col = pd.to_numeric(ladder_view[col], errors='coerce')
                    if not numeric_col.isna().all():
                        # Rank descending (higher values get lower rank numbers)
                        column_rankings[col] = numeric_col.rank(ascending=False, method='min')
                except Exception as e:
                    pass
        
        # Add data rows
        for idx, row in ladder_view.iterrows():
            html_table += "<tr>\n"
            for col in ladder_view.columns:
                value = row[col]
                
                # Determine cell styling
                if col == "Team":
                    html_table += f"<td>{value}</td>\n"
                elif col in metric_colors:
                    bg, fg = metric_colors[col]
                    # Calculate opacity based on ranking (100% for rank 1, 30% for rank 18)
                    opacity = 1.0
                    if col in column_rankings:
                        rank = column_rankings[col].loc[idx]
                        if pd.notna(rank):
                            # Linear interpolation: rank 1 = 1.0, rank 18 = 0.3
                            opacity = 1.0 - (rank - 1) / 17 * 0.7
                    
                    # Apply solid color with opacity (no gradient for better visibility)
                    r, g, b = int(bg.lstrip('#')[:2], 16), int(bg.lstrip('#')[2:4], 16), int(bg.lstrip('#')[4:], 16)
                    html_table += f"<td style='background: rgba({r}, {g}, {b}, {opacity}); color: {fg}; font-weight: 800;'>{value}</td>\n"
                elif "Rank" in col and "Ranking" not in col:
                    # Check if this specific rank column has its own color definition
                    if col in rank_colors:
                        bg, fg = rank_colors[col]
                        # For rank columns, use the same ranking as parent metric
                        opacity = 1.0
                        # Special handling for Team Rating Rank
                        if col == "Team Rating\nRank":
                            parent_check = "Team\nRating"
                        else:
                            parent_check = col.replace("\nRank", "\nRating") if "Rating" in col else col.replace("\nRank", "\nRanking")
                        
                        if parent_check in column_rankings:
                            rank = column_rankings[parent_check].loc[idx]
                            if pd.notna(rank):
                                opacity = 1.0 - (rank - 1) / 17 * 0.7
                        
                        r, g, b = int(bg.lstrip('#')[:2], 16), int(bg.lstrip('#')[2:4], 16), int(bg.lstrip('#')[4:], 16)
                        html_table += f"<td style='background: rgba({r}, {g}, {b}, {opacity}); color: {fg}; font-weight: 800;'>{value}</td>\n"
                    else:
                        # Try to find parent metric by replacing Rank with Ranking
                        parent_metric = col.replace("\nRank", "\nRanking")
                        if parent_metric in rank_colors:
                            bg, fg = rank_colors[parent_metric]
                            # For rank columns, use the same ranking as parent metric
                            opacity = 1.0
                            parent_ranking_col = parent_metric
                            if parent_ranking_col in column_rankings:
                                rank = column_rankings[parent_ranking_col].loc[idx]
                                if pd.notna(rank):
                                    opacity = 1.0 - (rank - 1) / 17 * 0.7
                            
                            r, g, b = int(bg.lstrip('#')[:2], 16), int(bg.lstrip('#')[2:4], 16), int(bg.lstrip('#')[4:], 16)
                            html_table += f"<td style='background: rgba({r}, {g}, {b}, {opacity}); color: {fg}; font-weight: 800;'>{value}</td>\n"
                        else:
                            # Default rank column styling
                            bg = "#404040"
                            fg = "white"
                            opacity = 1.0
                            parent_check = col.replace("\nRank", "\nRating") if "Rating" in col else col.replace("\nRank", "\nRanking")
                            if parent_check in column_rankings:
                                rank = column_rankings[parent_check].loc[idx]
                                if pd.notna(rank):
                                    opacity = 1.0 - (rank - 1) / 17 * 0.7
                            html_table += f"<td style='background: rgba(64, 64, 64, {opacity}); color: {fg}; font-weight: 800;'>{value}</td>\n"
                else:
                    # Handle other columns (like Team Rating) with black/grey gradient and opacity
                    if col in column_rankings:
                        bg = "#000000"
                        fg = "white"
                        opacity = 1.0
                        rank = column_rankings[col].loc[idx]
                        if pd.notna(rank):
                            opacity = 1.0 - (rank - 1) / 17 * 0.7
                        html_table += f"<td style='background: rgba(0, 0, 0, {opacity}); color: {fg}; font-weight: 800;'>{value}</td>\n"
                    else:
                        html_table += f"<td>{value}</td>\n"
            html_table += "</tr>\n"
        
        html_table += '</tbody>\n</table>\n'
        st.markdown(html_table, unsafe_allow_html=True)
        
        st.caption(f"Teams shown: {ladder_view['Team'].nunique()} (should be 18)")
    else:
        st.info("No ladder columns found to display.")


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


# ================= PLAYER PROFILE =================
elif page == "Player Profile":
    st.title("👤 Player Profile")

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

    # -----------------------------------
    # Load ALL player ratings (all seasons)
    # -----------------------------------
    all_players_all = []
    for s in get_player_seasons():
        df_s = load_players(s)
        df_s["Season"] = s
        all_players_all.append(df_s)

    players_full = pd.concat(all_players_all, ignore_index=True)
    players_full = _normalise_rating_column(players_full)

    # Ensure numeric season + rating
    players_full["Season"] = pd.to_numeric(players_full["Season"], errors="coerce")
    players_full["RatingPoints_Avg"] = pd.to_numeric(players_full["RatingPoints_Avg"], errors="coerce")

    # Season filter (default 2025 if exists)
    seasons_available = sorted(players_full["Season"].dropna().unique().tolist(), reverse=True)
    default_season_idx = 0
    if 2025 in seasons_available:
        default_season_idx = seasons_available.index(2025)

    selected_season = st.selectbox("Select Season", seasons_available, index=default_season_idx)

    # Filter by selected season
    players_season = players_full[players_full["Season"] == selected_season].copy()

    # Team selection (default from session state if available)
    teams = sorted(players_season["Team"].dropna().unique())
    if not teams:
        st.warning("No teams found for this season.")
        st.stop()

    default_idx = 0
    if "default_team" in st.session_state and st.session_state.default_team in teams:
        default_idx = teams.index(st.session_state.default_team)

    selected_team = st.selectbox("Select Team", teams, index=default_idx)

    # Player selection (from selected team + season)
    team_players = players_season[players_season["Team"] == selected_team].copy()
    player_names = sorted(team_players["Player"].dropna().unique())

    if not player_names:
        st.warning("No players found for this team.")
        st.stop()

    selected_player = st.selectbox("Select Player", player_names)

    # All seasons data for this player
    player_data_all = players_full[players_full["Player"] == selected_player].copy()
    if player_data_all.empty:
        st.info("No data found for this player.")
        st.stop()

    player_data_all = player_data_all.sort_values("Season", ascending=False)
    latest_record = player_data_all.iloc[0]

    # -----------------------------------
    # Layout: logo + photo + meta
    # -----------------------------------
    col_photo, col_meta = st.columns([1, 3])

    latest_team = latest_record.get("Team", "")
    if latest_team:
        _, logo_col, _ = col_photo.columns([1, 2, 1])
        display_logo(latest_team, logo_col, size=160)

    display_player_photo(selected_player, col_photo, use_container_width=True)

    # Meta from Summary sheet
    summary_df = load_player_summary()
    summary_match = summary_df[summary_df["Player"] == selected_player]
    summary_row = summary_match.iloc[0] if not summary_match.empty else None

    latest_position = latest_record.get("Position", "")
    latest_matches = latest_record.get("Matches", None)
    latest_rating = latest_record.get("RatingPoints_Avg", None)

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

    header_html = f"""
    <div style='background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
                border-left: 5px solid #FFFFFF; padding: 20px; border-radius: 12px; margin-bottom: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);'>
        <h2 style='color: #FFFFFF; margin: 0; font-size: 2.2em; font-weight: 900;'>{selected_player}</h2>
    </div>
    """
    col_meta.markdown(header_html, unsafe_allow_html=True)

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
        col_meta.markdown("".join(info_cards), unsafe_allow_html=True)

    # -----------------------------------
    # Ratings by season chart
    # -----------------------------------
    st.markdown("---")
    st.markdown("<h3 style='color: #FFFFFF; margin-bottom: 15px;'>📊 Rating by Season</h3>", unsafe_allow_html=True)

    player_data_all["RatingPoints_Avg"] = pd.to_numeric(player_data_all["RatingPoints_Avg"], errors="coerce")
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
    # Traits snapshot (from ENRICHED traits)
    # -----------------------------------
    st.markdown("---")
    st.markdown("<h3 style='color: #FFFFFF; margin-bottom: 15px;'>🎯 Traits Snapshot (ENRICHED)</h3>", unsafe_allow_html=True)

    try:
        traits_2025 = load_traits(2025)
        if traits_2025 is not None and not traits_2025.empty:
            # Canonical match by full name (preferred)
            t = traits_2025[traits_2025["Player_Full"] == selected_player].copy()

            # (Optional) if duplicates exist, pick first
            if not t.empty:
                row = t.iloc[0]
                cols = st.columns(4)

                def safe_float(x):
                    try:
                        return float(x)
                    except Exception:
                        return None

                metrics = [
                    ("Rating", row.get("Rating")),
                    ("Ball Winning", row.get("Ball Winning")),
                    ("Ball Use", row.get("Ball Use")),
                    ("Defence", row.get("Defence")),
                ]
                for i, (label, val) in enumerate(metrics):
                    with cols[i]:
                        fv = safe_float(val)
                        if fv is None:
                            st.metric(label, "—")
                        else:
                            st.metric(label, f"{fv:.2f}")
            else:
                st.info("No ENRICHED traits row found for this player in 2025.")
        else:
            st.info("Traits file not loaded / empty.")
    except Exception:
        st.info("Traits section unavailable (load_traits not ready).")

    # -----------------------------------
    # Raw season table
    # -----------------------------------
    st.markdown("---")
    st.markdown("<h3 style='color: #CCCCCC; margin-bottom: 15px;'>📋 Player Season Data</h3>", unsafe_allow_html=True)

    player_table = player_data_all.copy()
    age_col = "Age_Decimal" if "Age_Decimal" in player_table.columns else "Age"

    if age_col in player_table.columns:
        player_table[age_col] = pd.to_numeric(player_table[age_col], errors="coerce").round(1)

    player_table["RatingPoints_Avg"] = pd.to_numeric(player_table["RatingPoints_Avg"], errors="coerce").round(1)

    season_display_cols = [c for c in ["Season", "Team", "Position", age_col, "Matches", "RatingPoints_Avg"] if c in player_table.columns]
    player_table = player_table[season_display_cols].drop_duplicates().reset_index(drop=True)

    # Add comp + position rank per season (based on full competition)
    competition_ranks, positional_ranks = [], []
    for _, r in player_table.iterrows():
        season = r["Season"]
        position = r["Position"]
        rating = r["RatingPoints_Avg"]

        season_players = players_full[players_full["Season"] == season].copy()
        season_players["RatingPoints_Avg"] = pd.to_numeric(season_players["RatingPoints_Avg"], errors="coerce")

        comp_rank = (season_players["RatingPoints_Avg"] >= rating).sum()
        competition_ranks.append(get_ordinal(comp_rank))

        pos_players = season_players[season_players["Position"].astype(str) == str(position)]
        pos_rank = (pos_players["RatingPoints_Avg"] >= rating).sum()
        positional_ranks.append(get_ordinal(pos_rank))

    player_table["Comp Rank"] = competition_ranks
    player_table["Pos Rank"] = positional_ranks

    rename_map = {}
    if age_col in player_table.columns:
        rename_map[age_col] = "Age"
    rename_map["RatingPoints_Avg"] = "Rating"
    player_table = player_table.rename(columns=rename_map)

    st.dataframe(player_table, hide_index=True, use_container_width=True)


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

    def rating_colour_for_value(value, all_values):
        try:
            v = float(value)
            series = pd.to_numeric(all_values, errors="coerce").dropna()
        except Exception:
            return "#666666", "#FFFFFF"
        if series.empty:
            return "#666666", "#FFFFFF"
        p = (series < v).mean()
        if p >= 0.85:
            return "#008000", "#FFFFFF"
        elif p >= 0.65:
            return "#90EE90", "#000000"
        elif p >= 0.45:
            return "#FFA500", "#000000"
        else:
            return "#FF0000", "#FFFFFF"

    # -------------------------
    # Season selection
    # -------------------------
    # Use ratings seasons as the master list (usually consistent)
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

    # Display fields
    team_name_full = player_trait.get("Team_Full", selected_team_full)
    position = player_trait.get("Position_Full", "")
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

    overall_rank = None
    try:
        overall_rank = all_traits_sorted[all_traits_sorted["Player_Full"] == selected_player_full].index[0] + 1
    except Exception:
        overall_rank = None

    position_rank = None
    try:
        pos_df = traits_df.copy()
        pos_df = pos_df[pos_df["Position_Full"].astype(str) == str(position)]
        pos_df["Rating"] = pd.to_numeric(pos_df.get("Rating"), errors="coerce")
        pos_df = pos_df.dropna(subset=["Rating"]).sort_values("Rating", ascending=False).reset_index(drop=True)
        position_rank = pos_df[pos_df["Player_Full"] == selected_player_full].index[0] + 1
    except Exception:
        position_rank = None

    # -------------------------
    # Traits history (by season) — Full-name world
    # -------------------------
    st.markdown("---")
    st.subheader("Traits history (by season)")

    traits_history_parts = []
    for y in sorted([int(s) for s in history_seasons], reverse=True):
        df_y = load_traits(int(y))
        if df_y is None or df_y.empty:
            continue
        df_y = df_y.copy()
        if "Season" not in df_y.columns:
            df_y["Season"] = int(y)
        df_y["Season"] = pd.to_numeric(df_y["Season"], errors="coerce").fillna(int(y)).astype(int)

        # keep same player by full name
        df_y = df_y[df_y["Player_Full"] == selected_player_full].copy()
        traits_history_parts.append(df_y)

    traits_history_df = pd.concat(traits_history_parts, ignore_index=True) if traits_history_parts else pd.DataFrame()

    if traits_history_df.empty:
        st.info("No historical traits data available for this player in the selected seasons.")
    else:
        # Simple history table (you can swap back to your HTML builder later)
        cols_to_show = ["Season", "Team_Full", "Position_Full", "Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]
        cols_to_show = [c for c in cols_to_show if c in traits_history_df.columns]
        view = traits_history_df[cols_to_show].copy()

        # Round key fields
        for c in ["Rating", "Ball Winning", "Ball Use", "Aerial", "Defence"]:
            if c in view.columns:
                view[c] = pd.to_numeric(view[c], errors="coerce").round(2)

        st.dataframe(view.sort_values("Season", ascending=False), hide_index=True, use_container_width=True)

    st.markdown("---")

    # -------------------------
    # Page layout (photo/logo + header cards)
    # -------------------------
    col_photo, col_info = st.columns([1, 3])

    if team_name_full and not pd.isna(team_name_full):
        _, logo_col, _ = col_photo.columns([1, 2, 1])
        display_logo(team_name_full, logo_col, size=160)

    display_player_photo(selected_player_full, col_photo, use_container_width=True)

    header_html = f"""
    <div style='background: linear-gradient(135deg, #1a1a1a 0%, #3a3a3a 100%);
                border-left: 5px solid #FFFFFF; padding: 20px; border-radius: 12px; margin-bottom: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.3);'>
        <h2 style='color: #FFFFFF; margin: 0; font-size: 2.2em; font-weight: 900;'>{selected_player_full}</h2>
    </div>
    """
    col_info.markdown(header_html, unsafe_allow_html=True)

    info_cards = []
    if team_name_full and not pd.isna(team_name_full):
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
        col_info.markdown("".join(info_cards), unsafe_allow_html=True)

    # Small stats grid
    stats_grid = []

    if age not in [None, ""] and pd.notna(age):
        try:
            age_val = float(age)
            stats_grid.append(f"""
            <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>AGE</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{age_val:.1f}</div>
            </div>""")
        except Exception:
            stats_grid.append(f"""
            <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>AGE</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{age}</div>
            </div>""")

    stats_grid.append(f"""
    <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
        <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>SEASON</div>
        <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{int(primary_season)}</div>
    </div>""")

    if matches not in [None, ""] and pd.notna(matches):
        try:
            matches_val = int(float(matches))
            stats_grid.append(f"""
            <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>GAMES</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{matches_val}</div>
            </div>""")
        except Exception:
            stats_grid.append(f"""
            <div style='background: rgba(255,255,255,0.05); padding: 10px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.2);'>
                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>GAMES</div>
                <div style='color: #FFFFFF; font-size: 1.4em; font-weight: 700;'>{matches}</div>
            </div>""")

    if stats_grid:
        grid_html = f"""
        <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-top: 20px;'>
            {''.join(stats_grid)}
        </div>
        """
        col_info.markdown(grid_html, unsafe_allow_html=True)

    # -------------------------
    # Key metrics (rating + ranks)
    # -------------------------
    st.markdown("---")
    st.markdown("<h3 style='text-align: center; color: #FFFFFF; margin-top: 30px; margin-bottom: 25px;'>⭐ Key Performance Metrics</h3>", unsafe_allow_html=True)

    key_metrics = []

    if rating not in [None, ""] and pd.notna(rating):
        try:
            rating_val = float(rating)
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
        except Exception:
            pass

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
    # Trait cards
    # -------------------------
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

                r = int(trait_color.lstrip("#")[:2], 16)
                g = int(trait_color.lstrip("#")[2:4], 16)
                b = int(trait_color.lstrip("#")[4:], 16)

                substats_html = ""
                for substat_name, substat_value in substats.items():
                    if substat_value not in [None, ""] and pd.notna(substat_value):
                        try:
                            substat_val = float(substat_value)
                            substat_label = get_trait_label(substat_val)
                            substats_html += f"""
                            <div style='background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-bottom: 6px;'>
                                <div style='color: rgba(255, 255, 255, 0.7); font-size: 0.75em; margin-bottom: 4px;'>{substat_name}</div>
                                <div style='color: #FFFFFF; font-size: 1.2em; font-weight: 800;'>
                                    {substat_val:.2f}
                                    <span style='font-size: 0.7em; font-weight: 600;'>{substat_label}</span>
                                </div>
                            </div>"""
                        except Exception:
                            pass

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
        c1, c2 = st.columns(2)
        for i, card in enumerate(trait_cards):
            (c1 if i % 2 == 0 else c2).markdown(card, unsafe_allow_html=True)


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


# ================= TEAM AGE BREAKDOWN =================

elif page == "Team Age Breakdown":
    # Professional header
    st.markdown("""<div style='background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%); padding: 40px 20px; border-radius: 15px; margin-bottom: 30px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);'><h1 style='text-align: center; color: #FFFFFF; margin: 0; font-size: 2.8em; font-weight: 900; text-shadow: 2px 2px 4px rgba(0,0,0,0.5);'>📊 AFL TEAM AGE BREAKDOWN</h1><p style='text-align: center; color: #CCCCCC; margin: 10px 0 0 0; font-size: 1.2em; font-weight: 300;'>2025 Season | Age Group Performance Analysis</p></div>""", unsafe_allow_html=True)

    selected_season = 2025

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


# ================= LIST LADDER =================

elif page == "List Ladder":
    # Professional header
    st.markdown("""<div style='background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%); padding: 40px 20px; border-radius: 15px; margin-bottom: 30px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);'><h1 style='text-align: center; color: #FFFFFF; margin: 0; font-size: 2.8em; font-weight: 900; text-shadow: 2px 2px 4px rgba(0,0,0,0.5);'>📊 AFL LIST LADDER</h1><p style='text-align: center; color: #CCCCCC; margin: 10px 0 0 0; font-size: 1.2em; font-weight: 300;'>2025 Season | Positional Depth Rankings</p></div>""", unsafe_allow_html=True)

    # Load player data
    try:
        players_df = load_players(2025)
    except Exception as e:
        st.error(f"Error loading player data: {e}")
        st.stop()

    if players_df.empty:
        st.warning("No player data found for 2025.")
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


# ================= TEAM LIST SUMMARY =================

elif page == "Team List Summary":
    st.title("📊 Team List Summary")
    
    # Team selection
    # Get teams from player data
    try:
        players_df = load_players(2025)
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
            st.image(team_logo_path, width=120)
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

