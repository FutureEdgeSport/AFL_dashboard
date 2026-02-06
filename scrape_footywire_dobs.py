#!/usr/bin/env python3
"""
Scrape player DOBs from Footywire.com.au

Footywire has DOB on individual player profiles:
URL format: https://www.footywire.com/afl/footy/pp-{team-slug}--{player-slug}
DOB format: "Born: March 18, 1995"
"""
import requests
from bs4 import BeautifulSoup
import re
import json
import time
from datetime import datetime
from pathlib import Path

# Team slugs for Footywire URLs
TEAM_SLUGS = {
    "Adelaide": "adelaide-crows",
    "Brisbane": "brisbane-lions",
    "Carlton": "carlton-blues",
    "Collingwood": "collingwood-magpies",
    "Essendon": "essendon-bombers",
    "Fremantle": "fremantle-dockers",
    "Geelong": "geelong-cats",
    "Gold Coast": "gold-coast-suns",
    "GWS Giants": "gws-giants",
    "Greater Western Sydney": "gws-giants",
    "Hawthorn": "hawthorn-hawks",
    "Melbourne": "melbourne-demons",
    "North Melbourne": "north-melbourne-kangaroos",
    "Port Adelaide": "port-adelaide-power",
    "Richmond": "richmond-tigers",
    "St Kilda": "st-kilda-saints",
    "Sydney": "sydney-swans",
    "West Coast": "west-coast-eagles",
    "Western Bulldogs": "western-bulldogs",
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def player_to_slug(player_name):
    """Convert player name to URL slug."""
    # "Patrick Cripps" -> "patrick-cripps"
    slug = player_name.lower().replace("'", "").replace(" ", "-")
    # Handle special characters
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    return slug


def get_dob_from_footywire(player_name, team):
    """
    Fetch DOB from Footywire player profile.
    
    Returns DOB in YYYY-MM-DD format or None if not found.
    """
    team_slug = TEAM_SLUGS.get(team)
    if not team_slug:
        return None
    
    player_slug = player_to_slug(player_name)
    url = f"https://www.footywire.com/afl/footy/pp-{team_slug}--{player_slug}"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Look for "Born: Month DD, YYYY" pattern in text
        text = soup.get_text()
        
        # Pattern: "Born: March 18, 1995"
        match = re.search(r'Born:\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})', text)
        if match:
            month_str, day, year = match.groups()
            # Convert to YYYY-MM-DD
            months = {
                'January': '01', 'February': '02', 'March': '03', 'April': '04',
                'May': '05', 'June': '06', 'July': '07', 'August': '08',
                'September': '09', 'October': '10', 'November': '11', 'December': '12'
            }
            month = months.get(month_str, '01')
            return f"{year}-{month}-{int(day):02d}"
        
    except Exception as e:
        pass
    
    return None


def load_existing_dob_cache():
    """Load existing DOB cache."""
    cache_path = Path(__file__).parent / "data" / "cache" / "player_dobs.json"
    if cache_path.exists():
        with open(cache_path, 'r') as f:
            return json.load(f)
    return {}


def save_dob_cache(cache):
    """Save DOB cache."""
    cache_path = Path(__file__).parent / "data" / "cache" / "player_dobs.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, 'w') as f:
        json.dump(cache, f, indent=2)


if __name__ == "__main__":
    print("Footywire DOB Scraper Test")
    print("=" * 50)
    
    # Test with known players
    test_players = [
        ("Patrick Cripps", "Carlton"),
        ("Marcus Bontempelli", "Western Bulldogs"),
        ("Nick Daicos", "Collingwood"),
        ("Harley Reid", "West Coast"),
        ("Sam Darcy", "Western Bulldogs"),
    ]
    
    for player, team in test_players:
        print(f"\n{player} ({team})...")
        dob = get_dob_from_footywire(player, team)
        if dob:
            print(f"  ✓ DOB: {dob}")
        else:
            print(f"  ✗ Not found")
        time.sleep(0.5)  # Be nice to their server
    
    # Load current cache and check missing players
    print("\n" + "=" * 50)
    print("Checking missing DOBs in current cache...")
    
    cache = load_existing_dob_cache()
    missing = [k for k, v in cache.items() if v is None]
    print(f"Currently missing: {len(missing)} players")
    
    if missing:
        print(f"\nFirst 10 missing: {missing[:10]}")
