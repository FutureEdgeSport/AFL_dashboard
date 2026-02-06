"""
Historical Data Loader Module
=============================
Loads consolidated historical data (2012-2025) from the single source of truth workbook.
This module provides read-only access to historical data that won't change.

For 2026+ data, the app continues to use the API and scrapers.
"""
import pandas as pd
from pathlib import Path
from functools import lru_cache
from typing import Optional, Dict, List

# Path to consolidated historical data
HISTORICAL_FILE = Path(__file__).parent.parent / "data" / "AFL_Historical_2012_2025.xlsx"

# Feature flag - set to True to use consolidated workbook for historical data
USE_HISTORICAL_WORKBOOK = True

# Cache the Excel file object to avoid repeated file reads
_excel_cache: Optional[pd.ExcelFile] = None


def _get_excel_file() -> Optional[pd.ExcelFile]:
    """Get cached Excel file handle."""
    global _excel_cache
    if _excel_cache is None and HISTORICAL_FILE.exists():
        try:
            _excel_cache = pd.ExcelFile(HISTORICAL_FILE)
        except Exception as e:
            print(f"Warning: Could not load historical workbook: {e}")
            return None
    return _excel_cache


def is_historical_season(season: int) -> bool:
    """Check if a season is considered historical (in the consolidated workbook)."""
    return season <= 2025


def historical_workbook_available() -> bool:
    """Check if the historical workbook is available and enabled."""
    return USE_HISTORICAL_WORKBOOK and HISTORICAL_FILE.exists()


# ============================================================================
# PLAYER STATS LOADERS
# ============================================================================

@lru_cache(maxsize=20)
def load_player_stats_historical(season: int) -> pd.DataFrame:
    """
    Load player stats for a historical season (2012-2025) from consolidated workbook.
    
    Returns empty DataFrame if season not found or workbook unavailable.
    """
    if not historical_workbook_available() or season > 2025:
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        df = pd.read_excel(xl, sheet_name='Player_Stats_All')
        # Filter to requested season
        df = df[df['Season'] == season].copy()
        return df
    except Exception as e:
        print(f"Error loading player stats for {season}: {e}")
        return pd.DataFrame()


def load_all_player_stats_historical() -> pd.DataFrame:
    """Load all historical player stats (2012-2025) at once."""
    if not historical_workbook_available():
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        return pd.read_excel(xl, sheet_name='Player_Stats_All')
    except Exception:
        return pd.DataFrame()


# ============================================================================
# TRAITS LOADERS
# ============================================================================

@lru_cache(maxsize=10)
def load_traits_historical(season: int) -> pd.DataFrame:
    """
    Load traits for a historical season (2021-2025) from consolidated workbook.
    
    Note: Traits data starts from 2021.
    Returns empty DataFrame if season not found or workbook unavailable.
    """
    if not historical_workbook_available() or season > 2025 or season < 2021:
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        df = pd.read_excel(xl, sheet_name='Player_Traits_All')
        # Filter to requested season
        df = df[df['Season'] == season].copy()
        return df
    except Exception as e:
        print(f"Error loading traits for {season}: {e}")
        return pd.DataFrame()


def load_all_traits_historical() -> pd.DataFrame:
    """Load all historical traits (2021-2025) at once."""
    if not historical_workbook_available():
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        return pd.read_excel(xl, sheet_name='Player_Traits_All')
    except Exception:
        return pd.DataFrame()


# ============================================================================
# TEAM STATS LOADERS
# ============================================================================

@lru_cache(maxsize=10)
def load_team_stats_historical(season: int) -> pd.DataFrame:
    """
    Load team stats for a historical season (2021-2025) from consolidated workbook.
    
    Returns empty DataFrame if season not found or workbook unavailable.
    """
    if not historical_workbook_available() or season > 2025 or season < 2021:
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        df = pd.read_excel(xl, sheet_name='Team_Stats_All')
        # Filter to requested season
        df = df[df['Season'] == season].copy()
        return df
    except Exception as e:
        print(f"Error loading team stats for {season}: {e}")
        return pd.DataFrame()


def load_all_team_stats_historical() -> pd.DataFrame:
    """Load all historical team stats (2021-2025) at once."""
    if not historical_workbook_available():
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        return pd.read_excel(xl, sheet_name='Team_Stats_All')
    except Exception:
        return pd.DataFrame()


# ============================================================================
# REGISTRY LOADERS
# ============================================================================

@lru_cache(maxsize=1)
def load_player_registry() -> pd.DataFrame:
    """
    Load the master player registry with DOB, draft, contract info.
    
    This is a snapshot as of end of 2025.
    """
    if not historical_workbook_available():
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        return pd.read_excel(xl, sheet_name='Player_Registry')
    except Exception:
        return pd.DataFrame()


@lru_cache(maxsize=1)
def load_team_reference() -> pd.DataFrame:
    """Load team reference data (abbreviations, slugs, etc.)."""
    if not historical_workbook_available():
        return pd.DataFrame()
    
    xl = _get_excel_file()
    if xl is None:
        return pd.DataFrame()
    
    try:
        return pd.read_excel(xl, sheet_name='Team_Reference')
    except Exception:
        return pd.DataFrame()


# ============================================================================
# PLAYER LOOKUP HELPERS
# ============================================================================

def get_player_dob(player_name: str) -> Optional[str]:
    """Get DOB for a player from the registry."""
    registry = load_player_registry()
    if registry.empty:
        return None
    
    match = registry[registry['Player'] == player_name]
    if not match.empty:
        dob = match.iloc[0].get('DOB')
        return str(dob) if pd.notna(dob) else None
    return None


def get_player_draft_info(player_name: str) -> Dict:
    """Get draft information for a player."""
    registry = load_player_registry()
    if registry.empty:
        return {}
    
    match = registry[registry['Player'] == player_name]
    if not match.empty:
        row = match.iloc[0]
        return {
            'Draft_Year': row.get('Draft_Year'),
            'Draft_Pick': row.get('Draft_Pick'),
            'Draft_Type': row.get('Draft_Type'),
            'Draft_Round': row.get('Draft_Round'),
            'Acquisition': row.get('Acquisition'),
        }
    return {}


def get_player_contract_expiry(player_name: str) -> Optional[int]:
    """Get contract expiry year for a player."""
    registry = load_player_registry()
    if registry.empty:
        return None
    
    match = registry[registry['Player'] == player_name]
    if not match.empty:
        expiry = match.iloc[0].get('Contract_Expiry')
        return int(expiry) if pd.notna(expiry) else None
    return None


def get_player_career_stats(player_name: str) -> pd.DataFrame:
    """Get all historical season stats for a player."""
    all_stats = load_all_player_stats_historical()
    if all_stats.empty:
        return pd.DataFrame()
    
    return all_stats[all_stats['Player'] == player_name].copy()


def get_player_career_traits(player_name: str) -> pd.DataFrame:
    """Get all historical traits for a player."""
    all_traits = load_all_traits_historical()
    if all_traits.empty:
        return pd.DataFrame()
    
    # Traits use abbreviated names, try to match
    # First try exact match
    matches = all_traits[all_traits['Player'] == player_name]
    if not matches.empty:
        return matches.copy()
    
    # Try surname match
    surname = player_name.split()[-1] if ' ' in player_name else player_name
    matches = all_traits[all_traits['Player'].str.contains(surname, case=False, na=False)]
    return matches.copy()


# ============================================================================
# TEAM LOOKUP HELPERS
# ============================================================================

def get_team_history(team_name: str) -> pd.DataFrame:
    """Get all historical stats for a team."""
    all_stats = load_all_team_stats_historical()
    if all_stats.empty:
        return pd.DataFrame()
    
    return all_stats[all_stats['Team'] == team_name].copy()


def get_team_footywire_slug(team_name: str) -> Optional[str]:
    """Get the Footywire URL slug for a team."""
    ref = load_team_reference()
    if ref.empty:
        return None
    
    match = ref[ref['Team'] == team_name]
    if not match.empty:
        slug = match.iloc[0].get('Footywire_Slug')
        return str(slug) if pd.notna(slug) else None
    return None


# ============================================================================
# METADATA
# ============================================================================

def get_workbook_metadata() -> Dict:
    """Get metadata about the historical workbook."""
    if not historical_workbook_available():
        return {}
    
    xl = _get_excel_file()
    if xl is None:
        return {}
    
    try:
        meta = pd.read_excel(xl, sheet_name='Metadata')
        return dict(zip(meta['Category'], meta['Notes']))
    except Exception:
        return {}


def get_available_seasons() -> List[int]:
    """Get list of seasons available in historical data."""
    all_stats = load_all_player_stats_historical()
    if all_stats.empty:
        return []
    
    return sorted(all_stats['Season'].unique().tolist())


# ============================================================================
# CLEAR CACHE
# ============================================================================

def clear_historical_cache():
    """Clear all cached historical data (useful after workbook update)."""
    global _excel_cache
    _excel_cache = None
    
    # Clear lru_cache
    load_player_stats_historical.cache_clear()
    load_traits_historical.cache_clear()
    load_team_stats_historical.cache_clear()
    load_player_registry.cache_clear()
    load_team_reference.cache_clear()
