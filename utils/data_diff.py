"""
Data-Diff Alerting for AFL Dashboard Pipeline
===============================================
Compares newly written CSV/Excel files against their previous backup to detect
anomalies such as unexpected row-count drops, missing columns, or empty files.

Integrates with the notification system to send warnings when anomalies are
detected, but never blocks the pipeline — alerts are advisory only.

Usage:
    from utils.data_diff import check_data_diff

    issues = check_data_diff("data/raw/player/squads_2026.csv")
    # Returns a list of warning strings; empty list = all OK
"""

import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "data" / "backups"

# Thresholds
ROW_DROP_PCT_WARN = 30       # Warn if row count drops by ≥30%
ROW_DROP_PCT_CRITICAL = 60   # Critical if row count drops by ≥60%
COLUMN_DROP_THRESHOLD = 1    # Warn if any columns were lost


def _find_latest_backup(target: Path) -> Optional[Path]:
    """Find the most recent backup file for a given target."""
    if not BACKUP_DIR.exists():
        return None

    pattern = f"{target.stem}_*{target.suffix}"
    backups = sorted(
        BACKUP_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return backups[0] if backups else None


def _read_file(path: Path):
    """Read a CSV or Excel file into a DataFrame. Returns None on failure."""
    try:
        import pandas as pd
        if path.suffix == ".csv":
            return pd.read_csv(path)
        elif path.suffix in (".xlsx", ".xls"):
            return pd.read_excel(path)
    except Exception as e:
        logger.debug(f"Could not read {path.name}: {e}")
    return None


def check_data_diff(file_path, backup_path: Optional[str] = None) -> List[str]:
    """
    Compare a newly written file against its latest backup.

    Args:
        file_path: Path to the current (newly written) file.
        backup_path: Optional explicit path to the backup. If None,
                     auto-discovers the latest backup in data/backups/.

    Returns:
        List of warning/issue strings. Empty list means no anomalies.
    """
    target = Path(file_path)
    issues: List[str] = []

    if not target.exists():
        issues.append(f"MISSING: {target.name} does not exist after write")
        return issues

    # Find backup to compare against
    backup = Path(backup_path) if backup_path else _find_latest_backup(target)
    if not backup or not backup.exists():
        logger.debug(f"No backup found for {target.name} — skipping diff check")
        return issues  # First run — nothing to compare

    # Read both files
    current_df = _read_file(target)
    backup_df = _read_file(backup)

    if current_df is None:
        issues.append(f"UNREADABLE: {target.name} could not be parsed after write")
        return issues

    if backup_df is None:
        logger.debug(f"Backup {backup.name} unreadable — skipping diff check")
        return issues

    # --- Check 1: Empty file ---
    if len(current_df) == 0:
        issues.append(f"EMPTY: {target.name} has 0 rows (was {len(backup_df)})")
        return issues

    # --- Check 2: Row count drop ---
    if len(backup_df) > 0:
        drop_pct = ((len(backup_df) - len(current_df)) / len(backup_df)) * 100
        if drop_pct >= ROW_DROP_PCT_CRITICAL:
            issues.append(
                f"CRITICAL ROW DROP: {target.name} dropped from "
                f"{len(backup_df)} → {len(current_df)} rows ({drop_pct:.0f}% loss)"
            )
        elif drop_pct >= ROW_DROP_PCT_WARN:
            issues.append(
                f"ROW DROP: {target.name} dropped from "
                f"{len(backup_df)} → {len(current_df)} rows ({drop_pct:.0f}% loss)"
            )

    # --- Check 3: Missing columns ---
    old_cols = set(backup_df.columns)
    new_cols = set(current_df.columns)
    missing_cols = old_cols - new_cols
    if len(missing_cols) >= COLUMN_DROP_THRESHOLD:
        issues.append(
            f"COLUMNS LOST: {target.name} lost {len(missing_cols)} column(s): "
            f"{', '.join(sorted(missing_cols)[:5])}"
        )

    # --- Check 4: All-null new columns ---
    added_cols = new_cols - old_cols
    for col in added_cols:
        if current_df[col].isna().all():
            issues.append(f"EMPTY COLUMN: {target.name} new column '{col}' is all NaN")

    return issues


def diff_report(file_paths) -> str:
    """
    Run check_data_diff on multiple files and return a formatted report.

    Args:
        file_paths: Iterable of file paths to check.

    Returns:
        A formatted string report. Empty string if no issues found.
    """
    all_issues = []
    for fp in file_paths:
        issues = check_data_diff(fp)
        all_issues.extend(issues)

    if not all_issues:
        return ""

    header = f"⚠️ Data-diff alerts ({len(all_issues)} issue(s)):"
    body = "\n".join(f"  • {issue}" for issue in all_issues)
    return f"{header}\n{body}"
