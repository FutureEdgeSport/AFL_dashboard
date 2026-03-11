"""
Schema Validator for AFL Dashboard CSV Outputs
================================================
Validates that pipeline-produced CSV files have expected columns,
minimum row counts, and basic data-quality constraints.

Usage:
    from utils.schema_validator import validate_pipeline_schemas

    errors = validate_pipeline_schemas(season=2026)
    if errors:
        for e in errors:
            print(e)
"""

import pandas as pd
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent

# ============================================================================
# SCHEMA DEFINITIONS
# Each schema is a dict with:
#   path_template : str  — file path with {season} placeholder
#   required_cols : list — columns that MUST exist
#   min_rows      : int  — minimum expected row count
#   non_null_cols : list — columns that must have >80% non-null values
#   optional      : bool — if True, missing file is a warning not an error
# ============================================================================

SCHEMAS = [
    # ── Player CSVs ──────────────────────────────────────────────
    {
        "name": "squads",
        "path_template": "data/raw/player/squads_{season}.csv",
        "required_cols": [
            "Team", "Player", "Position", "Season",
        ],
        "min_rows": 300,
        "non_null_cols": ["Team", "Player"],
        "optional": False,
    },
    {
        "name": "player_stats",
        "path_template": "data/raw/player/player_stats_{season}.csv",
        "required_cols": [
            "Player", "Team",
        ],
        "min_rows": 300,
        "non_null_cols": ["Player", "Team"],
        "optional": False,
    },
    {
        "name": "footywire_lists",
        "path_template": "data/raw/player/footywire_{season}_lists.csv",
        "required_cols": [
            "Team", "Player", "DOB", "Height", "Position",
        ],
        "min_rows": 300,
        "non_null_cols": ["Team", "Player"],
        "optional": False,
    },
    {
        "name": "footywire_complete",
        "path_template": "data/raw/player/footywire_{season}_complete.csv",
        "required_cols": [
            "Team", "Player", "DOB", "Height", "Position",
        ],
        "min_rows": 300,
        "non_null_cols": ["Team", "Player"],
        "optional": False,
    },
    {
        "name": "traits",
        "path_template": "data/raw/traits/traits_{season}.csv",
        "required_cols": [
            "Player", "Team", "Overall_Rating",
        ],
        "min_rows": 100,
        "non_null_cols": ["Player", "Team"],
        "optional": True,
    },
    # ── Team CSVs ────────────────────────────────────────────────
    {
        "name": "team_stats",
        "path_template": "data/raw/team/team_stats_{season}.csv",
        "required_cols": [
            "Team", "Matches", "RatingPoints",
        ],
        "min_rows": 10,
        "non_null_cols": ["Team"],
        "optional": False,
    },
    # ── Computed CSVs ────────────────────────────────────────────
    {
        "name": "team_summary",
        "path_template": "data/computed/team_summary_{season}.csv",
        "required_cols": [
            "Team", "Overall Rating", "Overall Rank",
        ],
        "min_rows": 10,
        "non_null_cols": ["Team"],
        "optional": False,
    },
    {
        "name": "team_ladders",
        "path_template": "data/computed/team_ladders_{season}.csv",
        "required_cols": [
            "Team", "Overall Rating", "Overall Rank",
        ],
        "min_rows": 10,
        "non_null_cols": ["Team"],
        "optional": False,
    },
]


# ============================================================================
# VALIDATION
# ============================================================================

class SchemaError:
    """A single schema validation error or warning."""

    def __init__(self, file_name: str, message: str, is_warning: bool = False):
        self.file_name = file_name
        self.message = message
        self.is_warning = is_warning

    def __str__(self):
        level = "WARN" if self.is_warning else "ERROR"
        return f"[{level}] {self.file_name}: {self.message}"


def validate_csv(schema: dict, season: int) -> List[SchemaError]:
    """Validate a single CSV file against its schema definition."""
    errors: List[SchemaError] = []

    path = BASE_DIR / schema["path_template"].format(season=season)
    name = schema["name"]
    is_optional = schema.get("optional", False)

    # ── File existence ───────────────────────────────────────────
    if not path.exists():
        if is_optional:
            errors.append(SchemaError(name, f"File not found: {path.name}", is_warning=True))
        else:
            errors.append(SchemaError(name, f"File not found: {path.name}"))
        return errors

    # ── Load ─────────────────────────────────────────────────────
    try:
        df = pd.read_csv(path)
    except Exception as e:
        errors.append(SchemaError(name, f"Failed to read CSV: {e}"))
        return errors

    # ── Row count ────────────────────────────────────────────────
    min_rows = schema.get("min_rows", 0)
    if len(df) < min_rows:
        errors.append(
            SchemaError(
                name,
                f"Row count {len(df)} below minimum {min_rows}",
                is_warning=is_optional,
            )
        )

    # ── Required columns ─────────────────────────────────────────
    missing_cols = [c for c in schema.get("required_cols", []) if c not in df.columns]
    if missing_cols:
        errors.append(
            SchemaError(name, f"Missing required columns: {missing_cols}")
        )

    # ── Non-null checks ──────────────────────────────────────────
    for col in schema.get("non_null_cols", []):
        if col not in df.columns:
            continue  # Already flagged by required_cols check
        null_pct = df[col].isna().mean()
        if null_pct > 0.20:
            errors.append(
                SchemaError(
                    name,
                    f"Column '{col}' has {null_pct:.0%} null values (threshold: 20%)",
                    is_warning=True,
                )
            )

    # ── Duplicate-player check (player files only) ───────────────
    if min_rows >= 300 and "Player" in df.columns and "Team" in df.columns:
        dupes = df.duplicated(subset=["Player", "Team"], keep=False)
        n_dupes = dupes.sum()
        if n_dupes > 0:
            errors.append(
                SchemaError(
                    name,
                    f"{n_dupes} duplicate (Player, Team) rows detected",
                    is_warning=True,
                )
            )

    # ── Team-count check ─────────────────────────────────────────
    if "Team" in df.columns:
        n_teams = df["Team"].nunique()
        if n_teams < 18 and min_rows >= 300:
            errors.append(
                SchemaError(
                    name,
                    f"Only {n_teams} teams found (expected 18)",
                    is_warning=True,
                )
            )

    return errors


def validate_pipeline_schemas(
    season: int,
    schemas: Optional[List[dict]] = None,
) -> List[SchemaError]:
    """
    Validate all pipeline CSV outputs for a given season.

    Args:
        season: The season year to validate (e.g. 2026).
        schemas: Override the default SCHEMAS list (for testing).

    Returns:
        A list of SchemaError objects (empty = all OK).
    """
    all_errors: List[SchemaError] = []
    for schema in (schemas or SCHEMAS):
        all_errors.extend(validate_csv(schema, season))
    return all_errors


# ============================================================================
# CLI
# ============================================================================

def main():
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from config.constants import CURRENT_SEASON

    season = CURRENT_SEASON
    if len(sys.argv) > 1:
        try:
            season = int(sys.argv[1])
        except ValueError:
            pass

    print(f"Validating CSV schemas for season {season}...")
    print("=" * 60)

    errors = validate_pipeline_schemas(season)

    warnings = [e for e in errors if e.is_warning]
    hard_errors = [e for e in errors if not e.is_warning]

    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")

    if hard_errors:
        print(f"\n❌ Errors ({len(hard_errors)}):")
        for e in hard_errors:
            print(f"  {e}")
        print(f"\nSchema validation FAILED — {len(hard_errors)} error(s)")
        sys.exit(1)
    else:
        print(f"\n✅ Schema validation passed ({len(warnings)} warning(s))")
        sys.exit(0)


if __name__ == "__main__":
    main()
