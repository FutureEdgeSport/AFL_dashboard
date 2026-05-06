"""Configuration loader for pd_scraper.

Reads PD_USERNAME / PD_PASSWORD / PD_BASE_URL from the top-level .env file
(which is gitignored) using python-dotenv.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
load_dotenv(ENV_PATH)

DATA_ROOT = REPO_ROOT / "data" / "pd"
RAW_ROOT = DATA_ROOT / "raw"
DB_PATH = DATA_ROOT / "pd.db"
STATE_PATH = DATA_ROOT / "session_state.json"  # Playwright storage_state
LOG_ROOT = REPO_ROOT / "logs" / "pd_scraper"


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    base_url: str
    data_root: Path = DATA_ROOT
    raw_root: Path = RAW_ROOT
    db_path: Path = DB_PATH
    state_path: Path = STATE_PATH
    log_root: Path = LOG_ROOT


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required env var {name}. Add it to {ENV_PATH}"
        )
    return value


settings = Settings(
    username=_require("PD_USERNAME"),
    password=_require("PD_PASSWORD"),
    base_url=os.getenv("PD_BASE_URL", "https://pdapp2.advancedhp.com.au/").rstrip("/") + "/",
)

# Ensure output dirs exist lazily (don't create on import side-effects unless needed)
for _d in (DATA_ROOT, RAW_ROOT, LOG_ROOT):
    _d.mkdir(parents=True, exist_ok=True)
