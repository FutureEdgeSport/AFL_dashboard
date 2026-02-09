# AFL Team Rating System

## Overview

The AFL Dashboard uses a sophisticated statistical rating system to evaluate team performance across six key pillars. The system produces ratings on a **50-99 scale**, similar to FIFA/FC video game ratings, providing intuitive and meaningful performance indicators.

---

## Rating Scale Interpretation

| Rating Range | Classification | Description |
|--------------|----------------|-------------|
| 90-99 | **Elite** | League-leading performance |
| 80-89 | **Good** | Above average, competitive |
| 70-79 | **Average** | Mid-table performance |
| 60-69 | **Below Average** | Struggling in this area |
| 50-59 | **Poor** | Significant weakness |

---

## The Six Pillars

### 1. Ball Winning
How effectively a team wins possession of the ball.

| Metric | Weight | Description |
|--------|--------|-------------|
| Disposals | 35% | Total ball touches (kicks + handballs) |
| Clearances | 25% | Ball exits from stoppages |
| Contested Possessions | 25% | Possessions won under pressure |
| Tackles | 15% | Defensive pressure resulting in ball-ups or turnovers |

### 2. Ball Use
How efficiently a team uses the ball when in possession.

| Metric | Weight | Description |
|--------|--------|-------------|
| Disposal Efficiency | 40% | Percentage of disposals hitting target |
| Uncontested Possessions | 30% | Clean possessions without opposition pressure |
| Marks | 30% | Successful catches from kicks |

### 3. Scoring
How effectively a team converts opportunities into points.

| Metric | Weight | Description |
|--------|--------|-------------|
| Goals | 40% | 6-point scores |
| Points For | 35% | Total points scored |
| Inside 50s | 25% | Forward entries |

### 4. Defence
How well a team prevents the opposition from scoring.

| Metric | Weight | Description |
|--------|--------|-------------|
| Points Against | 50% | Opposition points (inverted - lower is better) |
| Rebound 50s | 30% | Exits from defensive zone |
| Intercept Marks | 20% | Marks cutting off opposition attacks |

### 5. Pressure
How much defensive pressure a team applies.

| Metric | Weight | Description |
|--------|--------|-------------|
| Tackles | 50% | Defensive pressure acts |
| Contested Possessions | 30% | Willingness to compete for the ball |
| Clearances | 20% | Pressure at stoppages |

### 6. Health Check
Overall team vitality and form indicators.

| Metric | Weight | Description |
|--------|--------|-------------|
| Wins | 50% | Games won |
| Percentage | 30% | Points For / Points Against ratio |
| Points For | 20% | Scoring output |

---

## Methodology: How Ratings Are Calculated

### Step 1: Z-Score Normalization

Each metric is standardized using **Z-score normalization**, which measures how many standard deviations a team's value is from the league average.

```
Z-score = (Team Value - League Mean) / League Standard Deviation
```

**Example:**
- If league average Disposals = 350 with StdDev = 25
- Team A has 400 Disposals
- Z-score = (400 - 350) / 25 = **+2.0** (2 standard deviations above average)

### Step 2: Direction Adjustment

Some metrics are inverted where **lower is better** (e.g., Points Against):
- For "Points Against", the Z-score is multiplied by -1
- This ensures that allowing fewer points results in a higher rating

### Step 3: Weighted Composite Score

For each pillar, the weighted Z-scores are combined:

```
Pillar Z-Score = Σ (Metric Z-Score × Metric Weight)
```

**Example for Ball Winning:**
```
Ball Winning Z = (Disposals_Z × 0.35) + (Clearances_Z × 0.25) + 
                 (Contested_Z × 0.25) + (Tackles_Z × 0.15)
```

### Step 4: Sigmoid Transformation

The composite Z-score is transformed using a **sigmoid function** to compress extreme values into a 0-1 probability range:

```
Sigmoid(z) = 1 / (1 + e^(-z))
```

This transformation:
- Maps Z = 0 (league average) → 0.5 (middle of scale)
- Maps Z = +2 (well above average) → ~0.88
- Maps Z = -2 (well below average) → ~0.12
- Naturally bounds extreme outliers

### Step 5: Scale to 50-99

The sigmoid output (0-1) is mapped to the final 50-99 rating scale:

```
Rating = 50 + (Sigmoid Value × 49)
```

This ensures:
- Minimum possible rating: **50**
- Maximum possible rating: **99**
- League average (Z=0): **~74-75**

---

## Overall Rating Calculation

The **Overall Rating** is the average of all six pillar ratings:

```
Overall Rating = (Ball Winning + Ball Use + Scoring + Defence + Pressure + Health Check) / 6
```

---

## Example Calculation

**Team: Geelong (2025)**

| Pillar | Z-Score | Sigmoid | Final Rating |
|--------|---------|---------|--------------|
| Ball Winning | +0.8 | 0.69 | 84 |
| Ball Use | +0.5 | 0.62 | 80 |
| Scoring | +0.6 | 0.65 | 82 |
| Defence | +0.4 | 0.60 | 79 |
| Pressure | +0.7 | 0.67 | 83 |
| Health Check | +0.9 | 0.71 | 85 |
| **Overall** | | | **82** |

---

## Key Advantages of This System

### 1. **Statistical Robustness**
Z-score normalization accounts for the natural distribution of each metric, ensuring fair comparison.

### 2. **Intuitive Scale**
The 50-99 scale is immediately understandable - everyone knows an 85 rating is "good" and a 58 is "poor".

### 3. **Resistance to Outliers**
The sigmoid transformation prevents extreme performances from skewing ratings unrealistically.

### 4. **Weighted Importance**
Not all metrics are equal - Disposal Efficiency matters more than raw Disposals for Ball Use, and Goals matter more than Inside 50s for Scoring.

### 5. **Relative Performance**
Ratings reflect performance **relative to the current league**, automatically adjusting for different eras or seasons.

---

## Match Cap for Fair Rankings

All calculations that use `Rating × Matches` are **capped at 23 matches** (regular season) to ensure fair comparison:

- **Why?** Teams that play finals (up to 27 matches) would otherwise get an unfair advantage in rankings
- **Cap Value**: 23 matches (regular season only)
- **Affects**:
  - Player Impact calculations (2025 Impact, Last 2 Impact)
  - Cap Value calculations (Rating % within team)
  - Weighted ratings used for ranking players
  - Team Age Breakdown calculations
  - List Ladder weighted scores

**Example:**
- A player with 27 matches and 12.0 rating will have their weighted score calculated as `12.0 × 23 = 276` (not `12.0 × 27 = 324`)

---

## Data Sources

- **Primary Stats**: Wheelo AFL Statistics
- **Computed Metrics**: Derived from raw match data
- **Update Frequency**: Weekly during season

---

## Technical Implementation

The rating system is implemented in:
- [`data_pipeline/compute_team_summary.py`](data_pipeline/compute_team_summary.py)

Key functions:
- `zscore_to_rating()` - Converts Z-scores to 50-99 scale
- `compute_category_rating()` - Calculates weighted pillar ratings
- `load_and_compute_summary()` - Main computation pipeline

Output files:
- `data/computed/team_summary_{season}.csv`

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | Feb 2026 | Sophisticated Z-score based system with sigmoid transformation |
| 1.0 | 2025 | Original percentile-rank based system (104 - ranking) |
