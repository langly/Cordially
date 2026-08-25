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

Two things must be right on the **application** side for a TLS proxy deployment,
because the app does not currently auto-detect the proxy:

1. **`INVITE_BASE_URL` — set this.** Shareable invite links are built with the
   public base URL. When `INVITE_BASE_URL` is set, links are correct; when it is
   unset the app falls back to Flask's own URL building, which behind a
   TLS-terminating proxy can emit `http://` or the internal host. Set it to the
   public origin:

   ```bash
   export INVITE_BASE_URL="https://party.example.com"
   ```

2. **Secure cookies — recommended, not yet wired.** The session cookie that
   holds the login is not currently marked `Secure`/`HttpOnly`/`SameSite`. Over
   HTTPS you want it marked `Secure` so it is never sent in cleartext. This
   needs a small `app/config.py` change (`SESSION_COOKIE_SECURE = True`, etc.)
   and, to make `request.scheme` reflect the `X-Forwarded-Proto` header,
   Werkzeug's `ProxyFix` middleware in `wsgi.py`. Ask and I will add both — they
   are a few lines. Until then, setting `INVITE_BASE_URL` covers the
   externally-visible URLs, and the audit IP works because it reads
   `X-Forwarded-For` directly.

The public invitation cards live under `/i/<token>` and are intentionally
unauthenticated — guests RSVP without logging in. NGINX should **not** put
`/i/` behind any auth (basic auth, IP allowlists); it must stay publicly
reachable.

---

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
Environment="LOG_DIR=/var/log/events"
# Create the socket directory with the right owner.
RuntimeDirectory=events
ExecStart=/srv/events/.venv/bin/gunicorn --workers 3 \
          --bind unix:/run/events/gunicorn.sock wsgi:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`RuntimeDirectory=events` makes systemd create and own `/run/events`, where the
socket lives. Add the `www-data` (NGINX) user to the `events` group, or set the
socket's permissions, so NGINX can connect to it.

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
