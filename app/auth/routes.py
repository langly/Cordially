"""Host sign-in."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.audit import audit
from app.auth import auth_bp
from app.services import users as users_svc


def _safe_next(target: str | None) -> str:
    """Only follow same-site relative redirects.

    ``next`` comes from the query string, so an absolute URL here would turn the
    login form into an open redirect.
    """
    if not target:
        return url_for("web.index")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return url_for("web.index")
    return target


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("web.index"))

    if request.method == "POST":
        user = users_svc.authenticate(
            request.form.get("email", ""), request.form.get("password", "")
        )
        if user is None:
            # Deliberately identical for unknown email, wrong password and
            # deactivated account, so the form cannot be used to enumerate users.
            audit("login.failure", actor="-", email=request.form.get("email", ""))
            flash("Those details did not match an active account.", "error")
            return render_template("auth/login.html", email=request.form.get("email", "")), 401

        login_user(user, remember=bool(request.form.get("remember")))
        audit("login.success", actor=user.email, admin=user.is_admin)
        return redirect(_safe_next(request.args.get("next")))

    return render_template("auth/login.html", email="")


@auth_bp.post("/logout")
@login_required
def logout():
    audit("logout")
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))
