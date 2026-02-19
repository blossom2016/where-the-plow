from where_the_plow.config import Settings


def test_default_settings():
    settings = Settings()
    assert settings.db_path == "/data/plow.db"
    assert settings.poll_interval == 6
    assert settings.log_level == "INFO"
    assert "MapServer" in settings.avl_api_url


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("POLL_INTERVAL", "10")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.db_path == "/tmp/test.db"
    assert settings.poll_interval == 10
    assert settings.log_level == "DEBUG"
