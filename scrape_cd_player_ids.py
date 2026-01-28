#!/usr/bin/env python3
"""
Champion Data Player ID Scraper
===============================
Scrapes Champion Data player IDs from AFL team websites and creates
a mapping file for all players.

Usage:
    python scrape_cd_player_ids.py
    
Output:
    champion_data_player_ids.xlsx - Mapping of player names to CD IDs
"""

import re
import json
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime

# Team website URLs - these contain embedded JSON with providerId
TEAM_URLS = {
    'Adelaide': 'https://www.afc.com.au/players',
    'Brisbane Lions': 'https://www.lions.com.au/players',
    'Carlton': 'https://www.carltonfc.com.au/players',
    'Collingwood': 'https://www.collingwoodfc.com.au/players',
    'Essendon': 'https://www.essendonfc.com.au/players',
    'Fremantle': 'https://www.fremantlefc.com.au/players',
    'Geelong': 'https://www.geelongcats.com.au/players',
    'Gold Coast': 'https://www.goldcoastfc.com.au/players',
    'GWS Giants': 'https://www.gwsgiants.com.au/players',
    'Hawthorn': 'https://www.hawthornfc.com.au/players',
    'Melbourne': 'https://www.melbournefc.com.au/players',
    'North Melbourne': 'https://www.nmfc.com.au/players',
    'Port Adelaide': 'https://www.portadelaidefc.com.au/players',
    'Richmond': 'https://www.richmondfc.com.au/players',
    'St Kilda': 'https://www.saints.com.au/players',
    'Sydney': 'https://www.sydneyswans.com.au/players',
    'West Coast': 'https://www.westcoasteagles.com.au/players',
    'Western Bulldogs': 'https://www.westernbulldogs.com.au/players',
}

def get_players_from_team_page(team_name, url):
    """Extract player data from team website."""
    players = []
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"    ⚠️ HTTP {response.status_code}")
            return players
        
        content = response.text
        
        # Method 1: Look for JSON player data in the page
        # Pattern: JSON.stringify([{...player data...}])
        json_match = re.search(r'JSON\.stringify\(\s*(\[.*?\])\s*\)', content, re.DOTALL)
        if json_match:
            try:
                player_list = json.loads(json_match.group(1))
                for item in player_list:
                    player = item.get('player', {})
                    provider_id = player.get('providerId', '')
                    cd_id = ''
                    if provider_id and 'CD_I' in provider_id:
                        cd_id = provider_id.replace('CD_I', '')
                    
                    players.append({
                        'team': team_name,
                        'first_name': player.get('firstName', ''),
                        'surname': player.get('surname', ''),
                        'full_name': f"{player.get('firstName', '')} {player.get('surname', '')}".strip(),
                        'jumper_number': item.get('jumperNumber', ''),
                        'champion_data_id': cd_id,
                        'provider_id_raw': provider_id,
                    })
                return players
            except json.JSONDecodeError:
                pass
        
        # Method 2: Look for providerId patterns directly in HTML/JS
        # Pattern: "providerId":"CD_I1002264","firstName":"Hunter","surname":"Clark"
        provider_matches = re.findall(
            r'"providerId":"(CD_I\d+)"[^}]*?"firstName":"([^"]+)"[^}]*?"surname":"([^"]+)"',
            content
        )
        if provider_matches:
            seen = set()
            for provider_id, first_name, surname in provider_matches:
                cd_id = provider_id.replace('CD_I', '')
                key = (first_name, surname)
                if key not in seen:
                    seen.add(key)
                    players.append({
                        'team': team_name,
                        'first_name': first_name,
                        'surname': surname,
                        'full_name': f"{first_name} {surname}".strip(),
                        'jumper_number': '',
                        'champion_data_id': cd_id,
                        'provider_id_raw': provider_id,
                    })
            return players
        
        # Method 3: HTML link fallback with individual page scraping
        player_links = re.findall(r'href="/players/(\d+)/([^"]+)"', content)
        if player_links:
            seen_ids = set()
            for page_id, slug in player_links:
                if page_id in seen_ids:
                    continue
                seen_ids.add(page_id)
                
                # Convert slug to name
                name_parts = slug.replace('-', ' ').title().split()
                first_name = name_parts[0] if name_parts else ''
                surname = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
                
                # Need to fetch individual page for CD ID
                players.append({
                    'team': team_name,
                    'first_name': first_name,
                    'surname': surname,
                    'full_name': f"{first_name} {surname}".strip(),
                    'jumper_number': '',
                    'champion_data_id': '',  # Need individual page fetch
                    'provider_id_raw': '',
                    '_page_url': f"{url.rsplit('/players', 1)[0]}/players/{page_id}/{slug}",
                })
        
        return players
        
    except Exception as e:
        print(f"    ❌ Error: {e}")
        return players


def fetch_cd_id_from_player_page(page_url, player_name):
    """Fetch CD ID from individual player page."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(page_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return None
        
        content = response.text
        first_name = player_name.split()[0].lower() if player_name else ''
        
        # Find providerId near player's first name
        matches = re.findall(r'"providerId":"(CD_I\d+)","firstName":"([^"]+)"', content)
        for provider_id, found_name in matches:
            if found_name.lower() == first_name:
                return provider_id.replace('CD_I', '')
        
        # Fallback: most common CD_I in page
        all_ids = re.findall(r'CD_I(\d+)', content)
        if all_ids:
            from collections import Counter
            most_common = Counter(all_ids).most_common(1)
            if most_common:
                return most_common[0][0]
        
        return None
    except Exception as e:
        return None


def main():
    print("="*60)
    print("   CHAMPION DATA PLAYER ID SCRAPER")
    print("="*60)
    print()
    
    all_players = []
    
    for team_name, url in TEAM_URLS.items():
        print(f"📥 {team_name}...")
        players = get_players_from_team_page(team_name, url)
        
        # Fetch individual pages for players without CD IDs
        players_needing_fetch = [p for p in players if not p.get('champion_data_id') and p.get('_page_url')]
        if players_needing_fetch:
            print(f"    Fetching {len(players_needing_fetch)} individual pages...")
            for i, player in enumerate(players_needing_fetch):
                cd_id = fetch_cd_id_from_player_page(player['_page_url'], player['full_name'])
                if cd_id:
                    player['champion_data_id'] = cd_id
                    player['provider_id_raw'] = f"CD_I{cd_id}"
                if (i + 1) % 10 == 0:
                    print(f"      Processed {i+1}/{len(players_needing_fetch)}")
                time.sleep(0.3)  # Be nice to servers
        
        # Clean up internal fields
        for p in players:
            p.pop('_page_url', None)
        
        all_players.extend(players)
        
        with_cd = sum(1 for p in players if p.get('champion_data_id'))
        print(f"    ✅ {len(players)} players ({with_cd} with CD IDs)")
        time.sleep(0.5)
    
    print()
    print("="*60)
    print("   SAVING RESULTS")
    print("="*60)
    
    # Create DataFrame
    df = pd.DataFrame(all_players)
    
    # Reorder columns
    cols = ['team', 'full_name', 'first_name', 'surname', 'jumper_number', 'champion_data_id', 'provider_id_raw']
    df = df[[c for c in cols if c in df.columns]]
    
    # Sort
    df = df.sort_values(['team', 'surname', 'first_name'])
    
    # Save
    output_file = Path(__file__).parent / 'champion_data_player_ids.xlsx'
    df.to_excel(output_file, index=False, sheet_name='CD Player IDs')
    
    print(f"\n✅ Saved: {output_file}")
    print(f"   Total players: {len(df)}")
    print(f"   With CD IDs: {len(df[df['champion_data_id'] != ''])}")
    print(f"   Missing CD IDs: {len(df[df['champion_data_id'] == ''])}")
    
    # Also save as CSV
    csv_file = Path(__file__).parent / 'champion_data_player_ids.csv'
    df.to_csv(csv_file, index=False)
    print(f"   Also saved: {csv_file}")


if __name__ == '__main__':
    main()
