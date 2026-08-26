# Cordially

Cordially is a party / event manager built on Flask + SQLAlchemy. You create **families and
groups**, add **members** to them, then invite whole families to an **event**
and track RSVPs per person with a per-family rollup.

Each invited group gets its own **shareable invitation card** at a secret URL.
The group passes the link around amongst themselves, and whoever opens it first
answers for everyone — one accept means the whole family is coming.

Runs on SQLite out of the box; moving to PostgreSQL or MySQL is a one-line
config change (see [Changing the database](#changing-the-database)).

## Logging

Two streams, one rotating file (`logs/events.log`, 10 MB × 5 by default), also
mirrored to stdout so a platform can capture it:

- **`events.audit`** — a security trail of who did what: sign-ins and failures,
  user create/modify/delete, co-host and ownership changes. Each line is
  greppable `key=value`, recording actor and client IP:

  ```
  events.audit login.success actor=admin@example.com ip=203.0.113.7 admin=True
  events.audit user.create actor=admin@example.com ip=… target=host@example.com admin=False
  events.audit event.cohost.add actor=host@example.com ip=… event=2 target=other@example.com
  ```

  Isolate it with `grep events.audit logs/events.log`.

- **`events.request`** — one line per request (method, path, status, timing,
  user) plus any unhandled error with a traceback.

Configure via env: `LOG_LEVEL`, `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUPS`. A
rotating file needs a persistent writable disk; on an ephemeral container host,
rely on the stdout mirror and set `LOG_DIR` to a mounted volume if you want the
file too.

## Startup guard

`app/startup.py` refuses to boot in production on insecure config — a default
`SECRET_KEY` (forgeable sessions) or a test-grade password hash factor
(`FLASK_ENV=testing` leaking in). Set `FLASK_DEBUG=1` for local development and
these downgrade to a warning instead. This is why a real deploy **must** set
`SECRET_KEY`.

## Accounts and access

Hosts sign in; **guests never do** — RSVPs happen through the unauthenticated
invite token, which is the whole point of the link.

| Role | Can do |
|---|---|
| Guest (no account) | open `/i/<token>`, RSVP for their group |
| Host | create events, manage the events they own or co-host, edit the shared address book |
| Co-host | everything the owner can do **for that event** |
| Site admin | all of the above on every event, plus add/modify/delete users |

A host owns any number of events and can add co-hosts to each. Co-hosts
currently have the owner's full powers on that event — but not site admin, and
not access to the owner's other events. Ownership can be transferred.

Families and groups are a **shared address book**: every signed-in host sees and
edits all of them. Events are the private part.

Bootstrap the first login, then claim any events created before accounts existed:

```bash
flask create-admin                       # prompts for email + password
flask claim-events --email you@example.com
```

Authorization is **default-deny**: `app/__init__.py` requires a session for every
endpoint except those named in `PUBLIC_ENDPOINTS` / `PUBLIC_BLUEPRINTS`, so a new
route is protected unless it is deliberately exempted. A test walks the URL map
and fails if any route answers anonymously.

Event access is decided in one place, `Event.is_managed_by()`, reached through
`authz.event_or_403`. Unknown event → 404, someone else's → 403.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env          # optional; defaults work as-is
export FLASK_APP=wsgi

.venv/bin/flask db upgrade    # create the schema
.venv/bin/flask create-admin  # your first login
.venv/bin/flask seed          # optional demo data
.venv/bin/flask run
```

Then open http://127.0.0.1:5000.

## The data model

```
Group  (a family, household, group of friends, company)
  ├── Member       many members per group; group_id is nullable for solo guests
  │     └── Invitation   one per (member, event), carries the RSVP
  │           └── Event
  └── InviteLink   one per (group, event) — the shareable card URL
```

| Model | Notable fields |
|---|---|
| `Group` | `name` (unique), `kind` (family/group/household/company), contact details, `notes` |
| `Member` | `first_name`, `last_name`, `group_id`, contact details, `is_child`, `age`, `dietary_notes` |
| `User` | `email` (unique, lowercased), `password_hash`, `is_admin`, `is_active` |
| `Event` | `owner_id`, co-hosts via `event_hosts`, `name`, `starts_at`, `ends_at`, `location`, `capacity`, `description`, `card_theme`, `card_layout` |
| `Invitation` | `rsvp` (pending/yes/no/maybe), `responded_at`, `plus_ones`, `table_assignment` |
| `InviteLink` | `token`, `restricted`, `adults_attending`, `children_attending`, `revoked`, `responded_by`, `response_note`, `view_count` |

Deletion behaviour: deleting a group deletes its members; deleting a member or
an event deletes the related invitations, and nothing else. Deleting an event
never removes people.

## Invitation cards

Inviting a group from the event page mints a link like `/i/<43-char-token>`.
Send that one URL to the family; anyone holding it sees a printed-card style
invitation with the event details, who it's addressed to, and the RSVP form.

**One reply covers the group.** Whoever answers sets the RSVP for every member,
which is the behaviour a shared family link needs — no per-person logins. The
card collects a free-text note plus dietary needs for the host.

### Themes and layouts

Every event picks how its invitation cards look, along two independent axes —
any theme works with any layout, so there are 32 combinations.

**Themes** (palette + typeface), shown in a grid where each swatch is a
miniature of the real card in its own colours and font:

| Formal | | Cheerful | |
|---|---|---|---|
| **Classic Ivory** | ivory and gold, the traditional choice | **Garden Party** | fresh greens, daytime and outdoors |
| **Midnight** | black tie, charcoal with antique gold | **Sunset** | warm coral and peach |
| **Bloom** | soft rose, weddings and showers | **Confetti** | bright and playful, birthdays |
| **Nordic** | clean and quiet, no ornament | **After Dark** | bold on black, late nights |

**Layouts**: Centred (ornament, everything centred), Banner (colour band across
the top), Split (details one side, RSVP the other), Minimal (left aligned and
compact).

Pick them when creating the event, or change them later under *Invitation card
→ Change the theme or layout* on the event page. **Preview selection** opens the
card in a new tab with sample guests, using whichever swatches are currently
selected — it submits the picker as a GET, so you can try a theme before saving
it. A ribbon names the theme and says whether it is the saved one. Previewing
creates nothing.

```
/events/<id>/preview                                    # the saved look
/events/<id>/preview?card_theme=neon&card_layout=split  # what the button sends
/events/<id>/preview?theme=neon&layout=split            # short form
```

Adding a theme is one entry in `app/themes.py` plus one `[data-theme="..."]`
block of custom properties in `invite.css` — no migration, since the choice is
stored as a plain string. Unknown names fall back to the default rather than
failing, so a renamed theme never breaks a live invitation; tests assert every
catalogued theme has a matching CSS block.

Note that invitation cards ignore the viewer's dark-mode preference. A card is
a designed artefact — a host who picks Garden Party should get it on every
screen — so themes are explicit, with Midnight and After Dark available when a
dark card is what you want.

### Restricted vs open invitations

When you add a group to an event there's a **Restricted** checkbox, on by
default. It decides what the group's card asks for:

| | Restricted (default) | Open |
|---|---|---|
| Who's invited | only the named members | the group plus anyone they bring |
| The card asks | accept/decline, per-person adjustments | accept/decline **plus how many adults and children** |
| Names needed | yes | no |
| Counted as | each member, using their `is_child` flag | the numbers the group reported |

Open invitations suit a group where you don't know the roster — "Climbing Crew,
bring whoever". The reported numbers **replace** that group's named members in
the totals, so 6 adults + 2 children counts as 8 regardless of how many people
are listed. A group that accepts without filling the numbers in falls back to
being counted by name, so nobody is ever silently dropped from the total.

The event page shows an **adults / children** tile alongside the attending
count, and marks open groups with an `open` pill plus the numbers they gave.
Switching a group back to restricted discards the numbers. Explicit zeros are a
real answer ("none of us can make it"), distinct from not having answered.

Details worth knowing:

- **The token is the credential.** There's no login, so it's generated with
  `secrets.token_urlsafe(32)` (~256 bits). The card is served `noindex` and
  `no-referrer` so it stays out of search results and doesn't leak the URL to
  sites linked from it.
- **A card never shows another group's guests** — only the event and the one
  group it's addressed to. There's a test asserting exactly that.
- **Links are stable and idempotent.** Re-inviting a group returns the same URL,
  so an already-shared link never breaks.
- **Revoke** kills a link (`410 Gone`, and responses are refused); **new link**
  rotates the token so a previously shared URL stops working (`404`).
- **People added to a group after the link went out** are picked up on the next
  reply, rather than being silently left pending.
- Hosts see whether each link has been opened, who answered, and any note left.

Set `INVITE_BASE_URL` in production so generated links point at your public
host rather than whatever the app sees behind a proxy.

## Layout

```
app/
  config.py        all settings, incl. DATABASE_URL
  extensions.py    db + migrate instances, constraint naming convention
  models/          Group, Member, Event, Invitation, UtcDateTime
  services/        every database query lives here
  themes.py        theme + layout catalogue (palettes, fonts, swatches)
  preview_data.py  sample guests for card previews
  api/             JSON API blueprint  (/api/...)
  invite/          public invitation cards  (/i/<token>) -- unauthenticated
  web/             server-rendered UI blueprint (host-facing)
  templates/, static/
migrations/        Alembic revisions
tests/
```

Views never touch the ORM directly — they call the service layer. That
indirection is what keeps a storage change contained to one package.

## Changing the database

Set `DATABASE_URL` and install the driver. No code changes:

```bash
# PostgreSQL
pip install "psycopg[binary]"
export DATABASE_URL="postgresql+psycopg://events:secret@localhost:5432/events"

# MySQL / MariaDB
pip install PyMySQL
export DATABASE_URL="mysql+pymysql://events:secret@localhost:3306/events?charset=utf8mb4"

flask db upgrade
flask db-info      # confirm which backend you're on
```

The schema is written to stay portable, deliberately:

- **No backend-specific column types.** Every `String` has an explicit length
  (MySQL requires it), and enum-like columns are `VARCHAR` + `CHECK` rather
  than native `ENUM` types, which differ per engine and are painful to alter.
- **`UtcDateTime` everywhere** (`app/models/types.py`). SQLite hands back naive
  datetimes while PostgreSQL returns aware ones; this normalises both to
  UTC-aware so behaviour doesn't shift under you. Covered by a test.
- **Timestamps generated in Python**, not by database `now()` functions, which
  every engine spells differently.
- **Named constraints** via a naming convention, so Alembic can autogenerate
  reliable migrations and SQLite's batch mode can find constraints to drop.
- **SQLite pragmas** (`foreign_keys=ON`, WAL) are applied behind a driver
  check, so they're inert elsewhere. Without the first, SQLite ignores
  `ON DELETE CASCADE` entirely.
- **`render_as_batch=True`** so migrations that alter or drop columns work on
  SQLite too.

## API

| Method | Path | Notes |
|---|---|---|
| `GET/POST` | `/api/groups` | `?q=` search, `?include=members` |
| `GET/PATCH/DELETE` | `/api/groups/<id>` | detail includes members |
| `GET/POST` | `/api/members` | `?group_id=`, `?q=` |
| `GET/PATCH/DELETE` | `/api/members/<id>` | `PATCH group_id` moves someone |
| `GET/POST` | `/api/events` | scoped to what you may manage |
| `GET/POST` | `/api/users` | site admins only |
| `PATCH/DELETE` | `/api/users/<id>` | site admins only |
| `POST/DELETE` | `/api/events/<id>/hosts[/<user_id>]` | add / remove a co-host |
| `GET/PATCH/DELETE` | `/api/events/<id>` | includes RSVP counts |
| `GET` | `/api/events/<id>/guests` | guest list, families kept together |
| `POST` | `/api/events/<id>/invite` | body: `member_id` **or** `group_id` |
| `POST` | `/api/events/<id>/rsvp` | body: `rsvp` + `member_id` or `group_id` |
| `GET/POST` | `/api/events/<id>/links` | list / mint links; `restricted` in body |
| `PATCH` | `/api/events/<id>/links/<group_id>` | toggle `restricted`, set head count |
| `DELETE` | `/api/events/<id>/links/<group_id>` | revoke a link |
| `POST` | `/api/events/<id>/links/<group_id>/rotate` | issue a new token |

Public, no auth (token is the credential):

| Method | Path | Notes |
|---|---|---|
| `GET` | `/i/<token>` | the invitation card |
| `POST` | `/i/<token>/respond` | RSVP for the whole group |
| `POST` | `/i/<token>/member/<id>` | adjust one person |

Inviting is idempotent — re-inviting a family adds only the people who weren't
already on the list.

```bash
curl -X POST localhost:5000/api/groups -H 'Content-Type: application/json' \
     -d '{"name": "The Smith Family"}'

curl -X POST localhost:5000/api/events/1/invite -H 'Content-Type: application/json' \
     -d '{"group_id": 1}'

curl -X POST localhost:5000/api/events/1/rsvp -H 'Content-Type: application/json' \
     -d '{"group_id": 1, "rsvp": "yes"}'
```

## Commands

| Command | Purpose |
|---|---|
| `flask db upgrade` | apply migrations |
| `flask db migrate -m "..."` | generate a migration after model changes |
| `flask seed [--force]` | demo data: 3 groups, 7 members, 1 event |
| `flask create-admin` | create a site administrator (prompts for a password) |
| `flask claim-events --email …` | give unowned events to a user |
| `flask db-info` | show the active dialect, driver and tables |
| `flask init-db` | `create_all()` for a throwaway database |
| `flask shell` | preloaded with `db` and all models |

## Tests

```bash
.venv/bin/python -m pytest
```

152 tests, running against an in-memory SQLite database — including every
theme and layout rendering a real card, and a sweep asserting no route answers
anonymously.

Password hashing uses scrypt where the Python build provides it and PBKDF2
otherwise (`PASSWORD_HASH_METHOD`); tests drop the cost factor so the suite
stays fast.
