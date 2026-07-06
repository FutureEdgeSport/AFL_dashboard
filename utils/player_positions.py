from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from config.constants import normalize_team_name
except Exception:  # pragma: no cover - fallback when constants unavailable
    def normalize_team_name(team: str) -> str:
        return team


EXPECTED_AFL_TEAM_COUNT = 18


GENERIC_POSITIONS = {
    "Forward",
    "Defender",
    "Midfield",
    "Ruck",
    "DefenderForward",
    "MidfieldForward",
    "ForwardRuck",
    "DefenderMidfield",
    "DefenderRuck",
}

POSITION_API_TO_FULL = {
    "R": "Ruck",
    "M": "Midfielder",
    "MF": "Mid-Forward",
    "GD": "Gen. Defender",
    "W": "Wing",
    "GF": "Gen. Forward",
    "KF": "Key Forward",
    "KD": "Key Defender",
}

FOOTYWIRE_POSITION_MAP = {
    "Forward": "Gen. Forward",
    "Defender": "Gen. Defender",
    "Midfield": "Midfielder",
    "Ruck": "Ruck",
    "DefenderForward": "Gen. Defender",
    "MidfieldForward": "Mid-Forward",
    "ForwardRuck": "Ruck",
    "DefenderMidfield": "Gen. Defender",
    "DefenderRuck": "Gen. Defender",
}


def map_position_label(value: object) -> str:
    pos = str(value).strip()
    if not pos or pos in {"nan", "None"}:
        return ""
    if pos in POSITION_API_TO_FULL:
        return POSITION_API_TO_FULL[pos]
    if pos in GENERIC_POSITIONS:
        return FOOTYWIRE_POSITION_MAP.get(pos, pos)
    return pos


def count_unique_teams(df: pd.DataFrame, team_col: str = "Team") -> int:
    if team_col not in df.columns:
        return 0
    return int(df[team_col].dropna().astype(str).str.strip().nunique())


def choose_preferred_position(raw_value: object, api_value: object = "") -> str:
    raw_position = map_position_label(raw_value)
    api_position = map_position_label(api_value)

    # Preserve established hybrid role buckets when Traits only exposes a
    # generic primary role; this keeps Mid-Forward population intact.
    if raw_position == "Mid-Forward" and api_position in {"Midfielder", "Gen. Forward"}:
        return raw_position

    if api_position:
        return api_position
    return raw_position


def load_wing_player_keys(base_dir: str | Path | None = None) -> set[tuple[str, str]]:
    """Load canonical wing players as (player_lower, team_lower) keys."""
    root = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent.parent
    candidates = [
        root / "data" / "AFL_Historical_2012_2025.xlsx",
        root / "AFL_Historical_2012_2025.xlsx",
    ]

    for path in candidates:
        if not path.exists():
            continue
        try:
            xl = pd.ExcelFile(path)
            if "Wings" not in xl.sheet_names:
                continue
            wings = xl.parse("Wings")
            if "Player" not in wings.columns or "Team" not in wings.columns:
                continue
            keys: set[tuple[str, str]] = set()
            for _, row in wings.iterrows():
                player = str(row.get("Player", "")).strip().lower()
                team = normalize_team_name(str(row.get("Team", "")).strip()).lower()
                if player and team and player not in {"nan", "none"} and team not in {"nan", "none"}:
                    keys.add((player, team))
            if keys:
                return keys
        except Exception:
            continue
    return set()


def load_key_forward_player_keys(
    season: int,
    base_dir: str | Path | None = None,
) -> set[tuple[str, str]]:
    """Infer likely key forwards from current-season match profile and height.

    Heuristic is intentionally conservative and only used as a fallback when
    source data is otherwise generic (e.g. plain "Forward").
    """
    root = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent.parent
    raw_player_dir = root / "data" / "raw" / "player"
    match_path = raw_player_dir / f"match_ratings_{season}.csv"

    if not match_path.exists():
        return set()

    try:
        match_df = pd.read_csv(match_path)
    except Exception:
        return set()

    required = {"Player", "Team", "Goals", "Marks"}
    if not required.issubset(match_df.columns):
        return set()

    # Build best-effort height map from squads/complete files.
    height_map: dict[tuple[str, str], float] = {}
    for hp in [
        raw_player_dir / f"squads_{season}.csv",
        raw_player_dir / f"footywire_{season}_complete.csv",
    ]:
        if not hp.exists():
            continue
        try:
            hdf = pd.read_csv(hp)
        except Exception:
            continue
        if not {"Player", "Team", "Height"}.issubset(hdf.columns):
            continue
        tmp = hdf[["Player", "Team", "Height"]].copy()
        tmp["Player"] = tmp["Player"].astype(str).str.strip().str.lower()
        tmp["Team"] = tmp["Team"].astype(str).str.strip().map(normalize_team_name).str.lower()
        tmp["Height"] = pd.to_numeric(tmp["Height"], errors="coerce")
        for _, row in tmp.dropna(subset=["Height"]).iterrows():
            height_map[(row["Player"], row["Team"])] = float(row["Height"])

    match_df = match_df.copy()
    match_df["Player"] = match_df["Player"].astype(str).str.strip().str.lower()
    match_df["Team"] = match_df["Team"].astype(str).str.strip().map(normalize_team_name).str.lower()
    match_df["Goals"] = pd.to_numeric(match_df["Goals"], errors="coerce").fillna(0)
    match_df["Marks"] = pd.to_numeric(match_df["Marks"], errors="coerce").fillna(0)

    agg = (
        match_df.groupby(["Player", "Team"], as_index=False)
        .agg(
            goals=("Goals", "sum"),
            marks=("Marks", "sum"),
            matches=("Player", "size"),
        )
    )
    if agg.empty:
        return set()

    keys: set[tuple[str, str]] = set()
    for _, row in agg.iterrows():
        player = str(row["Player"])
        team = str(row["Team"])
        goals = float(row["goals"])
        marks = float(row["marks"])
        matches = int(row["matches"])
        height = height_map.get((player, team))

        is_tall = height is not None and height >= 190
        # Conservative KPF profile: must be a tall forward with sustained output.
        if is_tall and matches >= 5 and goals >= 12:
            keys.add((player, team))

    return keys


def load_csv_with_team_fallback(
    path: str | Path,
    expected_teams: int = EXPECTED_AFL_TEAM_COUNT,
    backup_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, Path, bool]:
    """Load a CSV, falling back to the latest backup with the expected team count."""
    csv_path = Path(path)
    if backup_dir is None:
        backup_dir = csv_path.resolve().parent.parent.parent / "backups"
    backup_path = Path(backup_dir)

    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    current_df = pd.read_csv(csv_path)
    if count_unique_teams(current_df) == expected_teams:
        return current_df, csv_path, False

    pattern = f"{csv_path.stem}_*.csv"
    backups = sorted(backup_path.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in backups:
        try:
            candidate_df = pd.read_csv(candidate)
        except Exception:
            continue
        if count_unique_teams(candidate_df) == expected_teams:
            return candidate_df, candidate, True

    raise ValueError(
        f"{csv_path.name} has {count_unique_teams(current_df)} teams; no {expected_teams}-team backup found"
    )


def build_current_season_position_lookup(
    season: int,
    base_dir: str | Path | None = None,
) -> dict[str, str]:
    """Build a current-season player -> position lookup from fresh weekly files."""
    root = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent.parent
    raw_player_dir = root / "data" / "raw" / "player"

    source_files = [
        raw_player_dir / f"footywire_{season}_with_traits.csv",
        raw_player_dir / f"footywire_{season}_complete.csv",
        raw_player_dir / f"squads_{season}.csv",
        raw_player_dir / f"player_stats_{season}.csv",
    ]

    lookup: dict[str, str] = {}
    for path in source_files:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if "Player" not in df.columns:
            continue

        for _, row in df.iterrows():
            player = str(row.get("Player", "")).strip().lower()
            if not player or player in lookup:
                continue

            position = ""
            if "Position_API" in df.columns:
                position = choose_preferred_position(
                    row.get("Position", ""),
                    row.get("Position_API", ""),
                )
            if not position and "Position_Full" in df.columns:
                position = map_position_label(row.get("Position_Full", ""))
            if not position and "Position_Clean" in df.columns:
                position = map_position_label(row.get("Position_Clean", ""))
            if not position and "Position" in df.columns:
                position = map_position_label(row.get("Position", ""))

            if position:
                lookup[player] = position

    return lookup


def resolve_positions_for_output(
    df: pd.DataFrame,
    season: int,
    base_dir: str | Path | None = None,
    position_col: str = "Position",
) -> pd.DataFrame:
    """Add stable resolved/current-season position columns for pipeline outputs."""
    out = df.copy()
    if position_col not in out.columns:
        out["Position_Resolved"] = ""
        return out

    if "Position_Raw" not in out.columns:
        out["Position_Raw"] = out[position_col]

    lookup = build_current_season_position_lookup(season, base_dir)
    resolved = out["Player"].astype(str).str.strip().str.lower().map(lookup)
    fallback = out[position_col].map(map_position_label)
    out["Position_Resolved"] = resolved.fillna(fallback).fillna("")

    wing_keys = load_wing_player_keys(base_dir)
    if wing_keys and "Player" in out.columns and "Team" in out.columns:
        player_norm = out["Player"].astype(str).str.strip().str.lower()
        team_norm = out["Team"].astype(str).str.strip().map(normalize_team_name).str.lower()
        is_wing = [(p, t) in wing_keys for p, t in zip(player_norm, team_norm)]
        out.loc[is_wing, "Position_Resolved"] = "Wing"

    key_forward_keys = load_key_forward_player_keys(season, base_dir)
    if key_forward_keys and "Player" in out.columns and "Team" in out.columns:
        player_norm = out["Player"].astype(str).str.strip().str.lower()
        team_norm = out["Team"].astype(str).str.strip().map(normalize_team_name).str.lower()
        is_key_forward = [(p, t) in key_forward_keys for p, t in zip(player_norm, team_norm)]
        current_pos = out["Position_Resolved"].astype(str)
        can_promote = current_pos.isin({"Gen. Forward", "Mid-Forward", "Forward"})
        out.loc[pd.Series(is_key_forward, index=out.index) & can_promote, "Position_Resolved"] = "Key Forward"

    return out