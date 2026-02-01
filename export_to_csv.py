"""
Export Excel Data to CSV
Converts Excel workbooks to clean CSV files for the data pipeline.
"""

import pandas as pd
from pathlib import Path
import sys

# Project paths
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"

# Excel files
TEAM_FILE = "AFL Team Ratings.xlsx"
PLAYER_FILE = "AFL Player Ratings.xlsx"
TRAITS_FILE = "2025 Traits ENRICHED.xlsx"
WHEELO_TEAM_FILE = "Wheelo_Team_Data.xlsx"
WHEELO_PLAYER_FILE = "Wheelo_Player_Data.xlsx"


def export_team_raw_data(seasons: list[int] = None):
    """Export raw team data sheets to CSV."""
    print("\n📊 Exporting Team Raw Data...")
    
    xl = pd.ExcelFile(TEAM_FILE)
    output_dir = RAW_DIR / "team"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if seasons is None:
        # Auto-discover season sheets (4-digit years)
        seasons = [int(s) for s in xl.sheet_names if str(s).isdigit() and len(str(s)) == 4]
    
    for season in seasons:
        sheet_name = str(season)
        if sheet_name not in xl.sheet_names:
            print(f"   ⚠️ Sheet {sheet_name} not found")
            continue
        
        df = xl.parse(sheet_name)
        output_path = output_dir / f"team_stats_{season}.csv"
        df.to_csv(output_path, index=False)
        print(f"   ✅ {output_path.name}: {len(df)} rows, {len(df.columns)} columns")
    
    # Also export L10 if available
    if "L10" in xl.sheet_names:
        df = xl.parse("L10")
        output_path = output_dir / "team_stats_L10.csv"
        df.to_csv(output_path, index=False)
        print(f"   ✅ {output_path.name}: {len(df)} rows")


def export_player_raw_data(seasons: list[int] = None):
    """Export raw player data sheets to CSV."""
    print("\n👤 Exporting Player Raw Data...")
    
    xl = pd.ExcelFile(PLAYER_FILE)
    output_dir = RAW_DIR / "player"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if seasons is None:
        # Auto-discover season sheets (4-digit years)
        seasons = [int(s) for s in xl.sheet_names if str(s).isdigit() and len(str(s)) == 4]
    
    for season in seasons:
        sheet_name = str(season)
        if sheet_name not in xl.sheet_names:
            print(f"   ⚠️ Sheet {sheet_name} not found")
            continue
        
        df = xl.parse(sheet_name)
        output_path = output_dir / f"player_stats_{season}.csv"
        df.to_csv(output_path, index=False)
        print(f"   ✅ {output_path.name}: {len(df)} rows, {len(df.columns)} columns")
    
    # Export supporting sheets
    support_sheets = {
        "2025 AFL Squads": "squads_2025.csv",
        "Draft Data": "draft_data.csv",
        "Contract Expiry": "contract_expiry.csv",
    }
    
    for sheet_name, filename in support_sheets.items():
        if sheet_name in xl.sheet_names:
            df = xl.parse(sheet_name)
            output_path = output_dir / filename
            df.to_csv(output_path, index=False)
            print(f"   ✅ {filename}: {len(df)} rows")


def export_traits_data():
    """Export traits data to CSV (already clean - no formulas)."""
    print("\n🎯 Exporting Traits Data...")
    
    if not Path(TRAITS_FILE).exists():
        print(f"   ❌ File not found: {TRAITS_FILE}")
        return
    
    xl = pd.ExcelFile(TRAITS_FILE)
    output_dir = RAW_DIR / "traits"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name)
        
        # Clean column names
        df.columns = [str(c).strip() for c in df.columns]
        
        output_path = output_dir / f"traits_{sheet_name}.csv"
        df.to_csv(output_path, index=False)
        print(f"   ✅ {output_path.name}: {len(df)} rows, {len(df.columns)} columns")


def export_wheelo_data():
    """Export Wheelo external data to CSV (already clean - no formulas)."""
    print("\n📈 Exporting Wheelo Data...")
    
    output_dir = RAW_DIR / "external"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    files = [
        (WHEELO_TEAM_FILE, "wheelo_team_ratings.csv"),
        (WHEELO_PLAYER_FILE, "wheelo_player_ratings.csv"),
    ]
    
    for excel_file, csv_name in files:
        if not Path(excel_file).exists():
            print(f"   ⚠️ File not found: {excel_file}")
            continue
        
        xl = pd.ExcelFile(excel_file)
        # Usually just one sheet
        df = xl.parse(xl.sheet_names[0])
        
        output_path = output_dir / csv_name
        df.to_csv(output_path, index=False)
        print(f"   ✅ {csv_name}: {len(df)} rows, {len(df.columns)} columns")


def export_snapshots():
    """Export current Excel computed sheets as validation snapshots."""
    print("\n📸 Exporting Validation Snapshots...")
    
    output_dir = DATA_DIR / "snapshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Team ladders (computed by Excel formulas)
    xl = pd.ExcelFile(TEAM_FILE)
    
    snapshot_sheets = [
        "2025 Ladders",
        "2025 Ladders (L10)",
        "2025 Summary",
    ]
    
    for sheet_name in snapshot_sheets:
        if sheet_name not in xl.sheet_names:
            continue
        
        df = xl.parse(sheet_name)
        
        # Find header row (contains "Team")
        for i, row in df.iterrows():
            if "Team" in str(row.values):
                df.columns = df.iloc[i]
                df = df.iloc[i+1:].reset_index(drop=True)
                break
        
        df = df.dropna(how='all')
        
        safe_name = sheet_name.replace(" ", "_").replace("(", "").replace(")", "")
        output_path = output_dir / f"snapshot_{safe_name}.csv"
        df.to_csv(output_path, index=False)
        print(f"   ✅ {output_path.name}: {len(df)} rows")


def show_summary():
    """Show summary of exported files."""
    print("\n" + "="*70)
    print("EXPORT SUMMARY")
    print("="*70)
    
    for subdir in ["raw/team", "raw/player", "raw/traits", "raw/external", "computed", "snapshots"]:
        dir_path = DATA_DIR / subdir
        if dir_path.exists():
            files = list(dir_path.glob("*.csv"))
            total_size = sum(f.stat().st_size for f in files) / 1024  # KB
            print(f"\n📁 data/{subdir}/")
            for f in sorted(files):
                size_kb = f.stat().st_size / 1024
                print(f"   {f.name}: {size_kb:.1f} KB")
            print(f"   Total: {len(files)} files, {total_size:.1f} KB")


def main():
    print("="*70)
    print("AFL DASHBOARD - EXCEL TO CSV EXPORT")
    print("="*70)
    
    # Export all data
    export_team_raw_data()
    export_player_raw_data()
    export_traits_data()
    export_wheelo_data()
    export_snapshots()
    
    # Show summary
    show_summary()
    
    print("\n✅ Export complete!")
    print("   CSV files are now in the data/ directory")
    print("   You can delete the Excel files once verified")


if __name__ == "__main__":
    main()
