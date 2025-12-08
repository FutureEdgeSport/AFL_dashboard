#!/usr/bin/env python3
"""
AFL Image Scraper
Downloads player photos and team logos from individual team club websites
"""

import os
import requests
from bs4 import BeautifulSoup
import time
import pandas as pd
from pathlib import Path
from urllib.parse import urljoin
import re

# Configuration
PLAYER_PHOTOS_DIR = "player_photos"
TEAM_LOGOS_DIR = "team_logos"
PLAYER_FILE = "AFL Player Ratings.xlsx"

# Team name mapping (consistent with your app)
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

# Team club website base URLs (where player pages are hosted)
TEAM_CLUB_URLS = {
    "Adelaide": "https://www.afc.com.au",
    "Brisbane": "https://www.lions.com.au",
    "Carlton": "https://www.carltonfc.com.au",
    "Collingwood": "https://www.collingwoodfc.com.au",
    "Essendon": "https://www.essendonfc.com.au",
    "Fremantle": "https://www.fremantlefc.com.au",
    "Geelong": "https://www.geelongcats.com.au",
    "Gold Coast": "https://www.goldcoastfc.com.au",
    "GWS": "https://www.gwsgiants.com.au",
    "Hawthorn": "https://www.hawthornfc.com.au",
    "Melbourne": "https://www.melbournefc.com.au",
    "North Melbourne": "https://www.nmfc.com.au",
    "Port Adelaide": "https://www.portadelaidefc.com.au",
    "Richmond": "https://www.richmondfc.com.au",
    "St Kilda": "https://www.saints.com.au",
    "Sydney": "https://www.sydneyswans.com.au",
    "West Coast": "https://www.westcoasteagles.com.au",
    "Western Bulldogs": "https://www.westernbulldogs.com.au",
}

# AFL.com.au team slugs (kept for potential fallback)
AFL_TEAM_SLUGS = {
    "Adelaide": "adelaide-crows",
    "Brisbane": "brisbane-lions",
    "Carlton": "carlton",
    "Collingwood": "collingwood",
    "Essendon": "essendon",
    "Fremantle": "fremantle",
    "Geelong": "geelong-cats",
    "Gold Coast": "gold-coast-suns",
    "GWS Giants": "greater-western-sydney",
    "Hawthorn": "hawthorn",
    "Melbourne": "melbourne",
    "North Melbourne": "north-melbourne",
    "Port Adelaide": "port-adelaide",
    "Richmond": "richmond",
    "St Kilda": "st-kilda",
    "Sydney": "sydney-swans",
    "West Coast": "west-coast-eagles",
    "Western Bulldogs": "western-bulldogs",
}


def ensure_directories():
    """Create directories if they don't exist."""
    Path(PLAYER_PHOTOS_DIR).mkdir(exist_ok=True)
    Path(TEAM_LOGOS_DIR).mkdir(exist_ok=True)
    print(f"✓ Directories ready: {PLAYER_PHOTOS_DIR}/ and {TEAM_LOGOS_DIR}/")


def download_image(url, save_path, headers=None):
    """Download an image from URL and save it."""
    try:
        if headers is None:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        with open(save_path, 'wb') as f:
            f.write(response.content)
        
        return True
    except Exception as e:
        print(f"  ✗ Error downloading {url}: {e}")
        return False


def normalize_player_name(name):
    """Normalize player name for file naming."""
    # Remove special characters, convert to lowercase, replace spaces with underscores
    name = re.sub(r'[^\w\s-]', '', name)
    name = name.strip().lower().replace(' ', '_').replace('-', '_')
    return name


def download_team_logos():
    """Download team logos from AFL.com.au or resources."""
    print("\n=== Downloading Team Logos ===")
    
    # AFL often uses consistent logo URLs
    base_logo_url = "https://resources.afl.com.au/photo-resources/2024/AFL/Clubs/"
    
    for team_name, team_code in TEAM_CODE_MAP.items():
        save_path = os.path.join(TEAM_LOGOS_DIR, f"{team_code}.png")
        
        # Skip if already exists
        if os.path.exists(save_path):
            print(f"  ⊘ {team_name}: Already exists")
            continue
        
        # Try different URL patterns
        urls_to_try = [
            f"{base_logo_url}{team_name.replace(' ', '-')}.png",
            f"{base_logo_url}{team_name.replace(' ', '')}.png",
            f"https://resources.afl.com.au/afl/photo/2024/{team_code.upper()}_logo.png",
            f"https://squiggle.com.au/img/{team_code}.png",  # Alternative source
        ]
        
        success = False
        for url in urls_to_try:
            print(f"  → Trying {team_name}: {url}")
            if download_image(url, save_path):
                print(f"  ✓ {team_name}: Downloaded successfully")
                success = True
                break
            time.sleep(0.5)  # Be polite
        
        if not success:
            print(f"  ✗ {team_name}: Could not download from any source")
        
        time.sleep(1)  # Rate limiting


def get_players_from_excel():
    """Load player list from Excel file."""
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        df = xl.parse("Summary")
        
        # Get unique players with their teams
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


def get_team_players_page(team_name):
    """Get the players list page URL for a team."""
    club_url = TEAM_CLUB_URLS.get(team_name)
    if not club_url:
        return None
    
    # Common patterns for player list pages
    possible_paths = [
        "/players",
        "/team/players",
        "/club/players",
        "/teams/players",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    for path in possible_paths:
        try:
            url = club_url + path
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return url
        except:
            continue
    
    return club_url  # Fallback to home page


def find_player_on_club_site(player_name, team_name):
    """Find a player's profile page on their club website."""
    club_url = TEAM_CLUB_URLS.get(team_name)
    if not club_url:
        return None
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    # Normalize player name for URL matching
    player_slug = player_name.lower().replace(' ', '-').replace('.', '').replace("'", '')
    
    # Try direct URL pattern (like https://www.afc.com.au/players/1079/jordan-dawson)
    # We don't know the ID, so we'll need to search the players page
    
    try:
        # Get the team's players page
        players_page_url = get_team_players_page(team_name)
        if not players_page_url:
            return None
        
        response = requests.get(players_page_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for links to player profiles
        player_links = soup.find_all('a', href=re.compile(r'/players?/'))
        
        for link in player_links:
            href = link.get('href', '')
            link_text = link.get_text(strip=True).lower()
            
            # Check if this link matches our player
            if player_slug in href.lower() or player_name.lower() in link_text:
                # Convert to absolute URL
                if not href.startswith('http'):
                    player_url = urljoin(club_url, href)
                else:
                    player_url = href
                return player_url
        
        return None
    
    except Exception as e:
        print(f"    ⚠ Error finding player: {e}")
        return None


def get_player_photo_from_page(player_url):
    """Extract player photo URL from their profile page."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(player_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # First priority: Look for AFL's static image server URLs (s.afl.com.au)
        all_imgs = soup.find_all('img')
        for img in all_imgs:
            src = img.get('src', '')
            # Check for AFL's ChampID images (official player photos)
            if 's.afl.com.au' in src and 'ChampIDImages' in src:
                if not src.startswith('http'):
                    src = urljoin(player_url, src)
                return src
        
        # Second priority: Look for player photo with various selectors
        img_selectors = [
            'img.player-photo',
            'img.player-image',
            'img.player-profile',
            'div.player-header img',
            'div.player-profile img',
            'div.player-image img',
            'img[alt*="player"]',
            'img[alt*="Player"]',
        ]
        
        for selector in img_selectors:
            imgs = soup.select(selector)
            for img in imgs:
                src = img.get('src', '')
                if src and ('player' in src.lower() or 'profile' in src.lower() or 'headshot' in src.lower()):
                    if not src.startswith('http'):
                        src = urljoin(player_url, src)
                    return src
        
        # Fallback: look for any reasonably large image that might be a player photo
        for img in all_imgs:
            src = img.get('src', '')
            # Skip logos, icons, and very small images
            if any(skip in src.lower() for skip in ['logo', 'icon', 'sponsor', 'banner']):
                continue
            if src and not src.endswith('.svg'):
                if not src.startswith('http'):
                    src = urljoin(player_url, src)
                return src
        
        return None
    
    except Exception as e:
        print(f"    ⚠ Error getting photo: {e}")
        return None


def search_afl_player(player_name, team_name):
    """Search for a player on their club website and get their photo URL."""
    # First, find the player's profile page
    print(f"    → Searching club website for {player_name}...")
    player_url = find_player_on_club_site(player_name, team_name)
    
    if not player_url:
        print(f"    ✗ Could not find player profile page")
        return None
    
    print(f"    → Found profile: {player_url}")
    
    # Then get the photo from that page
    photo_url = get_player_photo_from_page(player_url)
    
    if photo_url:
        print(f"    ✓ Found photo URL")
    else:
        print(f"    ✗ No photo found on profile page")
    
    return photo_url


def download_player_photos(players, max_downloads=None):
    """Download player photos."""
    print("\n=== Downloading Player Photos ===")
    
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
        
        # Search for player photo
        photo_url = search_afl_player(player_name, team)
        
        if photo_url:
            print(f"  → Found: {photo_url}")
            if download_image(photo_url, save_path):
                downloaded += 1
                print(f"  ✓ Downloaded successfully")
            else:
                failed += 1
        else:
            failed += 1
            print(f"  ✗ Could not find photo URL")
        
        # Rate limiting - be respectful
        time.sleep(2)
    
    print(f"\n{'='*50}")
    print(f"Summary:")
    print(f"  Downloaded: {downloaded}")
    print(f"  Skipped (already exist): {skipped}")
    print(f"  Failed: {failed}")
    print(f"{'='*50}")


def main():
    """Main execution."""
    print("=" * 60)
    print("AFL Image Scraper")
    print("=" * 60)
    
    ensure_directories()
    
    # Download team logos first
    print("\nDo you want to download team logos? (y/n): ", end="")
    if input().lower().strip() == 'y':
        download_team_logos()
    
    # Download player photos
    print("\nDo you want to download player photos? (y/n): ", end="")
    if input().lower().strip() == 'y':
        players = get_players_from_excel()
        
        if players:
            print("\nOptions:")
            print("1. Download all player photos")
            print("2. Download a limited number (for testing)")
            print("3. Skip")
            
            choice = input("\nEnter choice (1-3): ").strip()
            
            if choice == '1':
                download_player_photos(players)
            elif choice == '2':
                max_num = input("How many photos to download? (e.g., 10): ").strip()
                try:
                    max_num = int(max_num)
                    download_player_photos(players, max_downloads=max_num)
                except ValueError:
                    print("Invalid number. Skipping.")
    
    print("\n✓ Script completed!")
    print(f"\nImages saved to:")
    print(f"  - Team logos: {TEAM_LOGOS_DIR}/")
    print(f"  - Player photos: {PLAYER_PHOTOS_DIR}/")


if __name__ == "__main__":
    main()
