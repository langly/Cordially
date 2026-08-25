# Running on PostgreSQL

The app is SQLite by default but the schema is written to run unchanged on
PostgreSQL — no code changes, only configuration. This file covers everything
that happens **on the Postgres side** to make that work.

Nothing here is app-specific trickery: it is a standard Flask + SQLAlchemy +
Alembic deployment. If you have done one before, skim to the [checklist](#checklist).

---

## 1. Prerequisites

- **PostgreSQL 12 or newer.** The schema uses only `SERIAL`, `TIMESTAMP WITH
  TIME ZONE`, `VARCHAR`, `TEXT`, `BOOLEAN`, and `INTEGER` — all available in
  every supported Postgres version. No extensions are required (no `uuid-ossp`,
  no `citext`, nothing to `CREATE EXTENSION`).
- A database **role** the app connects as, and a **database** it owns or can
  create tables in.

The app talks to Postgres through **psycopg 3**, so the driver in the
`DATABASE_URL` is `postgresql+psycopg` (not the older `psycopg2`).

---

## 2. Create the role and database

Connect as a superuser (`postgres`) and run:

```sql
-- A dedicated login role for the application.
CREATE ROLE events_app WITH LOGIN PASSWORD 'change-this-strong-password';

-- The database, owned by that role so it can create/alter its own tables.
CREATE DATABASE events OWNER events_app;
```

Making `events_app` the **owner** of the database is the simplest correct setup:
Alembic migrations issue `CREATE TABLE`, `ALTER TABLE`, etc., and the owner may
do all of that. If you need a tighter split (a privileged role for migrations
and a restricted role for the running app), see
[least privilege](#8-optional-least-privilege-runtime-role).

### PostgreSQL 15+ : the `public` schema gotcha

Since Postgres 15, non-owner roles can no longer create objects in the `public`
schema by default. If `events_app` is **not** the database owner (e.g. you
created the database as `postgres` and only granted `CONNECT`), migrations will
fail with *permission denied for schema public*. Fix it by granting the schema,
connected to the `events` database:

```sql
\connect events
GRANT USAGE, CREATE ON SCHEMA public TO events_app;
```

If `events_app` owns the database (the recipe above), this is already handled.

### Encoding and locale

`CREATE DATABASE` inherits the cluster template. A modern cluster is `UTF8`,
which is what you want. To be explicit:

```sql
CREATE DATABASE events OWNER events_app
  ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8' TEMPLATE template0;
```

The app stores all timestamps as UTC-aware values (`TIMESTAMP WITH TIME ZONE`),
so the server's `timezone` setting does not affect stored data.

---

## 3. Point the app at Postgres

Install the driver into the app's environment and set `DATABASE_URL`. These are
the only two changes on the application side.

```bash
.venv/bin/pip install "psycopg[binary]>=3.1"

export DATABASE_URL="postgresql+psycopg://events_app:change-this-strong-password@localhost:5432/events"
```

- `psycopg[binary]` ships a self-contained build — no local `libpq`/compiler
  needed, ideal for getting started and for most deployments. For a from-source
  build against the system `libpq`, use `psycopg[c]` instead.
- URL shape: `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME`.
- If the password contains URL-special characters (`@ : / ? # %`), percent-encode
  them (`@` → `%40`).

Put `DATABASE_URL` in your `.env` (see `.env.example`) or the process
environment. Nothing in the code changes.

### TLS / `sslmode`

For anything over a network, require TLS by appending libpq parameters to the
URL:

```
postgresql+psycopg://events_app:pw@db.internal:5432/events?sslmode=require
```

Use `sslmode=verify-full` with `sslrootcert=/path/to/ca.crt` when you have the
server's CA and want to defeat man-in-the-middle, not just encrypt. Managed
providers (RDS, Cloud SQL, Neon, Supabase) usually document the exact value.

---

## 4. Create the schema

The app does **not** create tables on startup. Run the Alembic migrations once
against the new database — the same command as on SQLite:

```bash
export FLASK_APP=wsgi
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
.venv/bin/flask db upgrade
```

This applies all five migrations and creates every table, index, and
constraint. Foreign-key `ON DELETE CASCADE` rules are enforced natively by
Postgres (unlike SQLite, which needs a runtime pragma), so deleting a group
removes its members and deleting an event removes its invitations with no extra
setup.

Confirm what the app is actually connected to:

```bash
.venv/bin/flask db-info
#   dialect: postgresql
#   driver:  psycopg
#   url:     postgresql+psycopg://events_app:***@localhost:5432/events
#   tables:  alembic_version, event_hosts, events, groups, invitations, invite_links, members, users
```

> Do **not** use `flask init-db` here — that is a SQLite convenience that calls
> `create_all()` and bypasses the migration history. Always use `flask db upgrade`
> on Postgres so the schema stays versioned.

---

## 5. Create the first administrator

The database is empty and the app is default-deny, so you must create the first
login before anyone can sign in:

```bash
.venv/bin/flask create-admin        # prompts for email + password
```

If you are migrating existing events from a previous database that had no
accounts, `flask claim-events --email you@example.com` assigns unowned events to
a user.

---

## 6. Migrating existing SQLite data (optional)

If you already ran on SQLite and want to keep that data, the schema is identical
but the dump formats are not — a plain `.sql` dump from SQLite will not load
into Postgres cleanly (different quoting, `AUTOINCREMENT`, boolean literals).
Use a row-level tool rather than a raw dump:

- **pgloader** — `pgloader ./instance/events.db "$DATABASE_URL"` handles the
  type translation in one command; the simplest path.
- Or a small script that reads via SQLAlchemy and re-inserts, running
  `flask db upgrade` on the empty Postgres database first so the schema exists.

After loading, reset the sequences so new inserts don't collide with imported
ids:

```sql
SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE(MAX(id), 1)) FROM users;
-- repeat for events, groups, members, invitations, invite_links
```

For a fresh start, skip all of this — just `flask db upgrade` and `create-admin`.

---

## 7. Connection pooling

`pool_pre_ping` is already enabled in `app/config.py`, which transparently
recovers from connections dropped by the server or an idle-timeout proxy. The
pool size uses SQLAlchemy's defaults (5 connections + up to 10 overflow) per
worker process.

Two things to keep in mind at scale:

- **Total connections = pool size × worker processes.** A gunicorn deployment
  with 4 workers can open ~60 connections; keep that under the server's
  `max_connections`.
- Pool size is not currently exposed as an environment variable. To tune it, add
  `pool_size` / `max_overflow` to `SQLALCHEMY_ENGINE_OPTIONS` in `app/config.py`.
- Behind an external pooler such as **PgBouncer in transaction mode**, disable
  SQLAlchemy's own pooling by setting the engine to `NullPool` (a code change),
  and note that transaction-mode PgBouncer does not support session-level
  features the app does not use anyway.

---

## 8. Optional: least-privilege runtime role

The owner-role recipe lets the app both migrate and serve. To separate those
powers, run migrations as the owner and serve as a role that can only read and
write rows:

```sql
-- Run migrations as the owner (events_app), then grant the runtime role:
CREATE ROLE events_run WITH LOGIN PASSWORD 'another-strong-password';
GRANT CONNECT ON DATABASE events TO events_run;
\connect events
GRANT USAGE ON SCHEMA public TO events_run;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO events_run;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO events_run;

-- Apply the same grants automatically to tables a future migration creates:
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO events_run;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO events_run;
```

Then the running app uses `events_run` in `DATABASE_URL`, while `flask db upgrade`
is run (during deploys) with the `events_app` owner URL. `events_run` cannot
`ALTER`/`DROP` tables, so a bug or injection cannot reshape the schema.

---

## 9. Backups

Postgres has first-class tooling; use it rather than copying files:

```bash
pg_dump --format=custom --file=events-$(date +%F).dump "$DATABASE_URL"   # backup
pg_restore --clean --if-exists --dbname="$DATABASE_URL" events-2026-08-25.dump  # restore
```

A managed provider usually gives you automated point-in-time recovery; if so,
prefer that for disaster recovery and use `pg_dump` for portable snapshots.

---

## Checklist

```
[ ] PostgreSQL 12+ reachable
[ ] Role created:            CREATE ROLE events_app LOGIN PASSWORD '…'
[ ] Database created:        CREATE DATABASE events OWNER events_app
[ ] (PG15+, non-owner only)  GRANT USAGE, CREATE ON SCHEMA public
[ ] Driver installed:        pip install "psycopg[binary]>=3.1"
[ ] DATABASE_URL set:        postgresql+psycopg://events_app:…@host:5432/events[?sslmode=require]
[ ] SECRET_KEY set           (a real random value — the app refuses to boot without one)
[ ] Schema created:          flask db upgrade
[ ] Verified:                flask db-info   → dialect: postgresql, 8 tables
[ ] First admin created:     flask create-admin
[ ] TLS required for any non-local connection
```

Everything above is standard Postgres administration. The application itself
needs only a correct `DATABASE_URL` and the psycopg driver — the portability was
built into the schema (explicit column lengths, `VARCHAR`+`CHECK` instead of
native enums, UTC-aware timestamps, named constraints). See the README's
"Changing the database" section for why those choices matter.
