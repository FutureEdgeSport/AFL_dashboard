#!/usr/bin/env python3
"""
AFL Image Scraper V2 - Using JSON data extraction
This extracts player data from team websites and constructs image URLs
"""

import os
import requests
import time
import pandas as pd
import re
import json

# Configuration
PLAYER_PHOTOS_DIR = "player_photos"
TEAM_LOGOS_DIR = "team_logos"
PLAYER_FILE = "AFL Player Ratings.xlsx"

# Team club website base URLs
TEAM_CLUB_URLS = {
    "Adelaide": "https://www.afc.com.au/players",
    "Brisbane": "https://www.lions.com.au/players",
    "Carlton": "https://www.carltonfc.com.au/players",
    "Collingwood": "https://www.collingwoodfc.com.au/players",
    "Essendon": "https://www.essendonfc.com.au/players",
    "Fremantle": "https://www.fremantlefc.com.au/players",
    "Geelong": "https://www.geelongcats.com.au/players",
    "Gold Coast": "https://www.goldcoastfc.com.au/players",
    "GWS": "https://www.gwsgiants.com.au/players",
    "GWS Giants": "https://www.gwsgiants.com.au/players",
    "Greater Western Sydney": "https://www.gwsgiants.com.au/players",
    "Hawthorn": "https://www.hawthornfc.com.au/players",
    "Melbourne": "https://www.melbournefc.com.au/players",
    "North Melbourne": "https://www.nmfc.com.au/players",
    "Port Adelaide": "https://www.portadelaidefc.com.au/players",
    "Richmond": "https://www.richmondfc.com.au/players",
    "St Kilda": "https://www.saints.com.au/players",
    "Sydney": "https://www.sydneyswans.com.au/players",
    "West Coast": "https://www.westcoasteagles.com.au/players",
    "Western Bulldogs": "https://www.westernbulldogs.com.au/players",
}

# AFL team codes for image URLs (based on AFL's internal numbering)
TEAM_IMAGE_CODES = {
    "Adelaide": "014",
    "Brisbane": "020",
    "Carlton": "030",
    "Collingwood": "040",
    "Essendon": "050",
    "Fremantle": "060",
    "Geelong": "070",
    "Gold Coast": "100",
    "GWS": "110",
    "GWS Giants": "110",
    "Greater Western Sydney": "110",
    "Hawthorn": "080",
    "Melbourne": "090",
    "North Melbourne": "150",
    "Port Adelaide": "160",
    "Richmond": "120",
    "St Kilda": "130",
    "Sydney": "140",
    "West Coast": "170",
    "Western Bulldogs": "180",
}

def normalize_player_name(name):
    """Normalize player name for filename."""
    return re.sub(r'[^\w\s-]', '', str(name).lower()).replace(' ', '_')

def ensure_directories():
    """Create necessary directories."""
    os.makedirs(PLAYER_PHOTOS_DIR, exist_ok=True)
    os.makedirs(TEAM_LOGOS_DIR, exist_ok=True)

def download_image(url, save_path):
    """Download an image from URL."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        return False

def get_team_player_data(team_name):
    """Extract player data JSON from team website."""
    url = TEAM_CLUB_URLS.get(team_name)
    if not url:
        return None
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None
        
        # Look for JSON player data in the page
        content = response.text
        
        # Pattern: JSON.stringify( [{player data}] )
        match = re.search(r'JSON\.stringify\(\s*(\[.*?\])\s*\)', content, re.DOTALL)
        if match:
            json_str = match.group(1)
            try:
                players_data = json.loads(json_str)
                return players_data
            except:
                pass
        
        return None
    except Exception as e:
        print(f"  ⚠ Error getting team data: {e}")
        return None

def construct_image_url(player_id, provider_id, team_name):
    """Construct AFL player image URL from IDs."""
    # Pattern: https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/2026014/1014026.png
    # Note: ALL players use team code "014" (not specific to Adelaide) and year prefix
    from datetime import datetime
    year = datetime.now().year  # Dynamic year (2026 in 2026, etc.)
    team_code = "014"  # All players stored under this code
    
    # Add image scaling parameter for better quality/size
    base_url = f"https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/{year}{team_code}/{provider_id}.png"
    
    # Try current year first, then previous year as fallback
    urls_to_try = [
        f"{base_url}?im=Scale,width=0.6,height=0.6",
        base_url,
        # Fallback to previous year in case new photos aren't up yet
        f"https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/{year-1}{team_code}/{provider_id}.png",
    ]
    
    return urls_to_try

def get_players_from_excel():
    """Load player list from Excel file."""
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        df = xl.parse("Summary")
        
        players = []
        for _, row in df.iterrows():
            player_name = row.get("Player", "")
            team = row.get("Team", "")
            
            if pd.notna(player_name) and pd.notna(team):
                players.append({
                    'name': str(player_name).strip(),
                    'team': str(team).strip(),
                    'normalized': normalize_player_name(str(player_name))
                })
        
        # Remove duplicates
        seen = set()
        unique_players = []
        for p in players:
            if p['normalized'] not in seen:
                seen.add(p['normalized'])
                unique_players.append(p)
        
        print(f"\n✓ Found {len(unique_players)} unique players from {PLAYER_FILE}")
        return unique_players
    
    except Exception as e:
        print(f"✗ Error loading Excel file: {e}")
        return []

def download_player_photos(players, max_downloads=None):
    """Download player photos using extracted JSON data."""
    print("\n=== Downloading Player Photos ===")
    
    # Cache team player data
    team_data_cache = {}
    
    downloaded = 0
    skipped = 0
    failed = 0
    
    for i, player in enumerate(players):
        if max_downloads and i >= max_downloads:
            print(f"\n⊙ Reached max downloads limit ({max_downloads})")
            break
        
        player_name = player['name']
        normalized = player['normalized']
        team = player['team']
        
        save_path = os.path.join(PLAYER_PHOTOS_DIR, f"{normalized}.png")
        
        # Skip if already exists
        if os.path.exists(save_path):
            skipped += 1
            if skipped % 50 == 0:
                print(f"  ⊘ Skipped {skipped} existing photos...")
            continue
        
        print(f"\n[{i+1}/{len(players)}] {player_name} ({team})")
        
        # Get team data if not cached
        if team not in team_data_cache:
            if team not in TEAM_CLUB_URLS:
                print(f"  ⚠ Team '{team}' not in URL mapping")
                failed += 1
                continue
            
            print(f"  → Loading {team} player data...")
            team_data = get_team_player_data(team)
            team_data_cache[team] = team_data
            time.sleep(1)  # Rate limiting
        else:
            team_data = team_data_cache[team]
        
        if not team_data:
            print(f"  ✗ Could not load team player data")
            failed += 1
            continue
        
        # Find this player in the team data
        player_found = False
        for entry in team_data:
            player_obj = entry.get('player', {})
            first_name = player_obj.get('firstName', '').lower()
            surname = player_obj.get('surname', '').lower()
            full_name = f"{first_name} {surname}"
            
            if player_name.lower() in full_name or full_name in player_name.lower():
                player_id = entry.get('player', {}).get('id')
                provider_id = entry.get('player', {}).get('providerId', '').replace('CD_I', '')
                
                print(f"  ✓ Found: ID={player_id}, ProviderID={provider_id}")
                
                # Try different URL patterns
                urls = construct_image_url(player_id, provider_id, team)
                photo_downloaded = False
                
                for url in urls:
                    print(f"  → Trying: {url[:80]}...")
                    if download_image(url, save_path):
                        downloaded += 1
                        print(f"  ✓ Downloaded successfully")
                        photo_downloaded = True
                        player_found = True
                        break
                    time.sleep(0.5)
                
                if not photo_downloaded:
                    print(f"  ✗ Could not download from any URL pattern")
                    failed += 1
                
                break
        
        if not player_found:
            print(f"  ✗ Player not found in team data")
            failed += 1
        
        time.sleep(1)  # Rate limiting
    
    print(f"\n=== Summary ===")
    print(f"Downloaded: {downloaded}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")

def main():
    """Main function."""
    print("AFL Player Photo Scraper V2 (JSON Extraction)")
    print("="*60)
    
    ensure_directories()
    
    players = get_players_from_excel()
    if not players:
        return
    
    print("\nOptions:")
    print("1. Download first 5 players (test)")
    print("2. Download first 20 players")
    print("3. Download all players")
    
    choice = input("\nEnter your choice (1-3): ").strip()
    
    if choice == '1':
        download_player_photos(players, max_downloads=5)
    elif choice == '2':
        download_player_photos(players, max_downloads=20)
    elif choice == '3':
        download_player_photos(players)
    else:
        print("Invalid choice")

if __name__ == "__main__":
    main()
