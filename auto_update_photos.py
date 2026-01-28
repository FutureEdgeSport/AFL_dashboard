#!/usr/bin/env python3
"""
AFL Player Photo Auto-Updater
Automatically downloads new/missing player photos at scheduled intervals.

USAGE:
    # Run once (check for missing photos and download)
    python auto_update_photos.py
    
    # Run as a daemon (continuous with interval)
    python auto_update_photos.py --daemon --interval 3600
    
    # Run with custom settings
    python auto_update_photos.py --interval 7200 --max-per-run 50
    
CRON SETUP (recommended):
    # Run daily at 6 AM
    0 6 * * * cd /Users/marcuswagner/coding/AFL_dashboard && /path/to/python auto_update_photos.py >> logs/photo_update.log 2>&1
    
    # Run every 6 hours
    0 */6 * * * cd /Users/marcuswagner/coding/AFL_dashboard && /path/to/python auto_update_photos.py >> logs/photo_update.log 2>&1

LAUNCHD SETUP (macOS):
    See the generated plist file: com.futureedge.afl-photo-updater.plist
"""

import os
import sys
import time
import argparse
import logging
import hashlib
import json
import re
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================
PLAYER_PHOTOS_DIR = "player_photos"
PLAYER_FILE = "AFL Player Ratings.xlsx"
LOG_DIR = "logs"
STATE_FILE = "logs/photo_update_state.json"

# Team club website URLs for JSON extraction
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
    "GWS Giants": "https://www.gwsgiants.com.au/players",
    "Greater Western Sydney": "https://www.gwsgiants.com.au/players",
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

# Default settings
DEFAULT_INTERVAL = 3600  # 1 hour in seconds
DEFAULT_MAX_PER_RUN = 100  # Max photos to download per run
RATE_LIMIT_DELAY = 1.5  # Seconds between requests

# ============================================================
# LOGGING SETUP
# ============================================================
def setup_logging(verbose=False):
    """Configure logging."""
    Path(LOG_DIR).mkdir(exist_ok=True)
    
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = '%(asctime)s [%(levelname)s] %(message)s'
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # File handler
    log_file = Path(LOG_DIR) / f"photo_update_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # Root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

# ============================================================
# STATE MANAGEMENT
# ============================================================
def load_state():
    """Load the state from previous runs."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"Could not load state file: {e}")
    
    return {
        'last_run': None,
        'total_downloaded': 0,
        'failed_players': [],
        'last_team_data_fetch': {},
        'player_teams': {}  # Track which team each player was on when photo was downloaded
    }

def save_state(state):
    """Save the current state."""
    try:
        Path(LOG_DIR).mkdir(exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logging.warning(f"Could not save state file: {e}")

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def normalize_player_name(name):
    """Normalize player name for filename."""
    return re.sub(r'[^\w\s-]', '', str(name).lower()).replace(' ', '_')

def ensure_directories():
    """Create necessary directories."""
    Path(PLAYER_PHOTOS_DIR).mkdir(exist_ok=True)
    Path(LOG_DIR).mkdir(exist_ok=True)

def download_image(url, save_path):
    """Download an image from URL."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200 and len(response.content) > 1000:  # Minimum size check
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        logging.debug(f"Download error: {e}")
        return False

def get_team_player_data(team_name):
    """Extract player data JSON from team website."""
    url = TEAM_CLUB_URLS.get(team_name)
    if not url:
        return None
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return None
        
        content = response.text
        
        # Look for JSON player data in the page
        match = re.search(r'JSON\.stringify\(\s*(\[.*?\])\s*\)', content, re.DOTALL)
        if match:
            json_str = match.group(1)
            try:
                return json.loads(json_str)
            except:
                pass
        
        return None
    except Exception as e:
        logging.debug(f"Error getting team data for {team_name}: {e}")
        return None

def construct_image_urls(provider_id):
    """Construct possible AFL player image URLs."""
    year = datetime.now().year
    urls = [
        f"https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/{year}014/{provider_id}.png",
        f"https://s.afl.com.au/staticfile/AFL%20Tenant/AFL/Players/ChampIDImages/AFL/{year-1}014/{provider_id}.png",
    ]
    return urls

# ============================================================
# MAIN PHOTO UPDATE LOGIC
# ============================================================
def get_players_from_excel():
    """Load player list from Excel file."""
    try:
        xl = pd.ExcelFile(PLAYER_FILE)
        
        # Try different sheets
        for sheet in ['2025', '2025 AFL Squads', 'Summary']:
            try:
                df = xl.parse(sheet)
                break
            except:
                continue
        else:
            logging.error("Could not find valid player sheet")
            return []
        
        players = []
        for _, row in df.iterrows():
            # Try different column names
            player_name = row.get("Player") or row.get("Player Name") or row.get("Name")
            team = row.get("Team") or row.get("Team_Full") or row.get("Club")
            
            if pd.notna(player_name) and pd.notna(team):
                players.append({
                    'name': str(player_name).strip(),
                    'team': str(team).strip(),
                    'normalized': normalize_player_name(str(player_name))
                })
        
        # Remove duplicates
        seen = set()
        unique = []
        for p in players:
            if p['normalized'] not in seen:
                seen.add(p['normalized'])
                unique.append(p)
        
        return unique
    
    except Exception as e:
        logging.error(f"Error loading Excel file: {e}")
        return []

def get_missing_photos(players):
    """Get list of players who don't have photos."""
    missing = []
    for player in players:
        photo_path = os.path.join(PLAYER_PHOTOS_DIR, f"{player['normalized']}.png")
        if not os.path.exists(photo_path):
            missing.append(player)
    return missing

def get_team_changed_players(players, state):
    """Get list of players who have changed teams since their photo was downloaded."""
    changed = []
    player_teams = state.get('player_teams', {})
    
    for player in players:
        normalized = player['normalized']
        current_team = player['team']
        
        # Check if we have a record of this player's team
        if normalized in player_teams:
            previous_team = player_teams[normalized]
            # Normalize team names for comparison
            prev_norm = previous_team.lower().replace(' ', '').replace('giants', '').replace('gws', 'gws')
            curr_norm = current_team.lower().replace(' ', '').replace('giants', '').replace('gws', 'gws')
            
            if prev_norm != curr_norm:
                player['previous_team'] = previous_team
                changed.append(player)
    
    return changed

def update_photos(max_downloads=None, force_refresh=False, check_team_changes=True):
    """Main function to update missing player photos and refresh team-changed players."""
    state = load_state()
    ensure_directories()
    
    # Ensure player_teams exists in state
    if 'player_teams' not in state:
        state['player_teams'] = {}
    
    logging.info("=" * 60)
    logging.info("AFL Player Photo Auto-Updater")
    logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("=" * 60)
    
    # Load players
    players = get_players_from_excel()
    if not players:
        logging.error("No players found. Exiting.")
        return {'downloaded': 0, 'failed': 0, 'skipped': 0, 'team_changes': 0}
    
    logging.info(f"Loaded {len(players)} players from Excel")
    
    # Find missing photos
    missing = get_missing_photos(players)
    logging.info(f"Found {len(missing)} players without photos")
    
    # Find players who changed teams (only check players WITH existing photos)
    team_changed = []
    if check_team_changes:
        players_with_photos = [p for p in players if p not in missing]
        team_changed = get_team_changed_players(players_with_photos, state)
        if team_changed:
            logging.info(f"Found {len(team_changed)} players who changed teams:")
            for p in team_changed:
                logging.info(f"  • {p['name']}: {p.get('previous_team', '?')} → {p['team']}")
    
    # Combine missing + team changed (team changes first for priority)
    to_download = team_changed + missing
    
    if not to_download:
        logging.info("All players have photos and no team changes. Nothing to do.")
        state['last_run'] = datetime.now().isoformat()
        save_state(state)
        return {'downloaded': 0, 'failed': 0, 'skipped': len(players), 'team_changes': 0}
    
    # Limit downloads per run
    if max_downloads and len(to_download) > max_downloads:
        to_download = to_download[:max_downloads]
        logging.info(f"Limited to {max_downloads} downloads this run")
    
    # Cache team data
    team_data_cache = {}
    
    downloaded = 0
    failed = 0
    team_change_downloads = 0
    failed_players = []
    
    for i, player in enumerate(to_download):
        player_name = player['name']
        normalized = player['normalized']
        team = player['team']
        is_team_change = 'previous_team' in player
        
        save_path = os.path.join(PLAYER_PHOTOS_DIR, f"{normalized}.png")
        
        status_prefix = "[TEAM CHANGE]" if is_team_change else ""
        logging.info(f"[{i+1}/{len(to_download)}] {status_prefix} {player_name} ({team})")
        
        # Get team data if not cached
        if team not in team_data_cache:
            if team not in TEAM_CLUB_URLS:
                logging.warning(f"  Team '{team}' not in URL mapping")
                failed += 1
                failed_players.append({'name': player_name, 'team': team, 'reason': 'Unknown team'})
                continue
            
            logging.debug(f"  Fetching {team} player data...")
            team_data = get_team_player_data(team)
            team_data_cache[team] = team_data
            time.sleep(RATE_LIMIT_DELAY)
        else:
            team_data = team_data_cache[team]
        
        if not team_data:
            logging.warning(f"  Could not load team player data")
            failed += 1
            failed_players.append({'name': player_name, 'team': team, 'reason': 'No team data'})
            continue
        
        # Find player in team data
        player_found = False
        for entry in team_data:
            player_obj = entry.get('player', {})
            first_name = player_obj.get('firstName', '').lower()
            surname = player_obj.get('surname', '').lower()
            full_name = f"{first_name} {surname}"
            
            if player_name.lower() in full_name or full_name in player_name.lower():
                provider_id = player_obj.get('providerId', '').replace('CD_I', '')
                
                if not provider_id:
                    continue
                
                # Try image URLs
                urls = construct_image_urls(provider_id)
                for url in urls:
                    if download_image(url, save_path):
                        downloaded += 1
                        if is_team_change:
                            team_change_downloads += 1
                            logging.info(f"  ✓ Downloaded (team change: {player.get('previous_team')} → {team})")
                        else:
                            logging.info(f"  ✓ Downloaded successfully")
                        
                        # Update player's team in state
                        state['player_teams'][normalized] = team
                        player_found = True
                        break
                    time.sleep(0.5)
                
                if player_found:
                    break
        
        if not player_found:
            failed += 1
            failed_players.append({'name': player_name, 'team': team, 'reason': 'Not found in team data'})
            logging.warning(f"  ✗ Could not download photo")
        
        time.sleep(RATE_LIMIT_DELAY)
    
    # Update state for all players (even those we didn't download - to track their current teams)
    for player in players:
        normalized = player['normalized']
        team = player['team']
        photo_path = os.path.join(PLAYER_PHOTOS_DIR, f"{normalized}.png")
        # Only update if they have a photo (so we can detect future team changes)
        if os.path.exists(photo_path):
            state['player_teams'][normalized] = team
    
    # Update state
    state['last_run'] = datetime.now().isoformat()
    state['total_downloaded'] = state.get('total_downloaded', 0) + downloaded
    state['failed_players'] = failed_players[-50:]  # Keep last 50 failures
    save_state(state)
    
    # Summary
    logging.info("=" * 60)
    logging.info("SUMMARY")
    logging.info(f"  Downloaded (new): {downloaded - team_change_downloads}")
    logging.info(f"  Downloaded (team changes): {team_change_downloads}")
    logging.info(f"  Total downloaded: {downloaded}")
    logging.info(f"  Failed: {failed}")
    logging.info(f"  Remaining: {len(to_download) - downloaded - failed}")
    logging.info("=" * 60)
    
    return {'downloaded': downloaded, 'failed': failed, 'skipped': len(players) - len(to_download), 'team_changes': team_change_downloads}

# ============================================================
# DAEMON MODE
# ============================================================
def run_daemon(interval, max_per_run, check_team_changes=True):
    """Run continuously at specified interval."""
    logging.info(f"Starting daemon mode. Interval: {interval}s, Max per run: {max_per_run}, Check team changes: {check_team_changes}")
    
    while True:
        try:
            result = update_photos(max_downloads=max_per_run, check_team_changes=check_team_changes)
            logging.info(f"Run complete. Downloaded: {result['downloaded']} (team changes: {result.get('team_changes', 0)}), Failed: {result['failed']}")
        except Exception as e:
            logging.error(f"Error during update: {e}")
        
        logging.info(f"Sleeping for {interval} seconds...")
        time.sleep(interval)

# ============================================================
# LAUNCHD PLIST GENERATOR (macOS)
# ============================================================
def generate_launchd_plist():
    """Generate a macOS launchd plist for scheduled runs."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    python_path = sys.executable
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.futureedge.afl-photo-updater</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{project_dir}/auto_update_photos.py</string>
        <string>--max-per-run</string>
        <string>50</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>{project_dir}</string>
    
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    
    <key>StandardOutPath</key>
    <string>{project_dir}/logs/launchd_stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>{project_dir}/logs/launchd_stderr.log</string>
    
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""
    
    plist_path = os.path.join(project_dir, "com.futureedge.afl-photo-updater.plist")
    with open(plist_path, 'w') as f:
        f.write(plist_content)
    
    print(f"\n✓ Generated launchd plist: {plist_path}")
    print("\nTo install (run daily at 6 AM):")
    print(f"  cp {plist_path} ~/Library/LaunchAgents/")
    print(f"  launchctl load ~/Library/LaunchAgents/com.futureedge.afl-photo-updater.plist")
    print("\nTo uninstall:")
    print(f"  launchctl unload ~/Library/LaunchAgents/com.futureedge.afl-photo-updater.plist")
    print(f"  rm ~/Library/LaunchAgents/com.futureedge.afl-photo-updater.plist")

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='AFL Player Photo Auto-Updater',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python auto_update_photos.py                     # Run once, check for missing + team changes
  python auto_update_photos.py --max-per-run 20   # Download max 20 photos
  python auto_update_photos.py --no-team-changes   # Only download missing, skip team changes
  python auto_update_photos.py --daemon            # Run continuously (every hour)
  python auto_update_photos.py --generate-plist    # Generate macOS launchd config
        """
    )
    
    parser.add_argument('--daemon', action='store_true',
                       help='Run continuously at specified interval')
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL,
                       help=f'Interval between runs in seconds (default: {DEFAULT_INTERVAL})')
    parser.add_argument('--max-per-run', type=int, default=DEFAULT_MAX_PER_RUN,
                       help=f'Max photos to download per run (default: {DEFAULT_MAX_PER_RUN})')
    parser.add_argument('--no-team-changes', action='store_true',
                       help='Skip re-downloading photos for players who changed teams')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    parser.add_argument('--generate-plist', action='store_true',
                       help='Generate macOS launchd plist file')
    
    args = parser.parse_args()
    
    # Generate plist and exit
    if args.generate_plist:
        generate_launchd_plist()
        return
    
    # Setup logging
    setup_logging(verbose=args.verbose)
    
    check_team_changes = not args.no_team_changes
    
    if args.daemon:
        run_daemon(args.interval, args.max_per_run, check_team_changes)
    else:
        update_photos(max_downloads=args.max_per_run, check_team_changes=check_team_changes)

if __name__ == "__main__":
    main()
