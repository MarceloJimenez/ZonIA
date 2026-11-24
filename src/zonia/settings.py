"""Settings from the environment. Each program calls load() once, when it starts.

.env keeps the provider address and key, the channel tokens, and ZONIA_DB (the database file).
Importing a module never reads .env: only load() does.
"""

import os

from dotenv import load_dotenv


def load() -> None:
    """Read .env in the current folder. A variable already set in the environment keeps its value."""
    load_dotenv(".env")


def db_path() -> str:
    """The SQLite file: ZONIA_DB, or zonia.db."""
    return os.environ.get("ZONIA_DB", "zonia.db")
