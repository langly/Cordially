"""Host sign-in."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.audit import audit
from app.auth import auth_bp
from app.services import users as users_svc


def google_enabled() -> bool:
    return current_app.extensions.get("oauth") is not None


def _safe_next(target: str | None) -> str:
    """Only follow same-site relative redirects, keeping the mount prefix.

    ``next`` comes from the query string, so an absolute URL here would turn the
    login form into an open redirect -- reject anything with a scheme/host. The
    stored value is app-relative (no SCRIPT_NAME), so prepend ``script_root`` to
    survive a sub-path mount (``/e``); at root ``script_root`` is empty.
    """
    if not target:
        return url_for("web.index")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return url_for("web.index")
    return request.script_root + target


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
            return render_template(
                "auth/login.html",
                email=request.form.get("email", ""),
                google_enabled=google_enabled(),
            ), 401

        login_user(user, remember=bool(request.form.get("remember")))
        audit("login.success", actor=user.email, admin=user.is_admin)
        return redirect(_safe_next(request.args.get("next")))

    return render_template("auth/login.html", email="", google_enabled=google_enabled())


@auth_bp.post("/logout")
@login_required
def logout():
    audit("logout")
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("auth.login"))


# --- Google sign-in (OpenID Connect, match-only) ----------------------------

@auth_bp.get("/auth/google")
def google_login():
    """Kick off the Google flow. Stashes `next` in the session because the
    round-trip through Google drops query params."""
    if not google_enabled():
        abort(404)
    session["next_after_login"] = request.args.get("next") or ""
    oauth = current_app.extensions["oauth"]
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.get("/auth/google/callback")
def google_callback():
    if not google_enabled():
        abort(404)

    oauth = current_app.extensions["oauth"]
    try:
        token = oauth.google.authorize_access_token()  # validates the ID token
    except Exception:  # noqa: BLE001 -- any OAuth failure is a failed sign-in
        flash("Google sign-in failed or was cancelled.", "error")
        return redirect(url_for("auth.login"))

    info = token.get("userinfo") or {}
    user = users_svc.login_with_google(
        info.get("sub", ""), info.get("email", ""), bool(info.get("email_verified"))
    )

    nxt = session.pop("next_after_login", "") or None
    if user is None:
        audit("login.google.denied", actor="-", email=info.get("email") or "-")
        flash(
            "No Cordially account matches that Google address. "
            "Ask an administrator to add you.", "error",
        )
        return redirect(url_for("auth.login"))

    login_user(user, remember=True)
    audit("login.success", actor=user.email, method="google", admin=user.is_admin)
    return redirect(_safe_next(nxt))
