from pathlib import Path

import pandas as pd

from utils.player_positions import (
    choose_preferred_position,
    build_current_season_position_lookup,
    load_key_forward_player_keys,
    load_wing_player_keys,
    load_csv_with_team_fallback,
    map_position_label,
    resolve_positions_for_output,
)


def test_map_position_label_handles_footywire_generic_roles():
    assert map_position_label("DefenderForward") == "Gen. Defender"
    assert map_position_label("MidfieldForward") == "Mid-Forward"
    assert map_position_label("GF") == "Gen. Forward"


def test_choose_preferred_position_preserves_mid_forward_against_generic_traits():
    assert choose_preferred_position("MidfieldForward", "M") == "Mid-Forward"
    assert choose_preferred_position("MidfieldForward", "GF") == "Mid-Forward"
    assert choose_preferred_position("MidfieldForward", "MF") == "Mid-Forward"


def test_current_season_lookup_prefers_traits_position_api(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw" / "player"
    raw_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "Player": "Koltyn Tholstrup",
                "Position": "DefenderForward",
                "Position_API": "GD",
            }
        ]
    ).to_csv(raw_dir / "footywire_2026_with_traits.csv", index=False)

    lookup = build_current_season_position_lookup(2026, tmp_path)

    assert lookup["koltyn tholstrup"] == "Gen. Defender"


def test_current_season_lookup_falls_back_to_roster_position(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw" / "player"
    raw_dir.mkdir(parents=True)

    pd.DataFrame(
        [{"Player": "Koltyn Tholstrup", "Position": "DefenderForward"}]
    ).to_csv(raw_dir / "player_stats_2026.csv", index=False)

    lookup = build_current_season_position_lookup(2026, tmp_path)

    assert lookup["koltyn tholstrup"] == "Gen. Defender"


def test_resolve_positions_for_output_prefers_current_traits_position(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw" / "player"
    raw_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "Player": "Koltyn Tholstrup",
                "Team": "Melbourne",
                "Position": "DefenderForward",
                "Position_API": "GD",
            }
        ]
    ).to_csv(raw_dir / "footywire_2026_with_traits.csv", index=False)

    source = pd.DataFrame(
        [{"Player": "Koltyn Tholstrup", "Team": "Melbourne", "Position": "Forward"}]
    )
    resolved = resolve_positions_for_output(source, 2026, tmp_path)

    assert resolved.loc[0, "Position_Raw"] == "Forward"
    assert resolved.loc[0, "Position_Resolved"] == "Gen. Defender"


def test_load_csv_with_team_fallback_uses_latest_good_backup(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw" / "player"
    backup_dir = tmp_path / "data" / "backups"
    raw_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)

    pd.DataFrame([
        {"Team": f"Team{i}", "Player": f"P{i}"} for i in range(14)
    ]).to_csv(raw_dir / "footywire_2026_lists.csv", index=False)
    pd.DataFrame([
        {"Team": f"Team{i}", "Player": f"P{i}"} for i in range(18)
    ]).to_csv(backup_dir / "footywire_2026_lists_20260706_090910.csv", index=False)

    df, source_path, used_backup = load_csv_with_team_fallback(raw_dir / "footywire_2026_lists.csv")

    assert used_backup is True
    assert source_path.name == "footywire_2026_lists_20260706_090910.csv"
    assert df["Team"].nunique() == 18


def test_load_wing_player_keys_from_historical_sheet(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    xlsx_path = data_dir / "AFL_Historical_2012_2025.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        pd.DataFrame(
            [
                {"Player": "Toby Bedford", "Team": "GWS Giants", "Position": "Wing"},
            ]
        ).to_excel(w, sheet_name="Wings", index=False)

    keys = load_wing_player_keys(tmp_path)
    assert ("toby bedford", "gws giants") in keys


def test_resolve_positions_for_output_applies_wing_overlay(tmp_path: Path):
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "player"
    raw_dir.mkdir(parents=True)
    xlsx_path = data_dir / "AFL_Historical_2012_2025.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        pd.DataFrame(
            [
                {"Player": "Toby Bedford", "Team": "GWS Giants", "Position": "Wing"},
            ]
        ).to_excel(w, sheet_name="Wings", index=False)

    source = pd.DataFrame(
        [
            {"Player": "Toby Bedford", "Team": "GWS Giants", "Position": "MidfieldForward"},
            {"Player": "Leek Aleer", "Team": "GWS Giants", "Position": "Defender"},
        ]
    )
    out = resolve_positions_for_output(source, 2026, tmp_path)

    assert out.loc[out["Player"] == "Toby Bedford", "Position_Resolved"].iloc[0] == "Wing"
    assert out.loc[out["Player"] == "Leek Aleer", "Position_Resolved"].iloc[0] == "Gen. Defender"


def test_load_key_forward_player_keys_from_match_profile(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw" / "player"
    raw_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {"Player": "Josh Treacy", "Team": "Fremantle", "Height": 196},
        ]
    ).to_csv(raw_dir / "squads_2026.csv", index=False)

    rows = []
    for _ in range(8):
        rows.append({"Player": "Josh Treacy", "Team": "Fremantle", "Goals": 2, "Marks": 5})
    pd.DataFrame(rows).to_csv(raw_dir / "match_ratings_2026.csv", index=False)

    keys = load_key_forward_player_keys(2026, tmp_path)
    assert ("josh treacy", "fremantle") in keys


def test_resolve_positions_for_output_applies_key_forward_overlay(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw" / "player"
    raw_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {"Player": "Josh Treacy", "Team": "Fremantle", "Height": 196},
            {"Player": "Sam Switkowski", "Team": "Fremantle", "Height": 180},
        ]
    ).to_csv(raw_dir / "squads_2026.csv", index=False)

    rows = []
    for _ in range(8):
        rows.append({"Player": "Josh Treacy", "Team": "Fremantle", "Goals": 2, "Marks": 5})
    for _ in range(8):
        rows.append({"Player": "Sam Switkowski", "Team": "Fremantle", "Goals": 1, "Marks": 2})
    pd.DataFrame(rows).to_csv(raw_dir / "match_ratings_2026.csv", index=False)

    source = pd.DataFrame(
        [
            {"Player": "Josh Treacy", "Team": "Fremantle", "Position": "Forward"},
            {"Player": "Sam Switkowski", "Team": "Fremantle", "Position": "Forward"},
        ]
    )
    out = resolve_positions_for_output(source, 2026, tmp_path)

    assert out.loc[out["Player"] == "Josh Treacy", "Position_Resolved"].iloc[0] == "Key Forward"
    assert out.loc[out["Player"] == "Sam Switkowski", "Position_Resolved"].iloc[0] == "Gen. Forward"


def test_resolve_positions_for_output_does_not_promote_non_tall_forwards(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw" / "player"
    raw_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {"Player": "Ben Ainsworth", "Team": "Carlton", "Height": 178},
        ]
    ).to_csv(raw_dir / "squads_2026.csv", index=False)

    rows = []
    for _ in range(16):
        rows.append({"Player": "Ben Ainsworth", "Team": "Carlton", "Goals": 1, "Marks": 5})
    pd.DataFrame(rows).to_csv(raw_dir / "match_ratings_2026.csv", index=False)

    source = pd.DataFrame(
        [
            {"Player": "Ben Ainsworth", "Team": "Carlton", "Position": "Forward"},
        ]
    )
    out = resolve_positions_for_output(source, 2026, tmp_path)

    assert out.loc[out["Player"] == "Ben Ainsworth", "Position_Resolved"].iloc[0] == "Gen. Forward"