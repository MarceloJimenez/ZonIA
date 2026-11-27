"""Settings from the environment. Each program calls load() once, when it starts.

.env keeps the provider address and key, the channel tokens, and ZONIA_DB (the database file).
Importing a module never reads .env: only load() does.
"""

import os

from dotenv import load_dotenv


def load() -> None:
    """Read .env in the current folder. A variable already set in the environment keeps its value."""
    load_dotenv(".env")


def dashboard_url() -> str:
    """Where the recruiter dashboard runs, for the links from the candidate pages: ZONIA_DASHBOARD_URL."""
    return os.environ.get("ZONIA_DASHBOARD_URL", "http://127.0.0.1:8000").rstrip("/")


def apply_url() -> str:
    """Where the candidate job page runs, for the link from the dashboard: ZONIA_APPLY_URL."""
    return os.environ.get("ZONIA_APPLY_URL", "http://127.0.0.1:8001/apply")


def db_path() -> str:
    """The SQLite file: ZONIA_DB, or zonia.db."""
    return os.environ.get("ZONIA_DB", "zonia.db")
