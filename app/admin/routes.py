"""User administration. Every view here is site-admin only."""

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.authz import admin_required
from app.services import users as users_svc


@admin_bp.get("/users")
@admin_required
def users():
    return render_template(
        "admin/users.html",
        users=users_svc.list_users(),
        admin_count=users_svc.admin_count(),
    )


@admin_bp.post("/users")
@admin_required
def create_user():
    try:
        user = users_svc.create_user(
            email=request.form.get("email", ""),
            password=request.form.get("password", ""),
            name=request.form.get("name"),
            is_admin=bool(request.form.get("is_admin")),
        )
        flash(f"Created {user.display_name}.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>")
@admin_required
def update_user(user_id: int):
    user = users_svc.get_user_or_404(user_id)

    # Checkboxes are absent when unticked, so read them only when the form
    # actually carries the flags -- a password-only submit must not demote.
    is_admin = bool(request.form.get("is_admin")) if "flags" in request.form else None
    is_active = bool(request.form.get("is_active")) if "flags" in request.form else None

    try:
        users_svc.update_user(
            user,
            email=request.form.get("email"),
            name=request.form.get("name"),
            is_admin=is_admin,
            is_active=is_active,
            password=request.form.get("password") or None,
        )
        flash(f"Updated {user.display_name}.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("admin.users"))


@admin_bp.post("/users/<int:user_id>/delete")
@admin_required
def delete_user(user_id: int):
    user = users_svc.get_user_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.users"))

    name = user.display_name
    try:
        users_svc.delete_user(user)
        flash(f"Deleted {name}. Their events are now unowned.", "success")
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("admin.users"))
