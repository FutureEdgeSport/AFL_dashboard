"""Season-level orchestration: for each season (2025, 2026), for each round,
click every clickable fixture and scrape it.

The PD TeamTracker account is scoped to one club (Mentone Grammar). The
team-selector ``button.team-select`` toggles between seasons — e.g.
"Mentone Grammar (2025)" and "Mentone Grammar (2026)".
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from playwright.async_api import Page

from .auth import authed_context
from .config import settings
from .scrape_match import scrape_match

log = logging.getLogger(__name__)

RAW = settings.raw_root
ROUND_LABELS = [str(i) for i in range(1, 10)] + ["SF", "PF", "GF"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "x"


async def _dismiss_overlays(page: Page) -> None:
    for sel in [".e-dialog .e-dlg-closeicon-btn", "button[aria-label='Close' i]"]:
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


async def _go_fixtures(page: Page) -> None:
    await _dismiss_overlays(page)
    loc = page.get_by_text(re.compile(r"^\s*FIXTURES\s*$", re.I)).first
    await loc.click(timeout=8000)
    await page.wait_for_timeout(1200)


async def _current_team_label(page: Page) -> str:
    btn = page.locator("button.team-select").first
    if not await btn.count():
        return ""
    return (await btn.inner_text()).strip()


async def _switch_season(page: Page, season: int) -> bool:
    """Click the team-selector, then choose the entry matching (season)."""
    label = await _current_team_label(page)
    if f"({season})" in label:
        return True
    btn = page.locator("button.team-select").first
    if not await btn.count():
        log.warning("team-select button not found")
        return False
    await btn.click(timeout=4000)
    await page.wait_for_timeout(600)
    # Popup menu items — try several container selectors
    for sel in [
        f".e-popup li:has-text('({season})')",
        f"[role='menuitem']:has-text('({season})')",
        f"li:has-text('({season})')",
        f"button:has-text('({season})')",
    ]:
        item = page.locator(sel).first
        if await item.count():
            try:
                await item.click(timeout=3000)
                await page.wait_for_timeout(1500)
                new_label = await _current_team_label(page)
                log.info("Switched season → %s", new_label)
                return f"({season})" in new_label
            except Exception:
                continue
    log.warning("Could not find season %s in team dropdown", season)
    # Close dropdown
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    return False


async def _available_rounds(page: Page) -> list[str]:
    rounds: list[str] = []
    buttons = page.locator("section#top-nav button")
    n = await buttons.count()
    for i in range(n):
        txt = (await buttons.nth(i).inner_text()).strip()
        if txt in ROUND_LABELS and txt not in rounds:
            rounds.append(txt)
    return rounds


async def _click_round(page: Page, label: str) -> bool:
    # Use an exact-text regex so `has-text('2')` doesn't substring-match the
    # "Mentone Grammar (2025)" team-select button (which lives in the same
    # top-nav). Playwright's ``has-text`` is a substring match; we need
    # anchored ``text=/^\s*LABEL\s*$/``.
    import re as _re
    pattern = _re.compile(rf"^\s*{_re.escape(label)}\s*$")
    buttons = page.locator("section#top-nav button").filter(has_text=pattern)
    if not await buttons.count():
        return False
    btn = buttons.first
    try:
        await btn.click(timeout=4000)
        await page.wait_for_timeout(1200)
        # Verify: check that the active round button matches
        active = page.locator("section#top-nav button.active").first
        if await active.count():
            txt = (await active.inner_text()).strip()
            if txt != label:
                log.warning("Round click: expected active=%r, got %r", label, txt)
                return False
        return True
    except Exception:
        return False


async def _fixture_cards(page: Page) -> list[dict[str, Any]]:
    """Return info for every clickable fixture card in the current round view."""
    cards = page.locator("button.card.fixture.clickable")
    out: list[dict[str, Any]] = []
    n = await cards.count()
    for i in range(n):
        try:
            txt = (await cards.nth(i).inner_text()).strip().replace("\n", " | ")
        except Exception:
            txt = ""
        out.append({"index": i, "label": txt})
    return out


async def _open_fixture(page: Page, index: int) -> bool:
    card = page.locator("button.card.fixture.clickable").nth(index)
    if not await card.count():
        return False
    try:
        await card.click(timeout=5000)
        # Wait for tab strip to appear
        await page.wait_for_selector(
            "text=/Score Sources|Shot Map|Player Stats/i", timeout=20_000
        )
        await page.wait_for_timeout(1500)
        return True
    except Exception as e:
        log.warning("Failed to open fixture %d: %s", index, e)
        return False


async def _back_to_fixtures(page: Page) -> None:
    # The header has a Back button; else click FIXTURES nav again.
    back = page.locator("button[aria-label='Back' i], button.back, button:has-text('Back')").first
    try:
        if await back.count():
            await back.click(timeout=3000)
            await page.wait_for_timeout(1000)
            return
    except Exception:
        pass
    await _go_fixtures(page)


def _match_slug(card_label: str) -> str:
    # "Mentone Grammar | 57 | 37 | Assumption" → "mentone_grammar_vs_assumption"
    parts = [p.strip() for p in card_label.split("|")]
    words = [p for p in parts if p and not re.match(r"^\d+$", p)]
    if len(words) >= 2:
        return f"{_slug(words[0])}_vs_{_slug(words[-1])}"
    return _slug(card_label)[:80]


async def scrape_season(
    page: Page,
    season: int,
    *,
    rounds: Iterable[str] | None = None,
    skip_existing: bool = True,
) -> list[Path]:
    """Scrape all clickable fixtures for a season. Returns list of written files."""
    await _go_fixtures(page)
    if not await _switch_season(page, season):
        log.warning("Skipping season %s (could not switch)", season)
        return []

    rounds_to_scrape: list[str]
    if rounds is None:
        rounds_to_scrape = await _available_rounds(page)
    else:
        rounds_to_scrape = list(rounds)
    log.info("Season %s rounds: %s", season, rounds_to_scrape)

    written: list[Path] = []
    for rnd in rounds_to_scrape:
        if not await _click_round(page, rnd):
            log.warning("Could not click round %s", rnd)
            continue
        cards = await _fixture_cards(page)
        log.info("  Round %s: %d clickable fixtures", rnd, len(cards))
        for c in cards:
            slug = _match_slug(c["label"])
            out_dir = RAW / str(season) / f"round_{_slug(rnd)}"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{slug}.json"
            if skip_existing and out_path.exists():
                log.info("    SKIP (exists): %s", out_path.name)
                continue
            # Re-query cards fresh each iteration because clicking back may re-render
            if not await _open_fixture(page, c["index"]):
                continue
            try:
                data = await scrape_match(page, match_id=slug)
                data["_meta"] = {
                    "season": season,
                    "round": rnd,
                    "card_label": c["label"],
                    "slug": slug,
                }
                out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
                written.append(out_path)
                log.info("    wrote %s (%d KB)", out_path.name, out_path.stat().st_size // 1024)
            except Exception as e:
                log.exception("    FAILED scraping %s: %s", slug, e)
            await _back_to_fixtures(page)
            # After going back we're on FIXTURES; need to reclick round
            if not await _click_round(page, rnd):
                log.warning("    lost round context; aborting round %s", rnd)
                break
    return written


async def run(
    seasons: Iterable[int],
    *,
    rounds: Iterable[str] | None = None,
    skip_existing: bool = True,
    headless: bool = True,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    async with authed_context(headless=headless) as (_b, _ctx, page):
        for season in seasons:
            await scrape_season(page, season, rounds=rounds, skip_existing=skip_existing)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=[2025])
    ap.add_argument("--rounds", nargs="*", default=None)
    ap.add_argument("--force", action="store_true", help="Re-scrape even if output exists")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    asyncio.run(
        run(
            args.seasons,
            rounds=args.rounds,
            skip_existing=not args.force,
            headless=not args.headed,
        )
    )
