#!/usr/bin/env python3
"""
Scrape DOBs from AFL.com.au and test Traits API integration.
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import os

API_KEY = "sk_4PCTg45wYI_udETo5kT6ad6lU7977L8DdqxZ2UFUl-c"
API_BASE = "https://partner-api.traitsinsights.app"


def test_api_with_player(name, dob):
    """Test the Traits API with a player."""
    url = f"{API_BASE}/profiles/participations/latest/ratings"
    
    params = {
        'name': name,
        'date_of_birth': dob
    }
    headers = {
        'Authorization': f'Bearer {API_KEY}'
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"API error for {name}: {resp.status_code}")
    except Exception as e:
        print(f"Request error for {name}: {e}")
    
    return None


def calc_dob_from_age_decimal(age_decimal, ref_date):
    """Calculate approximate DOB from age decimal."""
    if pd.isna(age_decimal):
        return None
    days_old = age_decimal * 365.25
    dob = ref_date - timedelta(days=days_old)
    return dob.strftime('%Y-%m-%d')


if __name__ == "__main__":
    # Load the player data
    df = pd.read_excel('AFL Player Ratings.xlsx', sheet_name='2025')
    
    print("Sample players with Age_Decimal:")
    sample = df[['Player', 'Team', 'Age', 'Age_Decimal']].head(10)
    print(sample.to_string())
    
    # Test with Patrick Cripps - known DOB is 1995-03-18
    print("\n" + "="*50)
    print("Testing with known DOB: Patrick Cripps (1995-03-18)")
    result = test_api_with_player("Patrick Cripps", "1995-03-18")
    if result:
        print(f"✓ API Success: {result['full_name']}")
    
    # Find Cripps in data
    cripps = df[df['Player'].str.contains('Cripps', case=False, na=False)]
    if not cripps.empty:
        age_dec = cripps['Age_Decimal'].iloc[0]
        print(f"\nCripps Age_Decimal in data: {age_dec}")
        
        # Try different reference dates to find the right one
        for ref_date in [datetime(2025, 9, 1), datetime(2025, 6, 30), datetime(2025, 1, 1)]:
            calc_dob = calc_dob_from_age_decimal(age_dec, ref_date)
            print(f"  Ref date {ref_date.strftime('%Y-%m-%d')}: Calculated DOB = {calc_dob}")
    
    # Test using data_provider_id instead
    print("\n" + "="*50)
    print("Testing data_provider_id format (no DOB needed):")
    
    def test_api_with_provider_id(data_provider_id):
        """Test API using data_provider_id instead of name+DOB."""
        url = f"{API_BASE}/profiles/participations/latest/ratings"
        
        params = {'data_provider_id': data_provider_id}
        headers = {'Authorization': f'Bearer {API_KEY}'}
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"  Status: {resp.status_code}")
        except Exception as e:
            print(f"  Error: {e}")
        return None
    
    # Try different data_provider_id formats
    test_ids = [
        "P.Cripps 18/3/1995",           # Original format from docs
        "CD_I291793",                    # Champion Data format - Cripps ID
        "291793",                        # Just the numeric ID
        "Patrick Cripps",                # Just name
    ]
    
    for pid in test_ids:
        print(f"\nTrying data_provider_id: '{pid}'")
        result = test_api_with_provider_id(pid)
        if result:
            print(f"  ✓ Found: {result['full_name']}")
            break
    
    # Test scraping DOBs from Wikipedia
    print("\n" + "="*50)
    print("Testing Wikipedia for player DOBs:")
    
    from bs4 import BeautifulSoup
    
    def get_dob_from_wikipedia(player_name):
        """Scrape DOB from Wikipedia."""
        name_slug = player_name.replace(' ', '_')
        
        # Try AFL player page format
        urls = [
            f"https://en.wikipedia.org/wiki/{name_slug}_(Australian_footballer)",
            f"https://en.wikipedia.org/wiki/{name_slug}",
        ]
        
        headers = {'User-Agent': 'Mozilla/5.0 (AFL Dashboard DOB Lookup)'}
        
        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    
                    # Find the infobox
                    infobox = soup.find('table', class_='infobox')
                    if infobox:
                        # Look for "Born" row
                        for row in infobox.find_all('tr'):
                            header = row.find('th')
                            if header and 'Born' in header.get_text():
                                bday = row.find('span', class_='bday')
                                if bday:
                                    return bday.get_text()
            except Exception as e:
                pass
        
        return None
    
    # Test with known players
    test_players = ["Patrick Cripps", "Marcus Bontempelli", "Jeremy Cameron"]
    for name in test_players:
        dob = get_dob_from_wikipedia(name)
        if dob:
            print(f"✓ {name}: DOB = {dob}")
            # Verify with API
            result = test_api_with_player(name, dob)
            if result:
                print(f"    API verified: {result['full_name']}")
        else:
            print(f"✗ {name}: DOB not found")
    
    # Count how many players we can find DOBs for
    print("\n" + "="*50)
    print("Testing bulk DOB lookup from Wikipedia...")
    
    # Get unique players from our data
    all_players = df['Player'].unique()[:50]  # Test first 50
    found = 0
    not_found = []
    
    for player in all_players:
        dob = get_dob_from_wikipedia(player)
        if dob:
            found += 1
        else:
            not_found.append(player)
    
    print(f"Found DOBs for {found}/{len(all_players)} players")
    print(f"Not found: {not_found[:10]}...")

