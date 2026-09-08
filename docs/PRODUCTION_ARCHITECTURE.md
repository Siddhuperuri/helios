# Production architecture

How Helios went from one process to a fleet, and what had to change to make that safe.

The solar engine did not change. Not the geometry, not Erbs, not HDKR, not Faiman, not
PVWatts, not the financial model, not the uncertainty bands. That was the constraint the
rest of this work had to fit around, and it held: the physical chain was already a set of
pure functions taking an input dataclass and returning a payload, so it never had an
opinion about where that payload was stored or who it belonged to.

What changed is everything around it.

---

## 1. The problem, stated precisely

The previous release was correct for exactly one process. Four things assumed it:

| Assumption | Where | What breaks with three replicas |
|---|---|---|
| Estimates are files on this disk | `app/estimate/store.py` | An estimate written by replica 1 does not exist for replicas 2 and 3 |
| Experiments are a JSONL file | `app/experiments/store.py` | Concurrent appends from three processes; each sees a different history |
| The rate limiter counts in a dict | `app/main.py` | A client gets three budgets and can evade the limit by being routed elsewhere |
| The weather cache is a directory | `app/data/sources.py` | The same upstream fetch is paid for three times and shared with nobody |

None of those are bugs. Each was a correct decision for a single-node deployment, and the
code said so — the old `store.py` docstring noted that its listing had no notion of "mine"
and that a multi-user deployment "must put ownership in front of it before exposing it".
This work is that sentence being cashed in.

Adding accounts made all four fatal rather than merely limiting, because an account implies
that state follows the person rather than the process.

---

## 2. Target topology

```
                         ┌───────────────────────┐
                         │       DNS / CDN       │
                         └───────────┬───────────┘
                                     │
                         ┌───────────▼───────────┐
                         │   Nginx (TLS, LB)     │
                         │   least_conn          │
                         │   readiness-routed    │
                         └───────────┬───────────┘
                    /api/*  ┌────────┴────────┐  /*
                            │                 │
        ┌───────────────────▼──┐         ┌────▼──────────────────┐
        │ backend1  backend2   │         │ frontend1  frontend2  │
        │ backend3             │         │                       │
        │ FastAPI · stateless  │         │ Next.js · stateless   │
        └───────────┬──────────┘         └───────────────────────┘
                    │
        ┌───────────┴───────────┬────────────────────┐
        │                       │                    │
 ┌──────▼──────┐        ┌───────▼───────┐    ┌───────▼───────┐
 │  PgBouncer  │        │     Redis     │    │ Email provider│
 │ transaction │        │  cache, rate  │    │  SES/Postmark │
 │   pooling   │        │  limits, auth │    │  /SendGrid/…  │
 └──────┬──────┘        └───────────────┘    └───────────────┘
        │
 ┌──────▼─────────────────────┐
 │ PostgreSQL                 │
 │ + WAL archiving → PITR     │
 │ + read replica (HA tier)   │
 └────────────────────────────┘

           Observability
 ┌─────────────────────────────────────────┐
 │ Logs    → JSON on stdout → Loki/ELK     │
 │ Metrics → /api/metrics → Prometheus     │
 │ Traces  → OTLP → Tempo/Jaeger           │
 │ Errors  → Sentry                        │
 └─────────────────────────────────────────┘
```

Three backends and two frontends are a **starting point, not a derived answer**. See
[`LOAD_TESTING.md`](LOAD_TESTING.md) for how to replace them with measured ones. The counts
live in `docker-compose.prod.yml` and nothing in the application knows them.

---

## 3. Where state lives now

The rule: **a backend container may be destroyed at any moment without losing anything.**

| State | Before | Now | Why there |
|---|---|---|---|
| Users, OAuth links | — | PostgreSQL | Durable, relational, needs constraints |
| Estimates | local JSON files | PostgreSQL | Must be readable by every replica |
| Experiments | local JSONL | PostgreSQL | Same, plus concurrent writes |
| Upstream weather cache | local files | Redis (30-day TTL) | Shared; one fetch serves the fleet |
| Rate-limit counters | process dict | Redis | One budget per client, fleet-wide |
| Refresh tokens | — | Redis (hashed) | Must be revocable from any replica |
| Email / reset tokens | — | Redis (hashed) | A link is clicked wherever the LB sends it |
| OAuth state, nonce, PKCE | — | Redis | Authorize and callback land on different replicas |
| Access tokens | — | nowhere | Signed JWTs; verified without a round trip |
| Analysis artefacts | process LRU(12) | **still a process LRU** | See below |
| Interview drafts | `sessionStorage` | **unchanged** | Per-device by design |

### The one thing still in process memory

`app/api/service.py` holds up to twelve completed analyses — raw DataFrames, fitted
estimators, feature matrices — so that the console's dozen follow-up requests do not re-run
a thirty-second training job.

That is deliberate, and it is not the same class of problem as the four above:

- **Nothing durable is lost.** Every analysis is written to the experiment store in
  PostgreSQL as it completes. A restart costs a re-run, not a record.
- **Serialising it would be worse.** A fitted scikit-learn ensemble plus several years of
  hourly features is tens of megabytes. Pushing that through Redis on every follow-up
  request would be slower than recomputing it.
- **The consequence is a cache miss, not an error.** A follow-up landing on another replica
  re-runs the analysis. With `least_conn` and a handful of console users, that is
  occasional rather than routine.

The honest statement: **the analysis console is the one surface where horizontal scaling
degrades an experience rather than improving it.** The fix is not shared memory, it is
moving the work off the request path entirely — see §7.

---

## 4. Ownership, and why reading is not gated

An estimate's opaque URL was the only access control the product had, and thousands of
those links may already have been sent to installers. Ownership had to be *additive*.

```
owner_id IS NULL     anonymous.  Readable and writable by whoever holds the link.
                     Exactly as before accounts existed.

owner_id = <user>    owned.      Readable by whoever holds the link.
                     Writable only by the owner.
```

Reading stays open because closing it would break every link already shared, and because
the link is the sharing mechanism — that is the feature, not an oversight. Writing is
gated because otherwise anyone holding a link could delete somebody's saved work.

Two consequences follow from taking that seriously:

- **`ON DELETE SET NULL`, not `CASCADE`.** Closing an account does not destroy its
  estimates; they revert to anonymous and their links keep working. Deleting an account is
  not consent to break a link for whoever else holds it.
- **The retention sweep spares owned estimates.** Anonymous estimates expire after a year
  because nobody will ever tidy them up. An owned one has somebody who can see it and
  delete it, and expiring it out from under them would be data loss dressed as
  housekeeping.

`GET /api/estimates` used to list every estimate on the server. It now requires a session
and returns only that user's rows, and there is deliberately no parameter that widens it.

---

## 5. Authentication

Full detail in [`SECURITY.md`](SECURITY.md). The architecturally relevant parts:

**Access tokens are signed, not stored.** A 15-minute JWT, verified by signature with no
database or Redis round trip. That is what makes an authenticated request cost the same as
an anonymous one, and it is why an access token cannot be revoked early — hence the short
lifetime.

**Refresh tokens are stored, hashed, and rotate on every use.** They must be revocable
(logout, password reset, theft), so they live in Redis as SHA-256 digests with a per-user
index set for bulk revocation. Presenting a rotated-away token is treated as evidence of
theft and revokes every session on the account.

**Nothing about a session lives in a process.** An access token minted on replica 1 is
accepted by replica 3 because both hold `JWT_SECRET`. A refresh token issued by replica 1
is rotated by replica 3 because Redis holds it. Signing out on one instance ends the
session on all of them.

### Why not `fastapi-users`

The reference architecture proposed it. It was not adopted, and the reason is structural
rather than a preference.

`fastapi-users` is async-first: it requires an async SQLAlchemy session, which requires
every DB-touching route to become `async def`. This backend is synchronous throughout —
blocking `urllib` for upstream weather, scikit-learn for training — and FastAPI runs sync
handlers in a threadpool precisely so that blocking work does not stall the event loop.
Converting the routes to `async def` while the work inside them stayed blocking would move
a thirty-second model fit *onto* the event loop and stall every other request on that
replica.

So the mature libraries used are the ones that matter cryptographically, and nothing is
hand-rolled:

| Concern | Library |
|---|---|
| Password hashing | `argon2-cffi` (Argon2id, OWASP parameters) |
| Token signing | `PyJWT` |
| OAuth2 client | `Authlib` + `requests` |
| Randomness | `secrets` |
| Email validation | `email-validator` |

---

## 6. Health, readiness and draining

Two endpoints, because they answer different questions and conflating them builds an
outage into the deployment.

| | Question | Checks | Consequence of failure |
|---|---|---|---|
| `/api/health/live` | Is this process running? | nothing | The orchestrator **kills the container** |
| `/api/health/ready` | Should it get traffic? | PostgreSQL, Redis, config | The load balancer **routes elsewhere** |

A liveness probe that queried PostgreSQL would turn a database blip into every container
restarting at once — a dependency outage *plus* a cold fleet. So liveness touches nothing,
and the Docker `HEALTHCHECK` uses liveness only.

Email is checked by readiness but **is not a gate**. A dead mail provider means nobody can
verify an address, which is bad; every instance refusing traffic and the calculator going
down entirely is worse, and self-inflicted.

**Draining** is what makes a rolling deploy lossless. On `SIGTERM` the order is:

```
SIGTERM
  ↓  readiness flips to 503 immediately   ← the load balancer stops sending new work
  ↓  in-flight requests continue          ← up to 45s, enough for a console training run
  ↓  DB and Redis connections closed
  ↓  exit
```

Reversing the first two steps is the classic mistake: stop accepting first, and the load
balancer discovers the instance is gone by getting an error from a user's request.
`stop_grace_period` in compose is set above the application's own budget, or Docker would
`SIGKILL` mid-drain and make the whole mechanism decorative.

---

## 7. Background analysis jobs — prepared, not built

The console's training work runs inside the request and takes 10–40 seconds. That is the
remaining architectural weakness, and this release **prepares** for the fix without
performing it.

What exists now:

- `helios_analysis_jobs` is already exported as a gauge labelled by state
  (`pending`/`running`/`complete`/`failed`), so dashboards and alerts do not have to change
  when the work moves.
- Nginx's `proxy_read_timeout` on `/api/` is 300s, chosen so a legitimate long request is
  not killed at the 60-second default.
- `loadtest/console.py` exists specifically to produce the measurement that decides when
  this stops being optional.

The eventual shape, which the current API can grow into without a breaking change:

```
POST /api/analysis        → 202 { analysis_id, status: "pending" }
GET  /api/analysis/{id}   → { status: "running" | "complete" | "failed", ... }
```

The existing `POST /api/analysis` already returns an `analysis_id` that the client then
polls follow-up endpoints with. Adding a `status` field and allowing `202` is additive; a
client that ignores `status` keeps working against a synchronous deployment.

**This is not implemented.** There is no Celery, no worker, no queue. Saying otherwise
would be the difference between an architecture document and a brochure.

---

## 8. Observability

| Signal | Mechanism | Where it goes |
|---|---|---|
| Logs | JSON on stdout, one object per line | Loki / ELK |
| Metrics | `/api/metrics`, Prometheus exposition | Prometheus → Grafana |
| Traces | OpenTelemetry, OTLP/HTTP | Tempo / Jaeger |
| Errors | Sentry SDK, scrubbed | Sentry |

Every log line carries `request_id`, `user_id` and `instance_id`, propagated through a
`ContextVar` — which is the right primitive here specifically because sync handlers run in
a threadpool, so a value set in middleware is visible to that request's handler and to no
other. The same `request_id` appears in the Nginx access log and in the `X-Request-ID`
response header, which is what joins the three together.

Log output is **redacted before it is written**: bearer tokens, anything shaped like a
password or secret assignment, and bare JWTs. A log line is copied to a central store, kept
for months, and read by people who are not the user.

Metrics label routes by **template** (`/api/estimate/{estimate_id}`), never by concrete
path. One time series per estimate id is how you take down a Prometheus server with your
own instrumentation.

Two counters exist for failure modes that are otherwise silent:
`helios_rate_limiter_degraded_total` (the limiter could not reach Redis and allowed the
request) and `helios_dependency_up` (last probe result per dependency).

Tracing and Sentry are both optional and degrade to no-ops. Tracing additionally needs
`requirements-tracing.txt`, kept out of the default image because it is a large transitive
tree for a feature most deployments leave off.

---

## 9. What is still a single point of failure

`docker-compose.prod.yml` runs one PostgreSQL, one Redis and one Nginx. Any of them failing
takes the platform down. That is honest for a single-host deployment and is **not what
production should run**. [`DEPLOYMENT.md`](DEPLOYMENT.md) sets out the HA topology that
replaces each.

---

## 10. File map

```
backend/app/
  config.py                 all settings + production_problems() fail-closed check
  main.py                   middleware, error envelope, lifecycle, draining
  db/
    base.py                 engine, session-per-request, pool sizing, draining
    models.py               users, oauth_accounts, estimates, experiments
    types.py                GUID and JSON that work on PostgreSQL and SQLite
  infra/
    redis_client.py         shared store + the memory:// development stand-in
    cache.py                upstream response cache (key scheme unchanged)
  security/
    passwords.py            Argon2id, rehash-on-login, constant-time miss
    tokens.py               JWT access, rotating refresh w/ reuse detection, email tokens
    rate_limit.py           Redis fixed-window, shared across replicas
    csrf.py                 signed double-submit
  auth/
    service.py              account rules; no silent OAuth merging
    deps.py                 optional_user / current_user / verified_user
    oauth.py                Google + GitHub, PKCE, Redis-backed state
    routes.py               /api/auth/*
  email/
    sender.py               provider abstraction: SES/SendGrid/Postmark/Resend/console
    templates.py            the two messages
  observability/
    logging.py              JSON logs, request context, redaction
    metrics.py              Prometheus collectors
    tracing.py              OpenTelemetry (optional)
    errors.py               Sentry with a scrubber (optional)
  api/routes/health.py      live / ready / startup + the original /api/health

backend/alembic/            migrations
deploy/nginx/               load balancer config
deploy/pgbouncer/           connection pooling config
loadtest/                   consumer and console profiles
```

---

## 11. Related documents

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — dev, production and HA topologies; rolling deploys
- [`SECURITY.md`](SECURITY.md) — threat model, protections, audit findings
- [`BACKUP_AND_RECOVERY.md`](BACKUP_AND_RECOVERY.md) — WAL archiving, PITR, restore drills
- [`LOAD_TESTING.md`](LOAD_TESTING.md) — how to turn "three backends" into a measured number
- [`DELIVERY.md`](DELIVERY.md) — the original delivery report; the science is unchanged
