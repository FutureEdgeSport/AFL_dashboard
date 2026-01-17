#!/usr/bin/env python3
"""
Quick script to download St Kilda player photos from AFL's image servers
"""

import requests
import pandas as pd
import os
import time
from pathlib import Path

# Read the player guide
guide = pd.read_csv('player_photo_guide.csv')
st_kilda_players = guide[guide['Team'] == 'St Kilda']

print(f"Found {len(st_kilda_players)} St Kilda players in guide\n")

# Ensure directory exists
Path('player_photos').mkdir(exist_ok=True)

downloaded = 0
already_exist = 0
failed = 0

for _, row in st_kilda_players.iterrows():
    player_name = row['Player']
    filename = row['Filename']
    filepath = f'player_photos/{filename}'
    
    # Skip if already exists
    if os.path.exists(filepath):
        print(f"  - {player_name} already exists")
        already_exist += 1
        continue
    
    # Try different AFL image URL patterns
    # Convert name to URL format: "Jack Steele" -> "jack-steele"
    url_name = player_name.lower().replace(' ', '-')
    
    patterns = [
        # AFL's official player headshots (most reliable)
        f'https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/240x240/{url_name}.png',
        f'https://s.afl.com.au/staticfile/AFL%20Tenant/StKilda/Players/2025%20-%20Verticals/{url_name}.png',
        # Fallback patterns
        f'https://resources.afl.com.au/photo/2024/{url_name}.png',
    ]
    
    success = False
    for img_url in patterns:
        try:
            print(f"  Trying {player_name}... ", end='')
            response = requests.get(img_url, timeout=10)
            
            # Check if we got a valid image (not a 404 page)
            if response.status_code == 200 and len(response.content) > 1000:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                print(f"✓ Downloaded from {img_url.split('/')[-2]}/")
                downloaded += 1
                success = True
                time.sleep(0.3)
                break
            else:
                print(f"✗ (status {response.status_code})")
        except Exception as e:
            print(f"✗ ({str(e)[:30]})")
            continue
    
    if not success:
        print(f"  ✗ Could not find {player_name} from any source")
        failed += 1

print(f"\n{'='*60}")
print(f"Summary:")
print(f"  Downloaded: {downloaded}")
print(f"  Already existed: {already_exist}")
print(f"  Failed: {failed}")
print(f"{'='*60}")

if failed > 0:
    print(f"\nNote: {failed} photos could not be found automatically.")
    print("You can manually download these from https://www.saints.com.au/afl/squad")
