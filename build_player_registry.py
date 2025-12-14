#!/usr/bin/env python3
# build_player_registry.py
#
# USAGE:
#   python build_player_registry.py [--dry-run]
#
# OUTPUT:
#   - player_registry.xlsx in project root (unless --dry-run)
#
# HOW TO USE THE OUTPUT:
#   1. Open player_registry.xlsx
#   2. Edit full_name_canonical for flagged rows (needs_review=TRUE)
#   3. Add alias rows if needed in the 'aliases' sheet
#   4. Use player_uid as the join key across datasets

import os
import sys
import re
import hashlib
import json
import pandas as pd
from pathlib import Path
from collections import defaultdict, Counter

from datetime import datetime

INCLUDE_KEYWORDS = ['player', 'players', 'ratings', 'traits', 'list']
EXCLUDE_KEYWORDS = ['logo', 'team_logos', 'fixture', 'ladder']
PLAYER_NAME_HEADERS = ['Player', 'Player Name', 'Name', 'Full Name', 'Player_Full', 'player']
SEASON_HEADERS = ['Season', 'Year']
TEAM_HEADERS = ['Team', 'Team_Full', 'Club']

MAX_SHEETS = 5
MAX_SOURCE_FILES = 5
MAX_NAME_VARIANTS = 10

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def normalise_name(name):
    if not isinstance(name, str):
        return ""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name

def is_ambiguous(name):
    # e.g. "J Smith" or "A B C"
    if not name: return True
    parts = name.strip().split()
    if len(parts) == 2 and len(parts[0]) == 1:
        return True
    if all(len(p) == 1 for p in parts[:-1]) and len(parts) > 1:
        return True
    return False

def find_column(cols, candidates):
    for c in candidates:
        for col in cols:
            col_str = str(col).strip().lower()
            c_str = str(c).strip().lower()
            if col_str == c_str:
                return col
    return None

def scan_files(root):
    files = []
    for path in Path(root).rglob("*"):
        if path.is_file():
            fname = path.name.lower()
            if any(k in fname for k in INCLUDE_KEYWORDS) and not any(k in fname for k in EXCLUDE_KEYWORDS):
                if fname.endswith(".csv") or fname.endswith(".xlsx"):
                    files.append(path)
    return files

def read_file(path):
    dfs = []
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str, engine="python", on_bad_lines="skip")
            dfs.append((df, path.name))
        elif path.suffix.lower() == ".xlsx":
            xl = pd.ExcelFile(path)
            for i, sheet in enumerate(xl.sheet_names[:MAX_SHEETS]):
                try:
                    df = xl.parse(sheet, dtype=str)
                    dfs.append((df, f"{path.name}:{sheet}"))
                except Exception as e:
                    log(f"  [WARN] Could not read sheet '{sheet}' in {path}: {e}")
    except Exception as e:
        log(f"  [WARN] Could not read {path}: {e}")
    return dfs

def main():
    dry_run = "--dry-run" in sys.argv
    root = Path(__file__).parent
    files = scan_files(root)
    log(f"Scanning {len(files)} candidate files...")


    player_rows = []
    file_count = 0
    row_count = 0
    for f in files:
        dfs = read_file(f)
        if not dfs:
            continue
        file_count += 1
        for df, src in dfs:
            name_col = find_column(df.columns, PLAYER_NAME_HEADERS)
            if not name_col:
                continue
            season_col = find_column(df.columns, SEASON_HEADERS)
            team_col = find_column(df.columns, TEAM_HEADERS)
            for _, row in df.iterrows():
                name = row.get(name_col, "")
                if not isinstance(name, str) or not name.strip():
                    continue
                season = row.get(season_col, "") if season_col else ""
                team = row.get(team_col, "") if team_col else ""
                player_rows.append({
                    "full_name_raw": name.strip(),
                    "season": str(season).strip() if season else "",
                    "team": str(team).strip() if team else "",
                    "source": src
                })
                row_count += 1

    log(f"Extracted {row_count} player rows from {file_count} files.")

    # --- AUTOMATED ALIAS MAPPING FOR INITIAL+SURNAME ---
    import re
    def extract_surname(name):
        parts = str(name).strip().split()
        return parts[-1] if parts else ''

    def is_initial_surname(name):
        return bool(re.match(r'^[A-Z]\. [A-Za-z\-]+$', str(name).strip()))

    # Build a mapping from surname to all full names (e.g., 'Riley Thilthorpe')
    surname_to_fullnames = {}
    for row in player_rows:
        name = row["full_name_raw"]
        if not is_initial_surname(name):
            surname = extract_surname(name)
            if len(name.split()) == 2 and len(name.split()[0]) > 2:
                surname_to_fullnames.setdefault(surname, set()).add(name)

    # Group by name_key, but for initial+surname, try to map to full name's UID
    registry = {}
    name_to_uid = {}
    for row in player_rows:
        name_raw = row["full_name_raw"]
        name_key = normalise_name(name_raw)
        # If initial+surname, try to find a matching full name
        if is_initial_surname(name_raw):
            surname = extract_surname(name_raw)
            candidates = surname_to_fullnames.get(surname, set())
            mapped_uid = None
            for cand in candidates:
                cand_key = normalise_name(cand)
                cand_uid = hashlib.sha1(cand_key.encode("utf-8")).hexdigest()[:12]
                if cand_uid in registry:
                    mapped_uid = cand_uid
                    break
            if mapped_uid:
                player_uid = mapped_uid
            else:
                player_uid = hashlib.sha1(name_key.encode("utf-8")).hexdigest()[:12]
        else:
            player_uid = hashlib.sha1(name_key.encode("utf-8")).hexdigest()[:12]
        if player_uid not in registry:
            registry[player_uid] = {
                "player_uid": player_uid,
                "full_name_raw": name_raw,
                "full_name_canonical": name_raw,
                "name_key": name_key,
                "seasons_seen": set(),
                "teams_seen": set(),
                "source_files": set(),
                "name_variants": set(),
                "needs_review": False,
                "review_notes": ""
            }
        reg = registry[player_uid]
        reg["seasons_seen"].add(row["season"])
        reg["teams_seen"].add(row["team"])
        reg["source_files"].add(row["source"])
        reg["name_variants"].add(name_raw)
        name_to_uid.setdefault(name_raw, player_uid)

    # Finalize registry
    for reg in registry.values():
        reg["seasons_seen"] = ",".join(sorted(s for s in reg["seasons_seen"] if s))
        reg["teams_seen"] = ",".join(sorted(t for t in reg["teams_seen"] if t))
        reg["source_files"] = ",".join(sorted(list(reg["source_files"]))[:MAX_SOURCE_FILES])
        reg["name_variants"] = ",".join(sorted(list(reg["name_variants"]))[:MAX_NAME_VARIANTS])
        variants = set(reg["name_variants"].split(","))
        teams = set(reg["teams_seen"].split(",")) if reg["teams_seen"] else set()
        reg["needs_review"] = (
            len(variants) > 1 or
            len(teams) > 1 or
            is_ambiguous(reg["full_name_raw"])
        )

    # Build DataFrames
    reg_cols = [
        "player_uid", "full_name_raw", "full_name_canonical", "name_key",
        "seasons_seen", "teams_seen", "source_files", "name_variants",
        "needs_review", "review_notes"
    ]
    registry_df = pd.DataFrame([reg for reg in registry.values()], columns=reg_cols)
    registry_df["needs_review"] = registry_df["needs_review"].astype(bool)

    # Aliases sheet
    alias_rows = []
    for reg in registry.values():
        player_uid = reg["player_uid"]
        full_name_canonical = reg["full_name_canonical"]
        for alias in set(reg["name_variants"].split(",")):
            alias_key = normalise_name(alias)
            alias_rows.append({
                "alias_raw": alias,
                "alias_key": alias_key,
                "player_uid": player_uid,
                "full_name_canonical": full_name_canonical
            })
    aliases_df = pd.DataFrame(alias_rows, columns=["alias_raw", "alias_key", "player_uid", "full_name_canonical"])

    log(f"Found {len(registry_df)} unique players in registry.")
    log(f"Flagged {registry_df['needs_review'].sum()} players for review.")

    if dry_run:
        log("[DRY RUN] No file written.")
        return

    # Write Excel
    out_path = root / "player_registry.xlsx"
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        registry_df.to_excel(writer, sheet_name="player_registry", index=False)
        aliases_df.to_excel(writer, sheet_name="aliases", index=False)
    log(f"Registry written to {out_path}")

if __name__ == "__main__":
    main()
