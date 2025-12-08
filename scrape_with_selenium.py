#!/usr/bin/env python3
"""
AFL Image Scraper using Selenium for JavaScript-rendered content
"""

import os
import requests
import time
import pandas as pd
from pathlib import Path
from urllib.parse import urljoin
import re

# Try importing selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠ Selenium not installed. Install with: pip install selenium")

# Configuration
PLAYER_PHOTOS_DIR = "player_photos"
TEAM_LOGOS_DIR = "team_logos"
PLAYER_FILE = "AFL Player Ratings.xlsx"

# Team club website base URLs
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
    "GWS Giants": "https://www.gwsgiants.com.au",
    "Greater Western Sydney": "https://www.gwsgiants.com.au",
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
        print(f"    ⚠ Download error: {e}")
        return False

def setup_driver():
    """Setup Selenium WebDriver with Chrome."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"✗ Error setting up Chrome driver: {e}")
        print("  Make sure Chrome and ChromeDriver are installed")
        return None

def find_player_page_with_selenium(driver, player_name, team_name):
    """Find player's page URL using Selenium."""
    club_url = TEAM_CLUB_URLS.get(team_name)
    if not club_url:
        return None
    
    try:
        # Normalize player name for matching
        player_slug = player_name.lower().replace(' ', '-').replace('.', '').replace("'", '')
        player_parts = player_name.lower().split()
        
        # Try different players page URLs
        possible_urls = [
            f"{club_url}/players",
            f"{club_url}/team/players",
            f"{club_url}/club/players",
        ]
        
        for players_url in possible_urls:
            try:
                driver.get(players_url)
                time.sleep(3)  # Wait for page to load and JavaScript to execute
                
                # Scroll down to load lazy-loaded content
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Find all links
                links = driver.find_elements(By.TAG_NAME, 'a')
                
                for link in links:
                    href = link.get_attribute('href')
                    text = link.text.lower().strip()
                    
                    if not href or '/player' not in href.lower():
                        continue
                    
                    # Check if this link matches our player
                    # Match by URL slug
                    if player_slug in href.lower():
                        return href
                    
                    # Match by link text (full name or parts)
                    if player_name.lower() in text:
                        return href
                    
                    # Match by first and last name in text
                    if len(player_parts) >= 2:
                        if player_parts[0] in text and player_parts[-1] in text:
                            return href
                
            except Exception as e:
                continue
        
        return None
    except Exception as e:
        print(f"    ⚠ Error finding player page: {e}")
        return None

def get_photo_from_page_with_selenium(driver, player_url):
    """Extract player photo from page using Selenium."""
    try:
        driver.get(player_url)
        time.sleep(4)  # Wait for JavaScript to load images
        
        # Scroll to load any lazy images
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(1)
        
        # Priority 1: AFL's official ChampID images
        images = driver.find_elements(By.TAG_NAME, 'img')
        for img in images:
            src = img.get_attribute('src')
            if src and 's.afl.com.au' in src and 'ChampIDImages' in src:
                return src
        
        # Priority 2: Look in common player photo containers
        photo_selectors = [
            'div.player-image img',
            'div.player-photo img',
            'div.player-header img',
            'div.player-profile img',
            '.player-image img',
            '.player-photo img',
            '.player-header img',
        ]
        
        for selector in photo_selectors:
            try:
                imgs = driver.find_elements(By.CSS_SELECTOR, selector)
                for img in imgs:
                    src = img.get_attribute('src')
                    if src and not any(skip in src.lower() for skip in ['logo', 'icon', 'sponsor', 'banner', 'watermark']):
                        if any(keyword in src.lower() for keyword in ['player', 'profile', 'headshot', 'photo']):
                            return src
            except:
                continue
        
        # Priority 3: Any reasonable image on the page
        for img in images:
            src = img.get_attribute('src')
            alt = img.get_attribute('alt') or ''
            
            # Skip obvious non-player images
            if not src or any(skip in src.lower() for skip in ['logo', 'icon', 'sponsor', 'banner', 'watermark', 'badge', '.svg']):
                continue
            
            # Accept images with player-related keywords
            if any(keyword in (src + alt).lower() for keyword in ['player', 'profile', 'headshot', 'photo']):
                return src
        
        # Priority 4: Largest image (likely to be player photo)
        largest_img = None
        largest_size = 0
        
        for img in images:
            try:
                width = img.get_attribute('width')
                height = img.get_attribute('height')
                src = img.get_attribute('src')
                
                if not src or any(skip in src.lower() for skip in ['logo', 'icon', 'sponsor', '.svg']):
                    continue
                
                if width and height:
                    size = int(width) * int(height)
                    if size > largest_size:
                        largest_size = size
                        largest_img = src
            except:
                continue
        
        if largest_img and largest_size > 10000:  # Reasonable size threshold
            return largest_img
        
        return None
    except Exception as e:
        print(f"    ⚠ Error getting photo: {e}")
        return None

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

def download_player_photos_with_selenium(players, max_downloads=None):
    """Download player photos using Selenium."""
    if not SELENIUM_AVAILABLE:
        print("✗ Selenium is required for this scraper")
        return
    
    print("\n=== Downloading Player Photos with Selenium ===")
    
    driver = setup_driver()
    if not driver:
        return
    
    try:
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
            
            # Check if team is supported
            if team not in TEAM_CLUB_URLS:
                print(f"  ⚠ Team '{team}' not found in URL mapping")
                failed += 1
                continue
            
            # Find player page
            print(f"  → Searching {TEAM_CLUB_URLS[team]}...")
            player_url = find_player_page_with_selenium(driver, player_name, team)
            
            if not player_url:
                print(f"  ✗ Could not find player page")
                failed += 1
                continue
            
            print(f"  ✓ Found: {player_url}")
            
            # Get photo from page
            photo_url = get_photo_from_page_with_selenium(driver, player_url)
            
            if photo_url:
                print(f"  → Photo: {photo_url[:80]}...")
                if download_image(photo_url, save_path):
                    downloaded += 1
                    print(f"  ✓ Downloaded successfully")
                else:
                    failed += 1
                    print(f"  ✗ Download failed")
            else:
                failed += 1
                print(f"  ✗ No photo found on page")
            
            time.sleep(2)  # Rate limiting
        
        print(f"\n=== Summary ===")
        print(f"Downloaded: {downloaded}")
        print(f"Skipped: {skipped}")
        print(f"Failed: {failed}")
        
    finally:
        driver.quit()

def main():
    """Main function."""
    print("AFL Player Photo Scraper (Selenium Version)")
    print("="*60)
    
    ensure_directories()
    
    if not SELENIUM_AVAILABLE:
        print("\n✗ Selenium is not installed")
        print("  Install with: pip install selenium")
        print("  Also install ChromeDriver from: https://chromedriver.chromium.org/")
        return
    
    players = get_players_from_excel()
    if not players:
        return
    
    print("\nOptions:")
    print("1. Download first 5 players (test)")
    print("2. Download first 20 players")
    print("3. Download all players")
    
    choice = input("\nEnter your choice (1-3): ").strip()
    
    if choice == '1':
        download_player_photos_with_selenium(players, max_downloads=5)
    elif choice == '2':
        download_player_photos_with_selenium(players, max_downloads=20)
    elif choice == '3':
        download_player_photos_with_selenium(players)
    else:
        print("Invalid choice")

if __name__ == "__main__":
    main()
