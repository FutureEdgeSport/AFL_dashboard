#!/usr/bin/env python3
"""Create Champion Data Team IDs lookup and add to spreadsheets"""
import pandas as pd

# Champion Data Team ID mapping (verified from AFL Fantasy API)
# Includes full names, common names, and abbreviations
CD_TEAM_IDS = {
    'Adelaide': 10, 'Adelaide Crows': 10, 'ADL': 10, 'AFC': 10,
    'Brisbane Lions': 20, 'Brisbane': 20, 'BRI': 20, 'BFC': 20,
    'Carlton': 30, 'Carlton Blues': 30, 'CAR': 30, 'CFC': 30,
    'Collingwood': 40, 'Collingwood Magpies': 40, 'COL': 40, 'COFC': 40,
    'Essendon': 50, 'Essendon Bombers': 50, 'ESS': 50, 'EFC': 50,
    'Fremantle': 60, 'Fremantle Dockers': 60, 'FRE': 60, 'FRFC': 60, 'FFC': 60,
    'Geelong': 70, 'Geelong Cats': 70, 'GEE': 70, 'GFC': 70,
    'Hawthorn': 80, 'Hawthorn Hawks': 80, 'HAW': 80, 'HFC': 80,
    'Melbourne': 90, 'Melbourne Demons': 90, 'MEL': 90, 'MFC': 90,
    'North Melbourne': 100, 'North Melbourne Kangaroos': 100, 'NTH': 100, 'NMFC': 100,
    'Port Adelaide': 110, 'Port Adelaide Power': 110, 'PTA': 110, 'PAFC': 110,
    'Richmond': 120, 'Richmond Tigers': 120, 'RIC': 120, 'RFC': 120,
    'St Kilda': 130, 'St Kilda Saints': 130, 'STK': 130, 'STKFC': 130,
    'Western Bulldogs': 140, 'Footscray': 140, 'WBD': 140, 'WBFC': 140,
    'West Coast': 150, 'West Coast Eagles': 150, 'WCE': 150, 'WCFC': 150,
    'Sydney': 160, 'Sydney Swans': 160, 'SYD': 160, 'SYFC': 160,
    'Gold Coast': 1000, 'Gold Coast Suns': 1000, 'GCS': 1000, 'GCFC': 1000,
    'GWS Giants': 1010, 'GWS': 1010, 'Greater Western Sydney': 1010, 'GWSFC': 1010,
}

def create_lookup_file():
    """Create the team ID lookup file"""
    teams = [
        ('Adelaide', 'Adelaide Crows', 'ADL', 10),
        ('Brisbane Lions', 'Brisbane', 'BRI', 20),
        ('Carlton', 'Carlton Blues', 'CAR', 30),
        ('Collingwood', 'Collingwood Magpies', 'COL', 40),
        ('Essendon', 'Essendon Bombers', 'ESS', 50),
        ('Fremantle', 'Fremantle Dockers', 'FRE', 60),
        ('Geelong', 'Geelong Cats', 'GEE', 70),
        ('Hawthorn', 'Hawthorn Hawks', 'HAW', 80),
        ('Melbourne', 'Melbourne Demons', 'MEL', 90),
        ('North Melbourne', 'North Melbourne Kangaroos', 'NTH', 100),
        ('Port Adelaide', 'Port Adelaide Power', 'PTA', 110),
        ('Richmond', 'Richmond Tigers', 'RIC', 120),
        ('St Kilda', 'St Kilda Saints', 'STK', 130),
        ('Western Bulldogs', 'Footscray', 'WBD', 140),
        ('West Coast', 'West Coast Eagles', 'WCE', 150),
        ('Sydney', 'Sydney Swans', 'SYD', 160),
        ('Gold Coast', 'Gold Coast Suns', 'GCS', 1000),
        ('GWS Giants', 'Greater Western Sydney', 'GWS', 1010),
    ]
    
    df = pd.DataFrame(teams, columns=['team_name', 'full_name', 'abbreviation', 'champion_data_team_id'])
    df['cd_team_id_formatted'] = df['champion_data_team_id'].apply(lambda x: f'CD_T{x}')
    
    df.to_excel('champion_data_team_ids.xlsx', index=False)
    df.to_csv('champion_data_team_ids.csv', index=False)
    
    print("Created champion_data_team_ids.xlsx")
    print(df.to_string(index=False))
    return df

def add_team_ids_to_file(filepath, team_column):
    """Add champion_data_team_id column to a file"""
    print(f"\nProcessing {filepath}...")
    
    df = pd.read_excel(filepath)
    print(f"  Loaded {len(df)} rows")
    
    # Add team IDs
    def get_team_id(team_name):
        if pd.isna(team_name):
            return None
        name = str(team_name).strip()
        return CD_TEAM_IDS.get(name)
    
    df['champion_data_team_id'] = df[team_column].apply(get_team_id)
    
    matched = df['champion_data_team_id'].notna().sum()
    print(f"  Matched: {matched}/{len(df)}")
    
    # Show unmatched
    unmatched = df[df['champion_data_team_id'].isna()][team_column].unique()
    if len(unmatched) > 0:
        print(f"  Unmatched teams: {list(unmatched)[:10]}")
    
    df.to_excel(filepath, index=False)
    print(f"  Saved {filepath}")
    
    return df

def main():
    # Create lookup file
    create_lookup_file()
    
    # Add team IDs to files with team columns
    files_to_update = [
        ('Wheelo_Player_Data.xlsx', 'Team'),
        ('Wheelo_Team_Data.xlsx', 'Team'),
        ('2025 Traits ENRICHED.xlsx', 'Team'),
        ('AFL Player Ratings.xlsx', 'Team'),
        ('champion_data_player_ids.xlsx', 'team'),
    ]
    
    for filepath, team_col in files_to_update:
        try:
            add_team_ids_to_file(filepath, team_col)
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    main()
