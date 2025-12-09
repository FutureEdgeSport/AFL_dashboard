"""
AFL Ladder Scraper
Scrapes AFL ladder data from footywire.com for seasons 2011 onwards
Saves data to CSV and Excel files
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
        response = requests.get(url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the ladder table
        table = soup.find('table', {'class': 'tbtitle'})
        
        if not table:
            print(f"  Warning: No table found for {year}")
            return None
        
        # Extract headers
        headers = []
        header_row = table.find('tr')
        if header_row:
            for th in header_row.find_all('td'):
                headers.append(th.text.strip())
        
        # Extract data rows
        data = []
        rows = table.find_all('tr')[1:]  # Skip header row
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) > 0:
                row_data = [col.text.strip() for col in cols]
                # Add year to each row
                row_data.insert(0, year)
                data.append(row_data)
        
        if data:
            print(f"  ✓ Found {len(data)} teams")
            return data, headers
        else:
            print(f"  Warning: No data found for {year}")
            return None
            
    except Exception as e:
        print(f"  Error scraping {year}: {e}")
        return None

def main():
    """Main function to scrape all years and save to files"""
    
    # Years to scrape (2011 to current year)
    current_year = datetime.now().year
    years = range(2011, current_year + 1)
    
    all_data = []
    headers = None
    
    for year in years:
        result = scrape_ladder(year)
        
        if result:
            data, year_headers = result
            if headers is None:
                headers = ['Year'] + year_headers
            all_data.extend(data)
        
        # Be polite to the server
        time.sleep(1)
    
    if not all_data:
        print("\nNo data scraped. Exiting.")
        return
    
    # Create DataFrame
    print(f"\nCreating dataframe with {len(all_data)} rows...")
    df = pd.DataFrame(all_data, columns=headers)
    
    # Clean up column names
    df.columns = df.columns.str.strip()
    
    # Save to CSV
    csv_filename = 'afl_ladder_data.csv'
    df.to_csv(csv_filename, index=False)
    print(f"✓ Saved to {csv_filename}")
    
    # Save to Excel
    try:
        excel_filename = 'afl_ladder_data.xlsx'
        df.to_excel(excel_filename, index=False, sheet_name='AFL Ladders')
        print(f"✓ Saved to {excel_filename}")
    except Exception as e:
        print(f"Note: Could not save Excel file: {e}")
        print("  (You may need to install openpyxl: pip install openpyxl)")
    
    # Display summary
    print(f"\nSummary:")
    print(f"  Years scraped: {df['Year'].min()} to {df['Year'].max()}")
    print(f"  Total rows: {len(df)}")
    print(f"  Columns: {', '.join(df.columns)}")
    
    # Show sample data
    print(f"\nSample data (first 5 rows):")
    print(df.head())
    
    print("\n✓ Scraping complete!")

if __name__ == "__main__":
    main()
