#!/usr/bin/env python3
"""
Traits API Integration Module

Scrapes DOBs from Wikipedia and uses them to query the Traits API
for player ratings data.
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

# Shared HTTP session with retry logic
_session = create_retry_session(retries=3, backoff_factor=1.0, timeout=10)

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


def query_traits_api(name, dob):
    """
    Query the Traits API for a single player.
    
    Args:
        name: Player full name
        dob: Date of birth in YYYY-MM-DD format
        
    Returns:
        API response dict, or None if not found
    """
    url = f"{API_BASE}/profiles/participations/latest/ratings"
    
    params = {
        'name': name,
        'date_of_birth': dob
    }
    headers = {
        'Authorization': f'Bearer {API_KEY}'
    }
    
    try:
        resp = _session.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            print(f"API auth failed for {name} — check AFL_TRAITS_API_KEY")
    except Exception as e:
        print(f"API error for {name}: {e}")
    
    return None


def parse_traits_response(api_response):
    """
    Parse API response into a flat dict suitable for DataFrame.
    
    Args:
        api_response: Raw API response dict
        
    Returns:
        Dict with trait ratings
    """
    if not api_response or 'participations' not in api_response:
        return None
    
    # Get the most recent participation
    participation = api_response['participations'][0]
    ratings = participation.get('ratings', {})
    
    result = {
        'Player': api_response.get('full_name'),
        'data_provider_id': api_response.get('data_provider_id'),
        'Team_API': participation.get('team_name'),
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
            result[f'{trait_name}_{metric_name}'] = metric.get('value')
    
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
    # First, ensure we have DOBs for all players
    dob_cache = get_player_dobs(players_df)
    
    # Load traits cache
    traits_cache = load_traits_cache() if not force_refresh else {"timestamp": None, "players": {}}
    
    # Get unique player names
    player_names = players_df['Player'].unique()
    total = len(player_names)
    
    results = []
    api_calls = 0
    
    for idx, player_name in enumerate(player_names):
        # Check traits cache first
        if player_name in traits_cache.get('players', {}):
            results.append(traits_cache['players'][player_name])
            if progress_callback:
                progress_callback(idx + 1, total, player_name, 'cached')
            continue
        
        # Get DOB
        dob = dob_cache.get(player_name)
        if not dob:
            if progress_callback:
                progress_callback(idx + 1, total, player_name, 'no_dob')
            continue
        
        # Query API
        response = query_traits_api(player_name, dob)
        api_calls += 1
        
        if response:
            parsed = parse_traits_response(response)
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
        dob: Optional DOB (will look up if not provided)
        
    Returns:
        Dict with player traits, or None if not found
    """
    # Try cache first
    traits_cache = load_traits_cache()
    if player_name in traits_cache.get('players', {}):
        return traits_cache['players'][player_name]
    
    # Get DOB if not provided
    if not dob:
        dob_cache = load_dob_cache()
        dob = dob_cache.get(player_name)
        
        if not dob:
            # Try Wikipedia
            dob = get_dob_from_wikipedia(player_name)
            if dob:
                dob_cache[player_name] = dob
                save_dob_cache(dob_cache)
    
    if not dob:
        return None
    
    # Query API
    response = query_traits_api(player_name, dob)
    if response:
        parsed = parse_traits_response(response)
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
