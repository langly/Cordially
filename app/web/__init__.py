"""Server-rendered UI blueprint."""

from __future__ import annotations

from flask import Blueprint

web_bp = Blueprint("web", __name__)

from app.web import routes  # noqa: E402,F401
