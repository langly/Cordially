"""Startup configuration guard."""

from __future__ import annotations

import pytest
from flask import Flask

from app.config import DEFAULT_SECRET_KEY
from app.startup import InsecureConfigError, validate_config


def _app(**config) -> Flask:
    app = Flask(__name__)
    app.config.update(config)
    return app


def test_default_secret_key_aborts_production_boot():
    app = _app(SECRET_KEY=DEFAULT_SECRET_KEY, DEBUG=False)
    with pytest.raises(InsecureConfigError, match="SECRET_KEY"):
        validate_config(app)


def test_a_real_secret_key_boots():
    validate_config(_app(SECRET_KEY="a-genuine-random-value", DEBUG=False))


def test_test_grade_hash_aborts_production_boot():
    app = _app(SECRET_KEY="real", PASSWORD_HASH_METHOD="pbkdf2:sha256:1", DEBUG=False)
    with pytest.raises(InsecureConfigError, match="cost factor"):
        validate_config(app)


def test_debug_downgrades_the_error_to_a_warning(caplog):
    app = _app(SECRET_KEY=DEFAULT_SECRET_KEY, DEBUG=True)
    validate_config(app)  # does not raise
    assert any("SECRET_KEY" in r.message for r in caplog.records)


def test_flask_debug_env_also_counts_as_dev(monkeypatch):
    """`flask run` sets FLASK_DEBUG after the factory, so the env is the signal."""
    monkeypatch.setenv("FLASK_DEBUG", "1")
    validate_config(_app(SECRET_KEY=DEFAULT_SECRET_KEY, DEBUG=False))  # no raise


def test_testing_config_is_exempt():
    # TestConfig deliberately keeps the default key and a 1-round hash.
    validate_config(_app(TESTING=True, SECRET_KEY=DEFAULT_SECRET_KEY,
                         PASSWORD_HASH_METHOD="pbkdf2:sha256:1"))


def test_the_message_names_all_problems_at_once():
    app = _app(SECRET_KEY=DEFAULT_SECRET_KEY, PASSWORD_HASH_METHOD="pbkdf2:sha256:1", DEBUG=False)
    with pytest.raises(InsecureConfigError) as exc:
        validate_config(app)
    assert "SECRET_KEY" in str(exc.value) and "cost factor" in str(exc.value)
