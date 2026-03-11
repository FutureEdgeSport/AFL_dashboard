#!/usr/bin/env python3
"""
Scrape 2026 AFL Player Lists from Footywire.com.au

Extracts: Jumper Number, Name, DOB, Height, Position for all 18 teams.
This becomes the foundation for the 2026 dataset.
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
from datetime import datetime
from pathlib import Path
from utils.http_utils import create_retry_session

# Shared HTTP session with retry logic
_session = create_retry_session(retries=3, backoff_factor=1.0, timeout=15)

# Team configurations
TEAMS = {
    "Adelaide": "adelaide-crows",
    "Brisbane": "brisbane-lions", 
    "Carlton": "carlton-blues",
    "Collingwood": "collingwood-magpies",
    "Essendon": "essendon-bombers",
    "Fremantle": "fremantle-dockers",
    "Geelong": "geelong-cats",
    "Gold Coast": "gold-coast-suns",
    "GWS Giants": "greater-western-sydney-giants",
    "Hawthorn": "hawthorn-hawks",
    "Melbourne": "melbourne-demons",
    "North Melbourne": "kangaroos",
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


def parse_dob(dob_str):
    """Parse DOB string like '19 Aug 1995' to 'YYYY-MM-DD'."""
    if not dob_str or pd.isna(dob_str):
        return None
    try:
        # Handle format: "19 Aug 1995"
        dt = datetime.strptime(dob_str.strip(), "%d %b %Y")
        return dt.strftime("%Y-%m-%d")
    except:
        return dob_str


def parse_height(height_str):
    """Parse height string like '181cm' to integer cm."""
    if not height_str or pd.isna(height_str):
        return None
    match = re.search(r'(\d+)', str(height_str))
    if match:
        return int(match.group(1))
    return None


def parse_name(name_str):
    """Convert 'Surname, FirstName' to 'FirstName Surname'."""
    if not name_str or pd.isna(name_str):
        return None
    name = str(name_str).strip()
    # Remove rookie indicator
    name = re.sub(r'\s*R$', '', name)
    # Handle "Surname, FirstName" format
    if ',' in name:
        parts = name.split(',', 1)
        if len(parts) == 2:
            return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def scrape_team_players(team_name, team_slug):
    """Scrape player list for a single team."""
    url = f"https://www.footywire.com/afl/footy/tp-{team_slug}"
    
    try:
        resp = _session.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ✗ HTTP {resp.status_code}")
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Find the player table - look for table containing "No", "Name", "Date of Birth"
        tables = soup.find_all('table')
        
        for table in tables:
            table_text = table.get_text()
            # Look for the table with player data pattern
            if 'No' in table_text and 'Name' in table_text and 'Date of Birth' in table_text:
                # Check if it has actual player data (numbers and names)
                rows = table.find_all('tr')
                
                players = []
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 6:
                        # First cell should be a number (jumper)
                        first_cell = cells[0].get_text(strip=True)
                        if first_cell.isdigit():
                            player = {
                                'Team': team_name,
                                'Jumper_No': first_cell,
                                'Name_Raw': cells[1].get_text(strip=True),
                                'Games': cells[2].get_text(strip=True),
                                'Age': cells[3].get_text(strip=True),
                                'DOB_Raw': cells[4].get_text(strip=True),
                                'Height_Raw': cells[5].get_text(strip=True),
                            }
                            if len(cells) >= 8:
                                player['Origin'] = cells[6].get_text(strip=True)
                                player['Position'] = cells[7].get_text(strip=True)
                            
                            # Clean up the data
                            player['Player'] = parse_name(player['Name_Raw'])
                            player['DOB'] = parse_dob(player['DOB_Raw'])
                            player['Height'] = parse_height(player['Height_Raw'])
                            player['Jumper_No'] = int(player['Jumper_No']) if player['Jumper_No'].isdigit() else None
                            
                            players.append(player)
                
                if players:  # Found valid data
                    return players
        
        print(f"  ✗ Player table not found")
        return []
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return []


def scrape_all_teams(output_file=None):
    """Scrape player lists for all 18 AFL teams."""
    all_players = []
    
    print("Scraping 2026 AFL Player Lists from Footywire")
    print("=" * 60)
    
    for team_name, team_slug in TEAMS.items():
        print(f"\n{team_name}...", end=" ", flush=True)
        players = scrape_team_players(team_name, team_slug)
        
        if players:
            print(f"✓ {len(players)} players")
            all_players.extend(players)
        else:
            print("✗ Failed")
        
        time.sleep(1)  # Be nice to their server
    
    print("\n" + "=" * 60)
    print(f"Total players scraped: {len(all_players)}")
    
    # Create DataFrame
    df = pd.DataFrame(all_players)
    
    # Select and order columns for output
    output_cols = ['Team', 'Jumper_No', 'Player', 'DOB', 'Height', 'Position', 'Games', 'Age', 'Origin']
    df = df[[c for c in output_cols if c in df.columns]]
    
    # Save to CSV
    if output_file:
        df.to_csv(output_file, index=False)
        print(f"\nSaved to: {output_file}")
    
    return df


def update_dob_cache(df):
    """Update the DOB cache with newly scraped data."""
    cache_path = Path(__file__).parent / "data" / "cache" / "player_dobs.json"
    
    import json
    
    # Load existing cache
    if cache_path.exists():
        with open(cache_path, 'r') as f:
            cache = json.load(f)
    else:
        cache = {}
    
    # Update with new DOBs
    updated = 0
    for _, row in df.iterrows():
        player = row['Player']
        dob = row['DOB']
        if player and dob:
            if player not in cache or cache[player] is None:
                cache[player] = dob
                updated += 1
    
    # Save
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, 'w') as f:
        json.dump(cache, f, indent=2)
    
    print(f"Updated DOB cache: {updated} new entries")
    return cache


if __name__ == "__main__":
    import sys
    
    # Output file path
    output_file = "data/raw/player/footywire_2026_lists.csv"
    
    # Scrape all teams
    df = scrape_all_teams(output_file)
    
    # Show sample
    if not df.empty:
        print("\nSample data:")
        print(df.head(10).to_string())
        
        # Position distribution
        print("\n\nPosition distribution:")
        print(df['Position'].value_counts())
        
        # Update DOB cache
        print("\n")
        update_dob_cache(df)
