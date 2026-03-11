"""
Safe I/O Utilities for AFL Dashboard Pipeline
===============================================
Provides atomic file writes and pre-write backups so that pipeline
steps are idempotent: if a step fails mid-write, the previous good
copy is preserved.

Usage:
    from utils.safe_io import safe_csv_write, safe_excel_write

    safe_csv_write(df, "data/raw/player/squads_2026.csv")
    safe_excel_write(df, "data/computed/team_ladders_2026.xlsx")
"""

import logging
import shutil
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "data" / "backups"

# Maximum number of backup copies to keep per file
MAX_BACKUPS_PER_FILE = 3


def _ensure_backup_dir():
    """Create the backup directory if it doesn't exist."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup_if_exists(target: Path):
    """
    If target file exists, copy it to data/backups/<stem>_<timestamp><suffix>.
    Rotates old backups to keep only MAX_BACKUPS_PER_FILE per base name.
    """
    if not target.exists():
        return

    _ensure_backup_dir()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{target.stem}_{ts}{target.suffix}"
    backup_path = BACKUP_DIR / backup_name

    try:
        shutil.copy2(target, backup_path)
        logger.info(f"  Backed up {target.name} → backups/{backup_name}")
    except OSError as e:
        logger.warning(f"  Backup failed for {target.name}: {e}")
        return

    # Rotate old backups for this stem
    _rotate_backups(target.stem, target.suffix)


def _rotate_backups(stem: str, suffix: str):
    """Keep only the most recent MAX_BACKUPS_PER_FILE backups for a given file."""
    pattern = f"{stem}_*{suffix}"
    backups = sorted(
        BACKUP_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[MAX_BACKUPS_PER_FILE:]:
        try:
            old.unlink()
        except OSError:
            pass


def safe_csv_write(df, path, index=False, **kwargs):
    """
    Write a DataFrame to CSV with backup-before-overwrite and atomic rename.

    1. Backs up the existing file (if any) to data/backups/
    2. Writes to a temporary file (.tmp)
    3. Atomically renames the temp file to the final path

    Args:
        df: pandas DataFrame to write.
        path: Target file path (str or Path).
        index: Whether to include the DataFrame index.
        **kwargs: Additional arguments passed to df.to_csv().
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    _backup_if_exists(target)

    tmp_path = target.with_suffix(target.suffix + ".tmp")
    try:
        df.to_csv(tmp_path, index=index, **kwargs)
        tmp_path.replace(target)  # Atomic on POSIX
    except Exception:
        # Clean up temp file on failure
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def safe_excel_write(df, path, sheet_name="Sheet1", index=False, **kwargs):
    """
    Write a DataFrame to Excel with backup-before-overwrite and atomic rename.

    Args:
        df: pandas DataFrame to write.
        path: Target file path (str or Path).
        sheet_name: Excel sheet name.
        index: Whether to include the DataFrame index.
        **kwargs: Additional arguments passed to df.to_excel().
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    _backup_if_exists(target)

    tmp_path = target.with_suffix(target.suffix + ".tmp")
    try:
        df.to_excel(tmp_path, sheet_name=sheet_name, index=index, **kwargs)
        tmp_path.replace(target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
