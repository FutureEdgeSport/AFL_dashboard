import os
import warnings
import math

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

try:
    from PIL import Image
except ImportError:
    Image = None

# Compatibility shim: some older Streamlit versions (e.g. 1.9.0) do not
# provide `st.cache_data`. Provide a lightweight fallback that maps
# `st.cache_data` to `st.cache` when absent so the app can run without
# forcing an immediate Streamlit upgrade in the user's environment.
if not hasattr(st, "cache_data"):
    def _cache_data_fallback(*dargs, **dkwargs):
        def _decorate(func):
            return st.cache(func)
        return _decorate

    st.cache_data = _cache_data_fallback

# Optional interactive grid (ag-Grid) for nicer interactive tables
try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
    AGGRID_AVAILABLE = True
except Exception:
    AGGRID_AVAILABLE = False

# ---------------- STREAMLIT CONFIG ----------------
st.set_page_config(
    page_title="FutureEdge AFL Dashboard",
    page_icon="🏉",
    layout="wide",
)

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

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

TEAM_SEASONS = [2025, 2024, 2023]

# Depth chart layout
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
    "Key Defender": ("#ff0000", "white"),     # red
    "Gen. Defender": ("#ff9900", "white"),    # orange
    "Midfielder": ("#00aa00", "white"),       # green
    "Mid-Forward": ("#00aa00", "white"),      # green
    "Wing": ("#ffff00", "black"),             # yellow
    "Gen. Forward": ("#ffff00", "black"),     # yellow
    "Ruck": ("#0099ff", "white"),             # blue
    "Key Forward": ("#0099ff", "white"),      # blue
}

# ---------------- DATA LOADERS – TEAM LADDERS ----------------


def _normalise_ladder_df(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Find the header row (contains 'Team'), rename '#' to Rank,
    drop totals/averages, and normalise metric + Rank pairs.
    """
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
        if s == "#":
            new_cols.append("Rank")
        else:
            new_cols.append(c)
    df.columns = new_cols

    df = df[df["Team"].notna()].copy()
    # Normalize GWS team names BEFORE filtering bad labels
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


@st.cache_data
def load_team_ladders(season: int, last10: bool = False) -> pd.DataFrame:
    xl = pd.ExcelFile(TEAM_FILE)
    sheet_name = f"{season} Ladders (L10)" if last10 else f"{season} Ladders"
    raw = xl.parse(sheet_name)
    return _normalise_ladder_df(raw)


# ---------------- DATA LOADERS – TEAM SUMMARY (2025) ----------------


@st.cache_data
def load_team_summary_2025() -> pd.DataFrame:
    xl = pd.ExcelFile(TEAM_FILE)
    df = xl.parse("2025 Summary")
    df.columns = df.columns.astype(str)
    return df


@st.cache_data
def get_available_summary_years() -> list:
    """Get list of years available in team summary data."""
    # Look for individual year summary sheets (e.g., "2025 Summary", "2024 Summary", etc.)
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        years = []
        
        # Check for individual year summary sheets (like "2025 Summary")
        for sheet in xl.sheet_names:
            if " Summary" in sheet and sheet[0].isdigit():
                try:
                    year = int(sheet.split()[0])
                    years.append(year)
                except (ValueError, IndexError):
                    pass
        
        # Return sorted years in descending order
        return sorted(set(years), reverse=True)
    except Exception:
        # Fallback: return common years
        return [2025, 2024, 2023, 2022, 2021]


@st.cache_data
def load_team_summary_for_year(season: int) -> pd.DataFrame:
    """Load team summary for a specific year."""
    try:
        xl = pd.ExcelFile(TEAM_FILE)
        year_sheet = f"{season} Summary"
        df = xl.parse(year_sheet)
        df.columns = df.columns.astype(str)
        return df
    except Exception:
        return pd.DataFrame()


# ---------------- DATA LOADERS – PLAYERS ----------------


@st.cache_data
def load_player_summary() -> pd.DataFrame:
    xl = pd.ExcelFile(PLAYER_FILE)
    df = xl.parse("Summary")
    df.columns = df.columns.astype(str).str.strip()
    return df


@st.cache_data
def get_player_seasons():
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


@st.cache_data
def load_players(season: int) -> pd.DataFrame:
    xl = pd.ExcelFile(PLAYER_FILE)
    df = xl.parse(str(season))
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
    return df[existing].copy()


# ---------------- ATTRIBUTE STRUCTURE HELPERS (2025 SUMMARY) ----------------


def _extract_attribute_structure(summary_df: pd.DataFrame, attribute_name: str):
    """
    For 2025 Summary: reads group header row and stat row to find columns for one
    attribute group. Returns list of dicts:
      { "stat_name": ..., "value_col": int, "rank_col": int | None }
    """
    if summary_df is None or summary_df.empty:
        return []

    header_row = summary_df.iloc[1]  # group header row
    stat_row = summary_df.iloc[2]    # stat labels row

    start_idx_list = [
        i for i, val in enumerate(header_row) if str(val).strip() == attribute_name
    ]
    if not start_idx_list:
        return []

    start = start_idx_list[0]
    group_starts = [
        i for i, val in enumerate(header_row)
        if pd.notna(val) and i > start
    ]
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

        stat_name = label_str
        value_col = col
        rank_col = None

        if col + 1 < end and str(stat_row.iloc[col + 1]).strip() in ["#", "Rank"]:
            rank_col = col + 1
            col += 2
        else:
            col += 1

        blocks.append(
            {
                "stat_name": stat_name,
                "value_col": value_col,
                "rank_col": rank_col,
            }
        )

    return blocks


def get_attribute_stat_distribution(
    summary_df: pd.DataFrame,
    attribute_name: str,
    stat_name: str,
    block: str = "Season",  # "Season" or "Last10"
) -> pd.DataFrame:
    """
    Returns distribution of a stat for 18 AFL teams from 2025 Summary.
    Uses its Rank column (adjacent col) so your Excel ranking logic is the truth.
    """
    blocks = _extract_attribute_structure(summary_df, attribute_name)
    if not blocks:
        return pd.DataFrame(columns=["Team", "Value", "Rank"])

    block_info = next((b for b in blocks if b["stat_name"] == stat_name), None)
    if block_info is None:
        return pd.DataFrame(columns=["Team", "Value", "Rank"])

    value_col = block_info["value_col"]
    rank_col = block_info["rank_col"]

    team_series = summary_df.iloc[:, 0]
    # Build a set of all known team aliases (including canonical and alternate names)
    team_aliases = set(TEAM_CODE_MAP.keys()) | {"Greater Western Sydney"}

    team_row_indices = [
        i
        for i, val in team_series.items()
        if str(val).strip() in team_aliases
    ]
    if not team_row_indices:
        return pd.DataFrame(columns=["Team", "Value", "Rank"])

    team_row_indices = sorted(team_row_indices)
    total_rows = len(team_row_indices)

    if total_rows <= 18:
        season_indices = team_row_indices
        last10_indices = team_row_indices
    else:
        chunk_size = total_rows // 2
        season_indices = team_row_indices[:chunk_size]
        last10_indices = team_row_indices[-chunk_size:]

    chosen_indices = last10_indices if block.lower().startswith("last") else season_indices

    records = []
    for idx in chosen_indices:
        team_raw = str(team_series.iloc[idx]).strip()
        # Normalize GWS/GWS Giants/Greater Western Sydney to 'GWS Giants' for consistency
        if team_raw in ["GWS", "GWS Giants", "Greater Western Sydney"]:
            team = "GWS Giants"
        else:
            team = team_raw
        val = summary_df.iloc[idx, value_col]
        rank = summary_df.iloc[idx, rank_col] if rank_col is not None else None
        records.append(
            {
                "Team": team,
                "Value": val,
                "Rank": rank,
            }
        )

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
    if Image is None or path is None:
        return None
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
            # If PIL / Streamlit can't identify the image file, skip showing it
            return


def display_player_photo(player_name: str, container, size: int = 160):
    path = get_player_photo_path(player_name)
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


# ---------------- RATING COLOUR HELPERS ----------------


def rating_colour_for_value(v: float, values: pd.Series) -> tuple:
    """
    Returns (bg_color, fg_color) based on percentile of v within values.
    Colour logic:
    - Top 15%  -> dark green
    - Top 40%  -> light green
    - Top 65%  -> orange
    - Rest     -> red
    """
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if len(vals) == 0 or pd.isna(v):
        return "#333333", "white"

    perc = (vals <= v).mean()
    if perc >= 0.85:
        return "#008000", "white"     # dark green
    elif perc >= 0.60:
        return "#90EE90", "black"     # light green
    elif perc >= 0.35:
        return "#FFA500", "white"     # orange
    else:
        return "#FF0000", "white"     # red


def rating_colour_style(col: pd.Series):
    """
    Styler apply function to colour cells in a Rating column.
    """
    vals = pd.to_numeric(col, errors="coerce").dropna()
    if vals.empty:
        return [""] * len(col)

    styles = []
    for v in col:
        if pd.isna(v):
            styles.append("")
        else:
            bg, fg = rating_colour_for_value(float(v), vals)
            styles.append(
                f"background-color:{bg};color:{fg};"
                "font-weight:bold;border-radius:4px;"
                "text-align:center;vertical-align:middle;"
            )
    return styles


# ---------------- TABLE STYLING ----------------


def style_ladder_table(ladder_view: pd.DataFrame):
    colour_map = {
        "Team Rating": ("black", "white"),
        "Ball Winning Ranking": ("#0066CC", "white"),
        "Ball Movement Ranking": ("#009933", "white"),
        "Scoring Ranking": ("#FFEB3B", "black"),
        "Defence Ranking": ("#CC0000", "white"),
        "Pressure Ranking": ("#800080", "white"),
    }

    styler = ladder_view.style
    stat_cols = [c for c in ladder_view.columns if c not in ["Pos", "Team"]]

    if stat_cols:
        styler = styler.set_properties(
            subset=stat_cols,
            **{
                "padding": "8px 12px",
                "font-size": "0.95em",
                "text-align": "center",
                "width": "80px",
            },
        )

    styler = styler.set_properties(
        subset=["Team"],
        **{"text-align": "left"}
    )

    for col, (bg, fg) in colour_map.items():
        if col in ladder_view.columns:
            styler = styler.set_properties(
                subset=[col],
                **{
                    "background-color": bg,
                    "color": fg,
                    "font-weight": "bold",
                },
            )

    def highlight_leader(row):
        if "Pos" in ladder_view.columns and row["Pos"] == 1:
            return [
                "color: #00CC00; font-weight: 900; font-size: 1.05em;"
                for _ in row
            ]
        return [""] * len(row)

    styler = styler.apply(highlight_leader, axis=1)
    # Centre all columns except the Team column for consistent table alignment
    try:
        cols_to_center = [c for c in ladder_view.columns if c not in ["Team"]]
        if cols_to_center:
            styler = styler.set_properties(
                subset=cols_to_center,
                **{"text-align": "center"},
            )
    except Exception:
        pass

    return styler


def style_numeric_center(df: pd.DataFrame):
    """
    Generic helper: centre numeric columns in any DataFrame styler.
    Detects numeric dtypes and applies `text-align:center` to them.
    """
    styler = df.style
    try:
        # Centre all columns except Player and Team by default
        exclude = {"Player", "Team"}
        cols_to_center = [c for c in df.columns if c not in exclude]
        if cols_to_center:
            styler = styler.set_properties(
                subset=cols_to_center,
                **{
                    "text-align": "center",
                    "width": "80px",
                }
            )
    except Exception:
        pass
    return styler


def render_interactive_table(df: pd.DataFrame, exclude_cols=None, color_col=None, pre_styled_styler=None):
    """Render an interactive table using st_aggrid when available.
    Centres all columns except those in `exclude_cols`. Optionally colours
    `color_col` cells using the existing `rating_colour_for_value` logic.
    Falls back to `st.table` with the pandas Styler if ag-Grid isn't installed.
    
    If pre_styled_styler is provided, it will always be used (prioritizes styling over interactivity).
    """
    if exclude_cols is None:
        exclude_cols = ["Player", "Team"]

    # If a pre-styled Styler is provided, always use it for consistent conditional formatting
    if pre_styled_styler is not None:
        st.table(pre_styled_styler)
        return

    if not AGGRID_AVAILABLE:
        # Fallback: show the pandas Styler table (static)
        # centre all except exclude_cols
        cols_to_center = [c for c in df.columns if c not in exclude_cols]
        styler = df.style.set_properties(subset=cols_to_center, **{"text-align": "center"})
        if color_col and color_col in df.columns:
            # try to apply colouring via existing styler function
            styler = styler.apply(rating_colour_style, subset=[color_col])
        st.table(styler)
        return

    df2 = df.copy()
    # If requested, compute a per-row colour tuple for the color_col
    if color_col and color_col in df2.columns:
        try:
            vals = pd.to_numeric(df2[color_col], errors="coerce")
            df2["_ag_color"] = [list(rating_colour_for_value(v, vals)) if not pd.isna(v) else None for v in vals]
        except Exception:
            df2["_ag_color"] = None

    gb = GridOptionsBuilder.from_dataframe(df2)
    gb.configure_default_column(filter=True, sortable=True, resizable=True)

    for c in df2.columns:
        if c in exclude_cols:
            gb.configure_column(c, cellStyle={'textAlign': 'left'})
        elif c == "_ag_color":
            gb.configure_column(c, hide=True)
        else:
            gb.configure_column(c, cellStyle={'textAlign': 'center'})

    if color_col and color_col in df2.columns:
        # Use JsCode to read the precomputed _ag_color list per row and apply styles
        js = JsCode(
            """
            function(params) {
                if(!params.data || !params.data._ag_color) return {};
                var c = params.data._ag_color;
                return {background: c[0], color: c[1], fontWeight: '700'};
            }
            """
        )
        gb.configure_column(color_col, cellStyle=js)

    gridOptions = gb.build()
    AgGrid(df2, gridOptions=gridOptions, allow_unsafe_jscode=True, fit_columns_on_grid_load=False)


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

        # line 1 – jumper + name
        line1_parts = []
        if pd.notna(num) and str(num).strip() != "":
            try:
                line1_parts.append(str(int(num)))
            except Exception:
                line1_parts.append(str(num))
        line1_parts.append(player_name)
        line1 = " ".join(line1_parts)

        # line 2 – age, height, rating box
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

        if rating_col in df_team.columns and pd.notna(rating) and str(rating).strip() != "":
            try:
                rating_float = float(rating)
                bg_color, text_color = get_rating_color_team_context(
                    rating_float, df_team, rating_col
                )

                rating_box_html = (
                    f"<span style='display:inline-block;"
                    f"padding:1px 6px;border-radius:4px;"
                    f"background-color:{bg_color};color:{text_color};"
                    f"border:1px solid #000;font-weight:bold;'>"
                    f"{rating_float:.1f}</span>"
                )
                line2_parts.append(f"Rating {rating_box_html}")
            except Exception:
                line2_parts.append(f"Rating {rating}")

        line2 = ", ".join(line2_parts)
        player_html = f"{line1}<br>{line2}"

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
        # Get unique teams
        teams = all_teams_df["Team"].dropna().unique()
        
        # Calculate age band rankings (column rankings)
        age_band_averages = {team: {band: [] for band in AGE_BANDS} for team in teams}
        
        for team in teams:
            team_df = all_teams_df[all_teams_df["Team"] == team]
            for _, row in team_df.iterrows():
                player_age = row.get(age_col, None)
                player_rating = row.get(rating_col, None)
                player_pos = row.get(pos_col, None)
                
                if pd.notna(player_age) and pd.notna(player_rating):
                    age_band = map_age_to_band(player_age)
                    try:
                        age_band_averages[team][age_band].append(float(player_rating))
                    except Exception:
                        pass
        
        # Calculate average for each team/age_band and rank
        for band in AGE_BANDS:
            team_avgs = []
            for team in teams:
                ratings = age_band_averages[team][band]
                if ratings:
                    avg = sum(ratings) / len(ratings)
                    team_avgs.append((team, avg))
            
            # Sort by average (descending) and assign ranks
            team_avgs.sort(key=lambda x: x[1], reverse=True)
            for rank, (team, avg) in enumerate(team_avgs, 1):
                if team == df_team["Team"].iloc[0]:
                    age_band_rankings[band] = (rank, len(teams), avg)
                    break
        
        # Calculate position rankings (row rankings)
        position_averages = {team: {pos: [] for pos in DEPTH_POSITIONS} for team in teams}
        
        for team in teams:
            team_df = all_teams_df[all_teams_df["Team"] == team]
            for _, row in team_df.iterrows():
                player_pos_raw = row.get(pos_col, None)
                player_rating = row.get(rating_col, None)
                
                if pd.notna(player_pos_raw) and pd.notna(player_rating):
                    depth_pos = map_position_to_depth(player_pos_raw)
                    try:
                        position_averages[team][depth_pos].append(float(player_rating))
                    except Exception:
                        pass
        
        # Calculate average for each team/position and rank
        for pos in DEPTH_POSITIONS:
            team_avgs = []
            for team in teams:
                ratings = position_averages[team][pos]
                if ratings:
                    avg = sum(ratings) / len(ratings)
                    team_avgs.append((team, avg))
            
            # Sort by average (descending) and assign ranks
            team_avgs.sort(key=lambda x: x[1], reverse=True)
            for rank, (team, avg) in enumerate(team_avgs, 1):
                if team == df_team["Team"].iloc[0]:
                    position_rankings[pos] = (rank, len(teams), avg)
                    break

    # Helper function to get ordinal suffix
    def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    
    # Helper function to get ranking color (same as Team Breakdown)
    def get_ranking_color(rank, total):
        if rank <= 4:
            return "darkgreen"
        elif rank <= 9:
            return "lightgreen"
        elif rank <= 14:
            return "orange"
        else:
            return "red"

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
            ranking_html = (
                f"<div style='margin-top:4px;'>"
                f"<span style='display:inline-block;background-color:{color};color:white;"
                f"padding:4px 8px;border-radius:4px;font-weight:bold;"
                f"font-size:1em;border:2px solid white;'>{ordinal}</span>"
                f"</div>"
            )
        
        html.append(
            f"<th style='background-color:#8BC34A;color:black;padding:6px;"
            f"border:2px solid #000;text-align:center;vertical-align:top;'>"
            f"<div>{band}</div>"
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
            pos_cell_html += (
                f"<div style='margin-top:4px;'>"
                f"<span style='display:inline-block;background-color:{color};color:white;"
                f"padding:4px 8px;border-radius:4px;font-weight:bold;"
                f"font-size:1em;border:2px solid white;'>{ordinal}</span>"
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


# ---------------- PAGE NAV ----------------

PAGES = ["Home", "Overview", "Team Breakdown", "Team Compare", "Player Dashboard", "Depth Chart", "Team Age Breakdown", "List Ladder"]

# Initialize session state for page navigation
if "selected_page" not in st.session_state:
    st.session_state.selected_page = None

# Use session state if set (from button click), otherwise use sidebar radio
if st.session_state.selected_page:
    page = st.session_state.selected_page
    # Update the sidebar radio to match
    st.sidebar.radio("Navigate", PAGES, index=PAGES.index(page))
    # Clear the flag so subsequent reruns use the sidebar
    st.session_state.selected_page = None
else:
    page = st.sidebar.radio("Navigate", PAGES)


# ================= HOME =================

if page == "Home":
    # Center content with columns
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        # Display logo image
        logo_path = "team_logos/Logo Transparent.png"
        
        if os.path.exists(logo_path):
            st.image(logo_path, use_container_width=True)
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
        
        # Enter button
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
        if st.button("Enter", use_container_width=True, key="home_enter_btn"):
            st.session_state.selected_page = "Overview"
            st.rerun()


# ================= OVERVIEW =================

if page == "Overview":
    st.title("🏉 FutureEdge AFL Dashboard – Overview")

    selected_season = st.selectbox("Season", TEAM_SEASONS)
    window = st.radio(
        "Data window",
        ["Season", "Last 10 Games"],
        horizontal=True,
    )
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
        "Team Rating": ("black", "white"),
        "Ball Winning Ranking": ("#0066CC", "white"),
        "Ball Movement Ranking": ("#009933", "white"),
        "Scoring Ranking": ("#FFEB3B", "black"),
        "Defence Ranking": ("#CC0000", "white"),
        "Pressure Ranking": ("#800080", "white"),
    }

    st.subheader(f"Team Leaders – {period_label}")

    metric_configs = [
        {"label": "Team Rating", "metric_col": "Team Rating"},
        {"label": "Ball Winning Ranking", "metric_col": "Ball Winning Ranking"},
        {"label": "Ball Movement Ranking", "metric_col": "Ball Movement Ranking"},
        {"label": "Scoring Ranking", "metric_col": "Scoring Ranking"},
        {"label": "Defence Ranking", "metric_col": "Defence Ranking"},
        {"label": "Pressure Ranking", "metric_col": "Pressure Ranking"},
    ]

    cols_row1 = st.columns(3)
    cols_row2 = st.columns(3)
    idx = 0

    for cfg in metric_configs:
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
                font_size = "1.1em"
                font_weight = "900"
            else:
                font_size = "0.85em"
                font_weight = "700"

            prefix = f"{j+1}. {team} – {val_str}" if j > 0 else f"{team} – {val_str}"

            line_html = (
                f"<div style='background-color:{bg};color:{fg};"
                f"border-radius:8px;padding:6px 10px;margin-bottom:4px;"
                f"font-size:{font_size};font-weight:{font_weight};'>"
                f"{prefix}</div>"
            )
            lines.append(line_html)

        target_col = cols_row1[idx] if idx < 3 else cols_row2[idx - 3]
        container = target_col.container()

        header_html = (
            f"<div style='font-size:1.2em;font-weight:900;margin-bottom:6px;'>"
            f"{cfg['label']}</div>"
        )
        container.markdown(header_html, unsafe_allow_html=True)

        leader_team = top4.iloc[0]["Team"]
        display_logo(leader_team, container, size=80)
        container.markdown("".join(lines), unsafe_allow_html=True)

        idx += 1

    st.markdown("---")
    st.subheader(f"Team Ladder – {period_label}")

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

        # Use interactive table with ranking colors
        if AGGRID_AVAILABLE:
            from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
            
            df_display = ladder_view.copy()
            
            # Convert only Rank columns (not Ranking columns) to ordinal format (1st, 2nd, 3rd, etc.)
            def to_ordinal(n):
                if pd.isna(n):
                    return ""
                n = int(n)
                if 10 <= n % 100 <= 20:
                    suffix = "th"
                else:
                    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
                return f"{n}{suffix}"
            
            for col in df_display.columns:
                # Only apply ordinal format to Rank columns (right columns), not Ranking columns (left columns)
                if "Rank" in col and "Ranking" not in col:
                    df_display[col] = df_display[col].apply(to_ordinal)
            
            gb = GridOptionsBuilder.from_dataframe(df_display)
            gb.configure_default_column(filter=True, sortable=True, resizable=True, wrapHeaderText=True, autoHeaderHeight=True)
            
            # Configure specific columns
            gb.configure_column("Team", cellStyle={'textAlign': 'left'}, pinned='left', width=150, wrapHeaderText=True, autoHeaderHeight=True)
            
            # Configure metric columns with background colors
            metric_colors = {
                "Team\nRating": ("black", "white"),
                "Ball Winning\nRanking": ("#0066CC", "white"),
                "Ball Movement\nRanking": ("#009933", "white"),
                "Scoring\nRanking": ("#FFEB3B", "black"),
                "Defence\nRanking": ("#CC0000", "white"),
                "Pressure\nRanking": ("#800080", "white"),
            }
            
            # Lighter shades for Rank columns
            rank_colors = {
                "Team\nRating": ("#404040", "white"),  # lighter black/gray
                "Ball Winning\nRanking": ("#3399FF", "white"),  # lighter blue
                "Ball Movement\nRanking": ("#33CC66", "white"),  # lighter green
                "Scoring\nRanking": ("#FFF176", "black"),  # lighter yellow
                "Defence\nRanking": ("#FF3333", "white"),  # lighter red
                "Pressure\nRanking": ("#B366CC", "white"),  # lighter purple
            }
            
            # Column widths - can be narrower now with wrapped headers
            metric_widths = {
                "Team\nRating": 90,
                "Ball Winning\nRanking": 110,
                "Ball Movement\nRanking": 110,
                "Scoring\nRanking": 90,
                "Defence\nRanking": 90,
                "Pressure\nRanking": 90,
            }
            
            for col in df_display.columns:
                if col in metric_colors:
                    bg_color, text_color = metric_colors[col]
                    width = metric_widths.get(col, 90)
                    gb.configure_column(
                        col,
                        cellStyle={
                            'textAlign': 'center',
                            'backgroundColor': bg_color,
                            'color': text_color,
                            'fontWeight': 'bold'
                        },
                        width=width,
                        wrapHeaderText=True,
                        autoHeaderHeight=True
                    )
                elif "Rank" in col:
                    # Match rank column to lighter shade of its parent metric
                    parent_metric = col.replace("\nRank", "\nRanking")
                    if parent_metric in rank_colors:
                        bg_color, text_color = rank_colors[parent_metric]
                        gb.configure_column(
                            col,
                            cellStyle={
                                'textAlign': 'center',
                                'backgroundColor': bg_color,
                                'color': text_color,
                                'fontWeight': 'bold'
                            },
                            width=70,
                            wrapHeaderText=True,
                            autoHeaderHeight=True
                        )
                    else:
                        gb.configure_column(col, cellStyle={'textAlign': 'center'}, width=70, wrapHeaderText=True, autoHeaderHeight=True)
                else:
                    gb.configure_column(col, cellStyle={'textAlign': 'center'}, width=90, wrapHeaderText=True, autoHeaderHeight=True)
            
            gridOptions = gb.build()
            AgGrid(df_display, gridOptions=gridOptions, allow_unsafe_jscode=True, fit_columns_on_grid_load=False, height=600)
        else:
            # Fallback to styled table without green highlight
            df_fallback = ladder_view.copy()
            
            # Convert only Rank columns (not Ranking columns) to ordinal format (1st, 2nd, 3rd, etc.)
            def to_ordinal(n):
                if pd.isna(n):
                    return ""
                n = int(n)
                if 10 <= n % 100 <= 20:
                    suffix = "th"
                else:
                    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
                return f"{n}{suffix}"
            
            for col in df_fallback.columns:
                # Only apply ordinal format to Rank columns (right columns), not Ranking columns (left columns)
                if "Rank" in col and "Ranking" not in col:
                    df_fallback[col] = df_fallback[col].apply(to_ordinal)
            
            styler = df_fallback.style
            
            # Apply metric colors (to both stat and rank columns) - using wrapped column names
            colour_map = {
                "Team\nRating": ("black", "white"),
                "Ball Winning\nRanking": ("#0066CC", "white"),
                "Ball Movement\nRanking": ("#009933", "white"),
                "Scoring\nRanking": ("#FFEB3B", "black"),
                "Defence\nRanking": ("#CC0000", "white"),
                "Pressure\nRanking": ("#800080", "white"),
            }
            
            # Lighter shades for Rank columns
            rank_colour_map = {
                "Team\nRating": ("#404040", "white"),  # lighter black/gray
                "Ball Winning\nRanking": ("#3399FF", "white"),  # lighter blue
                "Ball Movement\nRanking": ("#33CC66", "white"),  # lighter green
                "Scoring\nRanking": ("#FFF176", "black"),  # lighter yellow
                "Defence\nRanking": ("#FF3333", "white"),  # lighter red
                "Pressure\nRanking": ("#B366CC", "white"),  # lighter purple
            }
            
            for col, (bg, fg) in colour_map.items():
                if col in df_fallback.columns:
                    styler = styler.set_properties(
                        subset=[col],
                        **{"background-color": bg, "color": fg, "font-weight": "bold", "text-align": "center"}
                    )
                # Apply lighter shade to rank column
                rank_col = col.replace("\nRanking", "\nRank")
                if rank_col in df_fallback.columns and col in rank_colour_map:
                    rank_bg, rank_fg = rank_colour_map[col]
                    styler = styler.set_properties(
                        subset=[rank_col],
                        **{"background-color": rank_bg, "color": rank_fg, "font-weight": "bold", "text-align": "center"}
                    )
            
            # Center all columns except Team
            cols_to_center = [c for c in df_fallback.columns if c not in ["Team"]]
            styler = styler.set_properties(subset=cols_to_center, **{"text-align": "center"})
            styler = styler.set_properties(subset=["Team"], **{"text-align": "left"})
            
            st.table(styler)
        
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
    team_name = st.selectbox("Select a team", team_list)

    team_row = ladders[ladders["Team"] == team_name].iloc[0]
    display_logo(team_name, st, size=80)
    st.markdown(f"### {team_name}")

    # --- Team Ratings Snapshot ---
    st.subheader("Team Ratings Snapshot")

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
    
    # Numeric values below chart
    st.markdown("---")
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
                color = "darkgreen"
            elif rank_int <= 9:
                color = "lightgreen"
            elif rank_int <= 14:
                color = "orange"
            else:
                color = "red"
        else:
            color = "grey"

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
            value_str = f"{rating_str} ({ord_snap})"
        else:
            value_str = rating_str

        target_col = cols_row1[idx] if idx < 3 else cols_row2[idx - 3]
        target_col.markdown(f"**{metric_col}**")

        value_html = (
            "<div style='font-size:1.6em;font-weight:900;margin-top:4px;"
            f"color:{color};'>{value_str}</div>"
        )
        target_col.markdown(value_html, unsafe_allow_html=True)

        idx += 1

    # --- Attribute Detail – new design ---
    st.markdown("---")
    st.subheader("Attribute Detail – Team vs Competition")

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
                    "border-right:1px solid #e0e0e0;padding-right:12px;margin-right:8px;"
                    if idx < 3
                    else ""
                )
                st.markdown(f"<div style='{col_border}'>", unsafe_allow_html=True)
                st.markdown(f"### {stat_name}")
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
                            main_color = "darkgreen"
                        elif rank <= 9:
                            main_color = "lightgreen"
                        elif rank <= 14:
                            main_color = "orange"
                        else:
                            main_color = "red"
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
                        # Match snapshot styling: 1.6em font size for value with ordinal
                        st.markdown(
                            f"<div style='font-size:1.6em;font-weight:900;color:{main_color};margin-top:4px;'>{val_str} ({ord_str})</div>",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"<div style='font-size:0.85em;color:#aaaaaa;margin-top:2px;'>Data window: {'Last 10 Games' if which_block == 'Last10' else 'Season Total'}</div>", unsafe_allow_html=True)
                    # Top 4 by Rank
                    st.markdown(f"#### Top 4")
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
                                size = "1.05em"
                                weight = "900"
                                color = "#00CC00"
                            elif r == 1:
                                size = "1.0em"
                                weight = "800"
                                color = "#FFFFFF"
                            else:
                                size = "0.9em"
                                weight = "700"
                                color = "#DDDDDD"
                            line_html = (
                                "<div style='margin-bottom:4px;"
                                f"font-size:{size};font-weight:{weight};"
                                f"color:{color};'>"
                                f"{r}. {t} – {val_str}</div>"
                            )
                            lines.append(line_html)
                        st.markdown("".join(lines), unsafe_allow_html=True)
                        # Averages
                        st.markdown("<hr style='border:0;border-top:2px solid #333;margin:16px 0;'>", unsafe_allow_html=True)
                        st.markdown("#### Averages")
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
        team1 = st.selectbox("Team 1 (Base)", team_list, key="team_compare_team1")
    with col2:
        # Default to different team if available
        default_idx = 1 if len(team_list) > 1 else 0
        team2 = st.selectbox("Team 2 (Comparison)", team_list, index=default_idx, key="team_compare_team2")
    
    if team1 == team2:
        st.warning("Please select two different teams to compare.")
        st.stop()
    
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
    
    if spider_metrics and team1_values and team2_values:
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            
            # Clean metric names for display
            clean_metrics = [m.replace(' Ranking', '').replace('Ranking', '').strip() for m in spider_metrics]
            
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
    
    # ========== STRENGTH/WEAKNESS ANALYSIS ==========
    st.markdown("---")
    st.subheader("Strengths & Weaknesses Analysis")
    
    # Calculate metrics relative to league average
    metric_analysis = []
    for i, metric_col in enumerate(spider_metrics):
        team1_val = team1_values[i]
        team2_val = team2_values[i]
        top4_avg = top4_averages[i]
        
        team1_diff = team1_val - top4_avg
        team2_diff = team2_val - top4_avg
        
        metric_analysis.append({
            "metric": clean_metrics[i],
            "team1_val": team1_val,
            "team2_val": team2_val,
            "top4_avg": top4_avg,
            "team1_diff": team1_diff,
            "team2_diff": team2_diff,
        })
    
    # Identify top 4 strengths and weaknesses for Team 1
    metric_df = pd.DataFrame(metric_analysis)
    
    team1_strengths = metric_df.nlargest(4, "team1_diff")[["metric", "team1_val", "top4_avg", "team1_diff"]].reset_index(drop=True)
    team1_weaknesses = metric_df.nsmallest(4, "team1_diff")[["metric", "team1_val", "top4_avg", "team1_diff"]].reset_index(drop=True)
    
    # Display Team 1 analysis
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"### 🟢 {team1} – Strengths")
        for idx, row in team1_strengths.iterrows():
            metric = row["metric"]
            val = row["team1_val"]
            diff = row["team1_diff"]
            diff_str = f"+{diff:.1f}" if diff >= 0 else f"{diff:.1f}"
            st.markdown(f"**{idx + 1}. {metric}**: {val:.1f} ({diff_str} vs Top 4)")
    
    with col2:
        st.markdown(f"### 🔴 {team1} – Weaknesses")
        for idx, row in team1_weaknesses.iterrows():
            metric = row["metric"]
            val = row["team1_val"]
            diff = row["team1_diff"]
            diff_str = f"{diff:.1f}" if diff < 0 else f"+{diff:.1f}"
            st.markdown(f"**{idx + 1}. {metric}**: {val:.1f} ({diff_str} vs Top 4)")
    
    # ========== ENGLISH LANGUAGE SUMMARY ==========
    st.markdown("---")
    st.subheader("Summary Analysis")
    
    # Generate summary text
    def generate_summary(base_team, comp_team, base_strengths, base_weaknesses, metric_data, window_label):
        """Generate English language summary comparing two teams"""
        
        # Find top strength and weakness
        top_strength = base_strengths.iloc[0] if len(base_strengths) > 0 else None
        top_weakness = base_weaknesses.iloc[0] if len(base_weaknesses) > 0 else None
        
        summary_parts = []
        
        # Overall comparison
        summary_parts.append(f"**{base_team}** is being compared to **{comp_team}** based on {window_label}.")
        summary_parts.append("")
        
        # Strengths summary
        if top_strength is not None:
            summary_parts.append(f"### Key Strengths of {base_team}:")
            strengths_list = []
            for idx, row in base_strengths.iterrows():
                metric = row["metric"]
                val = row["team1_val"]
                diff = row["team1_diff"]
                strengths_list.append(f"• **{metric}** ({val:.1f}) – {diff:.1f} points above the Top 4 average")
            summary_parts.append("\n".join(strengths_list))
            summary_parts.append("")
        
        # Weaknesses summary
        if top_weakness is not None:
            summary_parts.append(f"### Areas for Improvement ({base_team}):")
            weaknesses_list = []
            for idx, row in base_weaknesses.iterrows():
                metric = row["metric"]
                val = row["team1_val"]
                diff = row["team1_diff"]
                weaknesses_list.append(f"• **{metric}** ({val:.1f}) – {abs(diff):.1f} points below the Top 4 average")
            summary_parts.append("\n".join(weaknesses_list))
            summary_parts.append("")
        
        # Comparative insight
        summary_parts.append(f"### How {base_team} Compares to {comp_team}:")
        
        # Find metrics where base team outperforms comp team significantly
        outperforms = metric_data[metric_data["team1_diff"] > metric_data["team2_diff"]].copy()
        underperforms = metric_data[metric_data["team1_diff"] < metric_data["team2_diff"]].copy()
        
        if len(outperforms) > 0:
            outperf_count = len(outperforms)
            best_vs = outperforms.nlargest(1, "team1_diff").iloc[0]
            summary_parts.append(
                f"• **{base_team}** outperforms **{comp_team}** in {outperf_count} metric(s), "
                f"most notably in **{best_vs['metric']}** (gap of {(best_vs['team1_diff'] - best_vs['team2_diff']):.1f} points)"
            )
        
        if len(underperforms) > 0:
            underperf_count = len(underperforms)
            worst_vs = underperforms.nsmallest(1, "team1_diff").iloc[0]
            summary_parts.append(
                f"• **{comp_team}** outperforms **{base_team}** in {underperf_count} metric(s), "
                f"most notably in **{worst_vs['metric']}** (gap of {(worst_vs['team2_diff'] - worst_vs['team1_diff']):.1f} points)"
            )
        
        return "\n".join(summary_parts)
    
    summary_text = generate_summary(team1, team2, team1_strengths, team1_weaknesses, metric_df, period_label)
    st.markdown(summary_text)
    
    # ========== DETAILED METRIC BREAKDOWN ==========
    st.markdown("---")
    st.subheader("Detailed Metric Breakdown")
    
    # Create comparison table
    comparison_data = []
    for i, metric_col in enumerate(spider_metrics):
        team1_val = team1_values[i]
        team2_val = team2_values[i]
        top4_avg = top4_averages[i]
        
        # Calculate difference
        diff = team1_val - team2_val
        diff_str = f"+{diff:.1f}" if diff >= 0 else f"{diff:.1f}"
        
        comparison_data.append({
            "Metric": clean_metrics[i],
            team1: f"{team1_val:.1f}",
            team2: f"{team2_val:.1f}",
            "Top 4 Avg": f"{top4_avg:.1f}",
            f"{team1} vs {team2}": diff_str,
        })
    
    comparison_table = pd.DataFrame(comparison_data)
    
    # Apply styling
    styler = comparison_table.style.set_properties(
        subset=[team1, team2, "Top 4 Avg", f"{team1} vs {team2}"],
        **{"text-align": "center"}
    )
    
    st.dataframe(styler, use_container_width=True, height=400)



# ================= PLAYER DASHBOARD =================

elif page == "Player Dashboard":
    st.title("👤 Player Dashboard")

    # ---- Season selection (main area) ----
    seasons_available = get_player_seasons()
    if not seasons_available:
        st.error("No season sheets found in AFL Player Ratings workbook.")
        st.stop()

    st.subheader("Select seasons to include")
    selected_seasons = st.multiselect(
        "",
        seasons_available,
        default=[seasons_available[0]],
    )

    if not selected_seasons:
        st.warning("Please select at least one season.")
        st.stop()

    dfs = []
    for s in selected_seasons:
        df_s = load_players(s)
        df_s["Season"] = s
        dfs.append(df_s)

    players_all = pd.concat(dfs, ignore_index=True)
    players_all = _normalise_rating_column(players_all)

    # Decide which age column to use
    age_col = "Age_Decimal" if "Age_Decimal" in players_all.columns else "Age"
    if age_col in players_all.columns:
        players_all[age_col] = pd.to_numeric(players_all[age_col], errors="coerce")

    # ---- Filters directly under seasons ----
    st.subheader("Filters")
    fcol1, fcol2 = st.columns(2)

    with fcol1:
        min_matches = st.slider(
            "Minimum matches (per season)",
            min_value=0,
            max_value=25,
            value=0,
        )

    with fcol2:
        # Age range
        if age_col in players_all.columns:
            age_min_val = float(players_all[age_col].min(skipna=True) or 17.0)
            age_max_val = float(players_all[age_col].max(skipna=True) or 40.0)
        else:
            age_min_val, age_max_val = 17.0, 40.0

        age_min, age_max = st.slider(
            "Age range",
            min_value=17.0,
            max_value=40.0,
            value=(17.0, 40.0),
            step=0.5,
        )

    fcol3, fcol4 = st.columns(2)
    with fcol3:
        teams = sorted(players_all["Team"].dropna().unique())
        # default to no selection (cleaner UI) — empty list means no filter applied
        team_filter = st.multiselect("Teams", teams, default=[])

    with fcol4:
        positions = sorted(players_all["Position"].dropna().unique())
        # default to no selection (cleaner UI) — empty list means no filter applied
        pos_filter = st.multiselect("Positions", positions, default=[])

    # ---- Apply filters to view ----
    df_view = players_all.copy()

    # Matches
    if "Matches" in df_view.columns:
        df_view["Matches"] = pd.to_numeric(df_view["Matches"], errors="coerce").fillna(0)
        df_view = df_view[df_view["Matches"] >= min_matches]

    # Age range
    if age_col in df_view.columns:
        df_view[age_col] = pd.to_numeric(df_view[age_col], errors="coerce")
        df_view = df_view[
            (df_view[age_col] >= age_min) & (df_view[age_col] <= age_max)
        ]

    # Team + position filters
    if team_filter:
        df_view = df_view[df_view["Team"].isin(team_filter)]
    if pos_filter:
        df_view = df_view[df_view["Position"].isin(pos_filter)]

    if df_view.empty:
        st.warning("No players match the current filters.")
        st.stop()

    # Ensure rating is numeric
    df_view["RatingPoints_Avg"] = pd.to_numeric(
        df_view["RatingPoints_Avg"], errors="coerce"
    )
    df_view = df_view.sort_values("RatingPoints_Avg", ascending=False)

    # ---- Player list table (rounding + centred numbers) ----
    st.subheader("Player List")

    display_cols = [
        "Player",
        "Team",
        "Season",
        "Position",
        age_col,
        "Matches",
        "RatingPoints_Avg",
    ]
    display_cols = [c for c in display_cols if c in df_view.columns]

    table_view = df_view[display_cols].copy()

    # Helper function to convert number to ordinal (1st, 2nd, 3rd, etc)
    def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"

    # Add competition rank (by rating, across all selected players)
    table_view["Competition_Rank"] = table_view["RatingPoints_Avg"].rank(method='min', ascending=False).astype(int)
    table_view["Competition_Rank"] = table_view["Competition_Rank"].apply(get_ordinal)

    # Add positional rank (by rating, within same position and season)
    table_view["Positional_Rank"] = table_view.groupby(["Position", "Season"])["RatingPoints_Avg"].rank(method='min', ascending=False).astype(int)
    table_view["Positional_Rank"] = table_view["Positional_Rank"].apply(get_ordinal)

    # Round age + rating to 1 decimal
    if age_col in table_view.columns:
        table_view[age_col] = pd.to_numeric(table_view[age_col], errors="coerce").round(1)
    if "RatingPoints_Avg" in table_view.columns:
        table_view["RatingPoints_Avg"] = pd.to_numeric(
            table_view["RatingPoints_Avg"], errors="coerce"
        ).round(1)

    # Rename columns nicely
    rename_map = {}
    if age_col in table_view.columns:
        rename_map[age_col] = "Age"
    if "RatingPoints_Avg" in table_view.columns:
        rename_map["RatingPoints_Avg"] = "Rating"
    rename_map["Competition_Rank"] = "Comp Rank"
    rename_map["Positional_Rank"] = "Pos Rank"
    table_view = table_view.rename(columns=rename_map)

    # Reorder columns to put ranks before Player
    cols = list(table_view.columns)
    cols.remove("Comp Rank")
    cols.remove("Pos Rank")
    cols.remove("Player")
    table_view = table_view[["Comp Rank", "Pos Rank", "Player"] + cols]

    # Centre all columns except Player, Team, Comp Rank, and Pos Rank
    cols_to_center = [c for c in table_view.columns if c not in ["Player", "Team", "Comp Rank", "Pos Rank"]]
    styler_players = table_view.style.set_properties(
        subset=cols_to_center,
        **{"text-align": "center"},
    )
    if "Rating" in table_view.columns:
        styler_players = styler_players.apply(rating_colour_style, subset=["Rating"])
    # Format Age and Rating columns to 1 decimal place where present
    fmt_map = {}
    if "Age" in table_view.columns:
        fmt_map["Age"] = "{:.1f}"
    if "Rating" in table_view.columns:
        fmt_map["Rating"] = "{:.1f}"
    if fmt_map:
        styler_players = styler_players.format(fmt_map)

    # Prefer interactive AgGrid if available, otherwise fall back to styled table
    render_interactive_table(table_view, exclude_cols=["Player", "Team", "Comp Rank", "Pos Rank"], color_col="Rating" if "Rating" in table_view.columns else None, pre_styled_styler=styler_players)

    # ---- Individual Player View (all seasons, photos, logos, summary info) ----
    st.markdown("---")
    st.subheader("Individual Player View")

    player_names = sorted(df_view["Player"].dropna().unique())
    selected_player = st.selectbox("Select player", player_names)

    # Load ALL seasons for this player, regardless of selected_seasons
    all_players_all = []
    for s in get_player_seasons():
        df_s = load_players(s)
        df_s["Season"] = s
        all_players_all.append(df_s)
    players_full = pd.concat(all_players_all, ignore_index=True)
    players_full = _normalise_rating_column(players_full)

    player_data_all = players_full[players_full["Player"] == selected_player].copy()
    if player_data_all.empty:
        st.info("No data found for this player.")
        st.stop()

    player_data_all["Season"] = pd.to_numeric(player_data_all["Season"], errors="coerce")

    # Latest season record for meta
    latest_record = player_data_all.sort_values("Season", ascending=False).iloc[0]

    col_photo, col_meta = st.columns([1, 3])

    # Player photo
    display_player_photo(selected_player, col_photo, size=160)

    # Team logo (latest team)
    latest_team = latest_record.get("Team", "")
    if latest_team:
        display_logo(latest_team, col_photo, size=70)

    # Meta info from Summary tab (Age, Draft, Draft #, Height, Total Matches, Contract Expiry)
    summary_df = load_player_summary()
    summary_match = summary_df[summary_df["Player"] == selected_player]
    summary_row = summary_match.iloc[0] if not summary_match.empty else None

    # Base fields
    latest_position = latest_record.get("Position", "")
    latest_matches = latest_record.get("Matches", None)
    latest_rating = latest_record.get("RatingPoints_Avg", None)

    # Age, Draft info, Height, Total Matches, Contract Expiry from Summary
    age_summary = summary_row.get("Age") if summary_row is not None else None
    # Try both "Draft" and "Draft Year" column names
    draft_year = None
    if summary_row is not None:
        draft_year = summary_row.get("Draft Year") if "Draft Year" in summary_row.index else summary_row.get("Draft")
    draft_no = summary_row.get("Draft #") if summary_row is not None else None
    height_summary = summary_row.get("Height") if summary_row is not None else None
    total_matches = summary_row.get("Total Matches") if summary_row is not None else None
    contract_expiry = summary_row.get("Contract Expiry") if summary_row is not None else None

    # Header
    col_meta.markdown(f"### {selected_player}")
    if latest_team:
        col_meta.markdown(f"**Team:** {latest_team}")
    if latest_position:
        col_meta.markdown(f"**Position:** {latest_position}")

    # Age line under position
    age_bits = []
    try:
        if age_summary is not None and pd.notna(age_summary):
            age_bits.append(f"Age: {float(age_summary):.1f}")
    except Exception:
        if age_summary not in [None, ""]:
            age_bits.append(f"Age: {age_summary}")
    if age_bits:
        col_meta.markdown(" • ".join(age_bits))

    # Draft info
    draft_bits = []
    if draft_no not in [None, ""]:
        draft_bits.append(f"Draft #: {int(draft_no)}")
    if draft_year not in [None, ""]:
        draft_bits.append(f"Draft Year: {int(draft_year)}")
    if draft_bits:
        col_meta.markdown(" • ".join(draft_bits))
    
    # Contract Expiry on separate line
    if contract_expiry not in [None, ""]:
        try:
            col_meta.markdown(f"**Contract Expiry:** {int(contract_expiry)}")
        except Exception:
            col_meta.markdown(f"**Contract Expiry:** {contract_expiry}")

    # Height on separate line
    if height_summary not in [None, ""]:
        try:
            col_meta.markdown(f"Height: {float(height_summary):.0f} cm")
        except Exception:
            col_meta.markdown(f"Height: {height_summary} cm")

    # Total Matches from Summary tab
    if total_matches not in [None, ""] and pd.notna(total_matches):
        try:
            col_meta.markdown(f"**Total Matches:** {int(total_matches)}")
        except Exception:
            col_meta.markdown(f"**Total Matches:** {total_matches}")

    # 2025 Games and Rating (bold and bigger)
    season_2025_data = player_data_all[player_data_all["Season"] == 2025]
    if not season_2025_data.empty:
        games_2025 = season_2025_data.iloc[0].get("Matches", None)
        rating_2025 = season_2025_data.iloc[0].get("RatingPoints_Avg", None)
        
        if pd.notna(games_2025):
            col_meta.markdown(f"<div style='font-size:1.3em;font-weight:bold;margin-top:8px;'>2025 Games: {int(games_2025)}</div>", unsafe_allow_html=True)
        
        if pd.notna(rating_2025):
            rating_2025_val = float(rating_2025)
            # Color based on all players in competition
            bg, fg = rating_colour_for_value(rating_2025_val, players_full["RatingPoints_Avg"])
            
            # Calculate positional ranking for 2025
            if latest_position:
                position_players_2025 = players_full[
                    (players_full["Season"] == 2025) & 
                    (players_full["Position"] == latest_position)
                ]
                if not position_players_2025.empty:
                    position_players_2025 = position_players_2025.sort_values("RatingPoints_Avg", ascending=False).reset_index(drop=True)
                    pos_rank = position_players_2025[position_players_2025["Player"] == selected_player].index[0] + 1 if selected_player in position_players_2025["Player"].values else None
                else:
                    pos_rank = None
            else:
                pos_rank = None
            
            # Calculate overall ranking for 2025
            all_players_2025 = players_full[players_full["Season"] == 2025]
            if not all_players_2025.empty:
                all_players_2025 = all_players_2025.sort_values("RatingPoints_Avg", ascending=False).reset_index(drop=True)
                overall_rank = all_players_2025[all_players_2025["Player"] == selected_player].index[0] + 1 if selected_player in all_players_2025["Player"].values else None
            else:
                overall_rank = None
            
            # Helper function for ordinal suffix
            def get_ordinal(n):
                if 10 <= n % 100 <= 20:
                    suffix = "th"
                else:
                    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
                return f"{n}{suffix}"
            
            rating_html = f"<div style='font-size:1.3em;font-weight:bold;margin-top:4px;'>2025 Rating: <span style='background-color:{bg};color:{fg};padding:2px 8px;border-radius:4px;border:1px solid #000;'>{rating_2025_val:.1f}</span></div>"
            col_meta.markdown(rating_html, unsafe_allow_html=True)
            
            # Rankings
            ranking_parts = []
            if pos_rank:
                ranking_parts.append(f"{get_ordinal(pos_rank)} ({latest_position})")
            if overall_rank:
                ranking_parts.append(f"{get_ordinal(overall_rank)} (Overall)")
            if ranking_parts:
                col_meta.markdown(" • ".join(ranking_parts))


    # ---- Rating by Season bar chart (all seasons for this player) ----
    st.markdown("#### Rating by Season")

    player_data_all["RatingPoints_Avg"] = pd.to_numeric(
        player_data_all["RatingPoints_Avg"], errors="coerce"
    )
    player_data_all = player_data_all.dropna(subset=["RatingPoints_Avg"])

    if player_data_all.empty:
        st.info("No rating data to chart.")
    else:
        # Use ALL player ratings from competition for consistent coloring
        all_ratings = players_full["RatingPoints_Avg"].dropna()

        def colour_for_value(v):
            # percentile within entire competition
            perc = (all_ratings <= v).mean()
            if perc >= 0.85:
                return "darkgreen"
            elif perc >= 0.60:
                return "lightgreen"
            elif perc >= 0.35:
                return "orange"
            else:
                return "red"

        player_data_all["Color"] = player_data_all["RatingPoints_Avg"].apply(colour_for_value)

        chart = (
            alt.Chart(player_data_all)
            .mark_bar()
            .encode(
                x=alt.X("Season:O", sort="ascending"),
                y=alt.Y("RatingPoints_Avg:Q", title="Rating (avg)"),
                color=alt.Color("Color:N", scale=None, legend=None),
                tooltip=["Season", "RatingPoints_Avg"],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)

    # ---- Performance Projection (next 5 years) ----
    st.markdown("#### Performance Projection (Next 5 Years)")
    
    try:
        # Get latest rating and age
        latest_rating_val = float(latest_record.get("RatingPoints_Avg", 50)) if pd.notna(latest_record.get("RatingPoints_Avg")) else 50
        latest_age_val = float(latest_record.get("Age", 25)) if pd.notna(latest_record.get("Age")) else 25
        
        # Get historical ratings for trend analysis
        historical_ratings = player_data_all["RatingPoints_Avg"].dropna().sort_values().reset_index(drop=True).tolist()
        
        # Generate prediction
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
            # Create line chart with prediction bands
            # Prepare data for Altair
            pred_melted = prediction_df.copy()
            pred_melted["Type"] = "Prediction"
            
            # Create the main line (predicted rating)
            line = (
                alt.Chart(pred_melted)
                .mark_line(point=True, color="steelblue", size=3)
                .encode(
                    x=alt.X("Year:O", title="Year"),
                    y=alt.Y("Predicted_Rating:Q", title="Predicted Rating", scale=alt.Scale(zero=False)),
                    tooltip=["Year", alt.Tooltip("Predicted_Rating:Q", format=".1f")],
                )
            )
            
            # Create the confidence band (area between upper and lower)
            band = (
                alt.Chart(pred_melted)
                .mark_area(opacity=0.2, color="steelblue")
                .encode(
                    x="Year:O",
                    y="Lower_Band:Q",
                    y2="Upper_Band:Q",
                    tooltip=[
                        alt.Tooltip("Lower_Band:Q", format=".1f", title="Lower Bound (−15%)"),
                        alt.Tooltip("Upper_Band:Q", format=".1f", title="Upper Bound (+15%)"),
                    ],
                )
            )
            
            # Add historical data points
            if not player_data_all.empty:
                hist_chart = (
                    alt.Chart(player_data_all.reset_index(drop=True))
                    .mark_circle(color="gray", size=100, opacity=0.6)
                    .encode(
                        x=alt.X("Season:O", title="Year"),
                        y=alt.Y("RatingPoints_Avg:Q", title="Rating"),
                        tooltip=["Season", alt.Tooltip("RatingPoints_Avg:Q", format=".1f", title="Historical Rating")],
                    )
                )
            else:
                hist_chart = None
            
            # Combine charts
            combined = band + line
            if hist_chart is not None:
                combined = combined + hist_chart
            
            combined = combined.properties(height=300, width=700).interactive()
            
            st.altair_chart(combined, use_container_width=True)
            
            # Show prediction table
            with st.expander("📊 View Detailed Predictions", expanded=False):
                pred_table = prediction_df.copy()
                pred_table["Predicted_Rating"] = pred_table["Predicted_Rating"].round(1)
                pred_table["Upper_Band"] = pred_table["Upper_Band"].round(1)
                pred_table["Lower_Band"] = pred_table["Lower_Band"].round(1)
                st.dataframe(pred_table, hide_index=True, use_container_width=True)
        else:
            st.info("Unable to generate performance projection with available data.")
    except Exception as e:
        st.warning(f"Could not generate performance projection: {str(e)}")

    # ---- Raw player data table (only this player) ----
    st.markdown("#### Player Season Data")

    player_table = player_data_all.copy()

    # Round age + rating
    if age_col in player_table.columns:
        player_table[age_col] = pd.to_numeric(player_table[age_col], errors="coerce").round(1)
    player_table["RatingPoints_Avg"] = pd.to_numeric(
        player_table["RatingPoints_Avg"], errors="coerce"
    ).round(1)

    season_display_cols = []
    for c in ["Season", "Team", "Position", age_col, "Matches", "RatingPoints_Avg"]:
        if c in player_table.columns:
            season_display_cols.append(c)

    player_table = player_table[season_display_cols].drop_duplicates()
    # Reset index so the displayed table does not show the original DataFrame index
    player_table = player_table.reset_index(drop=True)

    # Add competition rank per season (by rating within that season, across ALL players in competition)
    # Get all players for each season to calculate correct ranks
    competition_ranks = []
    positional_ranks = []
    
    for idx, row in player_table.iterrows():
        season = row["Season"]
        position = row["Position"]
        rating = row["RatingPoints_Avg"]
        
        # Get all players in this season from the full competition
        season_players = players_full[players_full["Season"] == season].copy()
        season_players["RatingPoints_Avg"] = pd.to_numeric(season_players["RatingPoints_Avg"], errors="coerce")
        
        # Competition rank: rank across all players in the season
        comp_rank = (season_players["RatingPoints_Avg"] >= rating).sum()
        competition_ranks.append(get_ordinal(comp_rank))
        
        # Positional rank: rank within position and season
        position_players = season_players[
            season_players["Position"].apply(lambda p: map_position_to_depth(p) if pd.notna(p) else "") == map_position_to_depth(position)
        ]
        pos_rank = (position_players["RatingPoints_Avg"] >= rating).sum()
        positional_ranks.append(get_ordinal(pos_rank))
    
    player_table["Competition_Rank"] = competition_ranks
    player_table["Positional_Rank"] = positional_ranks

    rename_map_season = {}
    if age_col in player_table.columns:
        rename_map_season[age_col] = "Age"
    rename_map_season["RatingPoints_Avg"] = "Rating"
    rename_map_season["Competition_Rank"] = "Comp Rank"
    rename_map_season["Positional_Rank"] = "Pos Rank"
    player_table = player_table.rename(columns=rename_map_season)

    # Reorder columns to put ranks before other info
    cols = list(player_table.columns)
    cols.remove("Comp Rank")
    cols.remove("Pos Rank")
    player_table = player_table[["Comp Rank", "Pos Rank"] + cols]

    # Centre all columns except Team (if present)
    cols_to_center_season = [c for c in player_table.columns if c not in ["Team", "Comp Rank", "Pos Rank"]]
    
    # Apply competition-wide percentile coloring to Rating column (same as Player List and graph)
    def rating_colour_style_competition(col: pd.Series):
        """
        Styler apply function using competition-wide percentiles (matches Player List table and graph).
        """
        # Use all ratings from entire competition for percentile calculation
        all_comp_ratings = players_full["RatingPoints_Avg"].dropna()
        if all_comp_ratings.empty:
            return [""] * len(col)

        styles = []
        for v in col:
            if pd.isna(v):
                styles.append("")
            else:
                bg, fg = rating_colour_for_value(float(v), all_comp_ratings)
                styles.append(
                    f"background-color:{bg};color:{fg};"
                    "font-weight:bold;border-radius:4px;"
                    "text-align:center;vertical-align:middle;"
                )
        return styles
    
    styler_player_table = player_table.style.set_properties(
        subset=cols_to_center_season,
        **{"text-align": "center"},
    )
    if "Rating" in player_table.columns:
        styler_player_table = styler_player_table.apply(
            rating_colour_style_competition, subset=["Rating"]
        )
    # Format Age and Rating columns to 1 decimal place where present
    fmt_map_season = {}
    if "Age" in player_table.columns:
        fmt_map_season["Age"] = "{:.1f}"
    if "Rating" in player_table.columns:
        fmt_map_season["Rating"] = "{:.1f}"
    if fmt_map_season:
        styler_player_table = styler_player_table.format(fmt_map_season)

    render_interactive_table(player_table, exclude_cols=["Team", "Comp Rank", "Pos Rank"], color_col="Rating" if "Rating" in player_table.columns else None, pre_styled_styler=styler_player_table)


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
    selected_team = st.selectbox("Team", teams)

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
    st.title("📊 Team Age Breakdown")

    # Season selection
    seasons_available = get_player_seasons()
    if not seasons_available:
        st.error("No season sheets found in AFL Player Ratings workbook.")
        st.stop()

    selected_season = st.selectbox("Season", seasons_available, index=0)

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

    # Display the table
    st.subheader(f"Age Group Contribution by Team ({selected_season})")
    st.caption(
        "Percentage shows each age group's contribution to total team performance. "
        "Performance = Sum of (Rating Points Average × Matches Played) for all players."
    )

    # Use interactive table if available, otherwise styled table
    if AGGRID_AVAILABLE:
        from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
        
        # Separate team data from league average for proper sorting
        df_teams = display_table.copy()
        df_league_avg = age_breakdown_with_avg[age_breakdown_with_avg["Team"] == "League Average"].copy()
        
        # Calculate min/max for each age band independently (from original numeric values)
        band_ranges = {}
        for band in AGE_BANDS:
            band_ranges[band] = {
                'min': age_breakdown_table[band].min(),
                'max': age_breakdown_table[band].max()
            }
        
        # Display team table (sortable)
        st.markdown("#### Teams")
        gb = GridOptionsBuilder.from_dataframe(df_teams)
        gb.configure_default_column(filter=True, sortable=True, resizable=True)
        gb.configure_column("Team", pinned='left', width=150)
        
        # Create separate JavaScript styling for each age band column with gradient color
        for band in AGE_BANDS:
            min_val = band_ranges[band]['min']
            max_val = band_ranges[band]['max']
            
            cell_style_js = JsCode(f"""
                function(params) {{
                    if (!params.value) return {{'textAlign': 'center'}};
                    
                    // Extract numeric value from "X.X% (Yth)" format
                    var text = params.value;
                    var match = text.match(/^([0-9.]+)%/);
                    var value = match ? parseFloat(match[1]) : 0;
                    
                    var min = {min_val};
                    var max = {max_val};
                    var range = max - min;
                    var normalized = range > 0 ? (value - min) / range : 0.5;
                    
                    // Green (high) to Red (low) gradient
                    var r, g, b;
                    if (normalized > 0.5) {{
                        r = Math.round(255 * 2 * (1 - normalized));
                        g = 200;
                        b = 0;
                    }} else {{
                        r = 255;
                        g = Math.round(200 * 2 * normalized);
                        b = 0;
                    }}
                    
                    var textColor = normalized > 0.3 ? 'black' : 'white';
                    var bgColor = 'rgb(' + r + ',' + g + ',' + b + ')';
                    
                    return {{
                        'backgroundColor': bgColor,
                        'color': textColor,
                        'fontWeight': 'bold',
                        'textAlign': 'center'
                    }};
                }}
            """)
            
            gb.configure_column(band, cellStyle=cell_style_js, width=150)
        
        gridOptions = gb.build()
        AgGrid(df_teams, gridOptions=gridOptions, allow_unsafe_jscode=True, fit_columns_on_grid_load=False, height=550)
        
        # Display league average separately at bottom (non-sortable)
        st.markdown("#### League Average")
        gb_avg = GridOptionsBuilder.from_dataframe(df_league_avg)
        gb_avg.configure_default_column(sortable=False, filter=False, resizable=False)
        gb_avg.configure_column("Team", cellStyle={'backgroundColor': 'black', 'color': 'white', 'fontWeight': 'bold', 'textAlign': 'left'}, width=150)
        
        for band in AGE_BANDS:
            gb_avg.configure_column(band, cellStyle={'backgroundColor': 'black', 'color': 'white', 'fontWeight': 'bold', 'textAlign': 'center'}, width=150)
        
        gridOptions_avg = gb_avg.build()
        AgGrid(df_league_avg, gridOptions=gridOptions_avg, allow_unsafe_jscode=True, fit_columns_on_grid_load=False, height=80)
    else:
        # Fallback: styled table
        # Separate team data from league average
        df_teams = display_table.copy()
        df_league_avg = age_breakdown_with_avg[age_breakdown_with_avg["Team"] == "League Average"].copy()
        
        # Style teams table with centered content
        st.markdown("#### Teams")
        styler_teams = df_teams.style.set_properties(**{'text-align': 'center'})
        styler_teams = styler_teams.set_properties(subset=['Team'], **{'text-align': 'left'})
        st.table(styler_teams)
        
        # Style league average table
        st.markdown("#### League Average")
        styler_avg = df_league_avg.style.set_properties(
            **{'background-color': 'black', 'color': 'white', 'font-weight': 'bold', 'text-align': 'center'}
        )
        styler_avg = styler_avg.set_properties(
            subset=['Team'],
            **{'text-align': 'left'}
        )
        st.table(styler_avg)


# ================= LIST LADDER =================

elif page == "List Ladder":
    st.title("📊 List Ladder")
    
    # Load player data from Summary sheet (has Wing position data, unlike season sheets)
    try:
        players_df = load_player_summary()
    except Exception as e:
        st.error(f"Error loading player summary data: {e}")
        st.stop()
    
    if players_df.empty:
        st.warning(f"No player data found in Summary sheet.")
        st.stop()
    
    # Ensure required columns exist
    required_cols = ["Player", "Team", "Position"]
    missing_cols = [c for c in required_cols if c not in players_df.columns]
    if missing_cols:
        st.error(f"Missing required columns: {', '.join(missing_cols)}")
        st.stop()
    
    # Rating selection dropdown (just the labels, no "current" or "Average")
    rating_options = {
        "2025": "2025",
        "Last 2 Seasons": "Last 2 Average",
        "Career": "Career",
    }
    rating_label = st.selectbox(
        "List Ladder Type",
        list(rating_options.keys()),
        index=0,
    )
    rating_col = rating_options[rating_label]
    
    # Verify rating column exists
    if rating_col not in players_df.columns:
        st.error(f"Column '{rating_col}' not found in Summary sheet")
        st.stop()
    
    # Convert to numeric
    players_df["RatingPoints_Avg"] = pd.to_numeric(players_df[rating_col], errors="coerce")
    
    # Remove players with no rating
    players_df = players_df[players_df["RatingPoints_Avg"].notna()]
    
    # Get all unique teams
    teams = sorted(players_df["Team"].dropna().unique())
    
    # Helper function to convert number to ordinal (1st, 2nd, 3rd, etc)
    def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"
    
    # Get percentile-based rating color and points for a player
    def get_rating_points(rating_val, all_ratings):
        """Returns points based on rating percentile"""
        all_ratings_clean = all_ratings.dropna()
        if len(all_ratings_clean) == 0 or pd.isna(rating_val):
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
    
    # Build the list ladder table
    ladder_data = []
    all_ratings = players_df["RatingPoints_Avg"]
    
    for team in teams:
        team_players = players_df[players_df["Team"] == team].copy()
        
        row_data = {"Team": team}
        position_totals = {}
        
        # For each position, get the TOTAL points of players in that position
        for position in DEPTH_POSITIONS:
            position_players = team_players[
                team_players["Position"].apply(lambda p: map_position_to_depth(p) if pd.notna(p) else "") == position
            ]
            
            if len(position_players) > 0:
                # Calculate points for each player in this position and SUM
                position_player_points = [get_rating_points(rating, all_ratings) for rating in position_players["RatingPoints_Avg"]]
                total_position_points = sum(position_player_points)
            else:
                total_position_points = 0
            
            position_totals[position] = total_position_points
            row_data[position] = total_position_points
        
        # Calculate total points across all positions
        total_points = sum(position_totals.values())
        row_data["Total_Points"] = total_points
        row_data["Position_Totals"] = position_totals
        
        ladder_data.append(row_data)
    
    # Create DataFrame
    ladder_df = pd.DataFrame(ladder_data)
    
    # Calculate ranks
    ladder_df["Overall_Rank"] = ladder_df["Total_Points"].rank(method='min', ascending=False).astype(int)
    
    # Calculate positional ranks (rank for each position across all teams)
    for position in DEPTH_POSITIONS:
        ladder_df[f"{position}_Rank"] = ladder_df[position].rank(method='min', ascending=False).astype(int)
    
    # Display the ladder
    st.subheader(f"Team List Ladder - {rating_label}")
    st.caption("Positional strength based on total player points. Points per player: Top 15% = 3pts, Top 40% = 1pt, Top 65% = 0.5pts, Rest = 0pts")
    
    # Create display table with ranks and total points
    display_data = []
    for idx, row in ladder_df.iterrows():
        display_row = {"Team": row["Team"]}
        
        # Add position ranks with total points
        for position in DEPTH_POSITIONS:
            rank = int(row[f"{position}_Rank"])
            points = row[position]
            display_row[position] = f"{get_ordinal(rank)} ({points:.0f}pts)"
        
        # Add total points and overall rank
        display_row["Total Points"] = f"{row['Total_Points']:.0f}pts"
        display_row["Overall Rank"] = get_ordinal(int(row["Overall_Rank"]))
        
        display_data.append(display_row)
    
    # Convert to DataFrame and sort by overall rank
    display_df = pd.DataFrame(display_data)
    
    # Create numeric version for sorting
    numeric_df = ladder_df[["Team", "Total_Points", "Overall_Rank"]].copy()
    numeric_df = numeric_df.sort_values("Overall_Rank")
    
    # Reorder display_df to match sorted order
    display_df = display_df.set_index("Team").loc[numeric_df["Team"].values].reset_index()
    
    # Ensure column order: Team, all positions, Total Points, Overall Rank
    column_order = ["Team"] + DEPTH_POSITIONS + ["Total Points", "Overall Rank"]
    display_df = display_df[column_order]
    
    # Use AgGrid for sortable table if available, otherwise fallback to styled table
    if AGGRID_AVAILABLE:
        gb = GridOptionsBuilder.from_dataframe(display_df)
        gb.configure_default_column(sortable=True, resizable=True, filter=True)
        
        # Configure Team column - left aligned, bold
        gb.configure_column("Team", pinned="left", cellStyle={"text-align": "left", "font-weight": "bold"})
        
        # Configure position columns - centered
        for pos in DEPTH_POSITIONS:
            gb.configure_column(pos, cellStyle={"text-align": "center", "font-size": "0.9em"})
        
        # Configure Total Points and Overall Rank - dark grey background, white text, bold, centered
        for col in ["Total Points", "Overall Rank"]:
            gb.configure_column(
                col,
                cellStyle={
                    "text-align": "center",
                    "font-weight": "bold",
                    "background-color": "#333333",
                    "color": "white"
                }
            )
        
        gridOptions = gb.build()
        AgGrid(display_df, gridOptions=gridOptions, height=600, fit_columns_on_grid_load=True)
    else:
        # Fallback to styled table
        styler = display_df.style
        
        # Style position columns
        styler = styler.set_properties(
            subset=DEPTH_POSITIONS,
            **{"text-align": "center", "font-size": "0.9em"}
        )
        
        # Style total and rank columns - dark grey with white text
        total_rank_cols = ["Total Points", "Overall Rank"]
        styler = styler.set_properties(
            subset=total_rank_cols,
            **{"text-align": "center", "font-weight": "bold", "background-color": "#333333", "color": "white"}
        )
        
        # Style team column
        styler = styler.set_properties(
            subset=["Team"],
            **{"text-align": "left", "font-weight": "bold"}
        )
        
        st.table(styler)
    
    # ---- Team Player Breakdown by Position ----
    st.markdown("---")
    st.subheader("Team Player Breakdown")
    
    # Team selector
    selected_team = st.selectbox("Select a team to view contributing players", teams, key="list_ladder_team_select")
    
    if selected_team:
        # Get players for selected team
        team_players = players_df[players_df["Team"] == selected_team].copy()
        
        if team_players.empty:
            st.warning(f"No players found for {selected_team}")
        else:
            # Map players to depth positions
            team_players["Depth_Position"] = team_players["Position"].apply(
                lambda p: map_position_to_depth(p) if pd.notna(p) else "Midfielder"
            )
            
            # Calculate points for each player
            team_players["Points"] = team_players["RatingPoints_Avg"].apply(
                lambda r: get_rating_points(r, all_ratings)
            )
            
            # Create display tables for each position
            positions_with_players = sorted([p for p in DEPTH_POSITIONS if any(team_players["Depth_Position"] == p)])
            
            if not positions_with_players:
                st.warning(f"No players found for {selected_team}")
            else:
                st.caption(f"Showing players for {selected_team}. Players are colored by rating percentile across the competition.")
                
                # Display tables in columns (2 per row)
                for i, position in enumerate(positions_with_players):
                    # Create new row every 2 positions
                    if i % 2 == 0:
                        cols = st.columns(2)
                    
                    col_idx = i % 2
                    
                    with cols[col_idx]:
                        # Get players for this position
                        pos_players = team_players[team_players["Depth_Position"] == position].copy()
                        pos_players = pos_players.sort_values(
                            ["Points", "RatingPoints_Avg"], ascending=[False, False]
                        )
                        
                        # Create display table
                        player_table = pos_players[["Player", "RatingPoints_Avg", "Points"]].copy()
                        player_table = player_table.rename(columns={
                            "RatingPoints_Avg": "Rating",
                        })
                        
                        # Round rating to 1 decimal
                        player_table["Rating"] = player_table["Rating"].round(1)
                        
                        # Format points to 1 decimal
                        player_table["Points"] = player_table["Points"].apply(lambda x: f"{x:.1f}")
                        
                        # Apply styling with rating color
                        def rating_colour_style_breakdown(col: pd.Series):
                            """Color cells based on rating percentile"""
                            styles = []
                            for v in col:
                                if pd.isna(v):
                                    styles.append("")
                                else:
                                    bg, fg = rating_colour_for_value(v, all_ratings)
                                    styles.append(f"background-color: {bg}; color: {fg}; font-weight: bold;")
                            return styles
                        
                        # Style the table
                        styler_table = player_table.style.set_properties(
                            subset=["Rating", "Points"],
                            **{"text-align": "center"}
                        )
                        
                        # Apply rating colors to the Rating column
                        if "Rating" in player_table.columns:
                            styler_table = styler_table.apply(
                                lambda col: rating_colour_style_breakdown(pos_players["RatingPoints_Avg"]) if col.name == "Rating" else [""] * len(col),
                                axis=0
                            )
                        
                        # Format Rating to 1 decimal
                        styler_table = styler_table.format({"Rating": "{:.1f}"})
                        
                        # Display position header and table
                        st.markdown(f"**{position}** ({len(player_table)} players)")
                        st.table(styler_table)
