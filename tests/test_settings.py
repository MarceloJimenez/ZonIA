"""settings.load() reads .env, and settings.db_path() gives the database file."""

from zonia import settings


def test_db_path_is_zonia_db_without_the_variable(monkeypatch):
    monkeypatch.delenv("ZONIA_DB", raising=False)
    assert settings.db_path() == "zonia.db"


def test_db_path_comes_from_zonia_db(monkeypatch):
    monkeypatch.setenv("ZONIA_DB", "other.db")
    assert settings.db_path() == "other.db"


def test_load_reads_env_file_in_current_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("ZONIA_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ZONIA_DB=from_env_file.db\n")
    settings.load()
    assert settings.db_path() == "from_env_file.db"
    monkeypatch.delenv("ZONIA_DB")
