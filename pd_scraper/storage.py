"""SQLite storage layer for pd_scraper.

Idempotent upsert of a match JSON (produced by ``scrape_match.scrape_match``)
into the normalised schema defined in ``schema.sql``.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import settings

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect() -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = connect()
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        if own:
            conn.close()


_PCT_RE = re.compile(r"^-?\d+(\.\d+)?%$")
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_RATIO_RE = re.compile(r"^\d+/\d+$")


def _coerce(v: Any) -> tuple[str | None, float | None, str]:
    """Return (text, numeric, type_tag)."""
    if v is None:
        return None, None, "null"
    if isinstance(v, bool):
        return str(v), 1.0 if v else 0.0, "bool"
    if isinstance(v, (int, float)):
        return str(v), float(v), "float" if isinstance(v, float) else "int"
    s = str(v).strip()
    if not s:
        return "", None, "text"
    if _INT_RE.match(s):
        return s, float(s), "int"
    if _FLOAT_RE.match(s):
        return s, float(s), "float"
    if _PCT_RE.match(s):
        return s, float(s.rstrip("%")), "pct"
    if _RATIO_RE.match(s):
        num, den = s.split("/")
        try:
            return s, float(num) / float(den) if float(den) else None, "ratio"
        except Exception:
            return s, None, "ratio"
    return s, None, "text"


def _upsert_match(cur: sqlite3.Cursor, data: dict, raw_path: Path | None) -> str:
    meta = data.get("_meta") or {}
    header = data.get("header") or {}
    match_id = data.get("match_id") or meta.get("slug")
    if not match_id:
        raise ValueError("No match_id/slug in data")
    cur.execute(
        """
        INSERT INTO matches(match_id, season, round, home_team, away_team,
                            home_score, away_score, home_goals_behinds,
                            away_goals_behinds, card_label, scraped_at, raw_json_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id) DO UPDATE SET
            season=excluded.season,
            round=excluded.round,
            home_team=excluded.home_team,
            away_team=excluded.away_team,
            home_score=excluded.home_score,
            away_score=excluded.away_score,
            home_goals_behinds=excluded.home_goals_behinds,
            away_goals_behinds=excluded.away_goals_behinds,
            card_label=excluded.card_label,
            scraped_at=excluded.scraped_at,
            raw_json_path=excluded.raw_json_path
        """,
        (
            match_id,
            int(meta.get("season") or 0) or None,
            str(meta.get("round") or header.get("round") or ""),
            header.get("home_team"),
            header.get("away_team"),
            header.get("home_score"),
            header.get("away_score"),
            header.get("home_goals_behinds"),
            header.get("away_goals_behinds"),
            meta.get("card_label"),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            str(raw_path) if raw_path else None,
        ),
    )
    return match_id


def _clear_dependent(cur: sqlite3.Cursor, match_id: str) -> None:
    for t in (
        "team_match_stats",
        "score_sources",
        "shots",
        "player_match_stats",
        "efficiency_ratios",
        "pie_stats",
    ):
        cur.execute(f"DELETE FROM {t} WHERE match_id = ?", (match_id,))


def _insert_summary(cur: sqlite3.Cursor, match_id: str, period: str, blob: dict) -> None:
    if not blob:
        return
    # Donuts (Disposal Eff / Kick Eff / Handball Eff), side may be None (=home)
    for d in blob.get("efficiency_donuts") or []:
        side = d.get("side") or "home"
        text, num, typ = _coerce(d.get("value"))
        cur.execute(
            """INSERT OR REPLACE INTO team_match_stats
               (match_id, period, tab, section, stat_name, side, value, value_num, value_type)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (match_id, period, "summary", "efficiency", d.get("label"), side, text, num, typ),
        )
    for section in blob.get("sections") or []:
        sec_name = section.get("name")
        for row in section.get("stats") or []:
            name = row.get("name")
            for side_key in ("home", "away", "diff"):
                v = row.get(side_key)
                text, num, typ = _coerce(v)
                cur.execute(
                    """INSERT OR REPLACE INTO team_match_stats
                       (match_id, period, tab, section, stat_name, side, value, value_num, value_type)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (match_id, period, "summary", sec_name, name, side_key, text, num, typ),
                )


def _insert_score_sources(cur: sqlite3.Cursor, match_id: str, period: str, blob: dict) -> None:
    if not blob:
        return
    # Donuts (scoring efficiency, goal accuracy)
    for d in blob.get("donuts") or []:
        text, num, typ = _coerce(d.get("value"))
        cur.execute(
            """INSERT OR REPLACE INTO team_match_stats
               (match_id, period, tab, section, stat_name, side, value, value_num, value_type)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (match_id, period, "score_sources", "efficiency",
             d.get("label"), d.get("side") or "home", text, num, typ),
        )
    for r in blob.get("rows") or []:
        cur.execute(
            """INSERT OR REPLACE INTO score_sources
               (match_id, period, parent, name, home_scoreline, home_pct, away_scoreline, away_pct)
               VALUES (?,?,?,?,?,?,?,?)""",
            (match_id, period, r.get("parent"), r.get("name"),
             r.get("home_scoreline"), r.get("home_pct"),
             r.get("away_scoreline"), r.get("away_pct")),
        )


def _insert_efficiencies(cur: sqlite3.Cursor, match_id: str, period: str, blob: dict) -> None:
    if not blob:
        return
    for sec in blob.get("sections") or []:
        sec_name = sec.get("name")
        for s in sec.get("stats") or []:
            cur.execute(
                """INSERT OR REPLACE INTO efficiency_ratios
                   (match_id, period, section, name, home_pct, home_ratio, away_pct, away_ratio)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (match_id, period, sec_name, s.get("name"),
                 s.get("home_pct"), s.get("home_ratio"),
                 s.get("away_pct"), s.get("away_ratio")),
            )
    for p in blob.get("pies") or []:
        cur.execute(
            """INSERT OR REPLACE INTO pie_stats
               (match_id, period, section, name, side, value, labels)
               VALUES (?,?,?,?,?,?,?)""",
            (match_id, period, p.get("section"), p.get("name"),
             p.get("side"), p.get("value"), json.dumps(p.get("labels") or [])),
        )


def _insert_shots(cur: sqlite3.Cursor, match_id: str, period: str, blob: dict) -> None:
    if not blob:
        return
    for idx, shot in enumerate(blob.get("shots") or []):
        cur.execute(
            """INSERT OR REPLACE INTO shots
               (match_id, period, idx, time, type, team, player, source, assist)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (match_id, period, idx,
             shot.get("Time"), shot.get("Type"), shot.get("Team"),
             shot.get("Player"), shot.get("Source"), shot.get("Assist")),
        )


def _insert_free_kicks(cur: sqlite3.Cursor, match_id: str, period: str, blob: dict) -> None:
    if not blob:
        return
    for r in blob.get("rows") or []:
        name = r.get("name")
        for side_key in ("home", "away", "diff"):
            text, num, typ = _coerce(r.get(side_key))
            cur.execute(
                """INSERT OR REPLACE INTO team_match_stats
                   (match_id, period, tab, section, stat_name, side, value, value_num, value_type)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (match_id, period, "free_kicks", "free_kicks", name, side_key, text, num, typ),
            )


_PLAYER_NONSTAT_KEYS = {"col_0", "Name", "jumper", "player", "_team_club_id"}


def _insert_player_stats(cur: sqlite3.Cursor, match_id: str, entries: list[dict],
                         header: dict) -> None:
    home_team = (header or {}).get("home_team")
    away_team = (header or {}).get("away_team")
    for entry in entries or []:
        view = entry.get("view") or "?"
        period = entry.get("period") or "TOTAL"
        tf = (entry.get("team_filter") or "").lower()
        if "home" in tf:
            side, team = "home", home_team
        elif "away" in tf:
            side, team = "away", away_team
        else:
            side, team = "unknown", None
        for row in entry.get("rows") or []:
            player = row.get("player") or row.get("Name") or "?"
            jumper = row.get("jumper")
            for k, v in row.items():
                if k in _PLAYER_NONSTAT_KEYS:
                    continue
                text, num, _ = _coerce(v)
                cur.execute(
                    """INSERT OR REPLACE INTO player_match_stats
                       (match_id, period, view, side, team, jumper, player, stat_name, value, value_num)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (match_id, period, view, side, team, jumper, player, k, text, num),
                )


def store_match(data: dict, *, raw_path: Path | None = None,
                conn: sqlite3.Connection | None = None) -> str:
    own = conn is None
    if own:
        init_db()
        conn = connect()
    try:
        cur = conn.cursor()
        match_id = _upsert_match(cur, data, raw_path)
        _clear_dependent(cur, match_id)

        for period, blob in (data.get("summary") or {}).items():
            _insert_summary(cur, match_id, period, blob or {})
        for period, blob in (data.get("score_sources") or {}).items():
            _insert_score_sources(cur, match_id, period, blob or {})
        for period, blob in (data.get("efficiencies") or {}).items():
            _insert_efficiencies(cur, match_id, period, blob or {})
        for period, blob in (data.get("shot_map") or {}).items():
            _insert_shots(cur, match_id, period, blob or {})
        for period, blob in (data.get("free_kicks") or {}).items():
            _insert_free_kicks(cur, match_id, period, blob or {})
        _insert_player_stats(cur, match_id, data.get("player_stats") or [],
                             data.get("header") or {})

        conn.commit()
        return match_id
    finally:
        if own:
            conn.close()


def ingest_raw_dir(root: Path | None = None) -> int:
    """Scan data/pd/raw for *.json match files and upsert each into SQLite."""
    root = root or settings.raw_root
    init_db()
    conn = connect()
    try:
        n = 0
        for p in sorted(root.rglob("*.json")):
            try:
                data = json.loads(p.read_text())
                store_match(data, raw_path=p, conn=conn)
                n += 1
            except Exception as e:
                log.exception("Failed to ingest %s: %s", p, e)
        return n
    finally:
        conn.close()
