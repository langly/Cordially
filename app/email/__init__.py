"""Email backends and delivery.

The backend is chosen by ``MAIL_BACKEND`` (console/smtp/memory), so dev needs no
mail server and tests capture in-process -- the same swappable-by-config
approach the app uses for its database.
"""

from __future__ import annotations

from flask import Flask

from app.email.backends import (
    ConsoleBackend,
    DisabledBackend,
    MemoryBackend,
    SmtpBackend,
)

_BACKENDS = {
    "console": ConsoleBackend,
    "smtp": SmtpBackend,
    "memory": MemoryBackend,
}


def init_mail(app: Flask) -> None:
    """Resolve the configured backend once and stash it on the app."""
    if not app.config.get("MAIL_ENABLED", True):
        # The kill switch wins over MAIL_BACKEND entirely.
        app.extensions["mail_backend"] = DisabledBackend(app)
        return

    name = (app.config.get("MAIL_BACKEND") or "console").lower()
    backend_cls = _BACKENDS.get(name)
    if backend_cls is None:
        raise ValueError(
            f"Unknown MAIL_BACKEND {name!r} (choose from {', '.join(_BACKENDS)})"
        )
    app.extensions["mail_backend"] = backend_cls(app)


def get_backend(app: Flask):
    backend = app.extensions.get("mail_backend")
    if backend is None:  # e.g. an app built without init_mail
        init_mail(app)
        backend = app.extensions["mail_backend"]
    return backend
