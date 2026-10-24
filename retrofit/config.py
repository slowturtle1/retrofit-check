"""Settings from .env. Secrets stay in the environment and are never logged."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

USER_AGENT = "retrofit-check-hackathon/0.1 (Open Agent Hackathon 2026)"


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"{name} is missing from .env")
    return value


def db_dsn() -> str:
    return f"postgresql://retrofit:{env('RETROFIT_DB_PASSWORD')}@127.0.0.1:55432/retrofit"
