"""
AFL Ladder Scraper
Scrapes AFL ladder data from FootyWire for seasons 2011 to current
Saves to Excel file for use in the dashboard

Flags:
  --current-only   Only scrape the current season (fast incremental mode)
"""

import argparse
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime
from pathlib import Path
from config.constants import CURRENT_SEASON
from utils.http_utils import create_retry_session
from utils.safe_io import safe_excel_write

# Shared HTTP session with retry logic
_session = create_retry_session(retries=3, backoff_factor=1.0, timeout=15)

def scrape_ladder(year):
    """Scrape AFL ladder for a specific year"""
    url = f"https://www.footywire.com/afl/footy/ft_ladder?year={year}"
    
    try:
        print(f"Scraping {year} ladder...")
        response = _session.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all tables and look for the actual ladder table
        # The ladder data is in a table with Position, Team, Played, etc. columns
        tables = soup.find_all('table')
        
        table = None
        for t in tables:
            rows = t.find_all('tr')
            if len(rows) > 1:
                # Check if first row contains ladder headers
                first_row_text = rows[0].get_text()
                if 'Position' in first_row_text and 'Team' in first_row_text and 'Played' in first_row_text:
                    table = t
                    break
        
        if not table:
            print(f"  ⚠️  No ladder table found for {year}")
            return None
        
        # Parse the table
        rows = table.find_all('tr')
        
        # Extract headers from first row
        headers = []
        if len(rows) > 0:
            header_cells = rows[0].find_all(['th', 'td'])
            headers = [cell.text.strip() for cell in header_cells]
        
        # Extract data rows (skip header row)
        data = []
        for row in rows[1:]:
            cells = row.find_all(['th', 'td'])
            if len(cells) >= len(headers):  # Valid data row
                row_data = [cells[i].text.strip() for i in range(len(headers))]
                # Check if this is a real team row (not empty or separator)
                if row_data and row_data[0] and row_data[0].isdigit():
                    data.append(row_data)
        
        if not data:
            print(f"  ⚠️  No data found for {year}")
            return None
        
        df = pd.DataFrame(data, columns=headers)
        df['Season'] = year
        
        print(f"  ✓ Successfully scraped {len(df)} teams for {year}")
        return df
        
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Error scraping {year}: {e}")
        return None
    except Exception as e:
        print(f"  ✗ Unexpected error for {year}: {e}")
        return None

def main():
    """Main scraping function"""
    parser = argparse.ArgumentParser(description="Scrape AFL ladder data from FootyWire")
    parser.add_argument("--current-only", action="store_true",
                        help="Only scrape the current season (fast incremental mode)")
    args = parser.parse_args()

    print("=" * 60)
    print("AFL LADDER SCRAPER")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'CURRENT ONLY' if args.current_only else 'FULL (2011-present)'}\n")

    # Years to scrape
    start_year = 2011
    end_year = CURRENT_SEASON

    if args.current_only:
        # In incremental mode, only scrape the current season and merge
        # with the existing file for historical data
        years_to_scrape = [end_year]
    else:
        years_to_scrape = list(range(start_year, end_year + 1))

    all_ladders = []

    for year in years_to_scrape:
        df = scrape_ladder(year)
        
        if df is not None:
            all_ladders.append(df)
        
        # Be polite - don't hammer the server
        if year < end_year:
            time.sleep(1)
    
    if not all_ladders:
        print("\n⚠️  No data scraped!")
        return
    
    # Combine scraped data
    print("\n" + "=" * 60)
    print("COMBINING DATA")
    print("=" * 60)
    
    scraped_df = pd.concat(all_ladders, ignore_index=True)

    # In --current-only mode, merge with existing historical data
    output_dir = Path('data')
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f'afl_ladders_2011_{end_year}.xlsx'
    legacy_file = Path('afl_ladders_2011_2025.xlsx')

    if args.current_only and output_file.exists():
        existing_df = pd.read_excel(output_file)
        # Drop existing rows for the current season and replace with fresh
        existing_df = existing_df[existing_df['Season'] != end_year]
        combined_df = pd.concat([existing_df, scraped_df], ignore_index=True)
        print(f"  Merged: {len(existing_df)} historical + {len(scraped_df)} fresh = {len(combined_df)} total")
    elif args.current_only and legacy_file.exists():
        existing_df = pd.read_excel(legacy_file)
        existing_df = existing_df[existing_df['Season'] != end_year]
        combined_df = pd.concat([existing_df, scraped_df], ignore_index=True)
        print(f"  Merged: {len(existing_df)} historical + {len(scraped_df)} fresh = {len(combined_df)} total")
    else:
        combined_df = scraped_df
    
    # Save to Excel (atomic write with backup)
    safe_excel_write(combined_df, output_file)
    safe_excel_write(combined_df, legacy_file)
    
    n_seasons = combined_df['Season'].nunique()
    yr_min = int(combined_df['Season'].min())
    yr_max = int(combined_df['Season'].max())
    print(f"\n✓ Saved {len(combined_df)} rows to {output_file}")
    print(f"  - Years: {yr_min}-{yr_max}")
    print(f"  - Total seasons: {n_seasons}")
    print(f"  - Columns: {', '.join(combined_df.columns.tolist())}")
    
    # Display summary
    print("\n" + "=" * 60)
    print("SUMMARY BY SEASON")
    print("=" * 60)
    season_counts = combined_df['Season'].value_counts().sort_index()
    for year, count in season_counts.items():
        print(f"  {year}: {count} teams")
    
    print("\n" + "=" * 60)
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

if __name__ == "__main__":
    main()
