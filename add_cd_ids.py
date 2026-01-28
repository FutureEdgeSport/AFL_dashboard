#!/usr/bin/env python3
"""
Add Champion Data IDs to any spreadsheet with player names.

Usage:
    python add_cd_ids.py <spreadsheet.xlsx> [options]

Examples:
    python add_cd_ids.py my_players.xlsx
    python add_cd_ids.py my_players.xlsx --name-column "Player"
    python add_cd_ids.py my_players.xlsx --name-column "Full Name" --output updated.xlsx
    python add_cd_ids.py my_players.xlsx --sheet "Squad List"
"""

import argparse
import pandas as pd
from pathlib import Path
import sys

# Path to the CD IDs lookup file
CD_IDS_FILE = Path(__file__).parent / "champion_data_player_ids.xlsx"


def normalize_name(name):
    """Normalize player name for matching"""
    if pd.isna(name):
        return ""
    return str(name).strip().lower().replace("'", "'").replace("'", "'")


def load_cd_lookup():
    """Load the Champion Data IDs lookup table"""
    if not CD_IDS_FILE.exists():
        print(f"❌ Error: CD IDs file not found: {CD_IDS_FILE}")
        print("   Run scrape_cd_player_ids.py first to create it.")
        sys.exit(1)
    
    df = pd.read_excel(CD_IDS_FILE)
    
    # Create lookup dictionary by normalized name
    lookup = {}
    for _, row in df.iterrows():
        name = normalize_name(row.get('full_name'))
        if name and pd.notna(row.get('champion_data_id')):
            lookup[name] = int(row['champion_data_id'])
    
    return lookup


def find_name_column(df, hint=None):
    """Find the column most likely to contain player names"""
    if hint:
        # Check for exact match (case-insensitive)
        for col in df.columns:
            if col.lower() == hint.lower():
                return col
        # Check for partial match
        for col in df.columns:
            if hint.lower() in col.lower():
                return col
        print(f"⚠️  Warning: Column '{hint}' not found. Searching automatically...")
    
    # Common name column patterns
    name_patterns = [
        'full_name', 'fullname', 'player_name', 'playername', 'player',
        'name', 'athlete', 'full name', 'player name'
    ]
    
    for pattern in name_patterns:
        for col in df.columns:
            if pattern in col.lower():
                return col
    
    # If still not found, look for columns with typical name data
    for col in df.columns:
        sample = df[col].dropna().head(10).astype(str)
        # Names typically have spaces and are strings
        if sample.str.contains(' ').mean() > 0.5:
            return col
    
    return None


def add_cd_ids(input_file, name_column=None, output_file=None, sheet_name=0):
    """Add Champion Data IDs to a spreadsheet"""
    
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Error: File not found: {input_file}")
        sys.exit(1)
    
    # Load lookup
    print("📂 Loading Champion Data IDs lookup...")
    lookup = load_cd_lookup()
    print(f"   Loaded {len(lookup)} player IDs")
    
    # Load input file
    print(f"\n📊 Loading {input_file}...")
    if input_path.suffix.lower() == '.csv':
        df = pd.read_csv(input_file)
    else:
        df = pd.read_excel(input_file, sheet_name=sheet_name)
    print(f"   Loaded {len(df)} rows")
    
    # Find name column
    name_col = find_name_column(df, name_column)
    if not name_col:
        print("❌ Error: Could not find a player name column.")
        print(f"   Available columns: {list(df.columns)}")
        print("   Use --name-column to specify which column contains player names.")
        sys.exit(1)
    print(f"   Using name column: '{name_col}'")
    
    # Check if champion_data_id already exists
    if 'champion_data_id' in df.columns:
        existing = df['champion_data_id'].notna().sum()
        print(f"   ⚠️  'champion_data_id' column already exists ({existing} values)")
        response = input("   Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("   Cancelled.")
            return
    
    # Add CD IDs
    print("\n🔗 Matching players...")
    matched = 0
    unmatched = []
    
    cd_ids = []
    for idx, row in df.iterrows():
        name = normalize_name(row[name_col])
        if name in lookup:
            cd_ids.append(lookup[name])
            matched += 1
        else:
            cd_ids.append(None)
            if name:
                unmatched.append(row[name_col])
    
    df['champion_data_id'] = cd_ids
    
    print(f"   ✅ Matched: {matched}")
    print(f"   ❌ Unmatched: {len(unmatched)}")
    
    if unmatched and len(unmatched) <= 20:
        print("\n   Unmatched players:")
        for name in unmatched:
            print(f"      - {name}")
    elif unmatched:
        print(f"\n   First 10 unmatched: {unmatched[:10]}")
    
    # Save
    if output_file is None:
        output_file = input_path.stem + "_with_cd_ids" + input_path.suffix
    
    output_path = Path(output_file)
    print(f"\n💾 Saving to {output_file}...")
    
    if output_path.suffix.lower() == '.csv':
        df.to_csv(output_file, index=False)
    else:
        df.to_excel(output_file, index=False)
    
    print(f"   ✅ Done! {matched} players now have Champion Data IDs.")
    
    # Show sample
    print("\n📋 Sample output:")
    sample_cols = [name_col, 'champion_data_id']
    if 'team' in df.columns:
        sample_cols.insert(1, 'team')
    print(df[sample_cols].head(10).to_string())


def main():
    parser = argparse.ArgumentParser(
        description="Add Champion Data IDs to any spreadsheet with player names.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python add_cd_ids.py wheelo_ratings.xlsx
  python add_cd_ids.py my_players.xlsx --name-column "Player"
  python add_cd_ids.py squad.xlsx --name-column "Full Name" --output squad_updated.xlsx
  python add_cd_ids.py multi_sheet.xlsx --sheet "2025 Squad"
        """
    )
    
    parser.add_argument('input_file', help='Input spreadsheet (.xlsx or .csv)')
    parser.add_argument('--name-column', '-n', help='Column containing player names')
    parser.add_argument('--output', '-o', help='Output file (default: input_with_cd_ids.xlsx)')
    parser.add_argument('--sheet', '-s', default=0, help='Sheet name or index (default: first sheet)')
    
    args = parser.parse_args()
    
    # Handle sheet name/index
    sheet = args.sheet
    if isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)
    
    add_cd_ids(args.input_file, args.name_column, args.output, sheet)


if __name__ == "__main__":
    main()
