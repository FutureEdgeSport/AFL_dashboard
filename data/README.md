# AFL Dashboard Data Directory

This directory contains all data files for the AFL Dashboard.

## Directory Structure

```
data/
├── raw/                    # Raw data exported from Excel (input files)
│   ├── team/              # Team statistics by season
│   ├── player/            # Player statistics by season
│   ├── traits/            # Player traits data
│   └── external/          # Third-party data (Wheelo, etc.)
│
├── computed/              # Python-computed outputs (cached results)
│   └── (generated files)
│
└── snapshots/             # Excel snapshots for validation
    └── (validation files)
```

## Data Flow

1. **Raw Data** → Drop CSV files into `raw/` subdirectories
2. **Python Compute** → `data_pipeline/` calculates rankings, aggregations
3. **Cached Output** → Results stored in `computed/` for performance
4. **Dashboard** → `app.py` reads from `computed/` or calculates on-demand

## File Naming Convention

- `team_stats_{season}.csv` - Raw team statistics
- `player_stats_{season}.csv` - Raw player statistics  
- `traits_{season}.csv` - Player traits
- `team_ladders_{season}.csv` - Computed team ladders
- `team_ladders_{season}_L10.csv` - Last 10 games ladders

## Migration Status

See `/DATA_MIGRATION_ROADMAP.md` for full migration plan.
