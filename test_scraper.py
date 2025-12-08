#!/usr/bin/env python3
"""
Test scraper to diagnose AFL.com.au structure
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd

# Test with a known player
def test_player_search(player_name, team_name):
    print(f"\n{'='*60}")
    print(f"Testing: {player_name} ({team_name})")
    print('='*60)
    
    # Try direct player page URL patterns
    team_slugs = {
        "Adelaide": "adelaide-crows",
        "Brisbane": "brisbane-lions",
        "Carlton": "carlton",
        "Collingwood": "collingwood",
        "Essendon": "essendon",
        "Fremantle": "fremantle",
        "Geelong": "geelong-cats",
        "Gold Coast": "gold-coast-suns",
        "GWS": "gws-giants",
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
    
    # Normalize player name for URL
    name_normalized = player_name.lower().replace(' ', '-').replace('.', '').replace("'", '')
    team_slug = team_slugs.get(team_name, team_name.lower().replace(' ', '-'))
    
    # Try different URL patterns
    url_patterns = [
        f"https://www.afl.com.au/{team_slug}/players/profile/{name_normalized}",
        f"https://www.afl.com.au/players/{name_normalized}",
        f"https://www.afl.com.au/afl/players/{name_normalized}",
    ]
    
    for url in url_patterns:
        print(f"\nTrying: {url}")
        try:
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            print(f"Status code: {response.status_code}")
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for images
                img_selectors = [
                    'img.player-photo',
                    'img.player-image',
                    'img[alt*="player"]',
                    'div.player-profile img',
                    'img[src*="player"]',
                ]
                
                print("\nSearching for player images...")
                for selector in img_selectors:
                    imgs = soup.select(selector)
                    if imgs:
                        print(f"  Found {len(imgs)} image(s) with selector: {selector}")
                        for idx, img in enumerate(imgs[:3]):  # Show first 3
                            print(f"    {idx+1}. src={img.get('src', 'N/A')[:100]}")
                
                # Show all img tags
                all_imgs = soup.find_all('img')
                print(f"\nTotal img tags found: {len(all_imgs)}")
                if all_imgs:
                    print("First 5 image sources:")
                    for idx, img in enumerate(all_imgs[:5]):
                        src = img.get('src', 'N/A')
                        alt = img.get('alt', 'N/A')
                        print(f"  {idx+1}. alt='{alt[:50]}' src='{src[:80]}'")
                
                # Show page title
                title = soup.find('title')
                if title:
                    print(f"\nPage title: {title.text.strip()}")
                
                return True
                
        except Exception as e:
            print(f"Error: {str(e)}")
    
    return False

# Load some test players
def main():
    print("AFL Player Photo Scraper - Diagnostic Mode")
    print("="*60)
    
    # Try to load a few players from Excel
    try:
        df = pd.read_excel("AFL Player Ratings.xlsx", sheet_name="Summary")
        print(f"\nLoaded {len(df)} players from Excel")
        
        # Test with first 3 players
        for idx, row in df.head(3).iterrows():
            player = row.get("Player", "")
            team = row.get("Team", "")
            if pd.notna(player) and pd.notna(team):
                test_player_search(str(player).strip(), str(team).strip())
                
    except Exception as e:
        print(f"Error loading Excel: {e}")
        print("\nTrying with sample players...")
        # Test with known players
        test_players = [
            ("Marcus Bontempelli", "Western Bulldogs"),
            ("Patrick Cripps", "Carlton"),
            ("Max Gawn", "Melbourne"),
        ]
        for player, team in test_players:
            test_player_search(player, team)

if __name__ == "__main__":
    main()
