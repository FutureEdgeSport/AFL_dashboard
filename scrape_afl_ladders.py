"""
AFL Ladder Scraper
Scrapes AFL ladder data from FootyWire for seasons 2011-2024
Saves to Excel file for use in the dashboard
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime

def scrape_ladder(year):
    """Scrape AFL ladder for a specific year"""
    url = f"https://www.footywire.com/afl/footy/ft_ladder?year={year}"
    
    try:
        print(f"Scraping {year} ladder...")
        response = requests.get(url, headers={
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
    print("=" * 60)
    print("AFL LADDER SCRAPER")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Years to scrape (2011 to 2025)
    start_year = 2011
    end_year = 2025
    
    all_ladders = []
    
    for year in range(start_year, end_year + 1):
        df = scrape_ladder(year)
        
        if df is not None:
            all_ladders.append(df)
        
        # Be polite - don't hammer the server
        if year < end_year:
            time.sleep(1)
    
    if not all_ladders:
        print("\n⚠️  No data scraped!")
        return
    
    # Combine all years
    print("\n" + "=" * 60)
    print("COMBINING DATA")
    print("=" * 60)
    
    combined_df = pd.concat(all_ladders, ignore_index=True)
    
    # Save to Excel
    output_file = 'afl_ladders_2011_2025.xlsx'
    combined_df.to_excel(output_file, index=False)
    
    print(f"\n✓ Saved {len(combined_df)} rows to {output_file}")
    print(f"  - Years: {start_year}-{end_year}")
    print(f"  - Total seasons: {len(all_ladders)}")
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
