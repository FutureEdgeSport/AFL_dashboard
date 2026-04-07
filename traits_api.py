#!/usr/bin/env python3
"""
Traits API Integration Module

Queries the Traits API for player ratings data by name.
"""
import requests
import pandas as pd
import json
import os
import time
from datetime import datetime
from bs4 import BeautifulSoup
from pathlib import Path

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # dotenv not installed — rely on environment variables

from utils.http_utils import create_retry_session

# API Configuration — key MUST be set via environment variable or .env file
API_KEY = os.environ.get("AFL_TRAITS_API_KEY", "")
if not API_KEY:
    print("⚠️  AFL_TRAITS_API_KEY not set. Set it in .env or export it.")
API_BASE = "https://partner-api.traitsinsights.app"

# Shared HTTP session — NO automatic retries for the Traits API.
# The previous retry config (retries=3) caused each not-found player to
# hit the Traits server 4 times (1 original + 3 retries on 500),
# generating unnecessary load on their end.
_session = create_retry_session(retries=0, backoff_factor=0, timeout=10)

# Placeholder DOB used by Footywire when actual DOB is unknown
PLACEHOLDER_DOB = "2000-01-01"

# --- Name-variant mapping ---------------------------------------------------
# Footywire sometimes stores full/abbreviated names that differ from what
# Traits has on file.  We try the original name first then fall back to
# a common variant built from this table.
_NAME_SHORT_TO_FULL = {
    "Tom": "Thomas", "Tim": "Timothy", "Nick": "Nicholas",
    "Matt": "Matthew", "Jack": "Jackson", "Will": "William",
    "Sam": "Samuel", "Rob": "Robert", "Josh": "Joshua",
    "Mitch": "Mitchell", "Ben": "Benjamin", "Cam": "Cameron",
    "Zach": "Zachary", "Ollie": "Oliver", "Harry": "Harrison",
    "Lachie": "Lachlan", "Finn": "Finnegan", "Chris": "Christopher",
    "Nic": "Nicholas", "Dan": "Daniel", "Ed": "Edward",
    "Pat": "Patrick", "Alex": "Alexander", "Mike": "Michael",
    "Jake": "Jacob", "Joe": "Joseph", "Charlie": "Charles",
    "Archie": "Archibald", "Freddy": "Frederick", "Fred": "Frederick",
    "Max": "Maxwell", "Paddy": "Patrick",
}
# Build reverse map — prefer the more common short form when there are
# duplicates (e.g. both "Nick" and "Nic" map to "Nicholas"; we want
# "Nicholas" → "Nick").
_NAME_FULL_TO_SHORT = {}
for _short, _full in _NAME_SHORT_TO_FULL.items():
    # Keep the first (more common) mapping; skip duplicates like "Nic"
    if _full not in _NAME_FULL_TO_SHORT:
        _NAME_FULL_TO_SHORT[_full] = _short


def _name_variant(name: str) -> str | None:
    """Return an alternate first-name form, or None if no mapping exists."""
    parts = name.split(" ", 1)
    if len(parts) < 2:
        return None
    first, rest = parts
    alt = _NAME_FULL_TO_SHORT.get(first) or _NAME_SHORT_TO_FULL.get(first)
    if alt:
        return f"{alt} {rest}"
    return None


def _has_middle_initial(name: str) -> str | None:
    """If the name contains a middle initial (e.g. 'Bailey J. Williams'),
    return the version without it."""
    import re
    m = re.match(r'^(\S+)\s+[A-Z]\.\s+(\S.*)$', name)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return None

# Cache file paths
CACHE_DIR = Path(__file__).parent / "data" / "cache"
DOB_CACHE_FILE = CACHE_DIR / "player_dobs.json"
TRAITS_CACHE_FILE = CACHE_DIR / "traits_api_cache.json"


def ensure_cache_dir():
    """Ensure cache directory exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_dob_cache():
    """Load cached DOBs from file."""
    if DOB_CACHE_FILE.exists():
        with open(DOB_CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_dob_cache(cache):
    """Save DOB cache to file."""
    ensure_cache_dir()
    with open(DOB_CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)


def load_traits_cache():
    """Load cached traits data from file."""
    if TRAITS_CACHE_FILE.exists():
        with open(TRAITS_CACHE_FILE, 'r') as f:
            return json.load(f)
    return {"timestamp": None, "players": {}}


def save_traits_cache(cache):
    """Save traits cache to file."""
    ensure_cache_dir()
    with open(TRAITS_CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)


def get_dob_from_wikipedia(player_name, team=None):
    """
    Scrape DOB from Wikipedia for an AFL player.
    
    Args:
        player_name: Full player name (e.g., "Patrick Cripps")
        team: Optional team name for disambiguation
        
    Returns:
        DOB string in YYYY-MM-DD format, or None if not found
    """
    name_slug = player_name.replace(' ', '_')
    
    # Try different Wikipedia URL patterns
    urls = [
        f"https://en.wikipedia.org/wiki/{name_slug}_(Australian_footballer)",
        f"https://en.wikipedia.org/wiki/{name_slug}_(footballer)",
        f"https://en.wikipedia.org/wiki/{name_slug}",
    ]
    
    # Add team-specific pattern if team provided
    if team:
        team_slug = team.replace(' ', '_')
        urls.insert(0, f"https://en.wikipedia.org/wiki/{name_slug}_(footballer,_born_1990s)")
    
    headers = {'User-Agent': 'Mozilla/5.0 (AFL Dashboard DOB Lookup)'}
    
    for url in urls:
        try:
            resp = _session.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Find the infobox
                infobox = soup.find('table', class_='infobox')
                if infobox:
                    # Verify it's an AFL player by checking for AFL team names
                    text = infobox.get_text().lower()
                    afl_teams = ['adelaide', 'brisbane', 'carlton', 'collingwood', 'essendon',
                                 'fremantle', 'geelong', 'gold coast', 'gws', 'hawthorn',
                                 'melbourne', 'north melbourne', 'port adelaide', 'richmond',
                                 'st kilda', 'sydney', 'west coast', 'western bulldogs']
                    
                    is_afl = any(t in text for t in afl_teams)
                    
                    if is_afl or 'australian football' in text or 'afl' in text:
                        # Look for "Born" row
                        for row in infobox.find_all('tr'):
                            header = row.find('th')
                            if header and 'Born' in header.get_text():
                                bday = row.find('span', class_='bday')
                                if bday:
                                    return bday.get_text()
        except Exception as e:
            pass
    
    return None


def get_player_dobs(players_df, progress_callback=None):
    """
    Get DOBs for all players, using cache when available.
    
    Args:
        players_df: DataFrame with 'Player' and 'Team' columns
        progress_callback: Optional callback(current, total, player_name)
        
    Returns:
        Dict mapping player name to DOB
    """
    cache = load_dob_cache()
    
    # Get unique players
    if 'Team' in players_df.columns:
        players = players_df[['Player', 'Team']].drop_duplicates()
    else:
        players = players_df[['Player']].drop_duplicates()
        players['Team'] = None
    
    total = len(players)
    updated = 0
    
    for idx, row in players.iterrows():
        player_name = row['Player']
        team = row.get('Team')
        
        if player_name in cache:
            continue
        
        # Scrape from Wikipedia
        dob = get_dob_from_wikipedia(player_name, team)
        cache[player_name] = dob
        updated += 1
        
        if progress_callback:
            progress_callback(updated, total, player_name)
        
        # Be nice to Wikipedia
        time.sleep(0.5)
    
    if updated > 0:
        save_dob_cache(cache)
        print(f"Updated DOB cache with {updated} new players")
    
    return cache


def _is_placeholder_dob(dob: str) -> bool:
    """Return True if the DOB is a known placeholder (not real)."""
    return dob == PLACEHOLDER_DOB


def _is_rookie_dob(dob: str, cutoff_year: int = 2007) -> bool:
    """Return True if the player was born in or after *cutoff_year*.
    First-year draftees typically won't be in the Traits database yet."""
    try:
        return int(dob[:4]) >= cutoff_year
    except (ValueError, TypeError):
        return False


def _build_provider_id(name: str, dob: str) -> str | None:
    """Construct a data_provider_id from a player name and DOB.

    The Traits API uses the format ``FirstInitial.LastName DD/M/YYYY``.
    *dob* should be in ``YYYY-MM-DD`` format (as stored in Footywire data).
    Returns None if the inputs are invalid.
    """
    if not name or not dob:
        return None
    try:
        parts = name.split(" ", 1)
        if len(parts) < 2:
            return None
        first, last = parts
        # Convert YYYY-MM-DD → D/M/YYYY (no leading zeros)
        y, m, d = dob.split("-")
        dob_fmt = f"{int(d)}/{int(m)}/{y}"
        return f"{first[0]}.{last} {dob_fmt}"
    except (ValueError, IndexError):
        return None


def _query_traits_api_once(provider_id: str):
    """Single attempt to query the Traits API by data_provider_id."""
    url = f"{API_BASE}/profiles/participations/latest/ratings"
    params = {'data_provider_id': provider_id}
    headers = {'Authorization': f'Bearer {API_KEY}'}

    try:
        resp = _session.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            print(f"API auth failed for {provider_id} — check AFL_TRAITS_API_KEY")
    except Exception as e:
        print(f"API error for {provider_id}: {e}")
    return None


def _get_cached_provider_id(name: str) -> str | None:
    """Look up a data_provider_id from the traits cache."""
    cache = load_traits_cache()
    entry = cache.get('players', {}).get(name, {})
    return entry.get('data_provider_id')


def query_traits_api(name, dob=None):
    """
    Query the Traits API for a single player.

    Uses ``data_provider_id`` (not ``date_of_birth``) to identify
    players.  If a cached provider-id exists it is used directly;
    otherwise one is constructed from the Footywire DOB data.

    Tries the given *name* first, then automatically tries common
    name variants (e.g. "Thomas" ↔ "Tom") and drops middle initials
    (e.g. "Bailey J. Williams" → "Bailey Williams") before giving up.

    Args:
        name: Player full name
        dob:  Date of birth in YYYY-MM-DD format.  Used only to
              construct the data_provider_id for players not yet
              in the cache.

    Returns:
        API response dict, or None if not found
    """
    # --- Resolve provider-id -------------------------------------------------
    provider_id = _get_cached_provider_id(name)

    if not provider_id and dob:
        # Skip known-bad DOBs
        if _is_placeholder_dob(dob):
            return None
        # Skip first-year draftees (born 2007+) — Traits won't have them yet
        if _is_rookie_dob(dob):
            return None
        provider_id = _build_provider_id(name, dob)

    if not provider_id:
        return None

    # --- Try the resolved provider-id ----------------------------------------
    result = _query_traits_api_once(provider_id)
    if result:
        return result

    # --- Try name variant (short ↔ full first name) --------------------------
    alt = _name_variant(name)
    if alt:
        alt_pid = _get_cached_provider_id(alt) or (
            _build_provider_id(alt, dob) if dob else None
        )
        if alt_pid:
            result = _query_traits_api_once(alt_pid)
            if result:
                return result

    # --- Try dropping middle initial (e.g. "Bailey J. Williams") -------------
    no_mid = _has_middle_initial(name)
    if no_mid:
        no_mid_pid = _get_cached_provider_id(no_mid) or (
            _build_provider_id(no_mid, dob) if dob else None
        )
        if no_mid_pid:
            result = _query_traits_api_once(no_mid_pid)
            if result:
                return result
            # Also try variant of the no-middle-initial form
            alt2 = _name_variant(no_mid)
            if alt2:
                alt2_pid = _get_cached_provider_id(alt2) or (
                    _build_provider_id(alt2, dob) if dob else None
                )
                if alt2_pid:
                    result = _query_traits_api_once(alt2_pid)
                    if result:
                        return result

    return None


def parse_traits_response(api_response, competition="AFL"):
    """
    Parse API response into a flat dict suitable for DataFrame.
    
    Prefers the requested competition (default AFL) over others (e.g. VFL).
    Falls back to state-league data (VFL, SANFL, WAFL) if no AFL
    participation exists, so that fringe/rookie players still get ratings.
    
    Args:
        api_response: Raw API response dict
        competition: Preferred competition (default "AFL")
        
    Returns:
        Dict with trait ratings, or None if no participation at all
    """
    if not api_response or 'participations' not in api_response:
        return None
    
    participations = api_response['participations']
    
    # Find the participation matching the preferred competition
    participation = None
    for p in participations:
        if p.get('competition_name', '').upper() == competition.upper():
            participation = p
            break
    
    # Fall back to state leagues (VFL > SANFL > WAFL > anything)
    if participation is None:
        fallback_order = ['VFL', 'SANFL', 'WAFL']
        for fb in fallback_order:
            for p in participations:
                if p.get('competition_name', '').upper() == fb:
                    participation = p
                    break
            if participation:
                break
        # Last resort: take the first participation
        if participation is None and participations:
            participation = participations[0]
    
    if participation is None:
        return None
    
    ratings = participation.get('ratings', {})
    
    result = {
        'Player': api_response.get('full_name'),
        'data_provider_id': api_response.get('data_provider_id'),
        'Team_API': participation.get('team_name'),
        'Competition': participation.get('competition_name'),
        'Season_API': participation.get('season_name'),
        'Position_API': participation.get('position', {}).get('name'),
        'Overall_Rating': ratings.get('rating'),
    }
    
    # Add individual trait ratings
    for trait in ratings.get('traits', []):
        trait_name = trait['name']
        result[f'{trait_name}_Rating'] = trait.get('rating')
        
        # Also add individual metrics
        for metric in trait.get('metrics', []):
            metric_name = metric['name']
            result[f'{trait_name}_{metric_name}'] = metric.get('rating')
    
    return result


def fetch_all_traits(players_df, force_refresh=False, progress_callback=None):
    """
    Fetch traits data for all players from the API.
    
    Args:
        players_df: DataFrame with 'Player' and optionally 'Team' columns
        force_refresh: If True, ignore cache and re-fetch all
        progress_callback: Optional callback(current, total, player_name, status)
        
    Returns:
        DataFrame with all traits data
    """
    # Load DOB cache for constructing data_provider_id for uncached players
    dob_cache = load_dob_cache()

    # Load traits cache
    traits_cache = load_traits_cache() if not force_refresh else {"timestamp": None, "players": {}}
    
    # Get unique player names
    player_names = players_df['Player'].unique()
    total = len(player_names)
    
    results = []
    api_calls = 0
    
    for idx, player_name in enumerate(player_names):
        # Check traits cache first (re-query if cached data is from a previous season)
        if player_name in traits_cache.get('players', {}):
            cached_data = traits_cache['players'][player_name]
            cached_season = str(cached_data.get('Season_API', ''))
            from config.constants import CURRENT_SEASON
            is_current = str(CURRENT_SEASON) in cached_season
            if is_current:
                results.append(cached_data)
                if progress_callback:
                    progress_callback(idx + 1, total, player_name, 'cached')
                continue
        
        # Query API (pass DOB so data_provider_id can be constructed)
        dob = dob_cache.get(player_name)
        response = query_traits_api(player_name, dob)
        api_calls += 1
        
        if response:
            parsed = parse_traits_response(response, competition="AFL")
            if parsed:
                results.append(parsed)
                traits_cache.setdefault('players', {})[player_name] = parsed
                
                if progress_callback:
                    progress_callback(idx + 1, total, player_name, 'success')
        else:
            if progress_callback:
                progress_callback(idx + 1, total, player_name, 'not_found')
        
        # Rate limiting
        if api_calls % 10 == 0:
            time.sleep(1)
    
    # Update cache
    traits_cache['timestamp'] = datetime.now().isoformat()
    save_traits_cache(traits_cache)
    
    if results:
        return pd.DataFrame(results)
    return pd.DataFrame()


def get_traits_for_player(player_name, dob=None):
    """
    Get traits data for a single player.
    
    Args:
        player_name: Full player name
        dob: Optional DOB in YYYY-MM-DD format, used to construct
             data_provider_id for uncached players.
        
    Returns:
        Dict with player traits, or None if not found
    """
    # Try cache first
    traits_cache = load_traits_cache()
    if player_name in traits_cache.get('players', {}):
        return traits_cache['players'][player_name]
    
    # Look up DOB from cache if not provided
    if not dob:
        dob_cache = load_dob_cache()
        dob = dob_cache.get(player_name)
    
    # Query API (DOB used to construct data_provider_id, NOT sent directly)
    response = query_traits_api(player_name, dob)
    if response:
        parsed = parse_traits_response(response, competition="AFL")
        if parsed:
            # Update cache
            traits_cache.setdefault('players', {})[player_name] = parsed
            save_traits_cache(traits_cache)
            return parsed
    
    return None


def get_positions():
    """Get available positions from the API."""
    url = f"{API_BASE}/positions"
    headers = {'Authorization': f'Bearer {API_KEY}'}
    
    try:
        resp = _session.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching positions: {e}")
    
    return None


def get_position_weights(position_id):
    """Get weight profiles for a specific position."""
    url = f"{API_BASE}/positions/{position_id}/weight-profiles"
    headers = {'Authorization': f'Bearer {API_KEY}'}
    
    try:
        resp = _session.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching position weights: {e}")
    
    return None


if __name__ == "__main__":
    print("Traits API Integration Module")
    print("=" * 50)
    
    # Test with a few known players
    test_players = [
        ("Patrick Cripps", "1995-03-18"),
        ("Marcus Bontempelli", "1995-11-24"),
        ("Nick Daicos", None),  # Will look up DOB
    ]
    
    for name, dob in test_players:
        print(f"\nFetching traits for {name}...")
        traits = get_traits_for_player(name, dob)
        if traits:
            print(f"  ✓ Found: {traits.get('Player')}")
            print(f"    Position: {traits.get('Position_API')}")
            print(f"    Overall: {traits.get('Overall_Rating')}")
            for key, val in traits.items():
                if key.endswith('_Rating') and key != 'Overall_Rating':
                    print(f"    {key}: {val}")
        else:
            print(f"  ✗ Not found")
    
    # Get positions
    print("\n" + "=" * 50)
    print("Available positions:")
    positions = get_positions()
    if positions:
        for pos in positions:
            print(f"  {pos['name']}: {pos['id']}")
