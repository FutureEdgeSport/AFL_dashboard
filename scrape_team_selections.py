#!/usr/bin/env python3
"""
Scrape AFL Team Selections from FootyWire
==========================================
Fetches announced team selections (22 + interchange + emergencies)
for the upcoming round from FootyWire's team selections page.

Also fetches fixture data from the Squiggle API to determine game
dates and allow grouping by announcement day.

Usage:
    python scrape_team_selections.py              # Scrape current round
    python scrape_team_selections.py --round 7    # Scrape specific round
    python scrape_team_selections.py --fixture    # Refresh fixture cache only
"""
import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from config.constants import CURRENT_SEASON
from utils.http_utils import create_retry_session
from utils.safe_io import safe_csv_write

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data" / "raw"
FIXTURE_DIR = DATA_DIR / "fixture"
TEAM_SEL_DIR = DATA_DIR / "team"

FOOTYWIRE_URL = "https://www.footywire.com/afl/footy/afl_team_selections"
SQUIGGLE_GAMES_URL = "https://api.squiggle.com.au/"

# Map FootyWire team slugs (from player URLs) to canonical team names
_FW_SLUG_TO_TEAM = {
    "adelaide-crows": "Adelaide",
    "brisbane-lions": "Brisbane Lions",
    "carlton-blues": "Carlton",
    "collingwood-magpies": "Collingwood",
    "essendon-bombers": "Essendon",
    "fremantle-dockers": "Fremantle",
    "geelong-cats": "Geelong",
    "gold-coast-suns": "Gold Coast",
    "greater-western-sydney-giants": "GWS Giants",
    "hawthorn-hawks": "Hawthorn",
    "kangaroos": "North Melbourne",
    "melbourne-demons": "Melbourne",
    "port-adelaide-power": "Port Adelaide",
    "richmond-tigers": "Richmond",
    "st-kilda-saints": "St Kilda",
    "sydney-swans": "Sydney",
    "west-coast-eagles": "West Coast",
    "western-bulldogs": "Western Bulldogs",
}

# Map FootyWire match header names to canonical names
_FW_HEADER_TO_TEAM = {
    "Adelaide": "Adelaide",
    "Brisbane": "Brisbane Lions",
    "Brisbane Lions": "Brisbane Lions",
    "Carlton": "Carlton",
    "Collingwood": "Collingwood",
    "Essendon": "Essendon",
    "Fremantle": "Fremantle",
    "Geelong": "Geelong",
    "Gold Coast": "Gold Coast",
    "GWS": "GWS Giants",
    "GWS Giants": "GWS Giants",
    "Greater Western Sydney": "GWS Giants",
    "Hawthorn": "Hawthorn",
    "Melbourne": "Melbourne",
    "North Melbourne": "North Melbourne",
    "Port Adelaide": "Port Adelaide",
    "Richmond": "Richmond",
    "St Kilda": "St Kilda",
    "Sydney": "Sydney",
    "West Coast": "West Coast",
    "Western Bulldogs": "Western Bulldogs",
}

# Squiggle team names to canonical names
_SQUIGGLE_TO_TEAM = {
    "Adelaide": "Adelaide",
    "Brisbane Lions": "Brisbane Lions",
    "Carlton": "Carlton",
    "Collingwood": "Collingwood",
    "Essendon": "Essendon",
    "Fremantle": "Fremantle",
    "Geelong": "Geelong",
    "Gold Coast": "Gold Coast",
    "Greater Western Sydney": "GWS Giants",
    "Hawthorn": "Hawthorn",
    "Melbourne": "Melbourne",
    "North Melbourne": "North Melbourne",
    "Port Adelaide": "Port Adelaide",
    "Richmond": "Richmond",
    "St Kilda": "St Kilda",
    "Sydney": "Sydney",
    "West Coast": "West Coast",
    "Western Bulldogs": "Western Bulldogs",
}

# FootyWire position labels → Position group
_POS_MAP = {
    "FB": "Key Defender",
    "HB": "Gen. Defender",
    "C": "Midfielder",
    "HF": "Gen. Forward",
    "FF": "Key Forward",
    "Fol": "Ruck",
}

_session = create_retry_session(retries=3, backoff_factor=1.0, timeout=20)


# ── Fixture (Squiggle API) ─────────────────────────────────────────────────
def fetch_fixture(season: int, round_num: int | None = None) -> pd.DataFrame:
    """Fetch fixture from Squiggle API.  Returns DataFrame with columns:
    Season, Round, GameId, HomeTeam, AwayTeam, Venue, GameDate, GameDay, Status
    """
    params = {"q": "games", "year": str(season)}
    if round_num:
        params["round"] = str(round_num)
    resp = _session.get(
        SQUIGGLE_GAMES_URL,
        params=params,
        headers={"User-Agent": "AFL-Dashboard - github.com/FutureEdgeSport/AFL_dashboard"},
    )
    resp.raise_for_status()
    games = resp.json().get("games", [])
    rows = []
    for g in games:
        dt_str = g.get("date", "")  # "2026-04-16 19:30:00"
        try:
            dt = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            dt = None
        rows.append(
            {
                "Season": season,
                "Round": g.get("round"),
                "GameId": g.get("id"),
                "HomeTeam": _SQUIGGLE_TO_TEAM.get(g.get("hteam", ""), g.get("hteam", "")),
                "AwayTeam": _SQUIGGLE_TO_TEAM.get(g.get("ateam", ""), g.get("ateam", "")),
                "Venue": g.get("venue", ""),
                "GameDate": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
                "GameDay": dt.strftime("%A") if dt else "",
                "Status": "Complete" if g.get("complete") == 100 else "Scheduled",
            }
        )
    return pd.DataFrame(rows)


def save_fixture(season: int, round_num: int | None = None):
    """Fetch and save fixture CSV."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    df = fetch_fixture(season, round_num)
    if df.empty:
        logger.warning("No fixture data returned from Squiggle API")
        return df
    path = FIXTURE_DIR / f"fixture_{season}.csv"
    safe_csv_write(df, str(path))
    logger.info("Saved %d games to %s", len(df), path)
    return df


# ── Team Selections (FootyWire) ────────────────────────────────────────────
def _team_from_href(href: str) -> str | None:
    """Extract canonical team name from FootyWire player URL."""
    m = re.match(r"pp-([a-z-]+)--", href)
    if m:
        slug = m.group(1)
        return _FW_SLUG_TO_TEAM.get(slug)
    return None


def _parse_match_header(text: str):
    """Parse 'Team1 v Team2 (Venue)' → (home_canonical, away_canonical, venue)."""
    m = re.match(r"(.+?)\s+v\s+(.+?)\s*\(([^)]+)\)", text.strip())
    if not m:
        return None, None, None
    raw_home, raw_away, venue = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    home = _FW_HEADER_TO_TEAM.get(raw_home, raw_home)
    away = _FW_HEADER_TO_TEAM.get(raw_away, raw_away)
    return home, away, venue


def scrape_team_selections(season: int = CURRENT_SEASON) -> pd.DataFrame:
    """Scrape team selections from FootyWire.

    Returns DataFrame with columns:
        Season, Round, Team, Player, PlayerUrl, Position, SelectionType, ScrapedAt
    """
    resp = _session.get(FOOTYWIRE_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract round number from page title
    round_match = re.search(r"Round\s+(\d+)", soup.get_text())
    fw_round = int(round_match.group(1)) if round_match else None
    logger.info("FootyWire page shows Round %s", fw_round)

    # Find match sections via anchor tags: <a name="NNNNN"></a>
    # Each match has a unique anchor followed by a header cell with "X v Y (Venue)"
    match_anchors = soup.find_all("a", attrs={"name": re.compile(r"^\d+$")})

    all_rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for anchor in match_anchors:
        # The title cell is near the anchor
        title_td = anchor.find_parent("td")
        if not title_td:
            continue
        title_text = title_td.get_text(strip=True)
        home, away, venue = _parse_match_header(title_text)
        if not home:
            continue

        # Walk up to the containing TR/TABLE for this match section
        match_container = anchor.find_parent("table")
        if not match_container:
            match_container = anchor.find_parent("tr")
        if not match_container:
            continue

        # Walk through the match section to find all player links and sections
        # Strategy: iterate all elements in order, track current section context
        current_section = "selected"
        position_rows_seen = set()

        for elem in match_container.find_all(["b", "a", "td"]):
            tag = elem.name

            # Section headers in bold
            if tag == "b":
                text = elem.get_text(strip=True)
                if text == "Interchange":
                    current_section = "interchange"
                elif text == "Emergencies":
                    current_section = "emergency"
                elif text == "Ins":
                    current_section = "in"
                elif text == "Outs":
                    current_section = "out"
                elif text in _POS_MAP:
                    current_section = "selected"
                continue

            # Position labels in td cells (non-bold)
            if tag == "td":
                text = elem.get_text(strip=True).lstrip("\xa0").strip()
                if text in _POS_MAP:
                    current_section = "selected"
                continue

            # Player links
            if tag == "a":
                href = elem.get("href", "")
                if not href.startswith("pp-"):
                    continue
                team = _team_from_href(href)
                player_name = elem.get_text(strip=True)
                if not team or not player_name:
                    continue

                # Determine position from the URL → team, then from context
                # For 'selected' players, try to find position from nearby td
                position = ""
                if current_section == "selected":
                    # Look at parent row for position label
                    row = elem.find_parent("tr")
                    if row:
                        cells = row.find_all("td")
                        for c in cells:
                            ct = c.get_text(strip=True).lstrip("\xa0").strip()
                            if ct in _POS_MAP:
                                position = _POS_MAP[ct]
                                break
                elif current_section == "interchange":
                    position = "Interchange"

                # Determine selection type for output
                if current_section in ("in", "out"):
                    # Ins/Outs are metadata, not part of the actual selection
                    sel_type = current_section
                elif current_section == "emergency":
                    sel_type = "emergency"
                elif current_section == "interchange":
                    sel_type = "interchange"
                else:
                    sel_type = "selected"

                all_rows.append(
                    {
                        "Season": season,
                        "Round": fw_round,
                        "Team": team,
                        "Player": player_name,
                        "PlayerUrl": href,
                        "Position": position,
                        "SelectionType": sel_type,
                        "ScrapedAt": now,
                    }
                )

    df = pd.DataFrame(all_rows)
    if not df.empty:
        # Remove 'in'/'out' rows — they're just change metadata
        df = df[~df["SelectionType"].isin(["in", "out"])].reset_index(drop=True)
    return df


def _sunday_teams_for_round(season: int, round_num: int) -> set[str]:
    """Return the set of canonical team names playing on Sunday in this round."""
    fixture_path = FIXTURE_DIR / f"fixture_{season}.csv"
    if not fixture_path.exists():
        return set()
    fix = pd.read_csv(fixture_path)
    sunday = fix[(fix["Round"] == round_num) & (fix["GameDay"] == "Sunday")]
    teams = set(sunday["HomeTeam"].tolist()) | set(sunday["AwayTeam"].tolist())
    return teams


def save_team_selections(season: int = CURRENT_SEASON) -> pd.DataFrame:
    """Scrape and save team selections.

    Merges with any existing selections for the season (different rounds
    or earlier partial scrapes for the same round).

    Sunday game teams are excluded until Friday 7pm because earlier in
    the week they only have extended squads (not finalised 23-player lists).
    """
    TEAM_SEL_DIR.mkdir(parents=True, exist_ok=True)
    path = TEAM_SEL_DIR / f"team_selections_{season}.csv"

    new_df = scrape_team_selections(season)
    if new_df.empty:
        logger.warning("No team selections scraped from FootyWire")
        return new_df

    current_round = new_df["Round"].iloc[0]

    # ── Exclude Sunday-game teams before Friday 7pm ────────────────────
    now = datetime.now()
    is_friday_evening_or_later = (
        now.weekday() > 4  # Saturday (5) or Sunday (6)
        or (now.weekday() == 4 and now.hour >= 19)  # Friday 7pm+
    )
    if not is_friday_evening_or_later:
        sunday_teams = _sunday_teams_for_round(season, current_round)
        if sunday_teams:
            before = new_df["Team"].nunique()
            new_df = new_df[~new_df["Team"].isin(sunday_teams)].reset_index(drop=True)
            after = new_df["Team"].nunique()
            logger.info(
                "Excluded %d Sunday-game teams (extended squads only): %s",
                before - after,
                ", ".join(sorted(sunday_teams)),
            )
            if new_df.empty:
                logger.warning("All scraped teams are Sunday games — nothing to save yet")
                return new_df

    logger.info(
        "Scraped %d selection entries for Round %s (%d teams)",
        len(new_df),
        current_round,
        new_df["Team"].nunique(),
    )

    # Load existing and merge
    if path.exists():
        existing = pd.read_csv(path)
        # Remove existing data for this round (will be replaced with fresh scrape)
        existing = existing[existing["Round"] != current_round]
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    safe_csv_write(combined, str(path))
    logger.info("Saved %d total selection entries to %s", len(combined), path)
    return new_df


# ── Next round helper ──────────────────────────────────────────────────────
def get_next_round(season: int = CURRENT_SEASON) -> int | None:
    """Determine the next unplayed round from fixture data."""
    fixture_path = FIXTURE_DIR / f"fixture_{season}.csv"
    if not fixture_path.exists():
        save_fixture(season)
    if not fixture_path.exists():
        return None
    df = pd.read_csv(fixture_path)
    scheduled = df[df["Status"] == "Scheduled"]
    if scheduled.empty:
        return None
    return int(scheduled["Round"].min())


# ── Validation: announced vs actual ───────────────────────────────────────
def validate_selections(season: int = CURRENT_SEASON) -> pd.DataFrame:
    """Compare announced team selections against actual match-day players.

    Runs after games are played (Mon/Tue). Returns a DataFrame of discrepancies:
    - Players announced but didn't play (late withdrawals)
    - Players who played but weren't in announced squad (late inclusions)

    CSV output: data/raw/team/selection_validation_{season}.csv
    """
    sel_path = TEAM_SEL_DIR / f"team_selections_{season}.csv"
    mr_path = DATA_DIR / "player" / f"match_ratings_{season}.csv"

    if not sel_path.exists() or not mr_path.exists():
        logger.info("Validation skipped — missing selections or match ratings")
        return pd.DataFrame()

    sel_df = pd.read_csv(sel_path)
    mr_df = pd.read_csv(mr_path)
    mr_df["Team"] = mr_df["Team"].replace({"Greater Western Sydney": "GWS Giants"})

    # Only validate completed rounds (rounds present in match_ratings)
    played_rounds = set(mr_df["Round"].unique())
    announced_rounds = set(sel_df["Round"].unique())
    validate_rounds = played_rounds & announced_rounds

    if not validate_rounds:
        logger.info("No rounds to validate (no overlap between selections and ratings)")
        return pd.DataFrame()

    discrepancies = []
    for rnd in sorted(validate_rounds):
        _sel_rnd = sel_df[
            (sel_df["Round"] == rnd) &
            (sel_df["SelectionType"].isin(["selected", "interchange"]))
        ]
        _mr_rnd = mr_df[mr_df["Round"] == rnd]

        for team in _sel_rnd["Team"].unique():
            announced = set(_sel_rnd[_sel_rnd["Team"] == team]["Player"].tolist())
            actual = set(_mr_rnd[_mr_rnd["Team"] == team]["Player"].tolist())

            # Normalise for comparison (abbreviated vs full names)
            def _abbrev(name):
                parts = name.split()
                if len(parts) >= 2:
                    return (parts[0][0], parts[-1].lower())
                return (name[0] if name else "", name.lower())

            announced_abbrev = {_abbrev(n): n for n in announced}
            actual_abbrev = {_abbrev(n): n for n in actual}

            for key, name in announced_abbrev.items():
                if key not in actual_abbrev:
                    discrepancies.append({
                        "Season": season, "Round": rnd, "Team": team,
                        "Player": name, "Type": "late_withdrawal",
                        "Detail": "Announced but did not play",
                    })
            for key, name in actual_abbrev.items():
                if key not in announced_abbrev:
                    discrepancies.append({
                        "Season": season, "Round": rnd, "Team": team,
                        "Player": name, "Type": "late_inclusion",
                        "Detail": "Played but was not in announced squad",
                    })

    result = pd.DataFrame(discrepancies)
    if not result.empty:
        val_path = TEAM_SEL_DIR / f"selection_validation_{season}.csv"
        safe_csv_write(result, str(val_path))
        logger.info(
            "Validation: %d discrepancies across %d rounds saved to %s",
            len(result), len(validate_rounds), val_path,
        )
    else:
        logger.info("Validation: no discrepancies found for rounds %s", sorted(validate_rounds))

    return result


# ── CLI ────────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = argparse.ArgumentParser(description="Scrape AFL team selections")
    parser.add_argument("--round", type=int, help="Specific round to fetch fixture for")
    parser.add_argument("--fixture", action="store_true", help="Only refresh fixture data")
    parser.add_argument("--validate", action="store_true", help="Validate announced vs actual squads")
    parser.add_argument("--season", type=int, default=CURRENT_SEASON)
    args = parser.parse_args()

    season = args.season

    if args.validate:
        logger.info("Running selection validation ...")
        val_df = validate_selections(season)
        if not val_df.empty:
            logger.info("Discrepancies:\n%s", val_df.to_string(index=False))
        return

    # Always refresh fixture
    logger.info("Fetching fixture from Squiggle API ...")
    fixture_df = save_fixture(season, args.round)
    logger.info("Fixture: %d games", len(fixture_df))

    if args.fixture:
        return

    # Scrape team selections
    logger.info("Scraping team selections from FootyWire ...")
    sel_df = save_team_selections(season)
    if sel_df.empty:
        logger.warning("No team selections found — teams may not be announced yet")
    else:
        logger.info(
            "Done: %d entries for Round %s — teams: %s",
            len(sel_df),
            sel_df["Round"].iloc[0],
            ", ".join(sorted(sel_df["Team"].unique())),
        )


if __name__ == "__main__":
    main()
