# Clinic Booking API

A clinic appointment API plus a web page (see available slots, book one,
confirmation view), built to the exact contract of
<https://koyaacademy.com/assessment-api>.

Django 6 + Django REST Framework. PostgreSQL-ready (via `DATABASE_URL`),
falls back to SQLite for local development.

## Run it

```powershell
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py runserver
```

- Web page: <http://127.0.0.1:8000/>
- API explorer (Swagger UI): <http://127.0.0.1:8000/api> — lists every
  endpoint with the exact contract, "Authorize" stores the key, and
  "Try it out" sends real requests. The main page also has an "API key"
  dialog (top-right) that stores a key in the browser, taking priority
  over the server default.
- API base: <http://127.0.0.1:8000>
- API key: `clinic-demo-key` (override with `CLINIC_API_KEY`, see
  `.env.example`); every API request must send it as `X-API-Key` — the
  page does this automatically, and bare URLs in the address bar (no
  header) intentionally get `401 {"error": ...}`.

## Deploy (PostgreSQL)

1. Create a Postgres database.
2. Set env vars on the host: `DATABASE_URL=postgresql://...`,
   `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS` (include
   your domain), `CLINIC_API_KEY`.
3. Install deps, then `python manage.py migrate`.
4. Serve via any WSGI server:

```bash
gunicorn clinic.wsgi:application --bind 0.0.0.0:8000

# Windows-local: venv\Scripts\waitress-serve --listen=0.0.0.0:8000 clinic.wsgi:application
```

### On Render (one-click-ish)

`render.yaml` at the repo root is a render Blueprint that defines the web
service and a managed PostgreSQL database for you:

1. Push this repo to GitHub/GitLab.
2. Render dashboard → **New → Blueprint** → pick the repo. Render reads
   `render.yaml`, creates the service and the `clinic-db` Postgres, and
   injects `DATABASE_URL` automatically (secret key is generated).
3. You'll be prompted for `CLINIC_API_KEY` (`sync: false`) — set the value
   your clients/graders will send in `X-API-Key`.
4. On each deploy, `scripts/deploy/build.sh` runs: installs deps, verifies
   `DATABASE_URL`, runs `collectstatic` + `migrate`, then
   `scripts/deploy/start.sh` boots gunicorn bound to Render's `$PORT`.

No blueprint? Create the service manually with
**Build Command** `bash scripts/deploy/build.sh` and
**Start Command** `bash scripts/deploy/start.sh`, then add the env vars
from `.env.example` (plus `DATABASE_URL` from your attached Postgres).

Note: Render's free Postgres tier expires after 30 days — upgrade the
database plan for a persistent clinic deployment.

Static assets for the page are served through whitenoise; no
`collectstatic` step is needed. Behind a TLS-terminating proxy the app
already honors `X-Forwarded-Proto`.

## Hosting the page separately from the API

The frontend (`frontend/`) is plain HTML/CSS/JS with zero build step and
may be hosted anywhere (same server, GitHub Pages, S3, Netlify...).

- Served by the API's server: works out of the box — the server injects
  the key and uses same-origin requests.
- Hosted elsewhere: copy `frontend/` to your static host and set both
  fields in `frontend/static/booking/config.js`:
  `apiBase` (the deployed API's origin, no trailing slash) and `apiKey`
  (the server's `CLINIC_API_KEY` value).

Cross-origin browser calls are allowed by CORS (preflights accept the
`X-API-Key` and `Idempotency-Key` headers). To lock CORS down in
production, set `CORS_ALLOW_ALL_ORIGINS=0` and
`CORS_ALLOWED_ORIGINS=https://your-front-end-host,https://other-host`.

## API (contract summary)

All requests JSON. All errors: `{"error": "<message>"}`. All require the
`X-API-Key` header (missing/wrong → `401`).

| Endpoint | Method | Level | Behaviour |
|---|---|---|---|
| `/reset` | POST | 1 | Deletes all bookings (and idempotency + rate-limit state) and replaces all slots. Body: `{"slots": [...]}` |
| `/slots` | GET | 1 | All slots, earliest `start` first, `available: false` while a slot has a confirmed booking. `?provider=` filters exactly. |
| `/bookings` | POST | 1–5 | Books a slot → `201`. Validation `400` (missing/empty fields, invalid email, slot already started), unknown slot `404`, already-booked `409`, key-replay mismatch `422`, spam-blocked `429` (+`Retry-After`). |
| `/bookings` | GET | 4 | One person's bookings (email match ignores case), oldest first, cursor pagination (`limit` 1–50, default 10; anything else `400`); last page has `next_cursor: null`. |
| `/bookings/{id}` | GET | 1 | Look up a booking; unknown → `404`. |
| `/bookings/{id}` | DELETE | 3 | Cancel → `200` with `status: "cancelled"`, frees the slot; already cancelled → `409`. |

**Level semantics:**

- **L2** — names/emails are trimmed; emails stored lowercase. Missing or
  empty `slot_id`/`name`/`email` → `400`; malformed email → `400`; slot
  that already started → `400`.
- **L3** — at most one confirmed booking per slot, enforced both by a
  row-lock + re-check inside a transaction and by a partial unique index
  (`slot` restricted to `status='confirmed'`), so two concurrent requests
  can never both win; the loser gets `409`. Cancelling frees the slot.
- **L4** — optional `Idempotency-Key` header: same key + same body replays
  the stored response verbatim (no second booking, even concurrently);
  same key + different body → `422`. Listing supports keyset cursor
  pagination (stable under concurrent inserts).
- **L5** — per-email rolling 60 s window for `POST /bookings`; every
  attempt of any outcome counts. The 6th gets `429` with a whole-seconds
  `Retry-After`; other emails are unaffected. Idempotent replays do not
  consume attempt quota.

## Tests & verification

```powershell
venv\Scripts\python manage.py test          # 26 contract tests (incl. thread races)
venv\Scripts\python scripts\smoke_live.py   # 62+ live HTTP checks vs running server
venv\Scripts\python manage.py seed_pagination   # fixture for paging/demo
```

`smoke_live.py` accepts `[base_url] [api_key]` arguments so it can verify
a deployed instance too:

```bash
python scripts/smoke_live.py https://your-host.example.com your_api_key
```

## Project layout

```
clinic/          settings (env-driven), urls
booking/         models, serializers, middleware, views, tests
  management/commands/seed_pagination.py
frontend/        templates + static (vanilla JS single page)
scripts/         smoke_live.py — end-to-end contract verification
```
