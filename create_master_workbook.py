"""
AFL Dashboard Master Workbook Creator
=====================================
This script consolidates all data sources into a single master workbook:
  - AFL_Master_2012_2025.xlsx

This becomes the single source of truth for all historical data through 2025.

Sheets Structure:
-----------------
PLAYER DATA:
1. Players_2025_Squad     - Full 808 player squad (including reserves, delisted)
2. Players_2025_Stats     - 668 players who played in 2025 with full stats
3. Players_2024_Stats     - Historical stats for 2024
4. Players_2023_Stats     - Historical stats for 2023
5. Players_2022_Stats     - Historical stats for 2022
6. Players_2021_Stats     - Historical stats for 2021
7. Players_2012_2020      - Consolidated older stats (2012-2020)
8. Player_Summary         - Summary sheet with career ratings, rankings
9. Player_Contracts       - Contract expiry data
10. Player_Draft          - Draft data
11. Player_Traits_2025    - 2025 traits data (enriched)
12. Player_Traits_2024    - 2024 traits data
13. Player_Traits_2023    - 2023 traits data
14. Player_Traits_Historical - 2021-2022 traits
15. Player_Registry       - Master player ID mapping
16. Wings                 - Wing position players

TEAM DATA:
17. Teams_2025_Summary    - Team summary stats for 2025
18. Teams_2025_Full       - Full team stats for 2025
19. Teams_2024_Summary    - Team summary stats for 2024
20. Teams_2023_Summary    - Team summary stats for 2023
21. Teams_Historical      - 2021-2022 team data
22. Team_Ladders_All      - AFL ladder positions 2011-2025
23. Team_Reference        - Team ID mapping, logos, colors

REFERENCE DATA:
24. Champion_Data_IDs     - Champion Data player IDs
25. Wheelo_Player_Data    - Wheelo player metrics (2025)
26. Wheelo_Team_Data      - Wheelo team metrics (2025)
27. Metadata              - Data sources, update dates, version info
"""

import pandas as pd
from pathlib import Path
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

BASE_DIR = Path(__file__).parent

# Source files
PLAYER_RATINGS_FILE = BASE_DIR / "AFL Player Ratings.xlsx"
TEAM_RATINGS_FILE = BASE_DIR / "AFL Team Ratings.xlsx"
TRAITS_FILE = BASE_DIR / "2025 Traits ENRICHED.xlsx"
WHEELO_PLAYER_FILE = BASE_DIR / "Wheelo_Player_Data.xlsx"
WHEELO_TEAM_FILE = BASE_DIR / "Wheelo_Team_Data.xlsx"
LADDERS_FILE = BASE_DIR / "afl_ladders_2011_2025.xlsx"
CD_PLAYER_IDS_FILE = BASE_DIR / "champion_data_player_ids.xlsx"
CD_TEAM_IDS_FILE = BASE_DIR / "champion_data_team_ids.xlsx"
PLAYER_REGISTRY_FILE = BASE_DIR / "player_registry.xlsx"
HISTORICAL_FILE = BASE_DIR / "data" / "AFL_Historical_2012_2025.xlsx"

# Output file
OUTPUT_FILE = BASE_DIR / "AFL_Master_2012_2025.xlsx"


def load_sheet_safe(filepath, sheet_name):
    """Load a sheet with error handling."""
    try:
        df = pd.read_excel(filepath, sheet_name=sheet_name)
        df.columns = df.columns.astype(str).str.strip()
        return df
    except Exception as e:
        print(f"  ⚠️ Error loading {filepath.name}/{sheet_name}: {e}")
        return pd.DataFrame()


def create_master_workbook():
    """Create the consolidated master workbook."""
    print("=" * 60)
    print("AFL MASTER WORKBOOK CREATOR")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    sheets = {}
    
    # ========== PLAYER DATA ==========
    print("📊 Loading PLAYER DATA...")
    
    # 1. Players_2025_Squad (808 players - full squads)
    print("  Loading Players_2025_Squad...")
    df = load_sheet_safe(PLAYER_RATINGS_FILE, "2025 AFL Squads")
    if not df.empty:
        sheets["Players_2025_Squad"] = df
        print(f"    ✓ {len(df)} players")
    
    # 2-6. Player Stats by Year (2021-2025)
    for year in [2025, 2024, 2023, 2022, 2021]:
        print(f"  Loading Players_{year}_Stats...")
        df = load_sheet_safe(PLAYER_RATINGS_FILE, str(year))
        if not df.empty:
            sheets[f"Players_{year}_Stats"] = df
            print(f"    ✓ {len(df)} players, {len(df.columns)} columns")
    
    # 7. Historical 2012-2020 (consolidated)
    print("  Loading Players_2012_2020...")
    historical_dfs = []
    for year in range(2012, 2021):
        df = load_sheet_safe(PLAYER_RATINGS_FILE, str(year))
        if not df.empty:
            df["Season"] = year
            historical_dfs.append(df)
    if historical_dfs:
        df_hist = pd.concat(historical_dfs, ignore_index=True)
        sheets["Players_2012_2020"] = df_hist
        print(f"    ✓ {len(df_hist)} player-seasons")
    
    # 8. Player Summary
    print("  Loading Player_Summary...")
    df = load_sheet_safe(PLAYER_RATINGS_FILE, "Summary")
    if not df.empty:
        sheets["Player_Summary"] = df
        print(f"    ✓ {len(df)} players")
    
    # 9. Contract Expiry
    print("  Loading Player_Contracts...")
    df = load_sheet_safe(PLAYER_RATINGS_FILE, "Contract Expiry")
    if not df.empty:
        sheets["Player_Contracts"] = df
        print(f"    ✓ {len(df)} contracts")
    
    # 10. Draft Data
    print("  Loading Player_Draft...")
    df = load_sheet_safe(PLAYER_RATINGS_FILE, "Draft Data")
    if not df.empty:
        sheets["Player_Draft"] = df
        print(f"    ✓ {len(df)} draft records")
    
    # 11-14. Traits data
    print("  Loading Player_Traits...")
    for year in [2025, 2024, 2023]:
        df = load_sheet_safe(TRAITS_FILE, str(year))
        if not df.empty:
            sheets[f"Player_Traits_{year}"] = df
            print(f"    ✓ {year}: {len(df)} players, {len(df.columns)} traits")
    
    # Historical traits (2021-2022)
    historical_traits = []
    for year in [2022, 2021]:
        df = load_sheet_safe(TRAITS_FILE, str(year))
        if not df.empty:
            df["Season"] = year
            historical_traits.append(df)
    if historical_traits:
        df_traits_hist = pd.concat(historical_traits, ignore_index=True)
        sheets["Player_Traits_Historical"] = df_traits_hist
        print(f"    ✓ Historical: {len(df_traits_hist)} player-seasons")
    
    # 15. Player Registry
    print("  Loading Player_Registry...")
    df = load_sheet_safe(PLAYER_REGISTRY_FILE, "player_registry")
    if not df.empty:
        sheets["Player_Registry"] = df
        print(f"    ✓ {len(df)} players")
    
    # 16. Wings
    print("  Loading Wings...")
    df = load_sheet_safe(PLAYER_RATINGS_FILE, "Wings")
    if not df.empty:
        sheets["Wings"] = df
        print(f"    ✓ {len(df)} wing players")
    
    # ========== TEAM DATA ==========
    print()
    print("📊 Loading TEAM DATA...")
    
    # 17. Teams 2025 Summary
    print("  Loading Teams_2025_Summary...")
    df = load_sheet_safe(TEAM_RATINGS_FILE, "2025 Summary")
    if not df.empty:
        sheets["Teams_2025_Summary"] = df
        print(f"    ✓ {len(df)} teams")
    
    # 18. Teams 2025 Full
    print("  Loading Teams_2025_Full...")
    df = load_sheet_safe(TEAM_RATINGS_FILE, "2025")
    if not df.empty:
        sheets["Teams_2025_Full"] = df
        print(f"    ✓ {len(df)} teams, {len(df.columns)} columns")
    
    # 19-20. Team Summaries by Year
    for year in [2024, 2023]:
        print(f"  Loading Teams_{year}_Summary...")
        df = load_sheet_safe(TEAM_RATINGS_FILE, f"{year} Summary")
        if not df.empty:
            sheets[f"Teams_{year}_Summary"] = df
            print(f"    ✓ {len(df)} teams")
    
    # 21. Historical team data (2021-2022)
    print("  Loading Teams_Historical...")
    historical_teams = []
    for year in [2022, 2021]:
        df = load_sheet_safe(TEAM_RATINGS_FILE, f"{year} Summary")
        if not df.empty:
            df["Season"] = year
            historical_teams.append(df)
    if historical_teams:
        df_teams_hist = pd.concat(historical_teams, ignore_index=True)
        sheets["Teams_Historical"] = df_teams_hist
        print(f"    ✓ {len(df_teams_hist)} team-seasons")
    
    # 22. Team Ladders All
    print("  Loading Team_Ladders_All...")
    df = load_sheet_safe(LADDERS_FILE, "Sheet1")
    if not df.empty:
        sheets["Team_Ladders_All"] = df
        print(f"    ✓ {len(df)} ladder records (2011-2025)")
    
    # 23. Team Reference
    print("  Loading Team_Reference...")
    df = load_sheet_safe(CD_TEAM_IDS_FILE, "Sheet1")
    if not df.empty:
        sheets["Team_Reference"] = df
        print(f"    ✓ {len(df)} teams")
    
    # ========== REFERENCE DATA ==========
    print()
    print("📊 Loading REFERENCE DATA...")
    
    # 24. Champion Data IDs
    print("  Loading Champion_Data_IDs...")
    df = load_sheet_safe(CD_PLAYER_IDS_FILE, "Sheet1")
    if not df.empty:
        sheets["Champion_Data_IDs"] = df
        print(f"    ✓ {len(df)} player IDs")
    
    # 25. Wheelo Player Data
    print("  Loading Wheelo_Player_Data...")
    df = load_sheet_safe(WHEELO_PLAYER_FILE, "Sheet1")
    if not df.empty:
        sheets["Wheelo_Player_Data"] = df
        print(f"    ✓ {len(df)} players, {len(df.columns)} metrics")
    
    # 26. Wheelo Team Data
    print("  Loading Wheelo_Team_Data...")
    df = load_sheet_safe(WHEELO_TEAM_FILE, "Sheet1")
    if not df.empty:
        sheets["Wheelo_Team_Data"] = df
        print(f"    ✓ {len(df)} teams, {len(df.columns)} metrics")
    
    # 27. Metadata
    print("  Creating Metadata...")
    metadata = pd.DataFrame({
        "Field": [
            "Workbook_Name",
            "Created_Date",
            "Data_Through_Season",
            "Total_Sheets",
            "Source_Files",
            "Description",
            "Version",
            "Notes"
        ],
        "Value": [
            "AFL_Master_2012_2025.xlsx",
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "2025",
            str(len(sheets) + 1),  # +1 for metadata itself
            "AFL Player Ratings.xlsx, AFL Team Ratings.xlsx, 2025 Traits ENRICHED.xlsx, Wheelo files, Ladders, Champion Data IDs",
            "Consolidated AFL data source - single source of truth for historical data through 2025 season",
            "1.0",
            "Contains all player stats, traits, team stats, ladders, and reference data"
        ]
    })
    sheets["Metadata"] = metadata
    print(f"    ✓ Created")
    
    # ========== WRITE OUTPUT ==========
    print()
    print("=" * 60)
    print(f"📝 Writing {OUTPUT_FILE.name}...")
    print(f"   Total sheets: {len(sheets)}")
    
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"   ✓ {sheet_name}: {len(df)} rows")
    
    print()
    print("=" * 60)
    print(f"✅ COMPLETE: {OUTPUT_FILE}")
    print(f"   File size: {OUTPUT_FILE.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"   Total sheets: {len(sheets)}")
    print("=" * 60)
    
    # Print summary
    print()
    print("SHEET SUMMARY:")
    print("-" * 40)
    for i, (name, df) in enumerate(sheets.items(), 1):
        print(f"{i:2d}. {name}: {len(df):,} rows x {len(df.columns)} cols")


if __name__ == "__main__":
    create_master_workbook()
