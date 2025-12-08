#!/usr/bin/env python3
"""
Simple manual helper - generates URLs for manual downloading
This creates a CSV with player names and their likely profile URLs
"""

import pandas as pd
import re

PLAYER_FILE = "AFL Player Ratings.xlsx"

# Team club website base URLs
TEAM_CLUB_URLS = {
    "Adelaide": "https://www.afc.com.au/players",
    "Brisbane": "https://www.lions.com.au/players",
    "Carlton": "https://www.carltonfc.com.au/players",
    "Collingwood": "https://www.collingwoodfc.com.au/players",
    "Essendon": "https://www.essendonfc.com.au/players",
    "Fremantle": "https://www.fremantlefc.com.au/players",
    "Geelong": "https://www.geelongcats.com.au/players",
    "Gold Coast": "https://www.goldcoastfc.com.au/players",
    "GWS": "https://www.gwsgiants.com.au/players",
    "Hawthorn": "https://www.hawthornfc.com.au/players",
    "Melbourne": "https://www.melbournefc.com.au/players",
    "North Melbourne": "https://www.nmfc.com.au/players",
    "Port Adelaide": "https://www.portadelaidefc.com.au/players",
    "Richmond": "https://www.richmondfc.com.au/players",
    "St Kilda": "https://www.saints.com.au/players",
    "Sydney": "https://www.sydneyswans.com.au/players",
    "West Coast": "https://www.westcoasteagles.com.au/players",
    "Western Bulldogs": "https://www.westernbulldogs.com.au/players",
}

def normalize_player_name(name):
    """Normalize player name for filename."""
    return re.sub(r'[^\w\s-]', '', str(name).lower()).replace(' ', '_')

def main():
    print("AFL Player Photo Helper")
    print("="*60)
    
    # Load players
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        df = xl.parse("Summary")
        
        players_data = []
        
        for _, row in df.iterrows():
            player_name = row.get("Player", "")
            team = row.get("Team", "")
            
            if pd.notna(player_name) and pd.notna(team):
                team_str = str(team).strip()
                player_str = str(player_name).strip()
                
                players_url = TEAM_CLUB_URLS.get(team_str, "")
                normalized = normalize_player_name(player_str)
                
                players_data.append({
                    'Player': player_str,
                    'Team': team_str,
                    'Filename': f"{normalized}.png",
                    'Team_Players_Page': players_url
                })
        
        # Create DataFrame and save
        output_df = pd.DataFrame(players_data)
        output_df = output_df.drop_duplicates(subset=['Player'])
        
        output_df.to_csv('player_photo_guide.csv', index=False)
        print(f"\n✓ Created player_photo_guide.csv with {len(output_df)} players")
        print("\nThis CSV contains:")
        print("  - Player names")
        print("  - Their teams")  
        print("  - The filename to save their photo as")
        print("  - The team's players page URL")
        print("\nYou can visit each team's players page and manually download photos.")
        print("Save them in the 'player_photos/' directory with the filename shown.")
        
        # Show summary by team
        print("\nPlayers by team:")
        team_counts = output_df['Team'].value_counts().sort_index()
        for team, count in team_counts.items():
            print(f"  {team}: {count} players")
        
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    main()
