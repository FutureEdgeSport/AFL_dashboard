"""One-off exploration: log in, walk the main sections, and dump HTML.

Run with:

    python -m pd_scraper.explore

Outputs land in ``data/pd/explore/`` — HTML + screenshots + a network log
(captured XHR/WS requests with URLs and payload sizes). This is the basis
for writing precise selectors and endpoint hooks for the real scrapers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from playwright.async_api import Page, Request, Response

from .auth import authed_context
from .config import settings

log = logging.getLogger(__name__)

EXPLORE_DIR = settings.data_root / "explore"
EXPLORE_DIR.mkdir(parents=True, exist_ok=True)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "page"


async def _dump(page: Page, label: str, network: list[dict[str, Any]]) -> None:
    slug = _slug(label)
    html_path = EXPLORE_DIR / f"{slug}.html"
    png_path = EXPLORE_DIR / f"{slug}.png"
    html = await page.content()
    html_path.write_text(html, encoding="utf-8")
    await page.screenshot(path=str(png_path), full_page=True)
    log.info("Dumped %s → %s (%d bytes)", label, html_path, len(html))
    # Also snapshot network activity to date, keyed by label
    (EXPLORE_DIR / f"{slug}.network.json").write_text(
        json.dumps(network, indent=2, default=str),
        encoding="utf-8",
    )


async def _dismiss_overlays(page: Page) -> None:
    """Close any Syncfusion dialog / cookie / welcome overlay that may block clicks."""
    # Try common close affordances.
    for sel in [
        ".e-dlg-overlay + .e-dialog .e-dlg-closeicon-btn",
        ".e-dialog .e-dlg-closeicon-btn",
        "button[aria-label='Close' i]",
        "button:has-text('OK')",
        "button:has-text('Close')",
        "button:has-text('Got it')",
        "button:has-text('Accept')",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.click(timeout=2000)
                await page.wait_for_timeout(300)
        except Exception:
            pass
    # As a last resort, press Escape.
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _click_sidebar(page: Page, label: str) -> bool:
    await _dismiss_overlays(page)
    loc = page.get_by_text(re.compile(rf"^\s*{label}\s*$", re.I)).first
    if not await loc.count():
        log.warning("Sidebar item %r not found", label)
        return False
    try:
        await loc.click(timeout=8000)
    except Exception as exc:
        log.warning("Click %s blocked (%s); retrying via force", label, exc)
        try:
            await loc.click(timeout=5000, force=True)
        except Exception as exc2:
            log.error("Sidebar click %s failed: %s", label, exc2)
            return False
    # Give Blazor time to render
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await page.wait_for_timeout(1500)
    return True


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    network: list[dict[str, Any]] = []

    def on_request(req: Request) -> None:
        if req.resource_type in {"image", "font", "stylesheet", "media"}:
            return
        network.append(
            {
                "phase": "request",
                "method": req.method,
                "url": req.url,
                "resource_type": req.resource_type,
                "post_data": req.post_data,
            }
        )

    def on_response(resp: Response) -> None:
        if resp.request.resource_type in {"image", "font", "stylesheet", "media"}:
            return
        network.append(
            {
                "phase": "response",
                "status": resp.status,
                "url": resp.url,
                "content_type": resp.headers.get("content-type"),
            }
        )

    async with authed_context(headless=True) as (_browser, context, page):
        context.on("request", on_request)
        context.on("response", on_response)

        await _dump(page, "00_landing_after_login", network)

        # Sidebar items we care about.
        for label in [
            "DASHBOARD",
            "TEAM SUMMARY",
            "SQUAD LIST",
            "FIXTURES",
            "LEADERS",
            "MATCH REPORTS",
        ]:
            if await _click_sidebar(page, label):
                await _dump(page, f"section_{_slug(label)}", network)

        # On MATCH REPORTS, try clicking the first visible match to capture
        # all match-detail tabs.
        await _click_sidebar(page, "MATCH REPORTS")
        await _dismiss_overlays(page)
        # Heuristic: find the first clickable row/card under the main content.
        first_match = page.locator(
            "main a, main [role='button'], main .match, main tr"
        ).first
        if await first_match.count():
            try:
                await first_match.click(timeout=8000)
                await page.wait_for_timeout(2500)
                await _dump(page, "match_default_tab", network)
            except Exception as exc:
                log.warning("Could not open a match: %s", exc)

        # Iterate through each match-report tab.
        for tab in [
            "Summary",
            "Score Sources",
            "Efficiencies",
            "Shot Map",
            "Free Kicks",
            "Player Stats",
        ]:
            tab_loc = page.get_by_role("tab", name=tab).first
            if not await tab_loc.count():
                tab_loc = page.get_by_text(re.compile(rf"^\s*{re.escape(tab)}\s*$", re.I)).first
            if await tab_loc.count():
                try:
                    await tab_loc.click()
                    await page.wait_for_timeout(1500)
                    await _dump(page, f"match_tab_{_slug(tab)}", network)
                except Exception as exc:
                    log.warning("Tab %s click failed: %s", tab, exc)

        # Final full network dump
        (EXPLORE_DIR / "_all_network.json").write_text(
            json.dumps(network, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("Exploration complete. See %s", EXPLORE_DIR)


if __name__ == "__main__":
    asyncio.run(main())
