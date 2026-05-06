"""Playwright-based authentication for PD TeamTracker.

Because the site is a Blazor Server app (SignalR over WebSockets), we drive
it with a real browser. We persist the authenticated cookies + localStorage
to ``settings.state_path`` so subsequent runs skip the login form.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import settings

log = logging.getLogger(__name__)


async def _dump_failure(page: Page, label: str) -> None:
    """Save HTML + screenshot when a login selector fails."""
    try:
        out_dir = settings.data_root / "explore"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{label}.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(out_dir / f"{label}.png"), full_page=True)
        log.error("Saved failure artefacts to %s", out_dir / label)
    except Exception as exc:
        log.error("Could not dump failure artefacts: %s", exc)


async def _perform_login(page: Page) -> None:
    """Fill the LOGIN form on the landing page and submit."""
    await page.goto(settings.base_url, wait_until="domcontentloaded")
    # Give the page a moment to settle without requiring true network idle
    # (Blazor keeps a WebSocket open, so networkidle may never fire).
    try:
        await page.wait_for_selector('input[type="password"]', timeout=15_000)
    except Exception:
        # Fall through — the diagnostic dump below will show what's there.
        pass

    # The login fields on pdapp2 are standard text inputs. We try a few
    # common selectors — Blazor often renders labelled inputs.
    username_selectors = [
        'input[name="_model.Usercode"]',
        'input[placeholder="Username" i]',
        'input[type="email"]',
        'input[name*="user" i]',
        'input[placeholder*="user" i]',
    ]
    password_selectors = [
        'input[name="_model.Password"]',
        'input[type="password"]',
        'input[name*="pass" i]',
    ]

    for sel in username_selectors:
        loc = page.locator(sel).first
        if await loc.count():
            await loc.fill(settings.username)
            break
    else:
        await _dump_failure(page, "login_username_not_found")
        raise RuntimeError("Could not find username input on login page")

    for sel in password_selectors:
        loc = page.locator(sel).first
        if await loc.count():
            await loc.fill(settings.password)
            break
    else:
        await _dump_failure(page, "login_password_not_found")
        raise RuntimeError("Could not find password input on login page")

    # Submit — the login form uses an <input type="submit"> button.
    submit = page.locator('input[type="submit"], button[type="submit"]').first
    if await submit.count():
        await submit.click()
    else:
        await page.keyboard.press("Enter")

    # Wait for post-login navigation — the app lands on a dashboard with
    # a sidebar containing "DASHBOARD" / "FIXTURES" etc.
    await page.wait_for_selector(
        'text=/DASHBOARD|FIXTURES|MATCH REPORTS/i',
        timeout=30_000,
    )
    log.info("Login successful for %s", settings.username)


async def _is_logged_in(page: Page) -> bool:
    try:
        await page.goto(settings.base_url, wait_until="networkidle", timeout=20_000)
    except Exception:
        return False
    # If the word LOGIN headline is visible we're on the login screen.
    login_heading = page.locator("text=/^\\s*LOGIN\\s*$/").first
    if await login_heading.count():
        return False
    # Otherwise look for an authenticated sidebar item.
    return bool(await page.locator("text=/FIXTURES|MATCH REPORTS/i").count())


@asynccontextmanager
async def authed_context(
    *,
    headless: bool = True,
    force_login: bool = False,
) -> AsyncIterator[tuple[Browser, BrowserContext, Page]]:
    """Yield (browser, context, page) that is already logged in.

    Reuses ``settings.state_path`` if present. Performs a fresh login if the
    persisted session is missing or stale.
    """
    state_path: Path = settings.state_path
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx_kwargs: dict = {"viewport": {"width": 1600, "height": 900}}
        if state_path.exists() and not force_login:
            ctx_kwargs["storage_state"] = str(state_path)

        context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()

        if force_login or not state_path.exists() or not await _is_logged_in(page):
            log.info("Performing fresh login…")
            # New context without storage_state so the login page loads cleanly.
            await context.close()
            context = await browser.new_context(viewport={"width": 1600, "height": 900})
            page = await context.new_page()
            await _perform_login(page)
            await context.storage_state(path=str(state_path))
            log.info("Session state saved to %s", state_path)

        try:
            yield browser, context, page
        finally:
            await context.close()
            await browser.close()
