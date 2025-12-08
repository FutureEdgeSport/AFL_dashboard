#!/usr/bin/env python3
"""
Quick team logo downloader
"""

import requests
import os
import time

TEAM_LOGOS_DIR = "team_logos"
os.makedirs(TEAM_LOGOS_DIR, exist_ok=True)

# Team logo URLs - using simple approach
TEAM_LOGOS = {
    "afc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Adelaide-logo.png",
    "lions": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Brisbane-logo.png",
    "cfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Carlton-logo.png",
    "cofc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Collingwood-logo.png",
    "efc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Essendon-logo.png",
    "ffc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Fremantle-logo.png",
    "gfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Geelong-logo.png",
    "gcfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/GoldCoast-logo.png",
    "gws": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/GWS-logo.png",
    "hfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Hawthorn-logo.png",
    "mfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Melbourne-logo.png",
    "nmfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/NorthMelbourne-logo.png",
    "pafc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/PortAdelaide-logo.png",
    "rfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Richmond-logo.png",
    "skfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/StKilda-logo.png",
    "sfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/Sydney-logo.png",
    "wcfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/WestCoast-logo.png",
    "wbfc": "https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Clubs/Logos/WesternBulldogs-logo.png",
}

print("Downloading team logos...")
print("="*60)

for team_code, url in TEAM_LOGOS.items():
    save_path = os.path.join(TEAM_LOGOS_DIR, f"{team_code}.png")
    
    try:
        print(f"  → {team_code}: {url[:50]}...")
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        response = requests.get(url, timeout=10, headers=headers)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            print(f"  ✓ {team_code}: Downloaded successfully")
        else:
            print(f"  ✗ {team_code}: HTTP {response.status_code}")
    except Exception as e:
        print(f"  ✗ {team_code}: {str(e)}")
    
    time.sleep(0.3)

print("\n✓ Team logo download complete!")
