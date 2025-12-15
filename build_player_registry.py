#!/usr/bin/env python3
# build_player_registry.py
#
# USAGE:
#   python build_player_registry.py [--dry-run] [--root PATH]
#
# OUTPUT:
#   - player_registry.xlsx in project root (unless --dry-run)
#
# NOTES:
# - Generates stable player_uid from a normalized *full name* (sha1 first 12 chars).
# - Avoids unsafe surname-only mapping for "H. Smith" type names.
# - Writes only SAFE aliases by default (no initial+surname, no ambiguous multi-initial names).
#
# HOW TO USE THE OUTPUT:
#   1. Open player_registry.xlsx
#   2. Filter needs_review = TRUE and fix full_name_canonical / review_notes
#   3. If you want "H. Smith" to map to a specific player, add a row in 'aliases'
#      with alias_key = your make_name_key output (normalised) and player_uid set correctly.

import sys
import re
import hashlib
import pandas as pd
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# -------------------------
# Scan config
# -------------------------
INCLUDE_KEYWORDS = ["player", "players", "ratings", "traits", "list"]
EXCLUDE_KEYWORDS = ["logo", "team_logos", "fixture", "ladder"]

PLAYER_NAME_HEADERS = ["Player", "Player Name", "Name", "Full Name", "Player_Full", "player"]
SEASON_HEADERS = ["Season", "Year"]
TEAM_HEADERS = ["Team", "Team_Full", "Club"]

MAX_SHEETS = 5
MAX_SOURCE_FILES = 5
MAX_NAME_VARIANTS = 10

# -------------------------
# Logging
# -------------------------
def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# -------------------------
# Normalisation
# -------------------------
def normalise_name(name) -> str:
    """Lowercase, trim, remove punctuation, collapse spaces."""
    if not isinstance(name, str):
        return ""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)      # remove punctuation
    s = re.sub(r"\s+", " ", s)         # collapse spaces
    return s

def is_ambiguous(name: str) -> bool:
    """
    Returns True for inputs like:
      - "J Smith" (single initial + surname)
      - "A B C" (multi-initial)
    """
    if not name:
        return True
    parts = str(name).strip().split()
    if len(parts) == 2 and len(parts[0]) == 1:
        return True
    if len(parts) > 1 and all(len(p) == 1 for p in parts[:-1]):
        return True
    return False

def parse_initial_surname(name: str):
    """
    Accepts "H. Smith" or "H Smith" (with optional dot)
    Returns (initial, surname) or (None, None)
    """
    s = str(name).strip()
    m = re.match(r"^([A-Za-z])\.?\s+([A-Za-z\-]+)$", s)
    if not m:
        return None, None
    return m.group(1).upper(), m.group(2)

def is_initial_surname(name: str) -> bool:
    ini, sur = parse_initial_surname(name)
    return bool(ini and sur)

def stable_uid_from_name_key(name_key: str) -> str:
    return hashlib.sha1(str(name_key).encode("utf-8")).hexdigest()[:12]

def find_column(cols, candidates):
    """Find first exact (case-insensitive) match of candidate header in cols."""
    cols_l = {str(c).strip().lower(): c for c in cols}
    for cand in candidates:
        c = cols_l.get(str(cand).strip().lower())
        if c is not None:
            return c
    return None

# -------------------------
# File scanning / reading
# -------------------------
def scan_files(root: Path):
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if any(k in name for k in INCLUDE_KEYWORDS) and not any(k in name for k in EXCLUDE_KEYWORDS):
            if name.endswith(".csv") or name.endswith(".xlsx"):
                files.append(p)
    return files

def read_file(path: Path):
    """
    Returns list of tuples: (df, source_string)
    """
    out = []
    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str, engine="python", on_bad_lines="skip")
            out.append((df, path.name))
        elif path.suffix.lower() == ".xlsx":
            xl = pd.ExcelFile(path)
            for i, sheet in enumerate(xl.sheet_names[:MAX_SHEETS]):
                try:
                    df = xl.parse(sheet, dtype=str)
                    out.append((df, f"{path.name}:{sheet}"))
                except Exception as e:
                    log(f"  [WARN] Could not read sheet '{sheet}' in {path.name}: {e}")
    except Exception as e:
        log(f"  [WARN] Could not read {path.name}: {e}")
    return out

# -------------------------
# Main build
# -------------------------
def main():
    dry_run = "--dry-run" in sys.argv

    # Optional root override
    root_arg = None
    if "--root" in sys.argv:
        try:
            root_arg = sys.argv[sys.argv.index("--root") + 1]
        except Exception:
            root_arg = None

    root = Path(root_arg).resolve() if root_arg else Path(__file__).parent.resolve()

    files = scan_files(root)
    log(f"Scanning {len(files)} candidate files under: {root}")

    # Collect rows from sources
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

                player_rows.append(
                    {
                        "full_name_raw": name.strip(),
                        "season": str(season).strip() if season else "",
                        "team": str(team).strip() if team else "",
                        "source": src,
                    }
                )
                row_count += 1

    log(f"Extracted {row_count} player rows from {file_count} files.")

    if not player_rows:
        log("[ERROR] No player rows found. Check INCLUDE_KEYWORDS/EXCLUDE_KEYWORDS and your data headers.")
        return

    # Build candidate full names by (surname, first_initial) to safely resolve initial+surname
    surname_initial_to_fullnames = defaultdict(set)
    for r in player_rows:
        nm = r["full_name_raw"]
        if not isinstance(nm, str) or not nm.strip():
            continue
        if is_initial_surname(nm):
            continue

        parts = nm.strip().split()
        # Only consider "real" full name patterns: 2 tokens and a "real" first name (len > 2)
        if len(parts) == 2 and len(parts[0]) > 2:
            first, surname = parts[0], parts[1]
            surname_initial_to_fullnames[(surname, first[0].upper())].add(nm)

    # Registry structures
    registry = {}

    # Build registry entries
    for r in player_rows:
        name_raw = r["full_name_raw"]
        name_key = normalise_name(name_raw)

        # Default: UID from the exact key
        player_uid = stable_uid_from_name_key(name_key)

        # If initial+surname, only remap if uniquely resolvable by (surname, initial)
        if is_initial_surname(name_raw):
            ini, sur = parse_initial_surname(name_raw)
            candidates = sorted(list(surname_initial_to_fullnames.get((sur, ini), set())))
            if len(candidates) == 1:
                cand_key = normalise_name(candidates[0])
                player_uid = stable_uid_from_name_key(cand_key)
            # else: keep its own UID; will be flagged review later

        if player_uid not in registry:
            registry[player_uid] = {
                "player_uid": player_uid,
                "full_name_raw": name_raw,
                "full_name_canonical": name_raw,
                "name_key": normalise_name(name_raw if not is_initial_surname(name_raw) else name_raw),
                "seasons_seen": set(),
                "teams_seen": set(),
                "source_files": set(),
                "name_variants": set(),
                "needs_review": False,
                "review_notes": "",
            }

        reg = registry[player_uid]
        reg["seasons_seen"].add(r.get("season", "") or "")
        reg["teams_seen"].add(r.get("team", "") or "")
        reg["source_files"].add(r.get("source", "") or "")
        reg["name_variants"].add(name_raw)

    # Finalize + needs_review flags
    for reg in registry.values():
        variants = set(reg["name_variants"])
        teams = set(t for t in reg["teams_seen"] if t)
        seasons = set(s for s in reg["seasons_seen"] if s)

        # Determine review conditions
        notes = []

        # Ambiguous raw name
        if is_ambiguous(reg["full_name_raw"]) or is_initial_surname(reg["full_name_raw"]):
            notes.append("Ambiguous name pattern (initials/surname)")

        # Multiple name variants pointing to same UID (can be ok, but worth review)
        if len(variants) > 1:
            notes.append(f"Multiple name variants ({len(variants)})")

        # Multiple teams/seasons seen can be normal, but often signals data collisions
        if len(teams) > 1:
            notes.append(f"Multiple teams seen ({len(teams)})")
        if len(seasons) > 5:
            notes.append(f"Many seasons seen ({len(seasons)})")

        reg["needs_review"] = bool(notes)
        reg["review_notes"] = "; ".join(notes)

        # Convert sets to strings for export
        reg["seasons_seen"] = ",".join(sorted(s for s in reg["seasons_seen"] if s))
        reg["teams_seen"] = ",".join(sorted(t for t in reg["teams_seen"] if t))
        reg["source_files"] = ",".join(sorted(list(reg["source_files"]))[:MAX_SOURCE_FILES])
        reg["name_variants"] = ",".join(sorted(list(reg["name_variants"]))[:MAX_NAME_VARIANTS])

    # Build registry DataFrame
    reg_cols = [
        "player_uid",
        "full_name_raw",
        "full_name_canonical",
        "name_key",
        "seasons_seen",
        "teams_seen",
        "source_files",
        "name_variants",
        "needs_review",
        "review_notes",
    ]
    registry_df = pd.DataFrame(list(registry.values()), columns=reg_cols).copy()
    registry_df["needs_review"] = registry_df["needs_review"].astype(bool)

    # Build aliases DataFrame (SAFE ONLY)
    alias_rows = []
    for reg in registry.values():
        player_uid = reg["player_uid"]
        full_name_canonical = reg["full_name_canonical"]

        variants = [v.strip() for v in str(reg["name_variants"]).split(",") if v.strip()]
        for alias_raw in variants:
            # Do NOT include ambiguous initial+surname / multi-initial aliases automatically
            if is_initial_surname(alias_raw) or is_ambiguous(alias_raw):
                continue

            alias_key = normalise_name(alias_raw)
            if not alias_key:
                continue

            alias_rows.append(
                {
                    "alias_raw": alias_raw,
                    "alias_key": alias_key,
                    "player_uid": player_uid,
                    "full_name_canonical": full_name_canonical,
                }
            )

    aliases_df = pd.DataFrame(alias_rows, columns=["alias_raw", "alias_key", "player_uid", "full_name_canonical"]).copy()

    # De-dup aliases by alias_key (keep first) — safer than allowing collisions
    if not aliases_df.empty:
        aliases_df["alias_key"] = aliases_df["alias_key"].astype(str).str.strip()
        aliases_df["player_uid"] = aliases_df["player_uid"].astype(str).str.strip()
        aliases_df = aliases_df.drop_duplicates(subset=["alias_key"], keep="first").reset_index(drop=True)

    log(f"Found {len(registry_df)} unique players in registry.")
    log(f"Flagged {int(registry_df['needs_review'].sum())} players for review.")
    log(f"Wrote {len(aliases_df)} SAFE aliases (excluded ambiguous initial/surname aliases).")

    if dry_run:
        log("[DRY RUN] No file written.")
        return

    out_path = root / "player_registry.xlsx"
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        registry_df.to_excel(writer, sheet_name="player_registry", index=False)
        aliases_df.to_excel(writer, sheet_name="aliases", index=False)

    log(f"Registry written to: {out_path}")

if __name__ == "__main__":
    main()
