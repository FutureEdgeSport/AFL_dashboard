#!/usr/bin/env python3
"""
Scrape round-by-round match stats from wheeloratings.com/afl_match_stats.html

Produces data/raw/player/match_ratings_{season}.csv with columns:
    Player, Team, Round, RatingPoints, ...  (plus any other columns in the CSV)

Usage:
    python scrape_wheelo_match_stats.py                 # current season, all rounds
    python scrape_wheelo_match_stats.py --season 2025   # specific season
    python scrape_wheelo_match_stats.py --rounds 1 5    # rounds 1-5 only
    python scrape_wheelo_match_stats.py --no-headless    # visible browser
"""

import argparse
import re
import sys
import time
from pathlib import Path

from config.constants import CURRENT_SEASON

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("❌ Required packages not installed.")
    print("   Run: pip install selenium webdriver-manager")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("❌ Required: pip install pandas")
    sys.exit(1)

# Configuration
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "wheelo_downloads"
OUTPUT_DIR = BASE_DIR / "data" / "raw" / "player"
MATCH_STATS_URL = "https://www.wheeloratings.com/afl_match_stats.html"


class MatchStatsScraper:
    """Scrape per-game player stats from Wheelo Match Stats page."""

    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
        DOWNLOAD_DIR.mkdir(exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ driver
    def _setup_driver(self, max_retries=3):
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")

        prefs = {
            "download.default_directory": str(DOWNLOAD_DIR.absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "safebrowsing.disable_download_protection": True,
        }
        options.add_experimental_option("prefs", prefs)

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                print(f"🔧 Chrome driver attempt {attempt}/{max_retries}…")
                self.driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()),
                    options=options,
                )
                self.driver.execute_cdp_cmd(
                    "Page.setDownloadBehavior",
                    {"behavior": "allow", "downloadPath": str(DOWNLOAD_DIR.absolute())},
                )
                print("✅ Chrome driver ready")
                return
            except Exception as e:
                last_error = e
                print(f"  ⚠️  Attempt {attempt} failed: {e}")
                if self.driver:
                    try:
                        self.driver.quit()
                    except Exception:
                        pass
                    self.driver = None
                if attempt < max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to start Chrome after {max_retries} attempts: {last_error}")

    def _close_driver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

    # ----------------------------------------------------------- CSV download
    def _clear_downloads(self):
        for f in DOWNLOAD_DIR.glob("*.csv"):
            f.unlink()
        for f in DOWNLOAD_DIR.glob("*.crdownload"):
            f.unlink()
        for f in DOWNLOAD_DIR.glob("downloads.html*"):
            f.unlink()

    def _get_csv_files(self):
        return {f for f in DOWNLOAD_DIR.glob("*.csv") if not f.name.startswith("downloads")}

    def _click_download_csv(self) -> bool:
        try:
            btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "download-csv-button"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", btn)
            return True
        except Exception as e:
            print(f"    ❌ Download button click failed: {e}")
            return False

    def _wait_for_download(self, pre_files, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            current = self._get_csv_files()
            new = current - pre_files
            # Only check for real .crdownload files, not leftover downloads.html ones
            downloading = [f for f in DOWNLOAD_DIR.glob("*.crdownload")
                           if not f.name.startswith("downloads")]
            if new and not downloading:
                return max(new, key=lambda p: p.stat().st_mtime)
            time.sleep(0.5)
        return None

    def _download_current_view(self) -> pd.DataFrame | None:
        """Download CSV for the currently displayed data and return as DataFrame."""
        pre = self._get_csv_files()
        if not self._click_download_csv():
            return None
        csv_path = self._wait_for_download(pre)
        if csv_path is None:
            print("    ❌ Download timed out")
            return None
        try:
            df = pd.read_csv(csv_path)
            csv_path.unlink()  # clean up
            return df
        except Exception as e:
            print(f"    ❌ CSV parse error: {e}")
            return None

    # --------------------------------------------------------- page navigation
    def _get_round_options(self) -> list[tuple[str, str]]:
        """Get (value, text) pairs from the round-list dropdown."""
        sel_el = self.driver.find_element(By.ID, "round-list")
        sel = Select(sel_el)
        return [(o.get_attribute("value"), o.text.strip()) for o in sel.options]

    def _select_round(self, value: str):
        """Select a round by its option value (e.g. '202601')."""
        sel_el = self.driver.find_element(By.ID, "round-list")
        sel = Select(sel_el)
        sel.select_by_value(value)
        time.sleep(3)

    def _click_all_matches(self) -> bool:
        """Click the 'All matches' button if present (bulk download for a round)."""
        try:
            btn = self.driver.find_element(By.ID, "match-All")
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(2)
            return True
        except Exception:
            return False

    def _get_game_buttons(self) -> list:
        """Return game-selector buttons (id starts with 'match-', excluding 'match-All')."""
        btns = self.driver.find_elements(By.CSS_SELECTOR, "button[id^='match-']")
        return [b for b in btns if b.get_attribute("id") != "match-All"]

    def _parse_round_number_from_option(self, text: str, value: str) -> int:
        """Parse round number from option text/value.

        'Opening Round' (value 202600) -> 0
        'Round 1' (value 202601) -> 1
        """
        m = re.search(r"Round\s+(\d+)", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        if "opening" in text.lower():
            return 0
        # Fallback: last 2 digits of value
        return int(value[-2:])

    # -------------------------------------------------------- main entry point
    def scrape(self, season: int = CURRENT_SEASON,
               round_start: int = 0, round_end: int | None = None):
        """Scrape match stats for the given season/round range.

        round_start=0 includes Opening Round. Returns a combined DataFrame.
        """
        all_frames: list[pd.DataFrame] = []

        self._setup_driver()
        try:
            # Clean up old downloads
            self._clear_downloads()

            # Load page — use season in URL to load correct year
            url = f"{MATCH_STATS_URL}?id={season}0101"
            self.driver.get(url)
            time.sleep(4)

            # Discover available rounds from the dropdown
            round_options = self._get_round_options()
            print(f"  📋 Found {len(round_options)} rounds: {[t for _, t in round_options]}")

            for value, text in round_options:
                rnd = self._parse_round_number_from_option(text, value)
                if rnd < round_start:
                    continue
                if round_end is not None and rnd > round_end:
                    continue

                print(f"\n  📋 {text} (round {rnd})")
                self._select_round(value)

                # Try "All matches" button first (downloads all games at once)
                if self._click_all_matches():
                    print("    📥 Downloading all matches…")
                    df = self._download_current_view()
                    if df is not None and not df.empty:
                        df["Round"] = rnd
                        all_frames.append(df)
                        print(f"    ✅ {len(df)} rows")
                    continue

                # Otherwise download each game individually
                game_btns = self._get_game_buttons()
                if not game_btns:
                    print("    (no games found)")
                    continue

                for btn in game_btns:
                    label = btn.text.strip()
                    self.driver.execute_script("arguments[0].click();", btn)
                    print(f"    🏟  {label}")
                    time.sleep(2)

                    df = self._download_current_view()
                    if df is not None and not df.empty:
                        df["Round"] = rnd
                        all_frames.append(df)
                        print(f"      ✅ {len(df)} rows")

        finally:
            self._close_driver()

        if all_frames:
            return pd.concat(all_frames, ignore_index=True)
        return pd.DataFrame()

    def scrape_and_save(self, season: int = CURRENT_SEASON,
                        round_start: int = 0, round_end: int | None = None):
        """Scrape and write to data/raw/player/match_ratings_{season}.csv"""
        print(f"\n{'='*60}")
        print(f"  WHEELO MATCH STATS SCRAPER — {season}")
        print(f"{'='*60}")

        df = self.scrape(season, round_start, round_end)
        if df.empty:
            print("\n⚠️  No data scraped.")
            return None

        out_path = OUTPUT_DIR / f"match_ratings_{season}.csv"
        # If file exists and we're only scraping a subset, merge
        if out_path.exists() and (round_start > 0 or round_end is not None):
            existing = pd.read_csv(out_path)
            scraped_rounds = set(df["Round"].unique())
            existing = existing[~existing["Round"].isin(scraped_rounds)]
            df = pd.concat([existing, df], ignore_index=True)

        df.sort_values(["Round", "Team", "Player"], inplace=True, ignore_index=True)
        df.to_csv(out_path, index=False)
        print(f"\n💾 Saved {len(df)} rows → {out_path}")
        return out_path


def main():
    parser = argparse.ArgumentParser(description="Scrape Wheelo Match Stats (round-by-round)")
    parser.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year")
    parser.add_argument("--rounds", type=int, nargs=2, metavar=("START", "END"),
                        help="Round range (inclusive)")
    parser.add_argument("--no-headless", action="store_true", help="Show browser")
    args = parser.parse_args()

    r_start = args.rounds[0] if args.rounds else 0
    r_end = args.rounds[1] if args.rounds else None

    scraper = MatchStatsScraper(headless=not args.no_headless)
    scraper.scrape_and_save(args.season, r_start, r_end)


if __name__ == "__main__":
    main()
