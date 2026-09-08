# Production readiness — engineering report

What was found, what was changed, what was verified, and what was not.

---

## A. Existing architecture

FastAPI backend, fully **synchronous** (blocking `urllib` for upstream weather,
scikit-learn for training, sync handlers run by FastAPI in a threadpool). Next.js 15
frontend. No database, no cache server, no authentication, no container definitions, no CI.

State, and who owned it:

| Concern | Location | Statefulness |
|---|---|---|
| Estimates | `backend/var/store/estimates/<id>.json` | local disk |
| Experiments | `backend/var/store/experiments.jsonl` | local disk |
| Weather/geocode cache | `backend/var/cache/<sha256>.json` | local disk |
| Rate limiting | `_RateLimiter` dict in `app/main.py` | process memory |
| Analysis artefacts | `AnalysisCache` LRU(12) in `app/api/service.py` | process memory |
| Auth / sessions | — | did not exist |

Routes: `meta.py`, `estimate.py` (including a **public** `GET /api/estimates` that listed
every estimate on the server), `analysis.py` (14 endpoints), `experiments.py`. CORS was an
explicit allowlist with `allow_credentials=False`. One `/api/health`.

Baseline: **259 backend tests, 60 frontend tests**, all passing.

The code was honest about its own limits. `store.py` said its listing had "no notion of
'mine'" and that a multi-user deployment "must put ownership in front of it"; the experiment
store said JSONL was "not appropriate for concurrent multi-user writes". This work is those
sentences being cashed in.

---

## B. Architecture changes, and why

**Phase 0 — externalise state.** Four things assumed a single process. Each is correct for
one node and fatal for three: an estimate written by replica 1 does not exist for replicas
2 and 3; a client gets three rate-limit budgets; the same weather fetch is paid for three
times; an OAuth flow started on one replica cannot finish on another. Estimates and
experiments moved to PostgreSQL, cache and ephemeral auth state to Redis.

**Phases 1–2 — accounts.** Optional by construction. The calculator never asks who you are,
and ownership is *additive*: it gates writing, not reading, because the opaque link is the
sharing mechanism and thousands may already have been sent.

**Phase 3 — scaling.** Nginx, three backends, two frontends, PgBouncer, separate liveness
and readiness, graceful draining.

**Phases 6–8 — observability, CI/CD, security hardening.**

**The solar engine is untouched.** Not the geometry, Erbs, HDKR, Faiman, PVWatts, the
financial model or the uncertainty bands. The physical chain was already pure functions
taking an input dataclass and returning a payload, so it never had an opinion about where
that payload was stored.

Two deliberate deviations from the brief:

1. **`fastapi-users` was not used.** It is async-first and would require every DB-touching
   route to become `async def`. With the work inside them still blocking, a thirty-second
   model fit would move *onto* the event loop and stall every other request on that replica.
   Mature libraries were used for everything that matters cryptographically — `argon2-cffi`,
   `PyJWT`, `Authlib`, `secrets` — and nothing is hand-rolled.
2. **Development fallbacks exist** (SQLite, an in-process Redis stand-in) so `pytest` and
   `uvicorn` run with nothing installed. They are **fail-closed**: production startup
   refuses to boot while either is in use.

---

## C. Files created

**Backend** — `app/db/{base,models,types}.py`; `app/infra/{redis_client,cache}.py`;
`app/security/{passwords,tokens,rate_limit,csrf}.py`;
`app/auth/{service,deps,oauth,routes,schemas}.py`; `app/email/{sender,templates}.py`;
`app/observability/{logging,metrics,tracing,errors}.py`; `app/api/routes/health.py`;
`alembic/` + `alembic.ini` + the initial migration; `scripts/seed.py`; `pyproject.toml`;
`Dockerfile`; `.dockerignore`; `requirements-{dev,tracing}.txt`.

**Backend tests** — `conftest.py`, `test_auth.py`, `test_oauth.py`, `test_ownership.py`,
`test_cross_instance.py`, `test_health_and_config.py`.

**Frontend** — `lib/auth.ts`; `components/auth/{SessionProvider,AuthShell,LoginForm,RegisterForm,PasswordResetForms,VerifyEmailView}.tsx`;
`components/account/AccountSettings.tsx`; `components/result/SaveToAccount.tsx`;
`app/(auth)/` (layout + five pages); `app/account/page.tsx`; `tests/auth.test.ts`;
`Dockerfile`; `.dockerignore`.

**Infrastructure** — `docker-compose.yml`, `docker-compose.prod.yml`, `Makefile`,
`.env.example`, `deploy/nginx/{nginx.conf,conf.d/helios.conf}`,
`deploy/pgbouncer/pgbouncer.ini`, `loadtest/{consumer,console}.py`,
`.github/workflows/{ci,security}.yml`.

**Docs** — `PRODUCTION_ARCHITECTURE.md`, `DEPLOYMENT.md`, `SECURITY.md`,
`BACKUP_AND_RECOVERY.md`, `LOAD_TESTING.md`, this report.

---

## D. Files modified

| File | Change |
|---|---|
| `app/config.py` | six new settings sections; `production_problems()` fail-closed check |
| `app/main.py` | Redis rate limiting, JSON logging, metrics, draining, startup validation |
| `app/estimate/store.py` | DB-backed; same public interface; ownership; projection columns |
| `app/experiments/store.py` | DB-backed; same record shape and comparability rules |
| `app/data/sources.py` | cache calls route to Redis; **key scheme unchanged** |
| `app/api/routes/estimate.py` | optional user, ownership enforcement, listing scoped |
| `app/api/routes/meta.py` | `/api/health` keeps its shape, gains dependency fields |
| `frontend/lib/{api,estimate}.ts` | same-origin base, bearer token, refresh-and-retry |
| `frontend/components/site/{Nav,ProjectsDashboard}.tsx` | account control; per-user dashboard |
| `frontend/next.config.mjs` | same-origin `/api` rewrite, standalone output, headers |
| `README.md`, `.gitignore` | corrected claims; `.env.production` now ignored |

---

## E. Database schema

```
users                                    oauth_accounts
  id              uuid       PK            id                    uuid  PK
  email           str(320)   UNIQUE        user_id               uuid  FK → users ON DELETE CASCADE
  hashed_password str        NULL          provider              str(32)
  display_name    str        NULL          provider_account_id   str(255)
  is_active       bool                     provider_email        str   NULL
  is_verified     bool                     provider_username     str   NULL
  created_at      timestamptz              created_at            timestamptz
  updated_at      timestamptz            UNIQUE (provider, provider_account_id)
  last_login_at   timestamptz  NULL

estimates                                experiments
  estimate_id     str(64)  PK  (opaque)    experiment_id   str(64) PK
  owner_id        uuid NULL FK → SET NULL  owner_id        uuid NULL FK → SET NULL
  label           str(200)                 created_at      timestamptz
  payload         JSONB                    label, model_key, model_display_name
  created_at      timestamptz              target, location_label, latitude, longitude
  updated_at      timestamptz              period_start, period_end, n_train, n_test
  location_label  str  ┐                   metrics, cv_summary, skill_scores      JSONB
  user_type       str  │ projection of     interval_metrics, manifest, warnings   JSONB
  capacity_kwp    float│ the payload, so    notes           text NULL
  annual_kwh      float│ a listing never
  payback_years   float│ deserialises MB
  confidence      str  ┘ per row
```

**Indexes** — `users.email` UNIQUE; `oauth_accounts(provider, provider_account_id)`;
`oauth_accounts.user_id`; `estimates(owner_id, updated_at)`; `estimates.created_at`;
`experiments(owner_id, created_at)`; `experiments.created_at`; `experiments.model_key`.
Standalone `owner_id` indexes were deliberately removed as redundant with the composites.

**Cascades** — `users → oauth_accounts` CASCADE (a credential link to a deleted user is
meaningless). `users → estimates/experiments` **SET NULL**: an estimate may already have
been shared by its link, and closing an account is not consent to break it for whoever
holds it.

`estimates.estimate_id` keeps the opaque token as its primary key rather than gaining a
UUID surrogate — it already has a cryptographically random public identity, and a second
one would only create a way for the two to disagree.

---

## F. API changes

**New** — `POST /api/auth/{register,login,refresh,logout,logout-all,verify-email,resend-verification,forgot-password,reset-password,change-password,claim-estimate}`;
`GET/PATCH /api/auth/me`; `GET /api/auth/providers`;
`GET /api/auth/oauth/{provider}/{authorize,callback,link}`;
`POST /api/auth/oauth/exchange`; `DELETE /api/auth/oauth/{provider}`;
`GET /api/health/{live,ready,startup}`; `GET /api/metrics`.

**Changed** —

| Endpoint | Before | After |
|---|---|---|
| `GET /api/estimates` | public; every estimate on the server | **401 without a session**; owner-scoped |
| `POST /api/estimate` | anonymous only | optional auth; sets `owner_id` when signed in; adds `owned`/`editable` |
| `GET /api/estimate/{id}` | unchanged behaviour | adds `owned`/`editable` |
| `POST /api/estimate/{id}/{rename,update}`, `DELETE` | link is the capability | link for anonymous; **owner only** once owned |
| `GET /api/health` | status + cache | same shape, plus `dependencies`, `auth`, `instance` |

**Breaking:** only `GET /api/estimates`. It was a privacy defect once accounts existed;
nothing else changed incompatibly. Anonymous estimate creation, reading and editing are
byte-compatible.

---

## G. Authentication

**Password** — Argon2id (`argon2-cffi`, OWASP low-memory profile), per-password salt,
rehash-on-login, constant work on a missing account. Ten-character minimum, no composition
rules.

**Sessions** — 15-minute HS256 JWT in the `Authorization` header, never stored anywhere and
never written to browser storage; 30-day opaque refresh token in an httpOnly, path-scoped
cookie, stored in Redis as a SHA-256 digest, **rotating on every use**. Presenting a
rotated-away token is treated as theft and revokes every session on the account.

**Registration returns no session.** A response carrying a token for a new address and none
for an existing one is an enumeration oracle that no wording hides; the client calls
`/login` immediately after, which restores the single-step experience without it.

**Verification** — cryptographically random, hashed in Redis, single-use, 24 h, with a
tombstone so an expired link reports `token_expired` rather than an indistinguishable
"invalid". Resend throttled to one per two minutes per address.

**Reset** — same shape, 1 h, single-use, and **revokes every refresh token on success**.

**OAuth** — Google and GitHub with PKCE; state, nonce and verifier in Redis, single-use,
10-minute TTL. **No silent merging**: a provider asserting an address that already has an
account is refused with `link_required` and told to link explicitly from settings. Only
provider-verified addresses are trusted. Redirects allowlisted by scheme/host/port, never
by prefix. The callback hands back a single-use ten-second code, not a token in a URL.
Unlinking the last authentication method is refused.

**Ownership** — `owner_id IS NULL` → anonymous, readable and writable by the link-holder,
exactly as before. Non-null → readable by the link-holder, writable only by the owner.

---

## H. Infrastructure

| Component | Configuration |
|---|---|
| **Nginx** | `1.27.3-bookworm` pinned; `least_conn` (request cost spans 3 orders of magnitude); `/api/*` → backends, `/*` → frontends, one origin; `proxy_read_timeout 300s` so console training is not killed; edge rate limits; JSON access log carrying the backend's `X-Request-ID` |
| **Backends** | 3 replicas, one uvicorn worker each (several workers would split the analysis cache across siblings); `--timeout-graceful-shutdown 45`; Docker `HEALTHCHECK` on **liveness only** |
| **Frontends** | 2 replicas, Next standalone output |
| **PostgreSQL** | `16.4` pinned; WAL archiving on; `idle_in_transaction_session_timeout` |
| **PgBouncer** | transaction pooling, `default_pool_size 20`; backends point at `:6432`; per-replica SQLAlchemy pool of 5+5 |
| **Redis** | `7.4.1` pinned; AOF `everysec`; `volatile-lru` — every key has a TTL, so `allkeys-lru` could evict a live refresh token and sign somebody out at random |
| **Email** | provider abstraction: SES / SendGrid / Postmark / Resend, plus `console` and `memory`; no local mail server ever |

Images: multi-stage, non-root (uid 10001), pinned base **tags** (digests deliberately left
unresolved rather than invented — the file documents how to pin them), `.dockerignore`
excluding `.env*`.

---

## I. Security

Covered in full in [`SECURITY.md`](SECURITY.md). Summary: Argon2id storage; short-lived
signed access tokens with rotating, revocable refresh tokens and reuse detection; signed
double-submit CSRF on the only two cookie-authenticated endpoints; exact-origin CORS with
`*` refused at startup; ownership enforced server-side; Redis-backed rate limiting with
`X-Forwarded-For` counted from the right-hand end; log redaction and Sentry scrubbing; no
secrets in images, bundles or the repository.

**Two findings fixed during the work:**

1. **`.gitignore` admitted `.env.production`** — it enumerated `.env`, `.env.local` and
   `.env.*.local`, missing the one file that holds the JWT signing key, the database
   password and the OAuth secrets. Now `.env*` with an explicit allowlist.
2. **Registration was an enumeration oracle** — restructured as described in §G.

**Two accepted risks, stated rather than hidden:**

1. The analysis console (`/api/analysis/*`, `/api/experiments/*`) is **not** owner-scoped.
   Deliberate — it is a shared research workbench — and `experiments.owner_id` is populated
   so scoping it later is a query change, not a migration.
2. The rate limiter **fails open** if Redis is unreachable. An instance in that state also
   fails readiness and is drained within seconds; failing closed would 429 every user during
   a Redis blip. Counted by `helios_rate_limiter_degraded_total`.

Static audit: one `text()` call in the codebase (`SELECT 1`), no string-built SQL, no
`eval`/`exec`/`pickle`/`subprocess`, no debug flags, no secrets in log calls.

---

## J. Observability

**Logs** — JSON on stdout, one object per line, carrying `request_id`, `user_id`,
`instance_id`, route, method, status and latency. Context propagates via `ContextVar`, which
is the correct primitive here precisely because sync handlers run in a threadpool. Output is
**redacted before writing** (bearer tokens, password/secret assignments, bare JWTs). The
same `request_id` appears in the Nginx log and the response header.

**Metrics** — Prometheus at `/api/metrics` (not exposed through Nginx). Request rate, error
rate and latency histograms **by route template** — never by concrete path, which would
create one time series per estimate id; DB pool occupancy; dependency up/latency; auth-event
counters for spotting credential stuffing; and two counters for otherwise-silent failures:
limiter degradation and cache fallback. `helios_analysis_jobs` is already exported by state
so dashboards do not change when that work moves to a queue.

**Traces** — OpenTelemetry, automatic instrumentation of FastAPI, SQLAlchemy, Redis and
urllib; optional, in `requirements-tracing.txt`, degrades to a no-op.

**Errors** — Sentry, optional, with a scrubber walking headers, cookies, body, query string
and frame locals.

**Alerting** — recommended rules documented in `DEPLOYMENT.md §7`; wiring belongs to the
deployment platform.

---

## K. Testing

| Suite | Tests | Focus |
|---|---|---|
| `test_solar_geometry.py` | 47 | *(pre-existing, unchanged)* |
| `test_estimate.py` | 128 | *(pre-existing; store tests adapted, +2 for anonymous-by-default)* |
| `test_evaluation.py` | 34 | *(pre-existing, unchanged)* |
| `test_quality_and_features.py` | 24 | *(pre-existing, unchanged)* |
| `test_api.py` | 28 | *(pre-existing; fixture switched to per-test isolation)* |
| `test_auth.py` | 41 | registration uniformity, sessions, rotation, verification, reset |
| `test_oauth.py` | 31 | linking rules, last-method protection, redirect allowlist |
| `test_ownership.py` | 16 | IDOR, listing scope, cascades, retention |
| `test_cross_instance.py` | 18 | shared state, cross-instance OAuth, cumulative limits |
| `test_health_and_config.py` | 21 | liveness/readiness split, fail-closed config, middleware |
| **Backend total** | **388** | baseline 259 |
| **Frontend** | **70** | baseline 60; +10 session-client tests |

**Result: 388 backend + 70 frontend passing. 0 failing. Ruff clean, mypy clean.**

Cross-instance validation builds two complete application objects against the same
infrastructure and asserts, among others, that a login budget of 10 is consumed
*cumulatively* across both — not 10 each. CI runs the whole suite a second time against real
PostgreSQL and real Redis service containers.

**Live verification** against a running server (documented in §N for what was *not*
verified):

- anonymous estimate through the real engine → Vijayawada, 2.75 kWp, 4074 kWh/yr,
  range 3478–4671, payback 9.1 y
- opaque link still reads and still edits an anonymous estimate
- `GET /api/estimates` → 401; per-user dashboards isolated
- IDOR: other user DELETE → 403, stranger rename → 403, stranger read → 200 (link works),
  claim of an owned estimate → 404
- register: byte-identical responses for new and existing addresses
- CSRF: missing header → 403, forged pair → 403, valid → 200
- refresh rotation, reuse detection → `token_revoked`, family revoked
- password reset invalidates old password and old sessions
- **two separate OS processes** sharing durable state: account created on A logs in on B; a
  JWT minted by B is accepted by A
- production startup refuses 5 unsafe defaults, accepts a configured deployment

---

## L. Deployment commands

```bash
# Development — nothing to provision
make install && make dev            # SQLite + in-process Redis stand-in
make seed                           # sample accounts; prints the password
make test                           # 388 + 70, no services needed

# Development with real services
make stack                          # Postgres, Redis, migrations, backend, frontend
make stack-down

# Production
cp .env.example .env.production     # fill in every secret
make prod                           # 3 backends, 2 frontends, Nginx, PgBouncer
# or: docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

# Database
make migrate                        # alembic upgrade head
make migration m="add widget table"
make rollback

# Quality and capacity
make lint && make typecheck
make scan                           # Trivy, fails on HIGH/CRITICAL
make load-test                      # consumer profile
make load-test-console              # console profile
```

---

## M. Environment variables

See [`.env.example`](../.env.example) — every variable with what it does and what happens if
it is wrong. No real credentials appear anywhere in the repository.

The executable version of that file is
`backend/app/config.py::Settings.production_problems`, which refuses to start a production
process holding a development default and names the consequence of each.

---

## N. Remaining work

**Implemented and verified**

State externalisation · optional accounts · email/password auth · email verification ·
password reset with session revocation · Google and GitHub OAuth with explicit linking ·
estimate ownership and dashboard · distributed rate limiting · liveness/readiness/draining ·
CSRF · structured logging · Prometheus metrics · Alembic migrations · fail-closed
configuration · 458 tests.

**Implemented, not verifiable in this environment**

Docker builds, Nginx routing, PgBouncer pooling and the full three-replica topology.
**Docker is not installed on this machine.** The Dockerfiles, compose files and Nginx/
PgBouncer configuration are written and syntax-checked (compose YAML parses, config
reviewed), and CI builds both images and smoke-tests the composed stack — but *I did not run
a container*. Treat the CI run as the first real proof.

Likewise, cross-instance behaviour over **real Redis** is proven by the test suite in-process
and by CI; locally I could only demonstrate the PostgreSQL half across two OS processes,
because Redis is not installed. The `memory://` fallback's non-sharing across processes was
demonstrated explicitly — which is exactly why production rejects it.

**Partially implemented**

- **Sentry and OpenTelemetry** — wired and configurable; never exercised against a real
  collector.
- **Backups** — WAL archiving is configured in compose; the backup script, off-host
  shipping, restore testing and stale-backup alerting are documented, not automated.
- **Alerting** — rules recommended, not wired.
- **Load testing** — both profiles written, runnable, with pass/fail thresholds. **No
  capacity numbers are published**, deliberately: figures from a laptop with SQLite, no
  Nginx and a cold cache would be quoted. Three backends and two frontends remains a
  starting point.

**Future work (architected, not built)**

- **Background analysis jobs.** Training still runs inside the request. `helios_analysis_jobs`
  is exported by state, the Nginx timeout accommodates it, and the `202 + status` transition
  is additive — but there is no Celery, no worker and no queue. This is the main remaining
  architectural weakness.
- **HA infrastructure.** `docker-compose.prod.yml` has one PostgreSQL, one Redis, one Nginx.
  Replacements are specified in `DEPLOYMENT.md §4`; none is deployed here.
- **Read-replica routing**, account self-deletion, and owner-scoping for the analysis console.

**Not claimed:** that this is running in production, that the topology has been load-tested,
or that any container has been built.
