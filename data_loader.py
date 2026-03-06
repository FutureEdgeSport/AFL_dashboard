"""
AFL Dashboard Data Loader
=========================
Unified data loading layer that uses the Master Workbook as the single source of truth,
with automatic fallback to legacy files for backwards compatibility.

This module provides:
- Automatic master workbook detection
- Fallback to legacy files if master doesn't exist
- Sheet-level fallback (if a specific sheet is missing from master)
- Caching for performance
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional, Dict, Tuple
import pandas as pd
import streamlit as st
import warnings

warnings.filterwarnings('ignore')

# Import file path constants
from config.constants import (
    MASTER_FILE,
    PLAYER_FILE,
    TEAM_FILE,
    TRAITS_FILE,
    LADDERS_FILE,
)

# ============================================================================
# MASTER WORKBOOK SHEET MAPPINGS
# ============================================================================
# Maps legacy file + sheet combinations to master workbook sheets

LEGACY_TO_MASTER_MAP = {
    # Player stats by year
    ("player", "2025"): "Players_2025_Stats",
    ("player", "2024"): "Players_2024_Stats",
    ("player", "2023"): "Players_2023_Stats",
    ("player", "2022"): "Players_2022_Stats",
    ("player", "2021"): "Players_2021_Stats",
    ("player", "2025 AFL Squads"): "Players_2025_Squad",
    ("player", "Summary"): "Player_Summary",
    ("player", "Contract Expiry"): "Player_Contracts",
    ("player", "Draft Data"): "Player_Draft",
    ("player", "Wings"): "Wings",
    
    # Team stats by year
    ("team", "2025"): "Teams_2025_Full",
    ("team", "2025 Summary"): "Teams_2025_Summary",
    ("team", "2024 Summary"): "Teams_2024_Summary",
    ("team", "2023 Summary"): "Teams_2023_Summary",
    ("team", "2022 Summary"): "Teams_Historical",  # Filtered by year
    ("team", "2021 Summary"): "Teams_Historical",  # Filtered by year
    
    # Traits by year
    ("traits", "2026"): "Player_Traits_2026",
    ("traits", "2025"): "Player_Traits_2025",
    ("traits", "2024"): "Player_Traits_2024",
    ("traits", "2023"): "Player_Traits_2023",
    ("traits", "2022"): "Player_Traits_Historical",  # Filtered by year
    ("traits", "2021"): "Player_Traits_Historical",  # Filtered by year
    
    # Ladders
    ("ladders", "Sheet1"): "Team_Ladders_All",
}


def _get_base_path() -> Path:
    """Get base path for data files."""
    return Path(__file__).parent


@lru_cache(maxsize=1)
def master_workbook_available() -> bool:
    """Check if master workbook exists and is valid."""
    master_path = _get_base_path() / MASTER_FILE
    if not master_path.exists():
        return False
    try:
        xl = pd.ExcelFile(master_path)
        # Check for at least a few key sheets
        required = ["Player_Summary", "Players_2025_Stats", "Teams_2025_Summary"]
        return all(sheet in xl.sheet_names for sheet in required)
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_master_excel_file() -> Optional[pd.ExcelFile]:
    """Get cached ExcelFile object for master workbook."""
    if not master_workbook_available():
        return None
    try:
        return pd.ExcelFile(_get_base_path() / MASTER_FILE)
    except Exception:
        return None


def _get_legacy_excel_file(file_type: str) -> Optional[pd.ExcelFile]:
    """Get ExcelFile for legacy data files."""
    base = _get_base_path()
    file_map = {
        "player": PLAYER_FILE,
        "team": TEAM_FILE,
        "traits": TRAITS_FILE,
        "ladders": LADDERS_FILE,
    }
    filepath = base / file_map.get(file_type, "")
    if filepath.exists():
        try:
            return pd.ExcelFile(filepath)
        except Exception:
            return None
    return None


def load_from_master_or_legacy(
    file_type: str,
    sheet_name: str,
    filter_col: str = None,
    filter_val: any = None
) -> pd.DataFrame:
    """
    Load data from master workbook, falling back to legacy file if needed.
    
    Args:
        file_type: One of 'player', 'team', 'traits', 'ladders'
        sheet_name: Sheet name in legacy file format (e.g., '2025', 'Summary')
        filter_col: Optional column to filter by (for combined sheets)
        filter_val: Value to filter filter_col by
        
    Returns:
        DataFrame with requested data
    """
    master_xl = get_master_excel_file()
    
    if master_xl is not None:
        # Try master workbook first
        master_sheet = LEGACY_TO_MASTER_MAP.get((file_type, sheet_name))
        
        if master_sheet and master_sheet in master_xl.sheet_names:
            try:
                df = master_xl.parse(master_sheet)
                df.columns = df.columns.astype(str).str.strip()
                
                # Apply filter if needed (for historical combined sheets)
                if filter_col and filter_val is not None and filter_col in df.columns:
                    df = df[df[filter_col] == filter_val]
                
                return df
            except Exception as e:
                pass  # Fall through to legacy
    
    # Fall back to legacy file
    legacy_xl = _get_legacy_excel_file(file_type)
    if legacy_xl is not None and sheet_name in legacy_xl.sheet_names:
        try:
            df = legacy_xl.parse(sheet_name)
            df.columns = df.columns.astype(str).str.strip()
            return df
        except Exception:
            pass
    
    return pd.DataFrame()


# ============================================================================
# PLAYER DATA LOADERS
# ============================================================================

@st.cache_data(show_spinner=False)
def load_player_summary_data() -> pd.DataFrame:
    """
    Load player summary data (master: Player_Summary, legacy: Summary sheet).
    This is the primary source for the 808-player full squad list.
    """
    df = load_from_master_or_legacy("player", "Summary")
    if df.empty:
        st.warning("⚠️ Could not load player summary data")
    return df


@st.cache_data(show_spinner=False)
def load_player_stats_for_season(season: int) -> pd.DataFrame:
    """
    Load player stats for a specific season.
    Master: Players_{season}_Stats or Players_2012_2020 (with filter)
    Legacy: {season} sheet
    CSV fallback: data/raw/player/player_stats_{season}.csv (for 2026+)
    """
    # For years 2021+, use direct mapping
    if season >= 2021:
        df = load_from_master_or_legacy("player", str(season))
    else:
        # For 2012-2020, use combined sheet with filter
        master_xl = get_master_excel_file()
        if master_xl and "Players_2012_2020" in master_xl.sheet_names:
            df = master_xl.parse("Players_2012_2020")
            df.columns = df.columns.astype(str).str.strip()
            if "Season" in df.columns:
                df = df[df["Season"] == season]
        else:
            df = load_from_master_or_legacy("player", str(season))
    
    # CSV fallback for seasons not yet in Excel (e.g. 2026)
    if df.empty:
        csv_path = _get_base_path() / "data" / "raw" / "player" / f"player_stats_{season}.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                df.columns = df.columns.astype(str).str.strip()
            except Exception:
                pass
    
    return df


@st.cache_data(show_spinner=False)
def load_full_squad_data(season: int = 2025) -> pd.DataFrame:
    """
    Load full squad list including players who didn't play.
    Master: Players_{season}_Squad
    Legacy: {season} AFL Squads sheet
    CSV fallback: data/raw/player/squads_{season}.csv (for 2026+)
    """
    df = load_from_master_or_legacy("player", f"{season} AFL Squads")
    if df.empty:
        # Try CSV fallback (for seasons not yet in Excel)
        csv_path = _get_base_path() / "data" / "raw" / "player" / f"squads_{season}.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                df.columns = df.columns.astype(str).str.strip()
            except Exception:
                pass
    if df.empty:
        # Fall back to regular season sheet
        df = load_player_stats_for_season(season)
    return df


@st.cache_data(show_spinner=False)
def load_wings_data() -> pd.DataFrame:
    """Load wings position data."""
    df = load_from_master_or_legacy("player", "Wings")
    return df


@st.cache_data(show_spinner=False)
def load_player_contracts_data() -> pd.DataFrame:
    """Load player contract expiry data."""
    df = load_from_master_or_legacy("player", "Contract Expiry")
    return df


@st.cache_data(show_spinner=False)
def load_player_draft_data() -> pd.DataFrame:
    """Load player draft data."""
    df = load_from_master_or_legacy("player", "Draft Data")
    return df


# ============================================================================
# TEAM DATA LOADERS
# ============================================================================

@st.cache_data(show_spinner=False)
def load_team_summary_for_season(season: int) -> pd.DataFrame:
    """
    Load team summary for a specific season.
    Master: Teams_{season}_Summary or Teams_Historical (with filter)
    Legacy: {season} Summary sheet
    """
    if season >= 2023:
        df = load_from_master_or_legacy("team", f"{season} Summary")
    else:
        # For older years, use historical sheet with filter
        master_xl = get_master_excel_file()
        if master_xl and "Teams_Historical" in master_xl.sheet_names:
            df = master_xl.parse("Teams_Historical")
            df.columns = df.columns.astype(str).str.strip()
            if "Season" in df.columns:
                df = df[df["Season"] == season]
        else:
            df = load_from_master_or_legacy("team", f"{season} Summary")
    
    return df


@st.cache_data(show_spinner=False)
def load_team_full_stats(season: int) -> pd.DataFrame:
    """Load full team stats for a season."""
    if season == 2025:
        df = load_from_master_or_legacy("team", "2025")
    else:
        # For other years, load from legacy or team summary
        df = load_team_summary_for_season(season)
    return df


@st.cache_data(show_spinner=False)
def load_ladder_positions() -> pd.DataFrame:
    """
    Load all historical ladder positions (2011-2025).
    Master: Team_Ladders_All
    Legacy: afl_ladders_2011_2025.xlsx
    """
    df = load_from_master_or_legacy("ladders", "Sheet1")
    
    # Normalize team names
    if not df.empty and "Team" in df.columns:
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


# ============================================================================
# TRAITS DATA LOADERS
# ============================================================================

@st.cache_data(show_spinner=False)
def load_traits_for_season(season: int) -> pd.DataFrame:
    """
    Load player traits for a specific season.
    Master: Player_Traits_{season} or Player_Traits_Historical (with filter)
    Legacy: {season} sheet from 2025 Traits ENRICHED.xlsx
    CSV fallback: data/raw/traits/traits_{season}.csv (for 2026+)
    """
    if season >= 2023:
        df = load_from_master_or_legacy("traits", str(season))
    else:
        # For 2021-2022, use historical sheet with filter
        master_xl = get_master_excel_file()
        if master_xl and "Player_Traits_Historical" in master_xl.sheet_names:
            df = master_xl.parse("Player_Traits_Historical")
            df.columns = df.columns.astype(str).str.strip()
            if "Season" in df.columns:
                df = df[df["Season"] == season]
        else:
            df = load_from_master_or_legacy("traits", str(season))
    
    # CSV fallback for seasons not yet in Excel (e.g. 2026)
    if df.empty:
        csv_path = _get_base_path() / "data" / "raw" / "traits" / f"traits_{season}.csv"
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                df.columns = df.columns.astype(str).str.strip()
            except Exception:
                pass
    
    return df


# ============================================================================
# REFERENCE DATA LOADERS  
# ============================================================================

@st.cache_data(show_spinner=False)
def load_player_registry() -> pd.DataFrame:
    """Load player registry with ID mappings."""
    master_xl = get_master_excel_file()
    if master_xl and "Player_Registry" in master_xl.sheet_names:
        df = master_xl.parse("Player_Registry")
        df.columns = df.columns.astype(str).str.strip()
        return df
    
    # Fall back to standalone file
    registry_path = _get_base_path() / "player_registry.xlsx"
    if registry_path.exists():
        try:
            df = pd.read_excel(registry_path, sheet_name="player_registry")
            df.columns = df.columns.astype(str).str.strip()
            return df
        except Exception:
            pass
    
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_champion_data_ids() -> pd.DataFrame:
    """Load Champion Data player IDs."""
    master_xl = get_master_excel_file()
    if master_xl and "Champion_Data_IDs" in master_xl.sheet_names:
        df = master_xl.parse("Champion_Data_IDs")
        df.columns = df.columns.astype(str).str.strip()
        return df
    
    # Fall back to standalone file
    cd_path = _get_base_path() / "champion_data_player_ids.xlsx"
    if cd_path.exists():
        try:
            df = pd.read_excel(cd_path, sheet_name="Sheet1")
            df.columns = df.columns.astype(str).str.strip()
            return df
        except Exception:
            pass
    
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_wheelo_player_data() -> pd.DataFrame:
    """Load Wheelo player metrics."""
    master_xl = get_master_excel_file()
    if master_xl and "Wheelo_Player_Data" in master_xl.sheet_names:
        df = master_xl.parse("Wheelo_Player_Data")
        df.columns = df.columns.astype(str).str.strip()
        return df
    
    # Fall back to standalone file
    wheelo_path = _get_base_path() / "Wheelo_Player_Data.xlsx"
    if wheelo_path.exists():
        try:
            df = pd.read_excel(wheelo_path, sheet_name="Sheet1")
            df.columns = df.columns.astype(str).str.strip()
            return df
        except Exception:
            pass
    
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_wheelo_team_data() -> pd.DataFrame:
    """Load Wheelo team metrics."""
    master_xl = get_master_excel_file()
    if master_xl and "Wheelo_Team_Data" in master_xl.sheet_names:
        df = master_xl.parse("Wheelo_Team_Data")
        df.columns = df.columns.astype(str).str.strip()
        return df
    
    # Fall back to standalone file
    wheelo_path = _get_base_path() / "Wheelo_Team_Data.xlsx"
    if wheelo_path.exists():
        try:
            df = pd.read_excel(wheelo_path, sheet_name="Sheet1")
            df.columns = df.columns.astype(str).str.strip()
            return df
        except Exception:
            pass
    
    return pd.DataFrame()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_data_source_info() -> Dict[str, any]:
    """Get information about current data source being used."""
    using_master = master_workbook_available()
    master_path = _get_base_path() / MASTER_FILE
    
    info = {
        "using_master": using_master,
        "master_exists": master_path.exists(),
        "master_path": str(master_path) if master_path.exists() else None,
        "legacy_files": {
            "player": (_get_base_path() / PLAYER_FILE).exists(),
            "team": (_get_base_path() / TEAM_FILE).exists(),
            "traits": (_get_base_path() / TRAITS_FILE).exists(),
            "ladders": (_get_base_path() / LADDERS_FILE).exists(),
        }
    }
    
    if using_master:
        try:
            xl = get_master_excel_file()
            info["master_sheets"] = xl.sheet_names if xl else []
        except Exception:
            info["master_sheets"] = []
    
    return info


def clear_data_cache():
    """Clear all cached data (use after updating data files)."""
    # Clear lru_cache
    master_workbook_available.cache_clear()
    get_master_excel_file.cache_clear()
    
    # Clear streamlit cache
    load_player_summary_data.clear()
    load_player_stats_for_season.clear()
    load_full_squad_data.clear()
    load_wings_data.clear()
    load_player_contracts_data.clear()
    load_player_draft_data.clear()
    load_team_summary_for_season.clear()
    load_team_full_stats.clear()
    load_ladder_positions.clear()
    load_traits_for_season.clear()
    load_player_registry.clear()
    load_champion_data_ids.clear()
    load_wheelo_player_data.clear()
    load_wheelo_team_data.clear()


# ============================================================================
# EXCEL FILE ACCESSORS (for functions that need direct Excel access)
# ============================================================================

def get_player_excel_file() -> Optional[pd.ExcelFile]:
    """
    Get ExcelFile for player data.
    Returns master workbook if available, otherwise legacy PLAYER_FILE.
    """
    master_xl = get_master_excel_file()
    if master_xl:
        return master_xl
    return _get_legacy_excel_file("player")


def get_team_excel_file() -> Optional[pd.ExcelFile]:
    """
    Get ExcelFile for team data.
    Returns master workbook if available, otherwise legacy TEAM_FILE.
    """
    master_xl = get_master_excel_file()
    if master_xl:
        return master_xl
    return _get_legacy_excel_file("team")


def get_traits_excel_file() -> Optional[pd.ExcelFile]:
    """
    Get ExcelFile for traits data.
    Returns master workbook if available, otherwise legacy TRAITS_FILE.
    """
    master_xl = get_master_excel_file()
    if master_xl:
        return master_xl
    return _get_legacy_excel_file("traits")
