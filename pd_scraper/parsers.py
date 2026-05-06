"""Pure-function HTML parsers for each PD match-detail tab.

Each ``parse_*`` function takes raw HTML (one snapshot of the page AFTER the
relevant tab/period has been activated) and returns a JSON-serialisable dict.

These are written to be permissive: missing sections return empty lists/
dicts rather than raising, and we never assume a particular stat is present
(the site hides some sections depending on league/competition).
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _active_tabpanel(soup: BeautifulSoup) -> Tag | None:
    """Return the active <div class="e-item e-active" role="tabpanel">."""
    return soup.select_one("div.e-item.e-active[role='tabpanel']")


def _text(el: Tag | None) -> str:
    return (el.get_text(" ", strip=True) if el else "").strip()


def _num(s: Any) -> float | int | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return s
    s = str(s).strip().replace(",", "")
    if not s:
        return None
    m = re.match(r"^[-+]?\d+(\.\d+)?$", s)
    if m:
        return float(s) if "." in s else int(s)
    return None


def _active_period(panel: Tag | None) -> str | None:
    if panel is None:
        return None
    btn = panel.select_one("button.qtr-filter.active")
    return _text(btn).upper() if btn else None


def _teams_from_fixture_block(fixture: Tag) -> dict[str, Any]:
    """Extract team names/scores from a ``.fixture-result`` block.

    Works for both the on-page top-nav header and the dialog modal, provided
    the block is scoped to a single fixture-result element (not the whole page).
    """
    home_block = fixture.select_one("div.home")
    away_block = fixture.select_one("div.away")
    home = _text(home_block.select_one(".team-name")) if home_block else ""
    away = _text(away_block.select_one(".team-name")) if away_block else ""
    home_score = _text(fixture.select_one(".home-score"))
    away_score = _text(fixture.select_one(".away-score"))
    score_details = fixture.select(".result .score .score-detail")
    home_detail = _text(score_details[0]) if len(score_details) > 0 else ""
    away_detail = _text(score_details[1]) if len(score_details) > 1 else ""
    round_text = _text(fixture.select_one(".round-text"))
    return {
        "home_team": home,
        "away_team": away,
        "home_score": _num(home_score),
        "home_goals_behinds": home_detail or None,
        "away_score": _num(away_score),
        "away_goals_behinds": away_detail or None,
        "round_text": round_text or None,
    }


def _teams_from_modal(soup: BeautifulSoup) -> dict[str, Any]:
    """Prefer the on-page top-nav fixture header (always reflects current
    match). Fall back to the hidden dialog.modal only if top-nav is missing.
    """
    # Primary: on-page header in section#top-nav (specific to current match)
    on_page = soup.select_one(
        "section#top-nav .fixture-result-header .fixture-result"
    )
    if on_page:
        out = _teams_from_fixture_block(on_page)
        if out.get("home_team") and out.get("away_team") and \
                out["home_team"] != out["away_team"]:
            return out

    # Fallback: hidden modal (may be stale/generic; guarded by same-team check)
    modal_fixture = soup.select_one("dialog.modal .fixture-result")
    if modal_fixture:
        out = _teams_from_fixture_block(modal_fixture)
        title = _text(soup.select_one("dialog.modal .modal-header h2"))
        if title:
            out["title"] = title
        return out
    return {}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def parse_summary(html: str) -> dict[str, Any]:
    soup = _soup(html)
    panel = _active_tabpanel(soup)
    out: dict[str, Any] = {
        "period": _active_period(panel),
        "efficiency_donuts": [],  # [{label, pct}]
        "sections": [],  # [{name, stats: [{name, home, away, diff}]}]
    }
    if not panel:
        return out

    # Left-side donuts: Disposal Efficiency / Kick Eff / Handball Eff
    for g in panel.select(".container__stat-summary .left .graph"):
        label = _text(g.select_one("label"))
        pct = _text(g.select_one(".donut title"))
        if label and pct:
            out["efficiency_donuts"].append({"label": label, "value": pct})
    # And the right-side mirror
    for g in panel.select(".container__stat-summary .right .graph"):
        label = _text(g.select_one("label"))
        pct = _text(g.select_one(".donut title"))
        if label and pct:
            out["efficiency_donuts"].append({"label": label, "value": pct, "side": "away"})

    # Each accordion = a section (Disposals / Marks / General Play / ...)
    for acc in panel.select(".accordion.section"):
        head = acc.select_one(".head > h2")
        section_name = _text(head)
        stats = []
        for row in acc.select(":scope > hr + div.body > div.graph__line-compare, "
                              ":scope .body > div.graph__line-compare"):
            name = _text(row.select_one(".header h3"))
            home = _num(_text(row.select_one(".home strong.score")))
            away = _num(_text(row.select_one(".away strong.score")))
            diff = _text(row.select_one(".winner-indicator strong.difference"))
            if name:
                stats.append({"name": name, "home": home, "away": away, "diff": diff})
        if section_name or stats:
            out["sections"].append({"name": section_name, "stats": stats})
    return out


# ---------------------------------------------------------------------------
# Score Sources
# ---------------------------------------------------------------------------
def parse_score_sources(html: str) -> dict[str, Any]:
    soup = _soup(html)
    panel = _active_tabpanel(soup)
    out: dict[str, Any] = {
        "period": _active_period(panel),
        "donuts": [],  # {side, label, value}
        "rows": [],    # {parent, name, home_scoreline, home_pct, away_scoreline, away_pct}
    }
    if not panel:
        return out

    for side in ("left", "right"):
        for g in panel.select(f".container__stat-summary .{side} .graph"):
            label = _text(g.select_one("label"))
            value = _text(g.select_one(".donut title"))
            if label:
                out["donuts"].append({"side": "home" if side == "left" else "away",
                                      "label": label, "value": value})

    # Score-source rows: 5 h4 children = home_scoreline, home_pct, name, away_pct, away_scoreline
    def _scan(accordion: Tag, parent: str | None) -> None:
        for src in accordion.select(":scope > .head > .score-source, :scope > hr + .body > .score-source"):
            h4s = [_text(h) for h in src.select(":scope > h4")]
            if len(h4s) >= 5:
                home_score, home_pct, name, away_pct, away_score = h4s[:5]
                out["rows"].append({
                    "parent": parent,
                    "name": name,
                    "home_scoreline": home_score,
                    "home_pct": home_pct,
                    "away_pct": away_pct,
                    "away_scoreline": away_score,
                })
        # recurse
        for sub in accordion.select(":scope > hr + .body > .accordion.section"):
            head_name = _text(sub.select_one(":scope > .head > .score-source > h4:nth-of-type(3)"))
            _scan(sub, head_name or parent)

    for root in panel.select(".center .accordion.section"):
        head_name = _text(root.select_one(":scope > .head > .score-source > h4:nth-of-type(3)"))
        _scan(root, None)
    return out


# ---------------------------------------------------------------------------
# Efficiencies
# ---------------------------------------------------------------------------
def parse_efficiencies(html: str) -> dict[str, Any]:
    soup = _soup(html)
    panel = _active_tabpanel(soup)
    out: dict[str, Any] = {
        "period": _active_period(panel),
        "sections": [],  # {name, stats: [{name, home_pct, home_ratio, away_pct, away_ratio}]}
        "pies": [],      # {section, name, home_value, home_won, home_neutral, away_value, away_won}
    }
    if not panel:
        return out

    for acc in panel.select(".accordion.section"):
        sec_name = _text(acc.select_one(":scope > .head > h2"))
        stats: list[dict[str, Any]] = []
        # Efficiency ratios: .grid.specific.col-3 contains 2 flex-column (home/away) + center h4 = name
        for grid in acc.select(":scope .grid.specific.col-3"):
            name = None
            # center text: the h4 directly under grid (between the two flex-column)
            all_children = list(grid.children)
            cols = grid.select(":scope > .flex-column")
            center_h4 = grid.select_one(":scope > h4")
            name = _text(center_h4)
            if len(cols) >= 2:
                home_pct = _text(cols[0].select_one(".donut title"))
                home_ratio = _text(cols[0].select_one("h4"))
                away_pct = _text(cols[1].select_one(".donut title"))
                away_ratio = _text(cols[1].select_one("h4"))
                if name or home_pct or away_pct:
                    stats.append({
                        "name": name,
                        "home_pct": home_pct,
                        "home_ratio": home_ratio,
                        "away_pct": away_pct,
                        "away_ratio": away_ratio,
                    })
        if stats:
            out["sections"].append({"name": sec_name, "stats": stats})

        # Pie graphs (Stoppages): .grid.basic .flex-column.center .pie-graph
        for pg in acc.select(":scope .pie-graph"):
            # parent flex-column contains h2.body = name
            container = pg.find_parent("div", class_="flex-column")
            name = _text(container.select_one("h2.body") if container else None)
            # Three spans of h4 (Won/Neutral/Won) plus the center donut value
            # Structure in HTML:
            #   <h4>Neutral N</h4>
            #   <span><h4>Won H</h4></span>
            #   <span><h4>Won A</h4></span>
            #   <div class="donut-pie"><div class="donut pie">VALUE</div>
            h4s = pg.select(":scope > h4, :scope > span > h4")
            labels = [_text(h) for h in h4s]
            value = _text(pg.select_one(".donut-pie .donut"))
            # Team side hint: donut-pie div has class home/away
            donut = pg.select_one(".donut-pie .donut")
            side = None
            if donut:
                classes = donut.get("class", [])
                if "home" in classes:
                    side = "home"
                elif "away" in classes:
                    side = "away"
            out["pies"].append({
                "section": sec_name,
                "name": name,
                "value": value,
                "labels": labels,
                "side": side,
            })
    return out


# ---------------------------------------------------------------------------
# Shot Map (tabular shot log — chart coordinates are SVG-only, captured
# separately via Playwright JS eval if needed later)
# ---------------------------------------------------------------------------
def _parse_grid(grid: Tag) -> list[dict[str, str]]:
    """Generic Syncfusion grid parser. Returns list of row dicts keyed by header.

    Also extracts a ``_team_club_id`` key when the first template cell
    contains a club-logo ``<img>`` with URL pattern ``/clubs/<id>/...``.
    """
    headers: list[str] = []
    head_row = grid.select_one(".e-gridheader thead tr.e-columnheader")
    if head_row:
        for th in head_row.select("th.e-headercell"):
            headers.append(_text(th.select_one(".e-headertext")))
    rows: list[dict[str, str]] = []
    for tr in grid.select(".e-gridcontent tbody tr.e-row, .e-content tbody tr.e-row"):
        cells = tr.select("td.e-rowcell")
        row: dict[str, str] = {}
        for i, td in enumerate(cells):
            key = headers[i] if i < len(headers) and headers[i] else f"col_{i}"
            val = _text(td)
            row[key] = val
            # Team club_id lives in the first template cell's <img src="…/clubs/<id>/…">
            if i == 0:
                img = td.select_one("img[src*='/clubs/']")
                if img:
                    m = re.search(r"/clubs/(\d+)/", img.get("src", ""))
                    if m:
                        row["_team_club_id"] = m.group(1)
        if row:
            rows.append(row)
    return rows


def parse_shot_map(html: str) -> dict[str, Any]:
    soup = _soup(html)
    panel = _active_tabpanel(soup)
    out: dict[str, Any] = {"period": _active_period(panel), "shots": []}
    if not panel:
        return out
    grid = panel.select_one(".sf-grid.e-grid")
    if grid:
        out["shots"] = _parse_grid(grid)
    return out


# ---------------------------------------------------------------------------
# Free Kicks (same line-compare widgets as Summary)
# ---------------------------------------------------------------------------
def parse_free_kicks(html: str) -> dict[str, Any]:
    soup = _soup(html)
    panel = _active_tabpanel(soup)
    out: dict[str, Any] = {"period": _active_period(panel), "rows": []}
    if not panel:
        return out
    for row in panel.select(".graph__line-compare"):
        name = _text(row.select_one(".header h3"))
        home = _num(_text(row.select_one(".home strong.score")))
        away = _num(_text(row.select_one(".away strong.score")))
        diff = _text(row.select_one(".winner-indicator strong.difference"))
        if name:
            out["rows"].append({"name": name, "home": home, "away": away, "diff": diff})
    return out


# ---------------------------------------------------------------------------
# Player Stats
# ---------------------------------------------------------------------------
def parse_player_stats(html: str, view: str, team_filter: str) -> dict[str, Any]:
    soup = _soup(html)
    panel = _active_tabpanel(soup)
    out: dict[str, Any] = {
        "period": _active_period(panel),
        "view": view,
        "team_filter": team_filter,
        "rows": [],
    }
    if not panel:
        return out
    grid = panel.select_one(".sf-grid.e-grid")
    if grid:
        rows = _parse_grid(grid)
        # First column is usually empty (avatar); "Name" column contains "#N Player"
        cleaned: list[dict[str, Any]] = []
        for r in rows:
            # Skip if all numeric cells empty
            if not any(r.values()):
                continue
            # Try to split "#N Player Name" into jumper + name
            name_key = next((k for k in r if k.lower() == "name"), None)
            if name_key and r[name_key]:
                m = re.match(r"^\s*(\d+)\s+(.*)$", r[name_key])
                if m:
                    r["jumper"] = int(m.group(1))
                    r["player"] = m.group(2).strip()
                else:
                    r["player"] = r[name_key].strip()
            # Coerce numeric cells
            for k, v in list(r.items()):
                n = _num(v)
                if n is not None:
                    r[k] = n
            cleaned.append(r)
        out["rows"] = cleaned
    return out


# ---------------------------------------------------------------------------
# Match header (shared across all tabs — date/round/teams/score)
# ---------------------------------------------------------------------------
def parse_match_header(html: str) -> dict[str, Any]:
    soup = _soup(html)
    hdr: dict[str, Any] = _teams_from_modal(soup)
    # The on-page match title bar (at the top of match detail) also has
    # team names and scores, plus the round number/date.
    title = soup.select_one("section#top-nav h1.title")
    if title:
        hdr["title_bar"] = _text(title)
    # Active round
    active_round = soup.select_one("section#top-nav button.active")
    if active_round:
        hdr["round"] = _text(active_round)
    return hdr
