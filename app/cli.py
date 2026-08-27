"""Custom ``flask`` CLI commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click
from flask import Flask

from app.extensions import db


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        """Create all tables directly (handy for a throwaway database).

        Prefer ``flask db upgrade`` for anything you intend to keep, so schema
        changes stay versioned.
        """
        db.create_all()
        click.echo(f"Tables created in {app.config['SQLALCHEMY_DATABASE_URI']}")

    @app.cli.command("seed")
    @click.option("--force", is_flag=True, help="Seed even if data already exists.")
    def seed(force: bool):
        """Insert a small demo party with two families and a friends group."""
        from app.models import Event, Group, GroupKind, Member
        from app.services import invitations as invites_svc

        if not force and db.session.query(Group).first():
            click.echo("Data already present; re-run with --force to seed anyway.")
            return

        smiths = Group(name="The Smith Family", kind=GroupKind.FAMILY,
                       contact_email="jane@example.com")
        smiths.members = [
            Member(first_name="Jane", last_name="Smith", email="jane@example.com"),
            Member(first_name="Tom", last_name="Smith", dietary_notes="Vegetarian"),
            Member(first_name="Ada", last_name="Smith", is_child=True, age=8),
        ]

        patels = Group(name="The Patel Family", kind=GroupKind.FAMILY)
        patels.members = [
            Member(first_name="Riya", last_name="Patel", dietary_notes="Nut allergy"),
            Member(first_name="Arjun", last_name="Patel"),
        ]

        climbing = Group(name="Climbing Crew", kind=GroupKind.GROUP)
        climbing.members = [
            Member(first_name="Mo", last_name="Hassan"),
            Member(first_name="Kari", last_name="Nilsen"),
        ]

        party = Event(
            name="Summer BBQ",
            description="Bring something for the grill.",
            location="Back garden",
            starts_at=datetime.now(timezone.utc) + timedelta(days=21),
            capacity=20,
        )

        # Attach to the first admin if one exists; otherwise the event is
        # unowned and admin-only until `flask claim-events` runs. No default
        # password is ever created here.
        from app.models import User

        owner = db.session.query(User).filter(User.is_admin.is_(True)).order_by(User.id).first()
        party.owner = owner

        db.session.add_all([smiths, patels, climbing, party])
        db.session.commit()

        for group in (smiths, patels, climbing):
            invites_svc.invite_group(party, group)

        click.echo("Seeded 3 groups, 7 members and 1 event.")
        if owner is None:
            click.echo(
                "No admin exists yet, so the event is unowned. Run:\n"
                "  flask create-admin   then   flask claim-events"
            )

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", default=None, help="Display name.")
    @click.password_option(help="At least 8 characters.")
    def create_admin(email: str, name: str, password: str):
        """Create a site administrator. Use this to bootstrap the first login."""
        from app.services import users as users_svc

        try:
            user = users_svc.create_user(email, password, name=name, is_admin=True)
        except ValueError as err:
            raise click.ClickException(str(err))
        click.echo(f"Created admin {user.email}")

    @app.cli.command("claim-events")
    @click.option("--email", prompt=True, help="User who should own unowned events.")
    def claim_events(email: str):
        """Assign every event with no owner to a user.

        Events created before accounts existed have no owner and are visible to
        site admins only; this hands them to a real host.
        """
        from app.models import Event
        from app.services import users as users_svc

        user = users_svc.find_by_email(email)
        if user is None:
            raise click.ClickException(f"No user with email {email!r}")

        orphans = db.session.query(Event).filter(Event.owner_id.is_(None)).all()
        for event in orphans:
            event.owner = user
        db.session.commit()
        click.echo(f"Assigned {len(orphans)} event(s) to {user.email}")

    @app.cli.command("send-pending-mail")
    @click.option("--limit", default=100, show_default=True, help="Max messages to send.")
    def send_pending_mail(limit: int):
        """Send queued emails. Run from cron or a systemd timer."""
        from app.services import mail as mail_svc

        if not mail_svc.is_enabled():
            click.echo("Email is disabled (MAIL_ENABLED=0); nothing sent.")
            return
        pending = mail_svc.pending_count()
        if not pending:
            click.echo("No pending email.")
            return
        result = mail_svc.flush(limit=limit)
        click.echo(f"Sent {result['sent']}, failed {result['failed']} "
                   f"(of {pending} pending, backend={app.config['MAIL_BACKEND']}).")

    @app.cli.command("mail-status")
    def mail_status():
        """Show outbox counts by status."""
        from sqlalchemy import func, select

        from app.models import EmailMessage

        rows = db.session.execute(
            select(EmailMessage.status, func.count(EmailMessage.id)).group_by(EmailMessage.status)
        ).all()
        counts = {status: n for status, n in rows}
        for status in ("pending", "sent", "failed"):
            click.echo(f"  {status:8} {counts.get(status, 0)}")

    @app.cli.command("retry-failed-mail")
    def retry_failed_mail():
        """Requeue permanently-failed emails (after fixing SMTP config)."""
        from app.services import mail as mail_svc

        click.echo(f"Requeued {mail_svc.retry_failed()} message(s).")

    @app.cli.command("db-info")
    def db_info():
        """Show which database this app is talking to."""
        from sqlalchemy import inspect

        engine = db.engine
        click.echo(f"dialect: {engine.dialect.name}")
        click.echo(f"driver:  {engine.dialect.driver}")
        click.echo(f"url:     {engine.url.render_as_string(hide_password=True)}")
        click.echo(f"tables:  {', '.join(sorted(inspect(engine).get_table_names())) or '(none)'}")
