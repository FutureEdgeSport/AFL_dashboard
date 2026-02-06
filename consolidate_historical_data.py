#!/usr/bin/env python3
"""
Consolidate All Historical AFL Data (up to end of 2025)

Creates a single Excel workbook as the "source of truth" for all historical data.
This data will not change - only 2026+ data gets updated via API/scrapers.

Sheets created:
1. Player_Stats_All - All player season stats 2012-2025
2. Player_Traits_All - All traits data 2021-2025  
3. Team_Stats_All - All team stats 2021-2025
4. Player_Registry - Master player list with DOB, draft, contract info
5. Team_Reference - Team reference data
6. Metadata - Data sources and timestamps
"""
import pandas as pd
import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("data/raw")
OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "AFL_Historical_2012_2025.xlsx"


def load_all_player_stats():
    """Load and combine all player stats 2012-2025."""
    print("Loading player stats 2012-2025...")
    
    all_dfs = []
    for year in range(2012, 2026):
        path = DATA_DIR / f"player/player_stats_{year}.csv"
        if path.exists():
            df = pd.read_csv(path)
            df['Season'] = year
            all_dfs.append(df)
            print(f"  {year}: {len(df)} players")
    
    combined = pd.concat(all_dfs, ignore_index=True)
    
    # Reorder columns - Season first, then Player, Team
    cols = ['Season', 'Player', 'Team'] + [c for c in combined.columns if c not in ['Season', 'Player', 'Team']]
    combined = combined[cols]
    
    print(f"  Total: {len(combined)} player-seasons")
    return combined


def load_all_traits():
    """Load and combine all traits data 2021-2025."""
    print("\nLoading traits 2021-2025...")
    
    all_dfs = []
    for year in range(2021, 2026):
        path = DATA_DIR / f"traits/traits_{year}.csv"
        if path.exists():
            df = pd.read_csv(path)
            # Ensure Season column exists and is correct
            df['Season'] = year
            all_dfs.append(df)
            print(f"  {year}: {len(df)} players")
    
    combined = pd.concat(all_dfs, ignore_index=True)
    
    # Reorder columns
    cols = ['Season', 'Player', 'Team'] + [c for c in combined.columns if c not in ['Season', 'Player', 'Team']]
    combined = combined[cols]
    
    print(f"  Total: {len(combined)} player-seasons")
    return combined


def load_all_team_stats():
    """Load and combine all team stats 2021-2025."""
    print("\nLoading team stats 2021-2025...")
    
    all_dfs = []
    for year in range(2021, 2026):
        path = DATA_DIR / f"team/team_stats_{year}.csv"
        if path.exists():
            df = pd.read_csv(path)
            df['Season'] = year
            all_dfs.append(df)
            print(f"  {year}: {len(df)} teams")
    
    combined = pd.concat(all_dfs, ignore_index=True)
    
    # Reorder columns
    cols = ['Season', 'Team'] + [c for c in combined.columns if c not in ['Season', 'Team']]
    combined = combined[cols]
    
    print(f"  Total: {len(combined)} team-seasons")
    return combined


def build_player_registry():
    """Build master player registry with all known info."""
    print("\nBuilding player registry...")
    
    # Start with 2025 squads as base (most current)
    squads = pd.read_csv(DATA_DIR / "player/squads_2025.csv")
    print(f"  Base: {len(squads)} players from 2025 squads")
    
    # Load DOB cache
    dob_cache = {}
    dob_file = Path("data/cache/player_dobs.json")
    if dob_file.exists():
        with open(dob_file) as f:
            dob_cache = json.load(f)
        print(f"  DOBs: {len(dob_cache)} entries")
    
    # Load contract data
    contract_df = pd.read_csv(DATA_DIR / "player/contract_expiry.csv")
    contract_dict = dict(zip(contract_df['Name'], contract_df['Expiry Year']))
    print(f"  Contracts: {len(contract_df)} entries")
    
    # Load draft data
    draft_df = pd.read_csv(DATA_DIR / "player/draft_data.csv")
    draft_dict = {}
    for _, row in draft_df.iterrows():
        draft_dict[row['Name']] = {
            'Draft_Year': row['Draft Year'],
            'Draft_Pick': row['Draft Number'],
            'Acquisition': row['Acquisition']
        }
    print(f"  Draft: {len(draft_df)} entries")
    
    # Load Footywire draft history for additional coverage
    fw_drafts = pd.read_csv(DATA_DIR / "player/footywire_drafts_history.csv")
    fw_draft_dict = {}
    for _, row in fw_drafts.iterrows():
        player = row['Player_Raw']
        if player not in fw_draft_dict:  # Keep first (most recent) entry
            fw_draft_dict[player] = {
                'Draft_Year': row['Draft_Year'],
                'Draft_Type': row['Draft_Type'],
                'Draft_Round': row['Draft_Round'],
                'Draft_Pick': row['Draft_Pick']
            }
    print(f"  Footywire drafts: {len(fw_draft_dict)} unique players")
    
    # Load Traits API cache for additional data
    traits_cache = {}
    traits_file = Path("data/cache/traits_api_cache.json")
    if traits_file.exists():
        with open(traits_file) as f:
            data = json.load(f)
            traits_cache = data.get('players', {})
        print(f"  Traits API: {len(traits_cache)} entries")
    
    # Build registry
    registry = squads[['Player', 'Team', 'JumperNumber', 'Age', 'Height', 'Position', 
                       'DebutYear', 'Matches_Career', 'Goals_Total_Career']].copy()
    
    # Add DOB
    registry['DOB'] = registry['Player'].map(dob_cache)
    
    # Add contract info
    registry['Contract_Expiry'] = registry['Player'].map(contract_dict)
    
    # Add draft info (prefer original draft_data, fall back to Footywire)
    def get_draft_info(player):
        if player in draft_dict:
            return draft_dict[player]
        elif player in fw_draft_dict:
            return fw_draft_dict[player]
        return {}
    
    draft_info = registry['Player'].apply(get_draft_info)
    registry['Draft_Year'] = draft_info.apply(lambda x: x.get('Draft_Year'))
    registry['Draft_Pick'] = draft_info.apply(lambda x: x.get('Draft_Pick'))
    registry['Draft_Type'] = draft_info.apply(lambda x: x.get('Draft_Type'))
    registry['Draft_Round'] = draft_info.apply(lambda x: x.get('Draft_Round'))
    registry['Acquisition'] = draft_info.apply(lambda x: x.get('Acquisition'))
    
    # Add Traits API ID where available
    def get_traits_id(player):
        if player in traits_cache:
            return traits_cache[player].get('data_provider_id')
        return None
    
    registry['Traits_API_ID'] = registry['Player'].apply(get_traits_id)
    
    print(f"  Registry built: {len(registry)} players")
    print(f"    With DOB: {registry['DOB'].notna().sum()}")
    print(f"    With Contract: {registry['Contract_Expiry'].notna().sum()}")
    print(f"    With Draft Year: {registry['Draft_Year'].notna().sum()}")
    
    return registry


def build_team_reference():
    """Build team reference data."""
    print("\nBuilding team reference...")
    
    # Load Wheelo team data as base
    wheelo = pd.read_csv(DATA_DIR / "external/wheelo_team_ratings.csv")
    
    # Team name mappings for consistency
    team_mapping = {
        'Adelaide': {'Abbreviation': 'ADE', 'Footywire_Slug': 'adelaide-crows'},
        'Brisbane': {'Abbreviation': 'BRI', 'Footywire_Slug': 'brisbane-lions'},
        'Carlton': {'Abbreviation': 'CAR', 'Footywire_Slug': 'carlton-blues'},
        'Collingwood': {'Abbreviation': 'COL', 'Footywire_Slug': 'collingwood-magpies'},
        'Essendon': {'Abbreviation': 'ESS', 'Footywire_Slug': 'essendon-bombers'},
        'Fremantle': {'Abbreviation': 'FRE', 'Footywire_Slug': 'fremantle-dockers'},
        'Geelong': {'Abbreviation': 'GEE', 'Footywire_Slug': 'geelong-cats'},
        'Gold Coast': {'Abbreviation': 'GCS', 'Footywire_Slug': 'gold-coast-suns'},
        'GWS Giants': {'Abbreviation': 'GWS', 'Footywire_Slug': 'greater-western-sydney-giants'},
        'Hawthorn': {'Abbreviation': 'HAW', 'Footywire_Slug': 'hawthorn-hawks'},
        'Melbourne': {'Abbreviation': 'MEL', 'Footywire_Slug': 'melbourne-demons'},
        'North Melbourne': {'Abbreviation': 'NTH', 'Footywire_Slug': 'kangaroos'},
        'Port Adelaide': {'Abbreviation': 'PTA', 'Footywire_Slug': 'port-adelaide-power'},
        'Richmond': {'Abbreviation': 'RIC', 'Footywire_Slug': 'richmond-tigers'},
        'St Kilda': {'Abbreviation': 'STK', 'Footywire_Slug': 'st-kilda-saints'},
        'Sydney': {'Abbreviation': 'SYD', 'Footywire_Slug': 'sydney-swans'},
        'West Coast': {'Abbreviation': 'WCE', 'Footywire_Slug': 'west-coast-eagles'},
        'Western Bulldogs': {'Abbreviation': 'WBD', 'Footywire_Slug': 'western-bulldogs'},
    }
    
    teams = pd.DataFrame([
        {'Team': team, **data} for team, data in team_mapping.items()
    ])
    
    # Merge with Wheelo data
    teams = teams.merge(wheelo[['Team', 'Matches', 'Players', 'Age', 'Experience', 'RatingPoints', 'Supercoach']], 
                        on='Team', how='left')
    
    print(f"  Teams: {len(teams)}")
    return teams


def create_metadata():
    """Create metadata sheet with data sources and timestamps."""
    metadata = pd.DataFrame([
        {'Category': 'Player Stats', 'Years': '2012-2025', 'Source': 'AFL Tables / Champion Data', 'Notes': '14 seasons of player performance data'},
        {'Category': 'Player Traits', 'Years': '2021-2025', 'Source': 'Traits Excel', 'Notes': '5 seasons of traits/ratings data'},
        {'Category': 'Team Stats', 'Years': '2021-2025', 'Source': 'AFL Tables', 'Notes': '5 seasons of team performance data'},
        {'Category': 'DOB Data', 'Years': 'Various', 'Source': 'Wikipedia, Footywire', 'Notes': f'892 player DOBs in cache'},
        {'Category': 'Contract Data', 'Years': '2025', 'Source': 'Footywire', 'Notes': 'Contract expiry years'},
        {'Category': 'Draft Data', 'Years': '2001-2025', 'Source': 'Footywire', 'Notes': 'Historical draft records'},
        {'Category': 'Traits API', 'Years': '2025', 'Source': 'Traits Insights API', 'Notes': 'API-based ratings'},
        {'Category': 'Created', 'Years': datetime.now().strftime('%Y-%m-%d %H:%M'), 'Source': 'consolidate_historical_data.py', 'Notes': 'Workbook creation timestamp'},
    ])
    return metadata


def main():
    print("=" * 70)
    print("CONSOLIDATING HISTORICAL AFL DATA (2012-2025)")
    print("=" * 70)
    print(f"Output: {OUTPUT_FILE}")
    print()
    
    # Load all data
    player_stats = load_all_player_stats()
    player_traits = load_all_traits()
    team_stats = load_all_team_stats()
    player_registry = build_player_registry()
    team_reference = build_team_reference()
    metadata = create_metadata()
    
    # Write to Excel
    print("\n" + "=" * 70)
    print("Writing to Excel workbook...")
    print("=" * 70)
    
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        # Player stats - all seasons
        player_stats.to_excel(writer, sheet_name='Player_Stats_All', index=False)
        print(f"  Player_Stats_All: {len(player_stats)} rows")
        
        # Player traits - all seasons
        player_traits.to_excel(writer, sheet_name='Player_Traits_All', index=False)
        print(f"  Player_Traits_All: {len(player_traits)} rows")
        
        # Team stats - all seasons
        team_stats.to_excel(writer, sheet_name='Team_Stats_All', index=False)
        print(f"  Team_Stats_All: {len(team_stats)} rows")
        
        # Player registry
        player_registry.to_excel(writer, sheet_name='Player_Registry', index=False)
        print(f"  Player_Registry: {len(player_registry)} rows")
        
        # Team reference
        team_reference.to_excel(writer, sheet_name='Team_Reference', index=False)
        print(f"  Team_Reference: {len(team_reference)} rows")
        
        # Metadata
        metadata.to_excel(writer, sheet_name='Metadata', index=False)
        print(f"  Metadata: {len(metadata)} rows")
    
    print(f"\n{'=' * 70}")
    print(f"SUCCESS! Historical data consolidated to:")
    print(f"  {OUTPUT_FILE}")
    print(f"  File size: {OUTPUT_FILE.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"{'=' * 70}")
    
    # Summary
    print(f"""
SUMMARY:
  - Player Stats: {len(player_stats)} player-seasons (2012-2025)
  - Player Traits: {len(player_traits)} player-seasons (2021-2025)
  - Team Stats: {len(team_stats)} team-seasons (2021-2025)
  - Player Registry: {len(player_registry)} unique players
  - Team Reference: {len(team_reference)} teams

This workbook is the "source of truth" for all historical data.
It should NOT be modified - only 2026+ data gets updated via API/scrapers.
""")


if __name__ == "__main__":
    main()
