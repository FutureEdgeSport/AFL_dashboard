#!/usr/bin/env python3
"""
Extended Footywire Scraper for AFL Data

Adds to the base player data:
1. Contract Expiry (Final Year) 
2. Free Agency Status
3. Draft information (Type, Round, Pick, Year)

Usage:
    python scrape_footywire_extended.py               # Full scrape (all draft years)
    python scrape_footywire_extended.py --current-only # Current season only (fast)

Uses team contracts pages (to-) and draft pages (td-?year=) from Footywire.
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import argparse
from datetime import datetime
from pathlib import Path
from utils.http_utils import create_retry_session
from config.constants import CURRENT_SEASON
from utils.safe_io import safe_csv_write

# Draft history cache for --current-only incremental mode
DRAFTS_CACHE = Path("data/cache/footywire_drafts.csv")

# Shared HTTP session with retry logic
_session = create_retry_session(retries=3, backoff_factor=1.0, timeout=15)

# Team configurations - same as main scraper
TEAMS = {
    "Adelaide": "adelaide-crows",
    "Brisbane": "brisbane-lions", 
    "Carlton": "carlton-blues",
    "Collingwood": "collingwood-magpies",
    "Essendon": "essendon-bombers",
    "Fremantle": "fremantle-dockers",
    "Geelong": "geelong-cats",
    "Gold Coast": "gold-coast-suns",
    "GWS Giants": "greater-western-sydney-giants",
    "Hawthorn": "hawthorn-hawks",
    "Melbourne": "melbourne-demons",
    "North Melbourne": "kangaroos",
    "Port Adelaide": "port-adelaide-power",
    "Richmond": "richmond-tigers",
    "St Kilda": "st-kilda-saints",
    "Sydney": "sydney-swans",
    "West Coast": "west-coast-eagles",
    "Western Bulldogs": "western-bulldogs",
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Draft types to look for
DRAFT_TYPES = ['National', 'Rookie', 'Father/Son', 'Pre-Season', 'Mid-Season', 'Academy', 'Supplementary']


def normalize_name(name):
    """Normalize player name for matching."""
    if not name:
        return ""
    # Remove suffixes like F, A, R etc that Footywire adds
    name = re.sub(r'[FAR]$', '', name.strip())
    # Remove Jr, Jnr, etc
    name = re.sub(r'\s*(Jr\.?|Jnr\.?|Sr\.?|Snr\.?)$', '', name, flags=re.IGNORECASE)
    return name.strip()


def scrape_team_contracts(team_name, team_slug):
    """Scrape contract information for a team."""
    url = f"https://www.footywire.com/afl/footy/to-{team_slug}"
    
    try:
        resp = _session.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ✗ Contracts HTTP {resp.status_code}")
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        tables = soup.find_all('table')
        
        contracts = []
        for table in tables:
            table_text = table.get_text()
            # Look for contracts table with Status and Final Year
            if 'Final Year' in table_text and 'Status' in table_text:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 4:
                        name = cells[0].get_text(strip=True)
                        final_year = cells[1].get_text(strip=True)
                        years_service = cells[2].get_text(strip=True)
                        status = cells[3].get_text(strip=True)
                        
                        # Validate - name should not be empty, final_year should be a number
                        if name and final_year.isdigit():
                            contracts.append({
                                'Team': team_name,
                                'Player_Raw': name,
                                'Contract_Expiry': int(final_year),
                                'Years_Service': years_service,
                                'FA_Status': status
                            })
                
                if contracts:
                    return contracts
        
        return []
        
    except Exception as e:
        print(f"  ✗ Contracts error: {e}")
        return []


def scrape_team_drafts(team_name, team_slug, start_year=2001, end_year=2025):
    """Scrape draft history for a team across multiple years."""
    all_drafts = []
    
    for year in range(end_year, start_year - 1, -1):
        url = f"https://www.footywire.com/afl/footy/td-{team_slug}?year={year}"
        
        try:
            resp = _session.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            tables = soup.find_all('table')
            
            # Find draft picks table - look for rows with draft type in first cell
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 5:
                        draft_type = cells[0].get_text(strip=True)
                        # Check if this is a draft pick row (type is in our list)
                        if draft_type in DRAFT_TYPES:
                            round_num = cells[1].get_text(strip=True)
                            pick = cells[2].get_text(strip=True)
                            player = cells[3].get_text(strip=True)
                            
                            # Skip summary rows (where player looks like a number)
                            if player.isdigit() or not player:
                                continue
                            
                            all_drafts.append({
                                'Team': team_name,
                                'Player_Raw': normalize_name(player),
                                'Draft_Year': year,
                                'Draft_Type': draft_type,
                                'Draft_Round': int(round_num) if round_num.isdigit() else None,
                                'Draft_Pick': int(pick) if pick.isdigit() else None
                            })
            
            time.sleep(0.3)  # Be nice to server
            
        except Exception as e:
            continue  # Skip failed years silently
    
    return all_drafts


def main():
    print("Scraping Extended Player Data from Footywire")
    print("=" * 60)
    print()
    
    all_contracts = []
    all_drafts = []
    
    for team_name, team_slug in TEAMS.items():
        print(f"{team_name}...", end=" ", flush=True)
        
        # Scrape contracts
        contracts = scrape_team_contracts(team_name, team_slug)
        all_contracts.extend(contracts)
        print(f"✓ {len(contracts)} contracts", end="", flush=True)
        
        time.sleep(0.5)
        
        # Scrape drafts (going back to 2001 to cover older players like Pendlebury, Zorko etc)
        drafts = scrape_team_drafts(team_name, team_slug, start_year=2001)
        all_drafts.extend(drafts)
        print(f", {len(drafts)} draft picks")
        
        time.sleep(0.5)
    
    print()
    print("=" * 60)
    
    # Save contracts data
    if all_contracts:
        contracts_df = pd.DataFrame(all_contracts)
        contracts_path = Path("data/raw/player/footywire_contracts_2026.csv")
        safe_csv_write(contracts_df, contracts_path)
        print(f"\nContracts saved to: {contracts_path}")
        print(f"  Total players: {len(contracts_df)}")
        
        # Show FA status breakdown
        print(f"\n  Free Agency Status breakdown:")
        print(contracts_df['FA_Status'].value_counts().to_string())
        
        # Show expiry year breakdown
        print(f"\n  Contract expiry by year:")
        print(contracts_df['Contract_Expiry'].value_counts().sort_index().to_string())
    
    # Save drafts data
    if all_drafts:
        drafts_df = pd.DataFrame(all_drafts)
        drafts_path = Path("data/raw/player/footywire_drafts_history.csv")
        safe_csv_write(drafts_df, drafts_path)
        print(f"\nDrafts saved to: {drafts_path}")
        print(f"  Total draft picks: {len(drafts_df)}")
        
        # Update the full drafts cache for future --current-only runs
        DRAFTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        safe_csv_write(drafts_df, DRAFTS_CACHE)
        print(f"  Cache updated: {DRAFTS_CACHE}")
        
        # Show draft type breakdown
        print(f"\n  Draft type breakdown:")
        print(drafts_df['Draft_Type'].value_counts().to_string())
    
    # Load base 2026 player data and merge
    base_path = Path("data/raw/player/footywire_2026_lists.csv")
    if base_path.exists():
        print(f"\n{'=' * 60}")
        print("Merging with base 2026 player data...")
        
        base_df = pd.read_csv(base_path)
        
        # Normalize player names for matching
        base_df['Player_Normalized'] = base_df['Player'].str.strip()
        
        # Create lookup dictionaries
        contracts_lookup = {}
        for _, row in pd.DataFrame(all_contracts).iterrows():
            key = (row['Team'], normalize_name(row['Player_Raw']))
            contracts_lookup[key] = {
                'Contract_Expiry': row['Contract_Expiry'],
                'FA_Status': row['FA_Status']
            }
        
        drafts_lookup = {}
        for _, row in pd.DataFrame(all_drafts).iterrows():
            # Use player name + team for lookup (current team may differ from draft team)
            player = normalize_name(row['Player_Raw'])
            if player not in drafts_lookup:
                drafts_lookup[player] = {
                    'Draft_Year': row['Draft_Year'],
                    'Draft_Type': row['Draft_Type'],
                    'Draft_Round': row['Draft_Round'],
                    'Draft_Pick': row['Draft_Pick']
                }
        
        # Apply to base data
        def get_contract_info(row):
            key = (row['Team'], row['Player_Normalized'])
            return contracts_lookup.get(key, {})
        
        def get_draft_info(row):
            return drafts_lookup.get(row['Player_Normalized'], {})
        
        # Add contract columns
        contract_info = base_df.apply(get_contract_info, axis=1)
        base_df['Contract_Expiry'] = contract_info.apply(lambda x: x.get('Contract_Expiry'))
        base_df['FA_Status'] = contract_info.apply(lambda x: x.get('FA_Status'))
        
        # Add draft columns
        draft_info = base_df.apply(get_draft_info, axis=1)
        base_df['Draft_Year'] = draft_info.apply(lambda x: x.get('Draft_Year'))
        base_df['Draft_Type'] = draft_info.apply(lambda x: x.get('Draft_Type'))
        base_df['Draft_Round'] = draft_info.apply(lambda x: x.get('Draft_Round'))
        base_df['Draft_Pick'] = draft_info.apply(lambda x: x.get('Draft_Pick'))
        
        # Remove temp column
        base_df.drop('Player_Normalized', axis=1, inplace=True)
        
        # Save merged data
        merged_path = Path("data/raw/player/footywire_2026_complete.csv")
        safe_csv_write(base_df, merged_path)
        print(f"\nMerged data saved to: {merged_path}")
        
        # Show coverage stats
        print(f"\nMerge Statistics:")
        print(f"  Total players: {len(base_df)}")
        print(f"  Contract data matched: {base_df['Contract_Expiry'].notna().sum()} ({base_df['Contract_Expiry'].notna().mean()*100:.1f}%)")
        print(f"  Draft data matched: {base_df['Draft_Year'].notna().sum()} ({base_df['Draft_Year'].notna().mean()*100:.1f}%)")
        
        # Show sample
        print(f"\nSample of merged data:")
        sample = base_df[['Team', 'Player', 'Contract_Expiry', 'FA_Status', 'Draft_Year', 'Draft_Type', 'Draft_Round', 'Draft_Pick']].head(10)
        print(sample.to_string())


if __name__ == "__main__":
    main()
