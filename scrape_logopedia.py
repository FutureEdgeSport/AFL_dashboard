import requests
from bs4 import BeautifulSoup
import re
import os
import time
from PIL import Image
from io import BytesIO

# Team name mapping to standardized codes
TEAM_MAPPING = {
    'Adelaide Crows': 'afc',
    'Adelaide Football Club': 'afc',
    'Brisbane Lions': 'lions',
    'Carlton Blues': 'cfc',
    'Carlton Football Club': 'cfc',
    'Collingwood Magpies': 'cofc',
    'Collingwood Football Club': 'cofc',
    'Essendon Bombers': 'efc',
    'Essendon Football Club': 'efc',
    'Fremantle Dockers': 'ffc',
    'Fremantle Football Club': 'ffc',
    'Geelong Cats': 'gfc',
    'Geelong Football Club': 'gfc',
    'Gold Coast Suns': 'gcfc',
    'Gold Coast Football Club': 'gcfc',
    'Greater Western Sydney Giants': 'gws',
    'GWS Giants': 'gws',
    'Hawthorn Hawks': 'hfc',
    'Hawthorn Football Club': 'hfc',
    'Melbourne Demons': 'mfc',
    'Melbourne Football Club': 'mfc',
    'North Melbourne Kangaroos': 'nmfc',
    'North Melbourne Football Club': 'nmfc',
    'Port Adelaide Power': 'pafc',
    'Port Adelaide Football Club': 'pafc',
    'Richmond Tigers': 'rfc',
    'Richmond Football Club': 'rfc',
    'St Kilda Saints': 'skfc',
    'St. Kilda Football Club': 'skfc',
    'St Kilda': 'skfc',
    'Sydney Swans': 'sfc',
    'Sydney Football Club': 'sfc',
    'West Coast Eagles': 'wcfc',
    'West Coast Football Club': 'wcfc',
    'Western Bulldogs': 'wbfc',
    'Footscray Football Club': 'wbfc',
}

def scrape_logopedia_logos():
    """Scrape AFL team logos from Logopedia"""
    url = "https://logos.fandom.com/wiki/Logopedia:Theme/Logos_of_Australian_Football_League_teams"
    
    print(f"Fetching page: {url}")
    response = requests.get(url)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.content, 'html.parser')
    
    team_logos = {}
    
    # Find all images on the page
    images = soup.find_all('img')
    
    for img in images:
        alt = img.get('alt', '')
        src = img.get('src', '')
        data_src = img.get('data-src', '')
        
        # Use data-src if available (for lazy-loaded images), otherwise src
        img_url = data_src if data_src else src
        
        # Skip if no URL or it's a placeholder
        if not img_url or 'data:image' in img_url:
            continue
        
        # Check if this is a team logo based on alt text
        team_code = None
        team_name = alt
        
        # Try direct mapping first
        if alt in TEAM_MAPPING:
            team_code = TEAM_MAPPING[alt]
        else:
            # Try partial match
            for tm_name, code in TEAM_MAPPING.items():
                if tm_name in alt or alt in tm_name:
                    team_code = code
                    break
        
        if team_code:
            # Convert to full-size URL by removing scale-to-width-down parameter
            if '/revision/latest/scale-to-width-down/' in img_url:
                # Replace with a larger size or remove scaling
                img_url = img_url.replace('/scale-to-width-down/115', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/104', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/113', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/106', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/120', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/105', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/110', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/111', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/93', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/108', '/scale-to-width-down/500')
                img_url = img_url.replace('/scale-to-width-down/107', '/scale-to-width-down/500')
            
            # Make sure URL is absolute
            if img_url.startswith('//'):
                img_url = 'https:' + img_url
            
            if team_code not in team_logos:
                team_logos[team_code] = {
                    'name': team_name,
                    'url': img_url
                }
                print(f"Found {team_name} ({team_code}): {img_url}")
    
    return team_logos

def download_logos(team_logos, output_dir='team_logos'):
    """Download the logos and convert to PNG"""
    os.makedirs(output_dir, exist_ok=True)
    
    success_count = 0
    for team_code, info in team_logos.items():
        img_url = info['url']
        team_name = info['name']
        
        # Handle relative URLs
        if img_url.startswith('//'):
            img_url = 'https:' + img_url
        elif img_url.startswith('/'):
            img_url = 'https://logos.fandom.com' + img_url
        
        output_path = os.path.join(output_dir, f"{team_code}.png")
        
        try:
            print(f"Downloading {team_name} ({team_code})...")
            response = requests.get(img_url, stream=True)
            response.raise_for_status()
            
            # Open image with PIL and convert to PNG
            img = Image.open(BytesIO(response.content))
            
            # Convert to RGBA if not already
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Save as proper PNG
            img.save(output_path, 'PNG', optimize=True)
            
            print(f"✓ Saved to {output_path}")
            success_count += 1
            time.sleep(0.5)
            
        except Exception as e:
            print(f"✗ Error downloading {team_name}: {e}")
    
    print(f"\n{'='*50}")
    print(f"Downloaded {success_count}/{len(team_logos)} logos")
    print(f"{'='*50}")

if __name__ == '__main__':
    team_logos = scrape_logopedia_logos()
    
    print(f"\n{'='*50}")
    print(f"Found {len(team_logos)} team logos")
    print(f"{'='*50}\n")
    
    if team_logos:
        download_logos(team_logos)
    else:
        print("No logos found. The page structure may have changed.")
