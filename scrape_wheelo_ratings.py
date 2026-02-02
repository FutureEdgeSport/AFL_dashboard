#!/usr/bin/env python3
"""
Wheelo Ratings Scraper
======================
Scrapes AFL statistics from wheeloratings.com and updates Excel spreadsheets.

Usage:
    python scrape_wheelo_ratings.py              # Interactive menu
    python scrape_wheelo_ratings.py --all        # Download all data
    python scrape_wheelo_ratings.py --team       # Download team stats only
    python scrape_wheelo_ratings.py --player     # Download player stats only
    python scrape_wheelo_ratings.py --squads     # Download squad lists only

Data Sources:
    - Team Stats: https://www.wheeloratings.com/afl_stats_team.html
    - Player Stats: https://www.wheeloratings.com/afl_stats.html  
    - Squad Lists: https://www.wheeloratings.com/afl_team_lists.html

Output Files (SEPARATE from main app files to avoid corruption):
    - Wheelo_Team_Data.xlsx (team statistics)
    - Wheelo_Player_Data.xlsx (player statistics and squad lists)
    
NOTE: This scraper saves to SEPARATE Excel files to avoid corrupting the main
      AFL Team Ratings.xlsx and AFL Player Ratings.xlsx files. openpyxl strips
      Excel features like conditional formatting when saving, which breaks the app.

Sheet Naming Conventions:
    Wheelo_Team_Data.xlsx:
        - "Wheelo 2025 Season" for full season data
        - "Wheelo 2025 L10" for last 10 games
        - "Wheelo 2025 L5" for last 5 games
        
    Wheelo_Player_Data.xlsx:
        - "Wheelo 2025 Season" for full season data
        - "Wheelo 2025 L10" for last 10 games
        - "Wheelo 2025 L5" for last 5 games
        - "2025 AFL Squads" for squad lists
"""

import os
import sys
import time
import argparse
import shutil
from datetime import datetime
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("❌ Required packages not installed.")
    print("   Run: pip install selenium webdriver-manager")
    sys.exit(1)

try:
    import pandas as pd
    from openpyxl import load_workbook
except ImportError:
    print("❌ Required packages not installed.")
    print("   Run: pip install pandas openpyxl")
    sys.exit(1)

# Configuration
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "wheelo_downloads"
# IMPORTANT: Save to SEPARATE files to avoid corrupting the main Excel files
# openpyxl strips Excel features (conditional formatting, data validation, etc.) when saving
WHEELO_TEAM_FILE = BASE_DIR / "Wheelo_Team_Data.xlsx"
WHEELO_PLAYER_FILE = BASE_DIR / "Wheelo_Player_Data.xlsx"
# Original files (kept for reference but NOT modified by scraper)
TEAM_RATINGS_FILE = BASE_DIR / "AFL Team Ratings.xlsx"
PLAYER_RATINGS_FILE = BASE_DIR / "AFL Player Ratings.xlsx"

# URLs
URLS = {
    "team_stats": "https://www.wheeloratings.com/afl_stats_team.html",
    "player_stats": "https://www.wheeloratings.com/afl_stats.html",
    "squad_lists": "https://www.wheeloratings.com/afl_team_lists.html"
}

# Season button texts and corresponding sheet names
# NOTE: Sheet names must NOT conflict with existing sheets in the Excel files!
# The app uses: "2026 Summary", "2026 Team Summary", "2026 Ladders", etc.
# We use "Wheelo" prefix to keep scraped data separate.
SEASONS = {
    "2026": {"team_sheet": "Wheelo 2026 Season", "player_sheet": "Wheelo 2026 Season"},
    "Last 10 games": {"team_sheet": "Wheelo 2026 L10", "player_sheet": "Wheelo 2026 L10"},
    "Last 5 games": {"team_sheet": "Wheelo 2026 L5", "player_sheet": "Wheelo 2026 L5"}
}


class WheeloScraper:
    def __init__(self, headless=True):
        """Initialize the scraper with Selenium WebDriver."""
        self.headless = headless
        self.driver = None
        
        # Create download directory
        DOWNLOAD_DIR.mkdir(exist_ok=True)
        
    def _setup_driver(self):
        """Set up Chrome WebDriver with download preferences."""
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")  # New headless mode in Chrome
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        
        # Configure download directory
        prefs = {
            "download.default_directory": str(DOWNLOAD_DIR.absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,  # Disable safebrowsing which can block downloads
            "safebrowsing.disable_download_protection": True
        }
        options.add_experimental_option("prefs", prefs)
        
        print("🔧 Setting up Chrome driver...")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        
        # Enable downloads in headless mode (Chrome 77+)
        self.driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(DOWNLOAD_DIR.absolute())
        })
        
        print("✅ Chrome driver ready")
        
    def _close_driver(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            
    def _click_season_button(self, season_text):
        """Click the season button matching the given text."""
        # Find all buttons in the nav-pills container
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "div.nav.nav-pills button")
        
        for btn in buttons:
            if btn.text.strip() == season_text:
                # Scroll to button and use JavaScript click to avoid interception
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.3)
                self.driver.execute_script("arguments[0].click();", btn)
                print(f"  📅 Selected: {season_text}")
                time.sleep(2)  # Wait for data to reload
                return True
                
        print(f"  ⚠️ Could not find button: {season_text}")
        return False
    
    def _wait_for_download(self, timeout=30, pre_download_files=None, debug=False):
        """Wait for download to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            pre_download_files: Set of file paths that existed before download started
            debug: Print debug information
        """
        if pre_download_files is None:
            pre_download_files = set()
        wait_start = time.time()
        
        while time.time() - wait_start < timeout:
            # Get all current CSV files (excluding any weird downloads.html files)
            current_files = {f for f in DOWNLOAD_DIR.glob("*.csv") if not f.name.startswith("downloads")}
            
            # Check for downloading files (CSV only)
            downloading = [f for f in DOWNLOAD_DIR.glob("*.crdownload") if not f.name.startswith("downloads")]
            
            # Find new files (files that weren't there before)
            new_files = current_files - pre_download_files
            
            if debug:
                print(f"    DEBUG: pre={[f.name for f in pre_download_files]}, current={[f.name for f in current_files]}, new={[f.name for f in new_files]}, downloading={[f.name for f in downloading]}")
            
            if new_files and not downloading:
                # Return the newest file
                new_file = max(new_files, key=lambda x: x.stat().st_mtime)
                return new_file
                
            time.sleep(0.5)
            
        return None
    
    def _get_current_csv_files(self):
        """Get set of current CSV file paths in download directory."""
        return set(DOWNLOAD_DIR.glob("*.csv"))
    
    def _click_download_button(self):
        """Click the Download as CSV button."""
        try:
            btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "download-csv-button"))
            )
            # Scroll to button to ensure it's visible
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.5)
            
            # Use JavaScript click to avoid "element click intercepted" error
            self.driver.execute_script("arguments[0].click();", btn)
            print("  📥 Download button clicked")
            return True
        except Exception as e:
            print(f"  ❌ Failed to click download: {e}")
            return False
    
    def _clear_downloads(self):
        """Clear old CSV files from download directory."""
        for f in DOWNLOAD_DIR.glob("*.csv"):
            f.unlink()
        # Also clean up any temp download files
        for f in DOWNLOAD_DIR.glob("downloads.html*"):
            f.unlink()
        for f in DOWNLOAD_DIR.glob("*.crdownload"):
            f.unlink()
            
    def download_team_stats(self, seasons=None):
        """Download team statistics for specified seasons."""
        if seasons is None:
            seasons = list(SEASONS.keys())
            
        print("\n" + "="*60)
        print("📊 DOWNLOADING TEAM STATS")
        print("="*60)
        
        downloaded_files = {}
        
        # Clear downloads at the start
        self._clear_downloads()
        
        self._setup_driver()
        try:
            self.driver.get(URLS["team_stats"])
            time.sleep(3)
            
            for season in seasons:
                print(f"\n  Processing: {season}")
                
                # Click season button
                if not self._click_season_button(season):
                    continue
                
                # Record existing files before download (as Path objects)
                pre_download_files = self._get_current_csv_files()
                
                # Click download
                if not self._click_download_button():
                    continue
                    
                # Wait for download (only NEW files)
                csv_file = self._wait_for_download(pre_download_files=pre_download_files)
                if csv_file:
                    # Rename file for clarity
                    sheet_name = SEASONS[season]["team_sheet"]
                    new_name = DOWNLOAD_DIR / f"team_stats_{sheet_name.replace(' ', '_').replace('(', '').replace(')', '')}.csv"
                    if new_name.exists():
                        new_name.unlink()
                    csv_file.rename(new_name)
                    downloaded_files[season] = new_name
                    print(f"  ✅ Downloaded: {new_name.name}")
                else:
                    print(f"  ❌ Download timed out for {season}")
                    
        finally:
            self._close_driver()
            
        return downloaded_files
    
    def download_player_stats(self, seasons=None):
        """Download player statistics for specified seasons."""
        if seasons is None:
            seasons = list(SEASONS.keys())
            
        print("\n" + "="*60)
        print("📊 DOWNLOADING PLAYER STATS")
        print("="*60)
        
        downloaded_files = {}
        
        # Clear downloads at the start
        self._clear_downloads()
        
        self._setup_driver()
        try:
            self.driver.get(URLS["player_stats"])
            time.sleep(3)
            
            for season in seasons:
                print(f"\n  Processing: {season}")
                
                # Scroll to top before clicking season button
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.5)
                
                # Click season button
                if not self._click_season_button(season):
                    continue
                
                # Record existing files before download (as Path objects)
                pre_download_files = self._get_current_csv_files()
                
                # Click download
                if not self._click_download_button():
                    continue
                    
                # Wait for download (only NEW files)
                csv_file = self._wait_for_download(pre_download_files=pre_download_files)
                if csv_file:
                    # Rename file for clarity
                    sheet_name = SEASONS[season]["player_sheet"]
                    new_name = DOWNLOAD_DIR / f"player_stats_{sheet_name.replace(' ', '_').replace('(', '').replace(')', '')}.csv"
                    if new_name.exists():
                        new_name.unlink()
                    csv_file.rename(new_name)
                    downloaded_files[season] = new_name
                    print(f"  ✅ Downloaded: {new_name.name}")
                else:
                    print(f"  ❌ Download timed out for {season}")
                    
        finally:
            self._close_driver()
            
        return downloaded_files
    
    def download_squad_lists(self):
        """Download squad/team lists."""
        print("\n" + "="*60)
        print("📊 DOWNLOADING SQUAD LISTS")
        print("="*60)
        
        # Don't clear downloads - we want to keep player stats files
        
        self._setup_driver()
        try:
            self.driver.get(URLS["squad_lists"])
            time.sleep(3)
            
            # Record existing files before download (as Path objects)
            pre_download_files = self._get_current_csv_files()
            
            # Click download
            if not self._click_download_button():
                return None
                
            # Wait for download (only NEW files)
            csv_file = self._wait_for_download(pre_download_files=pre_download_files)
            if csv_file:
                new_name = DOWNLOAD_DIR / "squad_lists.csv"
                if new_name.exists():
                    new_name.unlink()
                csv_file.rename(new_name)
                print(f"  ✅ Downloaded: {new_name.name}")
                return new_name
            else:
                print("  ❌ Download timed out")
                return None
                
        finally:
            self._close_driver()
    
    def update_team_excel(self, downloaded_files):
        """Update Wheelo Team Data file with downloaded data."""
        if not downloaded_files:
            print("  ⚠️ No files to update")
            return
            
        print(f"\n📝 Saving to: {WHEELO_TEAM_FILE.name}")
        
        # Create new Excel file with all team data (don't touch original files)
        with pd.ExcelWriter(WHEELO_TEAM_FILE, engine='openpyxl') as writer:
            for season, csv_path in downloaded_files.items():
                sheet_name = SEASONS[season]["team_sheet"]
                print(f"  Writing sheet: {sheet_name}")
                
                try:
                    df = pd.read_csv(csv_path)
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    print(f"    ✅ Written {len(df)} rows")
                except Exception as e:
                    print(f"    ❌ Error: {e}")
                    
        print(f"  💾 Saved: {WHEELO_TEAM_FILE.name}")
    
    def update_player_excel(self, downloaded_files, squad_file=None):
        """Update Wheelo Player Data file with downloaded data."""
        if not downloaded_files and not squad_file:
            print("  ⚠️ No files to update")
            return
            
        print(f"\n📝 Saving to: {WHEELO_PLAYER_FILE.name}")
        
        # Create new Excel file with all player data (don't touch original files)
        with pd.ExcelWriter(WHEELO_PLAYER_FILE, engine='openpyxl') as writer:
            # Update player stats sheets
            for season, csv_path in downloaded_files.items():
                sheet_name = SEASONS[season]["player_sheet"]
                print(f"  Writing sheet: {sheet_name}")
                
                try:
                    df = pd.read_csv(csv_path)
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    print(f"    ✅ Written {len(df)} rows")
                except Exception as e:
                    print(f"    ❌ Error: {e}")
                
            # Update squad list sheet
            if squad_file:
                sheet_name = "2025 AFL Squads"
                print(f"  Writing sheet: {sheet_name}")
                
                try:
                    df = pd.read_csv(squad_file)
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    print(f"    ✅ Written {len(df)} rows")
                except Exception as e:
                    print(f"    ❌ Error: {e}")
                
        print(f"  💾 Saved: {WHEELO_PLAYER_FILE.name}")


def interactive_menu():
    """Display interactive menu for the scraper."""
    print("\n" + "="*60)
    print("   WHEELO RATINGS SCRAPER")
    print("   Download AFL statistics from wheeloratings.com")
    print("="*60)
    print()
    print("  1. Download ALL data (Team Stats, Player Stats, Squad Lists)")
    print("  2. Download Team Stats only")
    print("  3. Download Player Stats only")
    print("  4. Download Squad Lists only")
    print("  5. Exit")
    print()
    
    choice = input("  Select option (1-5): ").strip()
    return choice


def main():
    parser = argparse.ArgumentParser(description="Scrape AFL statistics from wheeloratings.com")
    parser.add_argument("--all", action="store_true", help="Download all data")
    parser.add_argument("--team", action="store_true", help="Download team stats")
    parser.add_argument("--player", action="store_true", help="Download player stats")
    parser.add_argument("--squads", action="store_true", help="Download squad lists")
    parser.add_argument("--no-headless", action="store_true", help="Run browser in visible mode")
    
    args = parser.parse_args()
    
    scraper = WheeloScraper(headless=not args.no_headless)
    
    # Determine what to download
    if args.all:
        do_team = do_player = do_squads = True
    elif args.team or args.player or args.squads:
        do_team = args.team
        do_player = args.player
        do_squads = args.squads
    else:
        # Interactive mode
        while True:
            choice = interactive_menu()
            
            if choice == "1":
                do_team = do_player = do_squads = True
                break
            elif choice == "2":
                do_team, do_player, do_squads = True, False, False
                break
            elif choice == "3":
                do_team, do_player, do_squads = False, True, False
                break
            elif choice == "4":
                do_team, do_player, do_squads = False, False, True
                break
            elif choice == "5":
                print("\n👋 Goodbye!")
                return
            else:
                print("\n  ⚠️ Invalid choice, please try again.")
                
    print(f"\n🚀 Starting scraper...")
    print(f"   Download directory: {DOWNLOAD_DIR}")
    
    team_files = {}
    player_files = {}
    squad_file = None
    
    try:
        if do_team:
            team_files = scraper.download_team_stats()
            scraper.update_team_excel(team_files)
            
        if do_player:
            player_files = scraper.download_player_stats()
            
        if do_squads:
            squad_file = scraper.download_squad_lists()
            
        # Update player Excel with both player stats and squad lists
        if do_player or do_squads:
            scraper.update_player_excel(player_files, squad_file)
            
    except KeyboardInterrupt:
        print("\n\n⚠️ Scraper interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
        
    print("\n" + "="*60)
    print("✅ SCRAPER COMPLETE")
    print("="*60)
    
    # Summary
    if team_files:
        print(f"\n📊 Team Stats downloaded: {len(team_files)} files")
    if player_files:
        print(f"📊 Player Stats downloaded: {len(player_files)} files")
    if squad_file:
        print(f"📊 Squad Lists downloaded: 1 file")
        
    print(f"\n📁 CSV files saved in: {DOWNLOAD_DIR}")
    print()


if __name__ == "__main__":
    main()
