#!/usr/bin/env python3
# enrich_traits.py
#
# INPUTS (must be in same folder as this script):
#   - 2025 Traits.xlsx
#   - AFL Player Ratings.xlsx
#
# OUTPUT:
#   - 2025 Traits ENRICHED.xlsx
#
# What it does:
#   - Adds Player_Full, Team_Full, Position_Full to each Traits sheet
#   - Uses AFL Player Ratings as preferred source for full player name + position
#   - Matches using: Season (sheet name) + Team + initial+surname key

from pathlib import Path
import re
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

TRAITS_FILE = BASE_DIR / "2025 Traits.xlsx"
RATINGS_FILE = BASE_DIR / "AFL Player Ratings.xlsx"
OUT_FILE = BASE_DIR / "2025 Traits ENRICHED.xlsx"

TEAM_CODE_TO_NAME = {
    "AFC": "Adelaide", "BFC": "Brisbane", "CFC": "Carlton", "COFC": "Collingwood", "EFC": "Essendon",
    "FRFC": "Fremantle", "GFC": "Geelong", "GCFC": "Gold Coast", "GWS": "GWS Giants", "HFC": "Hawthorn",
    "MFC": "Melbourne", "NMFC": "North Melbourne", "PAFC": "Port Adelaide", "RFC": "Richmond",
    "SKFC": "St Kilda", "SFC": "Sydney", "WCFC": "West Coast", "WBFC": "Western Bulldogs",
}

# Your abbreviations → full names
POSITION_ABBREV_TO_FULL = {
    "R": "Ruck",
    "M": "Midfielder",
    "MF": "Mid-Forward",
    "GD": "Gen. Defender",
    "W": "Wing",
    "GF": "Gen. Forward",
    "KF": "Key Forward",
    "KD": "Key Defender",
}

def norm_text(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    s = str(x).strip().lower()
    s = re.sub(r"[^\w\s]", "", s)   # remove punctuation
    s = re.sub(r"\s+", " ", s)
    return s

def team_full_from_any(team_val: str) -> str:
    t = str(team_val).strip()
    if not t or t.lower() == "nan":
        return ""
    # If already a full name, keep it
    if t in TEAM_CODE_TO_NAME.values():
        return t
    # If code, map it
    return TEAM_CODE_TO_NAME.get(t, t)

def initial_surname_key_from_traits(player_raw: str) -> str:
    """
    Traits format examples:
      - "J. Crisp"
      - "J Crisp"
      - "Jordan Crisp" (if you ever have it)
    Returns: "j crisp"
    """
    s = str(player_raw).strip()
    if not s or s.lower() == "nan":
        return ""

    s = s.replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split(" ")
    if len(parts) == 1:
        return norm_text(parts[0])

    first = parts[0]
    surname = parts[-1]
    first_initial = first[0] if first else ""
    return norm_text(f"{first_initial} {surname}")

def initial_surname_key_from_fullname(full_name: str) -> str:
    """
    Ratings full name examples:
      - "Jordan Crisp" -> "j crisp"
      - "Oskar Baker"  -> "o baker"
    """
    s = str(full_name).strip()
    if not s or s.lower() == "nan":
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split(" ")
    if len(parts) < 2:
        return norm_text(s)
    first_initial = parts[0][0]
    surname = parts[-1]
    return norm_text(f"{first_initial} {surname}")

def load_ratings_all_sheets(path: Path) -> pd.DataFrame:
    """
    Loads all sheets, tags with _sheet (if sheet name is year-like, we also set Season).
    Tries to find key columns sensibly.
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing ratings file: {path}")

    xl = pd.ExcelFile(path)
    frames = []

    for sh in xl.sheet_names:
        df = xl.parse(sh)

        df.columns = [str(c).strip() for c in df.columns]

        # Identify player column
        player_col = None
        for c in ["Player_Full", "Player", "Name", "Full Name", "Player Name"]:
            if c in df.columns:
                player_col = c
                break
        if player_col is None:
            continue

        # Identify team column
        team_col = None
        for c in ["Team_Full", "Team", "Club"]:
            if c in df.columns:
                team_col = c
                break

        # Identify season column
        season_col = None
        for c in ["Season", "Year"]:
            if c in df.columns:
                season_col = c
                break

        # Identify position column
        pos_col = None
        for c in ["Position_Full", "Position"]:
            if c in df.columns:
                pos_col = c
                break

        out = pd.DataFrame()
        out["Player_Full"] = df[player_col].astype(str)
        out["player_key"] = out["Player_Full"].map(initial_surname_key_from_fullname)

        if team_col:
            out["Team_Full"] = df[team_col].map(team_full_from_any)
        else:
            out["Team_Full"] = ""

        if pos_col:
            out["Position_Full"] = df[pos_col].astype(str).str.strip()
        else:
            out["Position_Full"] = ""

        # Season logic:
        # - If sheet name looks like a year and there is no season column, use sheet name.
        # - Else if season column exists, use it.
        season_from_sheet = None
        if re.fullmatch(r"\d{4}", str(sh).strip()):
            season_from_sheet = int(str(sh).strip())

        if season_col:
            out["Season"] = pd.to_numeric(df[season_col], errors="coerce")
        elif season_from_sheet is not None:
            out["Season"] = season_from_sheet
        else:
            out["Season"] = pd.NA

        out["_sheet"] = str(sh)
        frames.append(out)

    if not frames:
        raise ValueError("Could not find any usable sheets/columns in AFL Player Ratings.xlsx")

    ratings_all = pd.concat(frames, ignore_index=True)

    # Clean
    ratings_all["Team_Full"] = ratings_all["Team_Full"].fillna("").astype(str).str.strip()
    ratings_all["Player_Full"] = ratings_all["Player_Full"].fillna("").astype(str).str.strip()
    ratings_all["Position_Full"] = ratings_all["Position_Full"].fillna("").astype(str).str.strip()
    ratings_all["player_key"] = ratings_all["player_key"].fillna("").astype(str).str.strip()
    ratings_all["Season"] = pd.to_numeric(ratings_all["Season"], errors="coerce")

    # Drop obvious blanks
    ratings_all = ratings_all[(ratings_all["player_key"] != "") & (ratings_all["Player_Full"] != "")]
    return ratings_all

def main():
    if not TRAITS_FILE.exists():
        raise FileNotFoundError(f"Missing traits file: {TRAITS_FILE}")

    print(f"[OK] Using ratings file: {RATINGS_FILE.name}")

    ratings_all = load_ratings_all_sheets(RATINGS_FILE)

    # To avoid duplicates ruining merges, keep ONE row per (Season, Team_Full, player_key)
    ratings_keyed = (
        ratings_all
        .dropna(subset=["Season"])
        .sort_values(["Season", "Team_Full", "player_key"])
        .drop_duplicates(subset=["Season", "Team_Full", "player_key"], keep="first")
        .copy()
    )

    xl_traits = pd.ExcelFile(TRAITS_FILE)

    with pd.ExcelWriter(OUT_FILE, engine="openpyxl") as writer:
        for sh in xl_traits.sheet_names:
            df = xl_traits.parse(sh)
            df.columns = [str(c).strip() for c in df.columns]

            # Determine season for this sheet
            season = None
            if re.fullmatch(r"\d{4}", str(sh).strip()):
                season = int(str(sh).strip())
            elif "Season" in df.columns:
                season = pd.to_numeric(df["Season"], errors="coerce").dropna()
                season = int(season.iloc[0]) if not season.empty else None

            if season is None:
                print(f"[SKIP] Sheet '{sh}': cannot determine season")
                df.to_excel(writer, sheet_name=str(sh)[:31], index=False)
                continue

            # Ensure baseline cols exist
            if "Season" not in df.columns:
                df["Season"] = season
            else:
                df["Season"] = pd.to_numeric(df["Season"], errors="coerce").fillna(season).astype(int)

            # Player raw column
            player_col = "Player_Full" if "Player_Full" in df.columns else ("Player" if "Player" in df.columns else None)
            if player_col is None:
                print(f"[SKIP] Sheet '{sh}': no Player column found")
                df.to_excel(writer, sheet_name=str(sh)[:31], index=False)
                continue

            # Team columns
            if "Team_Full" not in df.columns:
                if "Team" in df.columns:
                    df["Team_Full"] = df["Team"].map(team_full_from_any)
                else:
                    df["Team_Full"] = ""

            # Build matching key
            df["_player_key"] = df[player_col].map(initial_surname_key_from_traits)
            df["_Team_Full_norm"] = df["Team_Full"].astype(str).str.strip()
            df["_Season"] = season

            # Merge with ratings (preferred Player_Full + Position_Full)
            merge_left = df.copy()
            merge_left["Season"] = season  # ensure scalar
            merged = merge_left.merge(
                ratings_keyed[["Season", "Team_Full", "player_key", "Player_Full", "Position_Full"]],
                left_on=["Season", "Team_Full", "_player_key"],
                right_on=["Season", "Team_Full", "player_key"],
                how="left",
                validate="m:1"
            )

            # Fill Player_Full:
            # - If Ratings gave us a full name, use it
            # - Else keep existing Player_Full if present
            # - Else keep raw "Player" as fallback
            if "Player_Full" not in merge_left.columns:
                merged["Player_Full"] = merged["Player_Full_y"]  # from ratings
            else:
                # If traits already had Player_Full (rare), prefer ratings if present
                merged["Player_Full"] = merged["Player_Full_y"].fillna(merged["Player_Full_x"])

            # If still blank, fallback to raw player column
            merged["Player_Full"] = merged["Player_Full"].fillna(merged[player_col]).astype(str)

            # Position_Full:
            # Prefer ratings Position_Full; fallback to mapping from Traits Position abbrev
            if "Position" in merged.columns:
                merged["Position_Full"] = (
                    merged["Position_Full_y"]
                    .where(merged["Position_Full_y"].notna() & (merged["Position_Full_y"].astype(str).str.strip() != ""), None)
                )
                fallback = merged["Position"].astype(str).str.strip().map(POSITION_ABBREV_TO_FULL)
                merged["Position_Full"] = merged["Position_Full"].fillna(fallback)
            else:
                merged["Position_Full"] = merged["Position_Full_y"]

            # Clean up helper cols
            drop_cols = [
                "player_key",
                "Player_Full_x", "Player_Full_y",
                "Position_Full_y",
                "_player_key", "_Team_Full_norm", "_Season",
            ]
            merged = merged.drop(columns=[c for c in drop_cols if c in merged.columns], errors="ignore")

            # Match rate
            match_rate = (merged["Player_Full"].astype(str).str.contains(r"^\s*$") == False).mean()
            # But better: did ratings match? measure by Position_Full_y existence before cleanup
            # We already dropped it; estimate by whether Position_Full is non-null AND not from abbrev map (hard),
            # so just report how many got *any* Player_Full from ratings by checking if raw != full:
            # We'll compute simpler: how many had a non-null merge on ratings Player_Full_y (before we dropped)
            # Not available now, so we do a conservative proxy:
            proxy_rate = (merged["Position_Full"].notna() & (merged["Position_Full"].astype(str).str.strip() != "")).mean()

            print(f"[OK] Sheet '{sh}': rows={len(merged)} | filled Position_Full ~ {proxy_rate*100:.1f}%")

            merged.to_excel(writer, sheet_name=str(sh)[:31], index=False)

    print(f"\n[DONE] Wrote: {OUT_FILE}")

if __name__ == "__main__":
    main()
