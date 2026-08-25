"""Host accounts and site administration."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select

from app.extensions import db
from app.models import User


def list_users() -> List[User]:
    return list(db.session.scalars(select(User).order_by(User.email)))


def get_user(user_id: int) -> Optional[User]:
    return db.session.get(User, user_id)


def get_user_or_404(user_id: int) -> User:
    return db.get_or_404(User, user_id)


def find_by_email(email: str) -> Optional[User]:
    """Email lookup is case-insensitive; addresses are stored lowercased."""
    stmt = select(User).where(func.lower(User.email) == (email or "").strip().lower())
    return db.session.scalars(stmt).first()


def admin_count() -> int:
    stmt = select(func.count(User.id)).where(User.is_admin.is_(True), User.is_active.is_(True))
    return db.session.scalar(stmt) or 0


def authenticate(email: str, password: str) -> Optional[User]:
    """Return the user only for a correct password on an active account.

    A miss still runs a password check against a throwaway hash so that an
    unknown address costs the same as a wrong password -- otherwise response
    time alone reveals which accounts exist.
    """
    user = find_by_email(email)
    if user is None:
        _burn_password_check(password)
        return None
    if not user.check_password(password):
        return None
    if not user.is_active:
        return None
    return user


def _burn_password_check(password: str) -> None:
    from app.models.user import _hash_method

    from werkzeug.security import check_password_hash, generate_password_hash

    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = generate_password_hash("timing-equaliser", method=_hash_method())
    check_password_hash(_DUMMY_HASH, password or "")


_DUMMY_HASH: Optional[str] = None


def create_user(
    email: str,
    password: str,
    name: Optional[str] = None,
    is_admin: bool = False,
    is_active: bool = True,
) -> User:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("A valid email address is required")
    if find_by_email(email):
        raise ValueError(f"A user with the email {email!r} already exists")

    user = User(
        email=email,
        name=(name or "").strip() or None,
        is_admin=bool(is_admin),
        is_active=bool(is_active),
    )
    user.set_password(password)  # validates length before anything is written
    db.session.add(user)
    db.session.commit()
    return user


def update_user(
    user: User,
    email: Optional[str] = None,
    name: Optional[str] = None,
    is_admin: Optional[bool] = None,
    is_active: Optional[bool] = None,
    password: Optional[str] = None,
) -> User:
    if email is not None:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("A valid email address is required")
        existing = find_by_email(email)
        if existing and existing.id != user.id:
            raise ValueError(f"A user with the email {email!r} already exists")
        user.email = email

    if name is not None:
        user.name = name.strip() or None

    # Removing the last active admin would leave nobody able to manage users,
    # so both routes to that state are blocked.
    if is_admin is not None and not is_admin and user.is_admin:
        _guard_last_admin(user, "remove the last administrator")
    if is_active is not None and not is_active and user.is_active and user.is_admin:
        _guard_last_admin(user, "deactivate the last administrator")

    if is_admin is not None:
        user.is_admin = bool(is_admin)
    if is_active is not None:
        user.is_active = bool(is_active)
    if password:
        user.set_password(password)

    db.session.commit()
    return user


def delete_user(user: User) -> None:
    """Delete an account. Their events survive, becoming admin-only."""
    if user.is_admin and user.is_active:
        _guard_last_admin(user, "delete the last administrator")
    db.session.delete(user)
    db.session.commit()


def _guard_last_admin(user: User, action: str) -> None:
    if user.is_admin and user.is_active and admin_count() <= 1:
        raise ValueError(f"You cannot {action} — promote someone else first")
