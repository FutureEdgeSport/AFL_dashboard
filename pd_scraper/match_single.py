"""Single-match sanity-check scraper.

Navigates to MATCH REPORTS, selects a round, clicks the first fixture card,
then walks every tab × period (× view/team filter for Player Stats) and
saves:
  * raw HTML snapshot per state → data/pd/explore/match/<slug>.html
  * a parsed JSON digest with the key tables/cards → data/pd/explore/match/<slug>.json
  * a summary manifest → data/pd/explore/match/_manifest.json

Run:
    python -m pd_scraper.match_single --round 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import ElementHandle, Locator, Page

from .auth import authed_context
from .config import settings

log = logging.getLogger(__name__)

OUT = settings.data_root / "explore" / "match"
OUT.mkdir(parents=True, exist_ok=True)

TABS = ["Summary", "Score Sources", "Efficiencies", "Shot Map", "Free Kicks", "Player Stats"]
PERIODS = ["TOTAL", "Q1", "Q2", "Q3", "Q4"]
PLAYER_VIEWS = ["Basic", "Advanced", "Involvements"]
PLAYER_TEAM_FILTERS = ["All Players", "Home Team", "Away Team"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "x"


async def _dismiss_overlays(page: Page) -> None:
    for sel in [
        ".e-dialog .e-dlg-closeicon-btn",
        "button[aria-label='Close' i]",
        "button:has-text('OK')",
        "button:has-text('Close')",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.click(timeout=1500)
                await page.wait_for_timeout(200)
        except Exception:
            pass
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _click_sidebar(page: Page, label: str) -> None:
    await _dismiss_overlays(page)
    loc = page.get_by_text(re.compile(rf"^\s*{label}\s*$", re.I)).first
    await loc.click(timeout=8000)
    await page.wait_for_timeout(1500)


async def _click_round(page: Page, round_num: int) -> None:
    """Click the round button in the header strip (1..9 / SF)."""
    label = str(round_num)
    # The round buttons live inside the header footer area.
    btn = page.locator(f"section#top-nav button:has-text('{label}')").first
    if not await btn.count():
        btn = page.get_by_role("button", name=re.compile(rf"^\s*{label}\s*$")).first
    await btn.click(timeout=5000)
    await page.wait_for_timeout(1500)


async def _click_first_fixture_card(page: Page) -> str:
    """Click the first *clickable* fixture card. Return its inner text."""
    # Our team's matches have the ``clickable`` class. Other teams' cards
    # don't, and aren't actionable.
    card = page.locator("button.card.fixture.clickable").first
    await card.wait_for(timeout=15_000)
    text = (await card.inner_text()).strip().replace("\n", " | ")
    await card.click(timeout=5000)
    await page.wait_for_timeout(3000)
    # Wait until the match-detail tab strip is visible.
    await page.wait_for_selector(
        "text=/Score Sources|Shot Map|Free Kicks|Player Stats/i",
        timeout=20_000,
    )
    return text


async def _click_tab(page: Page, tab_label: str) -> bool:
    # Scope to the main body region so we don't hit the sidebar's
    # "Team Summary" item when clicking a "Summary" tab.
    scope = page.locator("section.pagebody, section#body.pagebody, section[id='body']").last
    for sel in [
        f"[role='tab']:has-text('{tab_label}')",
        f"button:has-text('{tab_label}')",
        f"a:has-text('{tab_label}')",
        f"div.e-tab-text:has-text('{tab_label}')",
    ]:
        loc = scope.locator(sel).first
        if await loc.count():
            try:
                await loc.click(timeout=4000)
                await page.wait_for_timeout(1000)
                return True
            except Exception:
                continue
    log.warning("Could not click tab %s", tab_label)
    return False


async def _click_period(page: Page, period: str) -> bool:
    """Click TOTAL/Q1/Q2/Q3/Q4. Scoped to body."""
    scope = page.locator("section.pagebody, section#body.pagebody, section[id='body']").last
    loc = scope.locator(f"button:has-text('{period}')").first
    if not await loc.count():
        return False
    try:
        await loc.click(timeout=3000)
        await page.wait_for_timeout(800)
        return True
    except Exception:
        return False


async def _snapshot(page: Page, slug: str) -> dict[str, Any]:
    html_path = OUT / f"{slug}.html"
    png_path = OUT / f"{slug}.png"
    html = await page.content()
    html_path.write_text(html, encoding="utf-8")
    try:
        await page.screenshot(path=str(png_path), full_page=True)
    except Exception:
        pass
    # Extract the visible main body text as a quick sanity digest.
    try:
        body_text = await page.locator("section#body").first.inner_text(timeout=3000)
    except Exception:
        body_text = ""
    digest = {
        "slug": slug,
        "html_bytes": len(html),
        "text_len": len(body_text),
        "text_preview": body_text[:1500],
    }
    (OUT / f"{slug}.json").write_text(json.dumps(digest, indent=2), encoding="utf-8")
    log.info("  snapshot %s (%d HTML bytes, %d text chars)", slug, len(html), len(body_text))
    return digest


async def main(round_num: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    manifest: dict[str, Any] = {"round": round_num, "snapshots": []}

    async with authed_context(headless=True) as (_b, _ctx, page):
        # The stats view (Summary / Score Sources / Shot Map / Free Kicks /
        # Player Stats / Report) is reached by clicking a fixture card on the
        # FIXTURES page — NOT the MATCH REPORTS page (which hosts the
        # AI-generated narrative reports and shows "No AI Match Report
        # Available" when the narrative hasn't been generated).
        await _click_sidebar(page, "FIXTURES")
        await _click_round(page, round_num)
        fixture_label = await _click_first_fixture_card(page)
        manifest["fixture_label"] = fixture_label
        log.info("Opened match: %s", fixture_label)

        await _snapshot(page, "00_match_landing")

        for tab in TABS:
            log.info("Tab: %s", tab)
            if not await _click_tab(page, tab):
                continue
            await _snapshot(page, f"tab_{_slug(tab)}_default")

            if tab == "Player Stats":
                # iterate view × team filter × period
                for view in PLAYER_VIEWS:
                    for team_filter in PLAYER_TEAM_FILTERS:
                        v_loc = page.locator(f"button:has-text('{view}')").first
                        t_loc = page.locator(f"button:has-text('{team_filter}')").first
                        if await v_loc.count():
                            try:
                                await v_loc.click(timeout=2500); await page.wait_for_timeout(400)
                            except Exception: pass
                        if await t_loc.count():
                            try:
                                await t_loc.click(timeout=2500); await page.wait_for_timeout(400)
                            except Exception: pass
                        await _snapshot(
                            page,
                            f"tab_player_stats_{_slug(view)}_{_slug(team_filter)}",
                        )
                # only do TOTAL period for player stats (one shot per view combo already covers it)
                continue

            for period in PERIODS:
                if period == "TOTAL":
                    # default, but still snapshot once after clicking to normalise state
                    pass
                if await _click_period(page, period):
                    await _snapshot(page, f"tab_{_slug(tab)}_{_slug(period)}")

        (OUT / "_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        log.info("Done. See %s", OUT)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, default=3, help="Round number to open (1-9 or 99 for SF)")
    args = ap.parse_args()
    asyncio.run(main(args.round))
