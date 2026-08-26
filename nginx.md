# Serving the app behind NGINX

NGINX does not run Python. The app is a WSGI application served by an
application server (**gunicorn**); NGINX sits in front of it as a reverse proxy
that terminates TLS, serves static files, and forwards everything else.

```
          HTTPS                     HTTP (localhost / unix socket)
client  ───────▶  NGINX  ─────────────────────────────▶  gunicorn ─▶  Flask (wsgi:app)
                   │
                   └── serves /static/* directly from disk
```

Do **not** expose `flask run` (the development server) to the internet — it is
single-threaded and unhardened. NGINX talks to gunicorn.

---

## 1. Run the app with gunicorn

gunicorn is not yet in `requirements.txt`; install it into the app's
environment. The WSGI entry point already exists as `wsgi:app`.

```bash
.venv/bin/pip install gunicorn

# Bind to a unix socket (recommended — no TCP port exposed) …
.venv/bin/gunicorn --workers 3 --bind unix:/run/events/gunicorn.sock wsgi:app

# … or to a loopback TCP port if you prefer:
.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 wsgi:app
```

gunicorn needs the same environment the app always needs — in particular
`SECRET_KEY` (the app refuses to boot without a real one) and `DATABASE_URL`.
A `--workers` count of `2 × CPU cores + 1` is the usual starting point; remember
each worker opens its own database connection pool (see `PostgreSQL.md`).

A systemd unit to keep it running is in [§6](#6-systemd-unit-for-gunicorn).

---

## 2. Minimal NGINX server block

TLS termination, static files served directly, everything else proxied:

```nginx
server {
    listen 443 ssl http2;
    server_name party.example.com;

    ssl_certificate     /etc/letsencrypt/live/party.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/party.example.com/privkey.pem;

    # Invitation cards can carry an RSVP note; keep a sane upload ceiling.
    client_max_body_size 2m;

    # Serve static assets straight from disk — never proxy these to Python.
    # Path is the app's static folder; adjust to your deploy location.
    location /static/ {
        alias /srv/events/app/static/;
        access_log off;
        expires 30d;
        add_header Cache-Control "public";
    }

    location / {
        proxy_pass http://events_upstream;

        # These headers are what let the app see the real client and scheme
        # rather than NGINX's localhost/http. The app reads X-Forwarded-For for
        # its audit log, and X-Forwarded-Proto matters for correct https links.
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host  $host;

        proxy_redirect off;
        proxy_read_timeout 60s;
    }
}

# Redirect plain HTTP to HTTPS.
server {
    listen 80;
    server_name party.example.com;
    return 301 https://$host$request_uri;
}
```

Define the upstream once, matching however you bound gunicorn:

```nginx
# unix socket (recommended)
upstream events_upstream { server unix:/run/events/gunicorn.sock; }

# — or — loopback TCP
# upstream events_upstream { server 127.0.0.1:8000; }
```

`X-Forwarded-For` feeds the audit trail's client-IP column
(`events.audit login.success … ip=203.0.113.7`), so those `proxy_set_header`
lines are not optional if you care about the audit log being accurate.

---

## 3. App-side settings this proxy assumes

1. **`PROXY_FIX_HOPS=1` — set this behind NGINX.** It tells the app one trusted
   proxy sits in front, enabling it to honour `X-Forwarded-Proto/Host/For`
   (and `X-Forwarded-Prefix`, see [§3a](#3a-serving-under-a-sub-path-eg-e)).
   Without it the app ignores those headers by design, so it would build
   `http://` links and log NGINX's IP instead of the client's. This is the
   single most important app-side setting behind a proxy.

2. **`INVITE_BASE_URL` — optional once `PROXY_FIX_HOPS` is set.** With the proxy
   trusted, shareable invite links are already built with the correct
   `https://host[/prefix]`. Set `INVITE_BASE_URL` only to pin a specific public
   origin (e.g. a canonical domain different from the forwarded host):

   ```bash
   export INVITE_BASE_URL="https://party.example.com"
   ```

3. **Secure cookies — optional hardening, not yet wired.** The session cookie is
   not marked `Secure`/`HttpOnly`/`SameSite`. Over HTTPS you may want `Secure`
   so it is never sent in cleartext; that is a small `app/config.py` change
   (`SESSION_COOKIE_SECURE = True`, etc.). `PROXY_FIX_HOPS` already makes
   `request.scheme` reflect `X-Forwarded-Proto`, so the groundwork is there.

The public invitation cards live under `/i/<token>` and are intentionally
unauthenticated — guests RSVP without logging in. NGINX should **not** put
`/i/` behind any auth (basic auth, IP allowlists); it must stay publicly
reachable.

---

## 3a. Serving under a sub-path (e.g. `/e`)

The app is **mount-point agnostic**: it runs at `/` by default, but can live
under any prefix — `/e`, `/cordially`, `/apps/rsvp`, any depth — with only
config, no code changes. Two pieces cooperate:

1. **NGINX strips the prefix and announces it.** Use matching trailing slashes
   so the prefix is removed before the app sees the path, and send it as
   `X-Forwarded-Prefix`:

   ```nginx
   location = /e { return 301 /e/; }        # bare /e → /e/

   location /e/static/ {                      # most-specific: served from disk
       alias /var/www/cordially/app/static/;
       access_log off; expires 30d;
       add_header Cache-Control "public";
   }

   location /e/ {
       proxy_pass http://events_upstream/;    # trailing slash strips /e/
       proxy_set_header X-Forwarded-Prefix /e;   # ← the prefix (no trailing slash)
       proxy_set_header Host              $host;
       proxy_set_header X-Real-IP         $remote_addr;
       proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_set_header X-Forwarded-Host  $host;
   }
   ```

   The trailing slash on **both** `location /e/` and `proxy_pass …/` is what
   rewrites `/e/events` → `/events`. Swap `/e` for whatever prefix you want.

2. **The app trusts the header** — set `PROXY_FIX_HOPS` to the number of
   proxies (1 for a single NGINX). This enables `ProxyFix`, which turns
   `X-Forwarded-Prefix` into the app's mount point so every generated URL —
   navigation, redirects, static assets, the post-login bounce, invite links —
   carries the prefix automatically:

   ```
   PROXY_FIX_HOPS=1
   ```

   Left at its default of `0`, the app ignores all `X-Forwarded-*` headers (a
   directly-exposed app must not trust spoofable headers). So this is required,
   not optional, behind a proxy — and it also gives you correct `https` links
   and real client IPs in the audit log.

Nothing else changes: the same image serves at root, at `/e`, or on a dedicated
subdomain, chosen entirely by `PROXY_FIX_HOPS` + what NGINX forwards. A subdomain
at `/` (no prefix) is the simplest of all — set `PROXY_FIX_HOPS=1` for correct
scheme/IP and skip the prefix machinery.

## 4. Recommended hardening

Optional but worth adding on a public deployment.

### Modern TLS

```nginx
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### Rate-limit the login endpoint

The app already returns an identical response for unknown-email and
wrong-password (no user enumeration) and pays a constant password-hash cost, but
a network-level throttle on `/login` blunts brute-force attempts. Declare a zone
in the `http { }` block:

```nginx
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
```

and apply it to just the login POST inside the `server { }` block:

```nginx
    location = /login {
        limit_req zone=login burst=5 nodelay;
        proxy_pass http://events_upstream;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
```

### Compression and security headers

```nginx
    gzip on;
    gzip_types text/css application/javascript image/svg+xml;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy no-referrer-when-downgrade always;
```

---

## 5. Certificates

Obtain and auto-renew a certificate with Certbot:

```bash
sudo certbot --nginx -d party.example.com
```

Certbot edits the `listen 443 ssl` block and installs a renewal timer. If you
manage TLS with your own or a provider's certificate, point `ssl_certificate` /
`ssl_certificate_key` at those files instead.

---

## 6. systemd unit for gunicorn

`/etc/systemd/system/events.service`:

```ini
[Unit]
Description=Events (gunicorn)
After=network.target

[Service]
User=events
Group=www-data
WorkingDirectory=/srv/events
Environment="SECRET_KEY=your-real-random-secret"
Environment="DATABASE_URL=postgresql+psycopg://events_app:pw@localhost:5432/events"
Environment="INVITE_BASE_URL=https://party.example.com"
Environment="PROXY_FIX_HOPS=1"
Environment="LOG_DIR=/var/log/events"
# systemd creates and owns both directories (service User/Group, before start):
#   RuntimeDirectory -> /run/events   (the gunicorn socket)
#   LogsDirectory    -> /var/log/events (events.log)
# This is why the app never needs permission to mkdir under /var/log itself.
RuntimeDirectory=events
LogsDirectory=events
ExecStart=/srv/events/.venv/bin/gunicorn --workers 3 \
          --bind unix:/run/events/gunicorn.sock wsgi:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`RuntimeDirectory=events` and `LogsDirectory=events` make systemd create and
own `/run/events` (the socket) and `/var/log/events` (the log file) before the
service starts, both with the service's `User`/`Group`. This is the clean fix
for a *permission denied* on the log directory: the app should not be creating
directories under `/var/log` itself, and with `LogsDirectory` it never tries to
— systemd has already made a writable one. The directories persist across
reboots and are recreated if deleted.

Add the `www-data` (NGINX) user to the `events` group, or set the socket's
permissions, so NGINX can connect to the socket.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now events
sudo nginx -t && sudo systemctl reload nginx
```

---

## Checklist

```
[ ] gunicorn installed and serving wsgi:app on a socket/port
[ ] SECRET_KEY, DATABASE_URL, INVITE_BASE_URL set in gunicorn's environment
[ ] NGINX upstream points at the same socket/port
[ ] /static/ served by NGINX via alias to app/static/
[ ] proxy_set_header: Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto
[ ] TLS certificate installed; port 80 redirects to 443
[ ] /i/<token> reachable without authentication (do not lock it down)
[ ] nginx -t passes, service reloaded
[ ] (recommended) rate limit on /login, HSTS, secure-cookie app settings
```

The only app-specific requirements are the forwarded headers, serving
`/static/` from disk, keeping `/i/` public, and setting `INVITE_BASE_URL` so
generated invite links carry the public HTTPS origin. Everything else is a
standard gunicorn-behind-NGINX setup.
