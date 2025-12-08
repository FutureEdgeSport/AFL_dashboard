#!/usr/bin/env python3
"""
Scrape team logos directly from club websites
"""

import requests
import re
import os
import time

TEAM_LOGOS_DIR = "team_logos"
os.makedirs(TEAM_LOGOS_DIR, exist_ok=True)

# Club websites to scrape logos from
CLUB_SITES = {
    "afc": "https://www.afc.com.au",
    "lions": "https://www.lions.com.au",
    "cfc": "https://www.carltonfc.com.au",
    "cofc": "https://www.collingwoodfc.com.au",
    "efc": "https://www.essendonfc.com.au",
    "ffc": "https://www.fremantlefc.com.au",
    "gfc": "https://www.geelongcats.com.au",
    "gcfc": "https://www.goldcoastfc.com.au",
    "gws": "https://www.gwsgiants.com.au",
    "hfc": "https://www.hawthornfc.com.au",
    "mfc": "https://www.melbournefc.com.au",
    "nmfc": "https://www.nmfc.com.au",
    "pafc": "https://www.portadelaidefc.com.au",
    "rfc": "https://www.richmondfc.com.au",
    "skfc": "https://www.saints.com.au",
    "sfc": "https://www.sydneyswans.com.au",
    "wcfc": "https://www.westcoasteagles.com.au",
    "wbfc": "https://www.westernbulldogs.com.au",
}

def find_logo_url(html):
    """Extract high-quality logo URL from HTML"""
    # Look for logo PNG URLs with dimensions
    patterns = [
        r'https://resources\.[^/]+\.com\.au/[^"\']*logo[^"\']*\.png\?[^"\']*width=\d+',
        r'https://resources\.[^/]+\.com\.au/[^"\']*logo[^"\']*\.png',
        r'https://[^"\']*staticfile[^"\']*logo[^"\']*\.png',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            # Return first match, add width if not present
            url = matches[0]
            if '?' not in url:
                url += '?width=500'
            elif 'width=' not in url:
                url += '&width=500'
            return url
    
    return None

print("Scraping team logos from club websites...")
print("="*60)

for team_code, club_url in CLUB_SITES.items():
    try:
        print(f"\n{team_code}: Fetching {club_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(club_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            logo_url = find_logo_url(response.text)
            
            if logo_url:
                print(f"  Found logo: {logo_url[:80]}...")
                
                # Download logo
                logo_response = requests.get(logo_url, headers=headers, timeout=10)
                if logo_response.status_code == 200:
                    save_path = os.path.join(TEAM_LOGOS_DIR, f"{team_code}.png")
                    with open(save_path, 'wb') as f:
                        f.write(logo_response.content)
                    print(f"  ✓ Downloaded to {save_path}")
                else:
                    print(f"  ✗ Failed to download logo: HTTP {logo_response.status_code}")
            else:
                print(f"  ✗ No logo URL found in HTML")
        else:
            print(f"  ✗ Failed to fetch website: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"  ✗ Error: {str(e)}")
    
    time.sleep(0.5)

print("\n" + "="*60)
print("✓ Logo scraping complete!")
