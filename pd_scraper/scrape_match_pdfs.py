"""
Scrape Premier Data match report PDFs for MGS matches.

For each Mentone Grammar match in the given season(s), navigates to the
FIXTURES page, opens the match, clicks the "Report" tab, and downloads
the PDF. PDFs are saved to:

    {MGS_AMS_DIR}/data/pdf_reports/{season}/R{NN:02d}.pdf

Usage:
    python -m pd_scraper.scrape_match_pdfs --seasons 2025 2026
    python -m pd_scraper.scrape_match_pdfs --seasons 2025 --rounds 2 3 4

Run from the AFL_dashboard repo root.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from playwright.async_api import Page

from .auth import authed_context
from .config import settings

log = logging.getLogger(__name__)

# Path to the MGS-AMS project PDF reports directory.
# Override via env var MGS_AMS_DIR if needed.
_DEFAULT_AMS = Path(os.environ.get("MGS_AMS_DIR", "/Users/marcuswagner/mgs-ams"))
AMS_DIR = _DEFAULT_AMS
MGS_TEAM = "Mentone Grammar"
ROUND_LABELS = [str(i) for i in range(1, 10)] + ["SF", "PF", "GF"]


def _pdf_out_dir(season: int) -> Path:
    d = AMS_DIR / "data" / "pdf_reports" / str(season)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pdf_path(season: int, round_num: int) -> Path:
    return _pdf_out_dir(season) / f"R{round_num:02d}.pdf"


def _db_rounds(season: int) -> list[int]:
    """Return round numbers for Mentone matches in the DB for the given season."""
    db = settings.db_path
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT round FROM matches WHERE season=? "
            "AND (home_team=? OR away_team=?) ORDER BY CAST(round AS INTEGER)",
            (season, MGS_TEAM, MGS_TEAM),
        ).fetchall()
        conn.close()
        return [int(r[0]) for r in rows if str(r[0]).isdigit()]
    except Exception as e:
        log.warning("DB lookup failed: %s", e)
        return []


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


async def _switch_season(page: Page, season: int) -> bool:
    btn = page.locator("button.team-select").first
    if not await btn.count():
        return False
    label = (await btn.inner_text()).strip()
    if f"({season})" in label:
        return True
    await btn.click(timeout=4000)
    await page.wait_for_timeout(600)
    for sel in [
        f".e-popup li:has-text('({season})')",
        f"[role='menuitem']:has-text('({season})')",
        f"li:has-text('({season})')",
    ]:
        item = page.locator(sel).first
        if await item.count():
            try:
                await item.click(timeout=3000)
                await page.wait_for_timeout(1500)
                return True
            except Exception:
                continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    return False


async def _click_round(page: Page, round_num: int) -> bool:
    label = str(round_num)
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*$")
    buttons = page.locator("section#top-nav button").filter(has_text=pattern)
    if not await buttons.count():
        return False
    try:
        await buttons.first.click(timeout=4000)
        await page.wait_for_timeout(1200)
        return True
    except Exception:
        return False


async def _open_mgs_fixture(page: Page) -> bool:
    """Click the MGS (clickable) fixture card in the current round view."""
    card = page.locator("button.card.fixture.clickable").first
    if not await card.count():
        log.warning("No clickable fixture card found")
        return False
    try:
        await card.click(timeout=5000)
        await page.wait_for_selector(
            "text=/Score Sources|Shot Map|Player Stats/i", timeout=20_000
        )
        await page.wait_for_timeout(1500)
        return True
    except Exception as e:
        log.warning("Failed to open fixture: %s", e)
        return False


async def _click_tab(page: Page, tab_label: str) -> bool:
    scope = page.locator("section.pagebody, section#body").last
    for sel in [
        f"[role='tab']:has-text('{tab_label}')",
        f"div.e-tab-text:has-text('{tab_label}')",
        f"button:has-text('{tab_label}')",
    ]:
        loc = scope.locator(sel).first
        if await loc.count():
            try:
                await loc.click(timeout=4000)
                await page.wait_for_timeout(1000)
                return True
            except Exception:
                continue
    log.warning("Could not click tab: %s", tab_label)
    return False


async def _try_download_pdf(page: Page, out_path: Path) -> bool:
    """
    Attempt to download the match report PDF from the Report tab.
    Tries multiple strategies and returns True if a PDF was saved.
    """
    # Strategy 1: Look for a download button/link and intercept the download
    download_selectors = [
        "button:has-text('Download')",
        "button:has-text('PDF')",
        "a[href*='.pdf']",
        "a[href*='matchReport']",
        "a[download]",
        "button:has-text('Export')",
        "button:has-text('Print')",
        "[title*='Download' i]",
        "[aria-label*='download' i]",
    ]

    for sel in download_selectors:
        loc = page.locator(sel).first
        if not await loc.count():
            continue
        log.info("  Found download trigger: %s", sel)
        try:
            async with page.expect_download(timeout=30_000) as dl_info:
                await loc.click(timeout=5000)
            download = await dl_info.value
            await download.save_as(str(out_path))
            log.info("  Downloaded via button: %s → %s", download.suggested_filename, out_path)
            return True
        except Exception as e:
            log.debug("  Download attempt failed (%s): %s", sel, e)

    # Strategy 2: Look for an iframe/embed with a PDF src
    for sel in ["iframe[src*='.pdf']", "iframe[src*='matchReport']",
                "embed[src*='.pdf']", "object[data*='.pdf']"]:
        loc = page.locator(sel).first
        if await loc.count():
            src = await loc.get_attribute("src") or await loc.get_attribute("data") or ""
            if src:
                log.info("  Found PDF embed: %s", src)
                try:
                    import urllib.request, urllib.parse
                    # Build an absolute URL if needed
                    if not src.startswith("http"):
                        base = settings.base_url.rstrip("/")
                        src = base + ("" if src.startswith("/") else "/") + src
                    # Download using session cookies
                    cookies = await page.context.cookies()
                    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                    req = urllib.request.Request(src, headers={"Cookie": cookie_str})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        out_path.write_bytes(resp.read())
                    log.info("  Downloaded via iframe src → %s", out_path)
                    return True
                except Exception as e:
                    log.debug("  iframe download failed: %s", e)

    # Strategy 3: Intercept network requests — look for any PDF fetched while on this tab
    pdf_bytes: list[bytes] = []

    async def _on_response(response):
        ct = response.headers.get("content-type", "")
        url = response.url
        if "pdf" in ct.lower() or "matchReport" in url or url.endswith(".pdf"):
            try:
                body = await response.body()
                if body[:4] == b"%PDF":
                    pdf_bytes.append(body)
                    log.info("  Intercepted PDF response: %s (%d bytes)", url, len(body))
            except Exception:
                pass

    page.on("response", _on_response)
    # Trigger any lazy loads by scrolling
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(3000)
    page.remove_listener("response", _on_response)

    if pdf_bytes:
        out_path.write_bytes(pdf_bytes[0])
        log.info("  Saved intercepted PDF → %s", out_path)
        return True

    # Strategy 4: Dump HTML and screenshot for manual investigation
    explore_dir = settings.data_root / "explore" / "report_tab"
    explore_dir.mkdir(parents=True, exist_ok=True)
    html = await page.content()
    (explore_dir / "report_tab.html").write_text(html, encoding="utf-8")
    await page.screenshot(path=str(explore_dir / "report_tab.png"), full_page=True)
    log.warning("  Could not find PDF download. Saved HTML+screenshot to %s", explore_dir)
    return False


async def _back_to_fixtures(page: Page) -> None:
    back = page.locator("button[aria-label='Back' i], button.back, button:has-text('Back')").first
    try:
        if await back.count():
            await back.click(timeout=3000)
            await page.wait_for_timeout(1000)
            return
    except Exception:
        pass
    await _go_fixtures(page)


async def scrape_pdfs_for_season(
    page: Page,
    season: int,
    rounds: list[int] | None = None,
    skip_existing: bool = True,
) -> list[Path]:
    """Scrape match report PDFs for all MGS rounds in a season."""
    if not await _switch_season(page, season):
        log.warning("Could not switch to season %s", season)
        return []

    if rounds is None:
        rounds = _db_rounds(season)
        if not rounds:
            log.warning("No rounds found in DB for season %s", season)
            return []

    log.info("Season %s — rounds to download PDFs for: %s", season, rounds)
    saved: list[Path] = []

    for rnd in rounds:
        out_path = _pdf_path(season, rnd)
        if skip_existing and out_path.exists():
            log.info("  R%02d: already have PDF, skipping", rnd)
            continue

        log.info("  R%02d: opening fixture…", rnd)
        await _go_fixtures(page)
        if not await _switch_season(page, season):
            continue
        if not await _click_round(page, rnd):
            log.warning("  R%02d: could not click round", rnd)
            continue
        if not await _open_mgs_fixture(page):
            log.warning("  R%02d: could not open fixture", rnd)
            continue

        # Click the Report tab
        if not await _click_tab(page, "Report"):
            log.warning("  R%02d: Report tab not found — skipping", rnd)
            await _back_to_fixtures(page)
            continue

        await page.wait_for_timeout(2000)

        if await _try_download_pdf(page, out_path):
            saved.append(out_path)
            log.info("  R%02d: ✓ PDF saved → %s", rnd, out_path.name)
        else:
            log.warning("  R%02d: ✗ Could not download PDF", rnd)

        await _back_to_fixtures(page)

    return saved


async def run(
    seasons: Iterable[int],
    rounds: list[int] | None = None,
    skip_existing: bool = True,
    headless: bool = True,
) -> list[Path]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    all_saved: list[Path] = []
    async with authed_context(headless=headless) as (_b, _ctx, page):
        await _go_fixtures(page)
        for season in seasons:
            saved = await scrape_pdfs_for_season(
                page, season, rounds=rounds, skip_existing=skip_existing
            )
            all_saved.extend(saved)
    log.info("Total PDFs saved: %d", len(all_saved))
    return all_saved


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Download MGS match report PDFs from PD portal")
    ap.add_argument("--seasons", nargs="+", type=int, default=[2025, 2026])
    ap.add_argument("--rounds", nargs="*", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="Re-download even if PDF exists")
    ap.add_argument("--headed", action="store_true", help="Show browser window")
    args = ap.parse_args()

    asyncio.run(run(
        args.seasons,
        rounds=args.rounds,
        skip_existing=not args.force,
        headless=not args.headed,
    ))
