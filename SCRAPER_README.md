# AFL Image Scraper

This script downloads player photos and team logos from AFL.com.au to keep your dashboard images consistent and up-to-date.

## Features

- Downloads team logos for all 18 AFL teams
- Downloads player photos based on your Excel player list
- Automatically normalizes file names to match your app's naming convention
- Skips already downloaded images
- Rate limiting to be respectful to AFL.com.au servers
- Interactive menu for selective downloads

## Installation

1. Install required dependencies:
```bash
pip install -r scraper_requirements.txt
```

Or if using your virtual environment:
```bash
.venv/bin/pip install -r scraper_requirements.txt
```

## Usage

### Basic Usage

Run the script:
```bash
python scrape_afl_images.py
```

Or with your virtual environment:
```bash
.venv/bin/python scrape_afl_images.py
```

### Interactive Menu

The script will prompt you to:
1. Download team logos (y/n)
2. Download player photos (y/n)
3. Choose to download all or a limited number of player photos (for testing)

### Options

- **Download all**: Downloads photos for all players in your Excel file
- **Limited download**: Specify a number (e.g., 10) to test the script first
- **Skip existing**: Automatically skips files that already exist

## How It Works

### Team Logos
- Tries multiple URL patterns for each team
- Saves logos as `{team_code}.png` (e.g., `afc.png`, `lions.png`)
- Uses backup sources if AFL.com.au doesn't have the image

### Player Photos
- Reads player names from `AFL Player Ratings.xlsx` (Summary tab)
- Searches AFL.com.au for each player
- Normalizes player names for file naming (e.g., "Marcus Bontempelli" → `marcus_bontempelli.png`)
- Implements rate limiting (2 seconds between downloads)

## File Structure

After running, your directories will look like:

```
AFL_dashboard/
├── team_logos/
│   ├── afc.png
│   ├── lions.png
│   ├── cfc.png
│   └── ... (all 18 teams)
├── player_photos/
│   ├── marcus_bontempelli.png
│   ├── patrick_cripps.png
│   ├── nick_daicos.png
│   └── ... (all players)
└── scrape_afl_images.py
```

## Tips

1. **Test First**: Start with a small number (5-10 players) to verify the script works
2. **Check Results**: Verify downloaded images are correct before running full download
3. **Re-run Anytime**: The script skips existing files, so you can re-run to get new players
4. **Manual Backup**: Some player photos might not be found automatically - you may need to download these manually

## Troubleshooting

### No photos downloading
- AFL.com.au might have changed their website structure
- Check your internet connection
- Verify the Excel file exists and has player data

### Wrong photos
- Player names might need manual adjustment
- Some players with common names might get confused
- Manually replace incorrect photos after download

### Rate Limiting
- If you get blocked, increase the `time.sleep()` values in the script
- Try again after a few minutes
- Consider downloading in smaller batches

## Important Notes

⚠️ **Respect AFL.com.au's Terms of Service**
- This script is for personal use only
- Images remain property of AFL/respective teams
- Do not redistribute downloaded images
- Be respectful with rate limiting

⚠️ **Website Changes**
- AFL.com.au may change their website structure
- The script may need updates if selectors change
- Check the AFL website if downloads stop working

## Support

If player photos aren't downloading:
1. Check if the player exists on AFL.com.au
2. Verify the URL pattern in the script
3. The script can be modified to use different sources or patterns
4. You can always add photos manually to the directories

## Manual Download Alternative

If automated scraping isn't working, you can:
1. Visit AFL.com.au player profiles
2. Right-click and save player images
3. Rename to match pattern: `firstname_lastname.png`
4. Place in `player_photos/` folder
