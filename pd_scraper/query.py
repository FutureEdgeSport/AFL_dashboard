"""High-level query helpers for consumers of ``data/pd/pd.db``.

Designed to be importable from external apps (e.g. the MGS app) without
needing to know the internal schema.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from .config import settings


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else settings.db_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def matches(season: int | None = None, team: str | None = None,
            db_path: Path | str | None = None) -> pd.DataFrame:
    """Return one row per match, optionally filtered by season and/or team."""
    sql = "SELECT * FROM matches WHERE 1=1"
    params: list[Any] = []
    if season is not None:
        sql += " AND season = ?"
        params.append(season)
    if team:
        sql += " AND (home_team = ? OR away_team = ?)"
        params += [team, team]
    sql += " ORDER BY season, round, match_id"
    with connect(db_path) as c:
        return pd.read_sql_query(sql, c, params=params)


def team_stats(match_id: str, period: str = "TOTAL",
               db_path: Path | str | None = None) -> pd.DataFrame:
    """Team-level stats (summary/efficiencies/free_kicks) pivoted to wide."""
    sql = """
        SELECT tab, section, stat_name, side, value, value_num
        FROM team_match_stats
        WHERE match_id = ? AND period = ?
        ORDER BY tab, section, stat_name
    """
    with connect(db_path) as c:
        return pd.read_sql_query(sql, c, params=[match_id, period])


def player_stats(match_id: str, view: str = "Basic", period: str = "TOTAL",
                 db_path: Path | str | None = None) -> pd.DataFrame:
    """Per-player stats for one match, pivoted wide (one row per player)."""
    sql = """
        SELECT side, team, jumper, player, stat_name, value_num
        FROM player_match_stats
        WHERE match_id = ? AND view = ? AND period = ?
    """
    with connect(db_path) as c:
        long = pd.read_sql_query(sql, c, params=[match_id, view, period])
    if long.empty:
        return long
    wide = long.pivot_table(
        index=["side", "team", "jumper", "player"],
        columns="stat_name", values="value_num", aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    return wide


def season_player_totals(season: int, view: str = "Basic",
                         db_path: Path | str | None = None) -> pd.DataFrame:
    """Aggregated per-player totals across all matches in a season."""
    sql = """
        SELECT p.team, p.player, p.stat_name,
               COUNT(DISTINCT p.match_id) AS matches,
               SUM(p.value_num)            AS total,
               AVG(p.value_num)            AS avg
        FROM player_match_stats p
        JOIN matches m USING (match_id)
        WHERE m.season = ? AND p.view = ? AND p.period = 'TOTAL'
        GROUP BY p.team, p.player, p.stat_name
    """
    with connect(db_path) as c:
        long = pd.read_sql_query(sql, c, params=[season, view])
    if long.empty:
        return long
    wide = long.pivot_table(
        index=["team", "player"], columns="stat_name",
        values="total", aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    # Tack on match count
    mc = long.groupby(["team", "player"])["matches"].max().reset_index()
    return wide.merge(mc, on=["team", "player"])


def shots(match_id: str, db_path: Path | str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM shots WHERE match_id = ? ORDER BY period, idx"
    with connect(db_path) as c:
        return pd.read_sql_query(sql, c, params=[match_id])


def players(team: str | None = None,
            db_path: Path | str | None = None) -> pd.DataFrame:
    """All players seen across all matches, optionally scoped to a team."""
    sql = "SELECT * FROM pd_players"
    params: list[Any] = []
    if team:
        sql += " WHERE team = ?"
        params.append(team)
    sql += " ORDER BY team, player"
    with connect(db_path) as c:
        return pd.read_sql_query(sql, c, params=params)
