"""Startup configuration checks.

Fails loud, at boot, on settings that are safe in development but a security
hole in production -- so a misconfigured deploy stops rather than quietly
running insecure.
"""

from __future__ import annotations

import logging
import os

from flask import Flask

from app.config import DEFAULT_SECRET_KEY

logger = logging.getLogger("events.startup")


class InsecureConfigError(RuntimeError):
    """Raised when production config would be unsafe to serve."""


def _looks_like_test_hash(method: str | None) -> bool:
    """A KDF cost factor of 1 (e.g. ``pbkdf2:sha256:1``) is test-only."""
    return bool(method) and method.rsplit(":", 1)[-1] == "1"


def validate_config(app: Flask) -> None:
    """Check security-critical config.

    Tests run with their own throwaway settings, so they are exempt. In debug
    mode problems are logged as warnings (local convenience); otherwise -- a
    real deployment -- they abort startup.
    """
    if app.config.get("TESTING"):
        return

    # `flask run` applies FLASK_DEBUG only after the factory returns, so app.debug
    # is still False here. Read the env signal directly to recognise local dev.
    is_debug = app.debug or os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}

    problems: list[str] = []

    if app.config.get("SECRET_KEY") == DEFAULT_SECRET_KEY:
        problems.append(
            "SECRET_KEY is still the built-in default, so anyone who has seen "
            "the source can forge a login session. Set the SECRET_KEY "
            "environment variable to a random secret, e.g.\n"
            "    export SECRET_KEY=\"$(python3 -c 'import secrets; "
            "print(secrets.token_urlsafe(48))')\""
        )

    if _looks_like_test_hash(app.config.get("PASSWORD_HASH_METHOD")):
        problems.append(
            "PASSWORD_HASH_METHOD has a cost factor of 1 (test-grade). This "
            "usually means FLASK_ENV=testing leaked into a real environment. "
            "Unset it or FLASK_ENV."
        )

    if not problems:
        return

    if is_debug:
        for problem in problems:
            logger.warning("Insecure configuration (allowed in debug): %s", problem)
        return

    raise InsecureConfigError(
        "Refusing to start with insecure configuration:\n\n- "
        + "\n\n- ".join(problems)
        + "\n\nSet the values above, or set FLASK_DEBUG=1 for local development."
    )
