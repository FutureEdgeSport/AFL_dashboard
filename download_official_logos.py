#!/usr/bin/env python3
"""
Download official AFL team logos from reliable sources
"""

import requests
import os
import time

TEAM_LOGOS_DIR = "team_logos"
os.makedirs(TEAM_LOGOS_DIR, exist_ok=True)

# Official team logo URLs - using direct logo image URLs
# Fallback to previously scraped logos if download fails
TEAM_LOGO_URLS = {
    "afc": [
        "https://resources.afc.com.au/photo-resources/2024/11/12/19f539d5-2bdc-48fa-882a-736a70fc27df/AFC-new-logo-1000x1000.png?width=400",
    ],
    "lions": [
        "https://resources.lions.com.au/photo-resources/2023/10/31/452943e5-cbfc-45c9-8ff3-c4c3e8abe3d0/ZGZyYjBr.png?width=400",
    ],
    "cfc": [
        "https://resources.carltonfc.com.au/photo-resources/2019/12/13/a7335b96-0cea-467f-9981-6cce85b06804/Monogram_Holding.png?width=400",
    ],
    "cofc": [
        "https://resources.collingwoodfc.com.au/photo-resources/2019/12/05/5e56e74c-54ec-49ad-a68a-a1bad9e95bd0/L1lKU5Zw.png?width=400",
    ],
    "efc": [
        "https://resources.essendonfc.com.au/photo-resources/2025/10/31/0a0ea13f-bed5-4309-9479-3bbe4b96aa65/EFC-Stacked-Black.png?width=400",
    ],
    "ffc": [
        "https://resources.fremantlefc.com.au/photo-resources/2019/11/26/111ac8fd-0c4e-4ce4-81e7-b7e7a9a77e17/2zlxJYFN.png?width=400",
    ],
    "gfc": [
        "https://resources.geelongcats.com.au/photo-resources/2020/05/20/04395772-e2a4-4dd1-96ce-83c7dcf25a5f/UiUm5bXe.png?width=400",
    ],
    "gcfc": [
        "https://resources.goldcoastfc.com.au/photo-resources/2025/07/15/86370e32-dbe0-47ed-9eae-f5ffea0c9ffd/P1cRtPnp.png?width=400",
    ],
    "gws": [
        "https://resources.gwsgiants.com.au/photo-resources/2019/12/05/23c36f03-eda8-455f-b0e9-50bdd4b71d7d/2zB68CTE.png?width=400",
    ],
    "hfc": [
        "https://resources.hawthornfc.com.au/photo-resources/2019/12/02/7018d537-1bb3-4090-a6e1-a645842a8808/cpawuHeu.png?width=400",
    ],
    "mfc": [
        "https://resources.afl.com.au/photo-resources/2019/12/05/9afccce2-87db-4a20-abcc-e97ac9266a92/w1AVeAQu.png?width=400",
    ],
    "nmfc": [
        "https://resources.nmfc.com.au/photo-resources/2023/11/15/22dc3344-b935-45aa-9ca6-bbcfff3cf992/OuXZLUci.png?width=400",
    ],
    "pafc": [
        "https://resources.portadelaidefc.com.au/photo-resources/2020/03/13/c975125f-d2cd-41d1-897f-7ca06c821769/vQlMUKhT.png?width=400",
    ],
    "rfc": [
        "https://resources.richmondfc.com.au/photo-resources/2023/10/18/c1c2a824-0733-4daf-875d-8dc4d5a22e53/vZj6rOmk.png?width=400",
    ],
    "skfc": [
        "https://resources.saints.com.au/photo-resources/2025/08/05/6307b480-ef71-417b-b721-3e3df0937ebb/V1YpYGl7.png?width=400",
    ],
    "sfc": [
        "https://resources.sydneyswans.com.au/photo-resources/2025/09/26/020ed9bc-fbd7-4564-badd-63f39dfdd48e/1zMdWpVE.png?width=400",
    ],
    "wcfc": [
        "https://resources.westcoasteagles.com.au/photo-resources/2019/12/05/51f71efa-d5b5-42c6-91b8-dd82e46f0d61/oC8UxMNY.png?width=400",
    ],
    "wbfc": [
        "https://resources.westernbulldogs.com.au/photo-resources/2020/05/29/84c48939-5ef7-4d6a-af26-1321edf99430/Western-Bulldogs-Logo-268X268px.jpg?width=400",
    ],
}

TEAM_NAMES = {
    "afc": "Adelaide Crows",
    "lions": "Brisbane Lions",
    "cfc": "Carlton Blues",
    "cofc": "Collingwood Magpies",
    "efc": "Essendon Bombers",
    "ffc": "Fremantle Dockers",
    "gfc": "Geelong Cats",
    "gcfc": "Gold Coast Suns",
    "gws": "GWS Giants",
    "hfc": "Hawthorn Hawks",
    "mfc": "Melbourne Demons",
    "nmfc": "North Melbourne Kangaroos",
    "pafc": "Port Adelaide Power",
    "rfc": "Richmond Tigers",
    "skfc": "St Kilda Saints",
    "sfc": "Sydney Swans",
    "wcfc": "West Coast Eagles",
    "wbfc": "Western Bulldogs",
}

print("Downloading official AFL team logos...")
print("="*70)

success_count = 0
for team_code, urls in TEAM_LOGO_URLS.items():
    team_name = TEAM_NAMES[team_code]
    print(f"\n{team_name} ({team_code}):")
    
    downloaded = False
    for i, url in enumerate(urls):
        try:
            print(f"  → {url[:65]}...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200 and len(response.content) > 1000:  # Ensure it's not an error page
                save_path = os.path.join(TEAM_LOGOS_DIR, f"{team_code}.png")
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ Downloaded ({len(response.content)} bytes)")
                downloaded = True
                success_count += 1
                break
            else:
                print(f"  ✗ Failed (HTTP {response.status_code}, size: {len(response.content)} bytes)")
        except Exception as e:
            print(f"  ✗ Error: {str(e)[:50]}")
    
    if not downloaded:
        print(f"  ⚠ Could not download logo for {team_name}")
    
    time.sleep(0.2)

print("\n" + "="*70)
print(f"✓ Successfully downloaded {success_count}/18 team logos")
print(f"Logos saved to: {TEAM_LOGOS_DIR}/")
