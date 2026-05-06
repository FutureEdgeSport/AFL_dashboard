"""Dump the raw login page HTML + screenshot to inspect its structure."""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from .config import settings

OUT = settings.data_root / "explore"
OUT.mkdir(parents=True, exist_ok=True)


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 900})
        page = await ctx.new_page()
        await page.goto(settings.base_url, wait_until="networkidle", timeout=30_000)
        # Blazor may rehydrate after networkidle — wait a bit more
        await page.wait_for_timeout(3000)
        (OUT / "login_page.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(OUT / "login_page.png"), full_page=True)

        # Enumerate inputs
        inputs = await page.evaluate(
            """() => Array.from(document.querySelectorAll('input, button, a')).map(el => ({
                tag: el.tagName,
                type: el.type || null,
                name: el.name || null,
                id: el.id || null,
                placeholder: el.placeholder || null,
                aria: el.getAttribute('aria-label'),
                text: (el.innerText || '').slice(0, 80),
                className: el.className || null,
            }))"""
        )
        import json

        (OUT / "login_elements.json").write_text(json.dumps(inputs, indent=2), encoding="utf-8")
        print(f"Dumped {len(inputs)} elements to {OUT / 'login_elements.json'}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
