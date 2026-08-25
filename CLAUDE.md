# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

There is no global install; everything runs from `.venv`. Every `flask` command
needs `FLASK_APP=wsgi`.

```bash
export FLASK_APP=wsgi

.venv/bin/flask run                      # dev server
.venv/bin/flask db upgrade               # apply migrations (do this before running)
.venv/bin/flask db migrate -m "message"  # generate a migration after model changes
.venv/bin/flask seed [--force]           # demo data: 3 groups, 7 members, 1 event
.venv/bin/flask db-info                  # which dialect/driver/tables are live
.venv/bin/flask shell                    # preloaded with db + all models

.venv/bin/python -m pytest -q                          # all tests
.venv/bin/python -m pytest tests/test_themes.py        # one file
.venv/bin/python -m pytest "tests/test_api.py::test_full_flow_over_the_api"  # one test
```

Tests run against in-memory SQLite (`TestConfig`), create their own schema via
`create_all`, and need no migration step. There is no linter or formatter
configured.

## Architecture

Flask app factory (`app/__init__.py`) + SQLAlchemy 2.0 declarative + Alembic.

### Blueprints and trust levels

| Blueprint | Prefix | Who reaches it |
|---|---|---|
| `app/auth` | `/login` | anonymous — the only public host-side endpoint |
| `app/web` | `/` | signed-in hosts |
| `app/api` | `/api` | signed-in hosts, JSON (401 instead of a redirect) |
| `app/admin` | `/admin` | site admins only |
| `app/invite` | `/i/<token>` | **the public** — the token is the only credential |

`app/invite` is the security boundary. Its views must never expose anything
beyond the single group the token addresses; `test_invite_links.py` asserts one
group's card cannot leak another's guests. Unknown token → 404, revoked → 410.

### Authorization is default-deny

`_install_auth_guard` in `app/__init__.py` requires a session for **every**
endpoint except those in `PUBLIC_ENDPOINTS` / `PUBLIC_BLUEPRINTS`. A new route
is therefore protected automatically; making one public is a deliberate edit in
that one place. `test_auth.py` walks the URL map and fails if any route answers
anonymously — do not weaken it.

Two rules, each with a single implementation:

- **Event access**: `Event.is_managed_by()` (admin, owner, or co-host), always
  reached via `authz.event_or_403`. Any route that loads an event by id must go
  through it, including ones that reach an event indirectly (invitation id,
  group id on a link endpoint).
- **Site admin**: the `authz.admin_required` decorator.

Events created before accounts exist have `owner_id = NULL` and are visible to
admins only; `flask claim-events` assigns them.

Guests never authenticate — that is a requirement, not an oversight. Any change
that puts `/i/<token>` behind a login is wrong.

### The service layer owns every query

`app/services/*` is the only place that touches the ORM. Views call services;
they never build queries. Keep it that way — it is what makes the storage
backend swappable and keeps the three blueprints consistent.

### Data model

```
Group ──< Member ──< Invitation >── Event
  └──────< InviteLink >───────────────┘
```

`InviteLink` is the (event, group) pairing and carries the sharing rules:

- **One reply covers the group.** Answering the card sets the RSVP for every
  member (`invite_links.respond` → `invitations.set_group_rsvp`). There are no
  per-guest logins by design.
- **Links are idempotent and stable.** `create_link` returns the existing link
  for a group, so an already-shared URL never breaks. `rotate` deliberately
  breaks it.
- **`restricted` vs open.** Restricted = only the named members. Open = the
  group reports `adults_attending` / `children_attending` instead of names.

### Head counts: the one subtle rule

`Event.counts()` and `invitations.group_summary()` must agree, and both
implement the same fallback:

- an **open** group that supplied numbers contributes *those numbers*, replacing
  its named members entirely;
- an open group that accepted **without** numbers falls back to being counted by
  name, so nobody is silently dropped;
- explicit `0` is a real answer ("none of us"), distinct from unanswered —
  hence `has_headcount` checks `is not None` rather than truthiness.

Restricted groups split adults/children using `Member.is_child`; plus-ones count
as adults. If you change one of these two functions, change the other.

### Themes

`app/themes.py` is the catalogue; `app/static/css/invite.css` holds the matching
`[data-theme="..."]` / `[data-layout="..."]` custom-property blocks. The choice
is stored on `Event` as a plain string, so **adding a theme needs no migration**
— one entry in `themes.py` plus one CSS block. Unknown names fall back to the
default (`get_theme`) so a renamed theme never breaks a live invitation, and
tests assert every catalogued theme has a CSS block (otherwise it would silently
render as Classic).

The card markup carries `.pane-main` / `.pane-side` wrappers that only the
`split` layout uses as grid columns; other layouts dissolve them with
`display: contents`. Invitation cards deliberately ignore
`prefers-color-scheme` — the host's chosen theme wins on every screen.

`/events/<id>/preview` renders sample guests from `app/preview_data.py` (plain
`SimpleNamespace`, not rows). It must never write to the database.

## Database portability

SQLite is the default but the schema is written to run unchanged on PostgreSQL
and MySQL via `DATABASE_URL`. These rules are deliberate — preserve them:

- **Explicit `String` lengths everywhere** (MySQL requires them).
- **No native `ENUM`s.** Enum-like columns are `VARCHAR` + `CHECK`
  (`SAEnum(..., native_enum=False)`).
- **`UtcDateTime`** (`app/models/types.py`) on every timestamp, never bare
  `DateTime`. SQLite returns naive datetimes and PostgreSQL aware ones; this
  normalises both to UTC-aware.
- **Timestamps generated in Python** (`mixins.utcnow`), not database `now()`.
- **Named constraints** via the naming convention in `extensions.py` — Alembic
  autogenerate and SQLite batch mode both depend on it.
- SQLite `PRAGMA foreign_keys=ON` is set in `app/__init__.py` behind a driver
  check. Without it SQLite ignores `ON DELETE CASCADE` entirely.

Two migration gotchas that have already bitten:

- Adding a **`NOT NULL` column** needs `server_default=` in the migration, or
  SQLite refuses it on a populated table (a Python-side `default=` is not
  enough).
- `migrations/script.py.mako` imports `app.models.types` because autogenerate
  renders `UtcDateTime` as a fully-qualified name without importing it.

Verify portability without a live server by compiling the metadata against the
other dialects:

```python
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql, mysql
# for t in db.metadata.sorted_tables: str(CreateTable(t).compile(dialect=postgresql.dialect()))
```

## Deletion semantics

Deleting a group deletes its members; deleting a member or an event deletes the
related invitations. **Deleting an event never removes people.** Cascades are
declared both on the relationship and as `ondelete=` on the FK.

## Notes

- **Password hashing** picks scrypt when `hashlib` provides it and PBKDF2
  otherwise — some Python builds (macOS system Python on LibreSSL) lack scrypt
  and werkzeug's default would raise. `TestConfig` lowers the cost factor.
- `users.authenticate` runs a throwaway password check on an unknown email so
  response time does not reveal which accounts exist.
- **The address book is shared**: any signed-in host sees and edits every group
  and member. Only events are scoped. This was a deliberate product decision.
- Last-admin protection lives in `users._guard_last_admin`, covering demote,
  deactivate and delete.
