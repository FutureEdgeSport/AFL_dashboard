# AFL Dashboard Data Migration Roadmap
## From Excel Formulas to Python-Computed CSV Data

**Created:** February 2026  
**Status:** Planning Phase  
**Goal:** Enable the dashboard to run from raw CSV data files with all calculations performed in Python

---

## 📊 Executive Summary

The AFL Dashboard currently relies on Excel workbooks containing complex formulas (VLOOKUP, RANK, COUNTIFS, etc.). This document outlines the migration path to a system where:

1. **Raw data** is stored in simple CSV files
2. **All calculations** are performed in Python
3. **No Excel formulas** are required
4. Data updates require only dropping new CSV files

---

## 🔍 Current State Analysis

### Data Files Currently Used

| File | Sheets | Formula Count | Purpose |
|------|--------|---------------|---------|
| `AFL Team Ratings.xlsx` | 28 | ~9,730 | Team statistics, ladders, rankings |
| `AFL Player Ratings.xlsx` | 35 | ~3,485 | Player statistics, projections, age profiles |
| `2025 Traits ENRICHED.xlsx` | 5 | 0 | Player traits (already clean!) |
| `Wheelo_Team_Data.xlsx` | 1 | 0 | External team ratings (already clean!) |
| `Wheelo_Player_Data.xlsx` | 1 | 0 | External player ratings (already clean!) |

### Formula Types Discovered

#### Team Ratings Formulas
```
=VLOOKUP($A5,'2025'!$A:$IZ,222,FALSE)     # Pull data from raw sheet
=RANK(B5,B$5:B$22)                         # Rank teams 1-18
=INDIRECT("'"&$B$1&"'!$A:$IZ")             # Dynamic season reference
```

**Key Calculations:**
- Ball Winning Ranking (aggregate of Post Clear CP Diff, Ground Ball Diff, Clearance Diff)
- Ball Movement Ranking (Def Half to Score %, Chain to Score %)
- Scoring Ranking
- Defence Ranking  
- Pressure Ranking
- Health Check Ranking

#### Player Ratings Formulas
```
=VLOOKUP(A2,'2025 AFL Squads'!A:X,2,FALSE)              # Pull player data
=IFERROR(VLOOKUP(A2,'Draft Data'!A:F,4,FALSE),"")       # Draft info with error handling
=COUNTIFS(Summary!$AH:$AH,"<20.1",Summary!$B:$B,$C5)    # Count players by criteria
=SUMIF(Summary!B:B,'Age Profile'!A3,Summary!AG:AG)      # Sum by team
=AVERAGEIF(Summary!$B:$B,'Age Games'!$A3,Summary!D:D)   # Average by team
=_xlfn.RANK.EQ(B3,$B$3:$B$20)                           # Rank calculation
```

**Key Calculations:**
- Player summary aggregation across seasons
- List Ladder (player quality distribution by team)
- Age Profile analysis (2yr and 1yr projections)
- Rating projections

---

## 🎯 Target Architecture

### Proposed File Structure

```
AFL_dashboard/
├── data/
│   ├── raw/                           # Raw CSV dumps (input)
│   │   ├── team_stats_2025.csv
│   │   ├── team_stats_2024.csv
│   │   ├── player_stats_2025.csv
│   │   ├── player_stats_2024.csv
│   │   ├── player_traits_2025.csv
│   │   ├── afl_squads_2025.csv
│   │   └── draft_data.csv
│   │
│   ├── computed/                      # Python-computed outputs (cached)
│   │   ├── team_ladders_2025.csv
│   │   ├── team_ladders_2025_L10.csv
│   │   ├── player_summary.csv
│   │   ├── age_profiles.csv
│   │   └── list_ladder.csv
│   │
│   └── external/                      # Third-party data (Wheelo, etc.)
│       ├── wheelo_team_ratings.csv
│       └── wheelo_player_ratings.csv
│
├── data_pipeline/
│   ├── __init__.py
│   ├── compute_ratings.py             # ✅ Already exists
│   ├── compute_player_summary.py      # To be created
│   ├── compute_age_profiles.py        # To be created
│   ├── compute_list_ladder.py         # To be created
│   └── validators.py                  # Validation against Excel snapshots
│
└── app.py
```

---

## 📋 Migration Phases

### Phase 1: Team Ladders (READY TO START)
**Status:** 🟡 Partially Complete  
**Effort:** Low  
**Risk:** Low

The `data_pipeline/compute_ratings.py` module already has functions to compute team ladders:
- `load_team_ladders_computed()` - Replaces Excel ladder sheets
- `compute_team_category_rankings()` - Calculates Ball Winning, Ball Movement, etc.

**Steps:**
1. ✅ Wire up `compute_ratings.py` to `app.py` (DONE)
2. ✅ Add feature flag `USE_COMPUTED_RATINGS` (DONE)
3. ⬜ Validate computed values match Excel (use `compare_to_excel_snapshot()`)
4. ⬜ Export raw team data to CSV format
5. ⬜ Switch feature flag to True
6. ⬜ Remove Excel ladder sheets

### Phase 2: Team Summary Calculations
**Status:** 🔴 Not Started  
**Effort:** Medium  
**Risk:** Medium

Replicate Excel Summary sheet calculations:

| Metric | Excel Formula | Python Equivalent |
|--------|---------------|-------------------|
| Ball Winning Ranking | `=AVERAGE(rank columns)` | `df[rank_cols].mean(axis=1).rank()` |
| Category Ranks | `=RANK(value, range)` | `df[col].rank(ascending=False)` |
| Team Aggregates | `=VLOOKUP(team, data, col)` | `df.merge(raw_data, on='Team')` |

**Functions to Create:**
```python
def compute_team_summary(raw_df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Compute all team summary metrics from raw match data."""
    pass

def compute_category_ranking(summary_df: pd.DataFrame, category: str) -> pd.Series:
    """Compute ranking for a specific category (Ball Winning, etc.)."""
    pass
```

### Phase 3: Player Summary Calculations
**Status:** 🔴 Not Started  
**Effort:** High  
**Risk:** Medium

The Player Summary sheet has 1,247 formulas in the first 30 rows alone.

**Key Calculations to Replicate:**
1. **Basic Info Pull** - Currently VLOOKUPs to Squads sheet
2. **Draft Data** - Merge from draft data source
3. **Career Stats** - Aggregate across seasons
4. **Projections** - Age-based rating projections

**Functions to Create:**
```python
def compute_player_summary(
    season_dfs: dict[int, pd.DataFrame],
    squads_df: pd.DataFrame,
    draft_df: pd.DataFrame
) -> pd.DataFrame:
    """Build complete player summary from raw season data."""
    pass

def compute_player_projection(
    player_row: pd.Series,
    historical_df: pd.DataFrame
) -> dict:
    """Project player's future ratings based on age curve."""
    pass
```

### Phase 4: List Ladder / Age Profiles
**Status:** 🔴 Not Started  
**Effort:** Medium  
**Risk:** Low

These are analytical views built from the Summary data.

**Calculations:**
- `List Ladder L2` - Count players by rating band per team per position
- `List Ladder Career` - Similar but using career ratings
- `Age Profile (2yr)` - Total ratings by age band per team
- `Age Profile (1yr)` - Single year ratings by age band

**Functions to Create:**
```python
def compute_list_ladder(
    summary_df: pd.DataFrame,
    rating_col: str,
    bands: list[tuple[float, float]]
) -> pd.DataFrame:
    """Compute list ladder showing player distribution by rating bands."""
    pass

def compute_age_profile(
    summary_df: pd.DataFrame,
    years: int = 2
) -> pd.DataFrame:
    """Compute age profile showing team strength by age band."""
    pass
```

### Phase 5: Traits Data
**Status:** 🟢 Already Clean  
**Effort:** Very Low  
**Risk:** Very Low

The `2025 Traits ENRICHED.xlsx` file already has no formulas - it's clean data.

**Action:** Simply convert to CSV format and update file path references.

---

## 🔄 Validation Strategy

### Snapshot Comparison

Before switching to computed data, validate against Excel:

```python
from data_pipeline.compute_ratings import compare_to_excel_snapshot

# Load Excel version (ground truth)
excel_df = load_team_ladders_from_excel(2025, last10=False)

# Compute Python version
computed_df = load_team_ladders_computed_wrapper(2025, last10=False)

# Compare
results = compare_to_excel_snapshot(computed_df, excel_df)
print(f"Match percentage: {results['match_pct']:.1f}%")
print(f"Differences: {len(results['numeric_diffs'])}")
```

**Acceptance Criteria:**
- 99%+ match rate for numeric values
- All team names present
- Ranks match exactly

---

## 📦 CSV Export Scripts

### Export Team Raw Data
```python
def export_team_raw_data(season: int, output_path: str):
    """Export raw team data sheet to CSV."""
    xl = pd.ExcelFile(TEAM_FILE)
    df = xl.parse(str(season))
    df.to_csv(output_path, index=False)
```

### Export Player Raw Data  
```python
def export_player_raw_data(season: int, output_path: str):
    """Export raw player data sheet to CSV."""
    xl = pd.ExcelFile(PLAYER_FILE)
    df = xl.parse(str(season))
    df.to_csv(output_path, index=False)
```

---

## ⏱️ Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Team Ladders | 1-2 days | None |
| Phase 2: Team Summary | 3-5 days | Phase 1 |
| Phase 3: Player Summary | 5-7 days | Phase 2 |
| Phase 4: List Ladder/Age | 2-3 days | Phase 3 |
| Phase 5: Traits | 1 day | None |
| **Total** | **~3 weeks** | |

---

## ✅ Immediate Next Steps

1. **Validate Team Ladders**
   - Run `compare_to_excel_snapshot()` for 2025 Season and L10
   - Fix any discrepancies in `compute_ratings.py`

2. **Export Raw Data**
   - Create `/data/raw/` directory
   - Export `2025` sheet from each Excel file to CSV

3. **Test Feature Flag**
   - Set `USE_COMPUTED_RATINGS = True` temporarily
   - Verify dashboard still works correctly

4. **Document Column Mappings**
   - Create mapping of Excel columns to CSV columns
   - Document any transformations needed

---

## 🔧 Configuration

The feature flag is located in `app.py`:

```python
# Set to True to use Python-computed ratings
# Set to False to use Excel formulas (current default)
USE_COMPUTED_RATINGS = False
```

Check current configuration:
```python
from app import get_data_source_info
print(get_data_source_info())
# {'mode': 'excel', 'description': 'Excel formulas (legacy)', ...}
```

---

## 📝 Notes

- The `2025 Traits ENRICHED.xlsx` and `Wheelo_*.xlsx` files already have **zero formulas** - they can be converted to CSV immediately
- The existing `data_pipeline/compute_ratings.py` module (779 lines) provides a solid foundation
- Streamlit caching (`@st.cache_data`) will ensure computed values are cached efficiently

---

*Document maintained as part of AFL Dashboard v10.x development*
