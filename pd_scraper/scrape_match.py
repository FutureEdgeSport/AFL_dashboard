"""Scrape a single open PD match-detail view into a structured dict.

Assumes the Playwright ``page`` is already on the match-detail view
(a fixture card was clicked). Iterates every tab × period × player-view
and returns a JSON-serialisable dict.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from playwright.async_api import Page

from . import parsers

log = logging.getLogger(__name__)

TABS = ["Summary", "Score Sources", "Efficiencies", "Shot Map", "Free Kicks", "Player Stats"]
PERIODS = ["TOTAL", "Q1", "Q2", "Q3", "Q4"]
PLAYER_VIEWS = ["Basic", "Advanced", "Involvements"]


async def _dismiss_overlays(page: Page) -> None:
    for sel in [
        ".e-dialog .e-dlg-closeicon-btn",
        "button[aria-label='Close' i]",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.click(timeout=1000)
        except Exception:
            pass
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _click_tab(page: Page, label: str) -> bool:
    scope = page.locator("section.pagebody, section#body.pagebody, section[id='body']").last
    for sel in [
        f"[role='tab']:has-text('{label}')",
        f"div.e-tab-text:has-text('{label}')",
        f"button:has-text('{label}')",
    ]:
        loc = scope.locator(sel).first
        if await loc.count():
            try:
                await loc.click(timeout=4000)
                await page.wait_for_timeout(600)
                return True
            except Exception:
                continue
    return False


async def _click_period(page: Page, period: str) -> bool:
    scope = page.locator("section.pagebody").last
    loc = scope.locator(f"button.qtr-filter:has-text('{period}')").first
    if not await loc.count():
        loc = scope.locator(f"button:has-text('{period}')").first
        if not await loc.count():
            return False
    try:
        await loc.click(timeout=2500)
        await page.wait_for_timeout(500)
        return True
    except Exception:
        return False


async def _click_pill(page: Page, label: str) -> bool:
    """Click a generic button/pill (e.g. Basic/Advanced, All Players, Home Team)."""
    scope = page.locator("section.pagebody").last
    loc = scope.locator(f"button:has-text('{label}')").first
    if not await loc.count():
        return False
    try:
        await loc.click(timeout=2500)
        await page.wait_for_timeout(400)
        return True
    except Exception:
        return False


async def _content(page: Page) -> str:
    return await page.content()


async def scrape_match(page: Page, *, match_id: str | None = None) -> dict[str, Any]:
    """Walk every tab × period × view on an already-open match-detail page.

    Returns a dict with keys:
        header, summary{period:...}, score_sources{period:...},
        efficiencies{period:...}, shot_map{period:...},
        free_kicks{period:...}, player_stats [list of {view, period, rows}]
    """
    await _dismiss_overlays(page)

    result: dict[str, Any] = {
        "match_id": match_id,
        "header": {},
        "summary": {},
        "score_sources": {},
        "efficiencies": {},
        "shot_map": {},
        "free_kicks": {},
        "player_stats": [],
    }

    # Header: available on any tab (uses hidden modal + top-nav)
    # Start by clicking Summary tab to have a known state.
    if await _click_tab(page, "Summary"):
        html = await _content(page)
        result["header"] = parsers.parse_match_header(html)

    period_map = {
        "Summary": "summary",
        "Score Sources": "score_sources",
        "Efficiencies": "efficiencies",
        "Shot Map": "shot_map",
        "Free Kicks": "free_kicks",
    }
    for tab in ["Summary", "Score Sources", "Efficiencies", "Shot Map", "Free Kicks"]:
        if not await _click_tab(page, tab):
            log.warning("scrape_match: could not open tab %s", tab)
            continue
        key = period_map[tab]
        per_period: dict[str, Any] = {}
        for period in PERIODS:
            if not await _click_period(page, period):
                continue
            html = await _content(page)
            if tab == "Summary":
                per_period[period] = parsers.parse_summary(html)
            elif tab == "Score Sources":
                per_period[period] = parsers.parse_score_sources(html)
            elif tab == "Efficiencies":
                per_period[period] = parsers.parse_efficiencies(html)
            elif tab == "Shot Map":
                per_period[period] = parsers.parse_shot_map(html)
            elif tab == "Free Kicks":
                per_period[period] = parsers.parse_free_kicks(html)
        result[key] = per_period

    # Player Stats: iterate view × team-filter × period.
    # The "Home Team" and "Away Team" filters let us tag each row with
    # home/away; combined with header.home_team/away_team that gives each
    # player a team name.
    if await _click_tab(page, "Player Stats"):
        for team_filter in ("Home Team", "Away Team"):
            if not await _click_pill(page, team_filter):
                continue
            for view in PLAYER_VIEWS:
                if not await _click_pill(page, view):
                    continue
                for period in PERIODS:
                    if not await _click_period(page, period):
                        continue
                    html = await _content(page)
                    parsed = parsers.parse_player_stats(html, view=view, team_filter=team_filter)
                    parsed["period"] = period
                    result["player_stats"].append(parsed)

    return result
