# AFL Dashboard - Quick Reference Guide

## 🚀 Running the App

### Current Setup (pip/venv):
```bash
cd /Users/marcuswagner/coding/AFL_dashboard
source .venv/bin/activate  # or: source ~/.venv/bin/activate
python -m streamlit run app.py
```

### Recommended Setup (conda):
```bash
cd /Users/marcuswagner/coding/AFL_dashboard
conda activate afl
python -m streamlit run app.py
```

### Using Launch Scripts:
```bash
# If using conda:
bash run.sh

# Or the alternative launcher:
bash run_app.sh
```

## 📦 Fresh Installation

### Option 1: Using Conda (Recommended for macOS)
```bash
cd /Users/marcuswagner/coding/AFL_dashboard

# Create environment
conda env create -f environment.yml

# Activate
conda activate afl

# Run app
python -m streamlit run app.py
```

### Option 2: Using pip/venv
```bash
cd /Users/marcuswagner/coding/AFL_dashboard

# Create virtual environment
python -m venv .venv

# Activate
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run app
python -m streamlit run app.py
```

## 🔧 Troubleshooting

### Player Photos Not Loading
✅ **Fixed** - All paths now use `BASE_DIR` for absolute path resolution

### "vertical_alignment" Error
✅ **Fixed** - Removed incompatible Streamlit 1.38+ parameter

### "use_container_width" Error  
✅ **Fixed** - Removed incompatible parameter for Streamlit 1.23.0

### Type Hint Errors (`|` operator)
✅ **Fixed** - All type hints now use `typing` module for Python 3.9

### Missing plotly Module
✅ **Fixed** - Added to requirements.txt and environment.yml

### Protobuf Errors
If you see protobuf-related errors:
```bash
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
```
Or add to your shell profile:
```bash
echo 'export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python' >> ~/.zshrc
```

## 📊 Data Files

### Required Files:
- `AFL Team Ratings.xlsx` - Team performance data
- `AFL Player Ratings.xlsx` - Player performance data  
- `afl_ladders_2011_2025.xlsx` - Historical ladder positions
- `player_photo_guide.csv` - Player photo filename mapping
- `2025 Traits.xlsx` / `2025 Traits ENRICHED.xlsx` - Player trait analysis

### Image Folders:
- `player_photos/` - Player headshots (640+ photos)
- `team_logos/` - Team logo images
- `assets/` - App assets (field diagrams, etc.)

## 🔄 Updating Dependencies

### Check what's installed:
```bash
pip list | grep -E "streamlit|pandas|numpy|plotly|altair"
```

### Update all dependencies:
```bash
pip install -r requirements.txt --upgrade
```

### Install missing dependency:
```bash
pip install <package_name>
```

## 🛠 Utility Scripts

### Scrape Player Images:
```bash
python scrape_afl_images.py
```

### Build Player Registry:
```bash
python build_player_registry.py
```

### Download Team Logos:
```bash
python download_team_logos.py
```

### Generate Player Guide:
```bash
python generate_player_guide.py
```

### Enrich Traits Data:
```bash
python enrich_traits.py
```

## 📱 Accessing the App

Once running, access at:
- **Local:** http://localhost:8501 (or 8502 if 8501 is taken)
- **Network:** http://192.168.x.x:8501 (shown in terminal output)

## 🎨 Pages in the App

1. **Team Breakdown** - Team ratings and performance metrics
2. **Team Compare** - Side-by-side team comparison
3. **Player Dashboard** - Individual player analysis
4. **Player Traits** - Player trait analysis and history
5. **List Ladder** - Ladder rankings and positions
6. **Depth Chart** - Team depth chart visualization
7. **Best 23** - Optimal team lineup builder
8. **GameDay Playground** - Match simulation and prediction
9. **IDP** - Interactive Dashboard Page (uses Plotly)

## 💾 Git Commands

### Check status:
```bash
git status
```

### Commit changes:
```bash
git add .
git commit -m "Your commit message"
git push
```

### View recent commits:
```bash
git log --oneline -10
```

## 🔍 Performance Tips

### Install Watchdog (recommended):
```bash
pip install watchdog
# or
conda install -c conda-forge watchdog
```

This improves Streamlit's file watching and auto-reload performance.

### Clear Streamlit Cache:
```bash
streamlit cache clear
```

### Run on specific port:
```bash
python -m streamlit run app.py --server.port 8080
```

## ⚙️ Environment Variables

Useful environment variables:
```bash
# Protobuf compatibility
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

# Streamlit config
export STREAMLIT_SERVER_PORT=8501
export STREAMLIT_SERVER_HEADLESS=true
```

## 📝 File Locations

```
/Users/marcuswagner/coding/AFL_dashboard/
├── app.py                  # Main application
├── requirements.txt        # Python dependencies  
├── environment.yml         # Conda environment
├── run.sh                  # Launch script (conda)
├── run_app.sh              # Alternative launcher
├── player_photos/          # Player images
├── team_logos/             # Team logos
├── archive/                # Backup versions
├── *.xlsx                  # Data files
└── scrape_*.py            # Utility scripts
```

## 🎯 Quick Fixes

### Restart the app:
1. Press `Ctrl+C` in terminal
2. Run `python -m streamlit run app.py` again

### Reset Python environment:
```bash
deactivate
rm -rf .venv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Force reload in browser:
- Mac: `Cmd + Shift + R`
- Windows/Linux: `Ctrl + Shift + R`

---

**Last Updated:** January 21, 2026  
**Python Version:** 3.9.6  
**Streamlit Version:** 1.23.0
