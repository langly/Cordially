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

        db.session.add_all([smiths, patels, climbing, party])
        db.session.commit()

        for group in (smiths, patels, climbing):
            invites_svc.invite_group(party, group)

        click.echo("Seeded 3 groups, 7 members and 1 event.")

    @app.cli.command("db-info")
    def db_info():
        """Show which database this app is talking to."""
        from sqlalchemy import inspect

        engine = db.engine
        click.echo(f"dialect: {engine.dialect.name}")
        click.echo(f"driver:  {engine.dialect.driver}")
        click.echo(f"url:     {engine.url.render_as_string(hide_password=True)}")
        click.echo(f"tables:  {', '.join(sorted(inspect(engine).get_table_names())) or '(none)'}")
