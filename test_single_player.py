#!/usr/bin/env python3
"""
Test scraper with a single known player
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import json

def test_jordan_dawson():
    url = "https://www.afc.com.au/players/1079/jordan-dawson"
    
    print(f"Testing: {url}")
    print("="*60)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status code: {response.status_code}")
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        content = response.text
        
        # Look for player ID in the page
        print("\nSearching for player ID patterns...")
        
        # Pattern 1: Look for ChampID in scripts
        champ_id_match = re.search(r'champId["\']?\s*:\s*["\']?(\d+)', content, re.IGNORECASE)
        if champ_id_match:
            champ_id = champ_id_match.group(1)
            print(f"  ✓ Found ChampID in script: {champ_id}")
            
            # Try to construct the image URL
            # Pattern from your example: 2026014/992242.png where 992242 might be the ID
            year = 2026
            photo_url = f"https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/{year}{champ_id}/{champ_id}.png"
            print(f"  → Constructed URL: {photo_url}")
            return photo_url
        
        # Pattern 2: Look for any player ID references
        player_id_patterns = [
            r'playerId["\']?\s*:\s*["\']?(\d+)',
            r'player[_-]?id["\']?\s*:\s*["\']?(\d+)',
            r'/players/(\d+)/',
            r'data-player-id["\']?\s*=\s*["\']?(\d+)',
        ]
        
        for pattern in player_id_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                player_id = match.group(1)
                print(f"  ✓ Found player ID: {player_id} (pattern: {pattern})")
        
        # Look for all images
        all_imgs = soup.find_all('img')
        print(f"\nFound {len(all_imgs)} total images")
        
        print("\nSearching for AFL ChampID images in img tags:")
        for idx, img in enumerate(all_imgs):
            src = img.get('src', '')
            if 's.afl.com.au' in src and 'ChampIDImages' in src:
                print(f"  ✓ FOUND: {src}")
                return src
        
        # Check if there's any reference to s.afl.com.au in the page source
        print("\nSearching for s.afl.com.au references in page source:")
        afl_static_matches = re.findall(r'https?://s\.afl\.com\.au[^"\s<>]+', content)
        if afl_static_matches:
            for match in afl_static_matches[:5]:
                print(f"  → {match}")
        
        print("\nAll image sources:")
        for idx, img in enumerate(all_imgs[:10]):  # Show first 10
            src = img.get('src', '')
            alt = img.get('alt', 'N/A')
            print(f"  {idx+1}. alt='{alt[:40]}' src='{src[:100]}'")
        
    return None

if __name__ == "__main__":
    photo_url = test_jordan_dawson()
    if photo_url:
        print(f"\n✓ SUCCESS! Photo URL: {photo_url}")
    else:
        print(f"\n✗ Could not find photo")
