"""PD TeamTracker scraper package.

Scrapes match, team and player data from https://pdapp2.advancedhp.com.au/
for all teams/seasons the authenticated user has access to.

Data is stored both as raw JSON (lossless archive) and normalised into
SQLite for downstream use by the AFL dashboard / MGS app.
"""
from .config import settings  # noqa: F401
