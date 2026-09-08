# Deployment

Three topologies, and the differences between them are deliberate rather than incidental.

| | Where it runs | Instances | Data | Single points of failure |
|---|---|---|---|---|
| **Development** | a laptop | 1 backend, 1 frontend | containerised PostgreSQL + Redis | everything, and that is fine |
| **Production** | one host | 3 backends, 2 frontends, Nginx, PgBouncer | containerised PostgreSQL + Redis | PostgreSQL, Redis, Nginx |
| **HA production** | several hosts / managed services | *n* backends, *m* frontends | managed PostgreSQL + Redis, ≥2 LBs | none by design |

The second is what `docker-compose.prod.yml` gives you. The third is what a real production
environment should be, and §4 sets out how to get there. Presenting the second as
production-ready without that caveat would be the single most misleading thing this
document could do.

---

## 1. Development

### Without containers

Nothing to install and nothing to provision. The backend falls back to a SQLite file and an
in-process Redis stand-in, both of which are rejected in production.

```bash
make install
make dev
```

Frontend on `http://localhost:3000`, API on `http://127.0.0.1:8000`.

Verification and password-reset emails are **printed to the backend log** rather than sent
(`EMAIL_PROVIDER=console`), so a signup can be completed without configuring a provider.
Copy the link out of the log.

```bash
make seed          # sample accounts and estimates; prints the shared password
make test          # 388 backend + 70 frontend tests, no services required
```

### With containers

Closer to production: real PostgreSQL, real Redis, migrations as their own step.

```bash
make stack         # docker compose up --build -d
make stack-logs
make stack-down
```

### Why the frontend proxies `/api`

The refresh token is a `SameSite=Lax` cookie, so a browser withholds it from cross-site
requests — and `localhost:3000` calling `127.0.0.1:8000` **is** cross-site, because a site
is a host, not a host and port.

A split-origin development setup therefore breaks silent refresh in a way that looks fine
until an access token expires fifteen minutes later, at which point the user is signed out
with no explanation. `next.config.mjs` rewrites `/api/*` to the backend so development
matches the deployed topology, where Nginx serves both from one origin.

Keep `NEXT_PUBLIC_API_BASE` empty. Setting it to an absolute URL disables the rewrite and
requires `SOLAR_COOKIE_SAMESITE=none`, `SOLAR_COOKIE_SECURE=true` and the frontend origin
in `SOLAR_CORS_ORIGINS`.

---

## 2. Production (single host)

### Prepare

```bash
cp .env.example .env.production
```

Fill in, at minimum:

```bash
# 48 bytes of real randomness. Anyone holding this can mint tokens for any account.
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

| Variable | Notes |
|---|---|
| `JWT_SECRET` | as above; rotating it signs everyone out, which is the intended blast radius |
| `DB_USER`, `DB_PASSWORD` | PostgreSQL credentials |
| `PUBLIC_ORIGIN` | e.g. `https://helios.example.com` — drives OAuth callbacks, email links, CORS and the redirect allowlist |
| `EMAIL_PROVIDER` + `EMAIL_PROVIDER_API_KEY` | `console` and `memory` are rejected |
| `EMAIL_FROM_ADDRESS` | must be a verified sender with your provider |
| `SOLAR_RELEASE` | tags the images and appears in logs, metrics and Sentry |

OAuth is optional. With a client ID/secret pair unset, that provider is simply not offered —
the frontend asks which are configured and renders buttons only for those. If you do
configure one, register **exactly** these callback URLs:

```
${PUBLIC_ORIGIN}/api/auth/oauth/google/callback
${PUBLIC_ORIGIN}/api/auth/oauth/github/callback
```

Providers match these exactly; a trailing slash or an `http`/`https` mismatch is the most
common reason an OAuth setup fails.

### TLS

`deploy/nginx/conf.d/helios.conf` ships a plain `:80` server block, because compose has no
certificate to offer. For a real deployment, obtain certificates (Let's Encrypt via certbot,
or your platform's managed certificate), mount them at `deploy/nginx/certs/`, and add:

```nginx
server {
    listen 443 ssl http2;
    server_name helios.example.com;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Only on the TLS listener. Sending HSTS from a plaintext port would pin browsers to
    # HTTPS for a host that is not serving it.
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # …the location blocks from the :80 server, unchanged…
}

server {
    listen 80;
    server_name helios.example.com;
    # Except the ACME challenge, which must stay on :80.
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
```

Set `SOLAR_COOKIE_SECURE=true` at the same time, or the refresh cookie travels in the clear.

### Start

```bash
make prod
# or
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

### Verify

```bash
curl -fsS http://localhost/healthz                     # the load balancer itself
docker compose -f docker-compose.prod.yml exec backend1 \
  curl -fsS http://127.0.0.1:8000/api/health/ready | jq
```

A healthy readiness payload reports `"status": "ready"` with `database.ok` and `redis.ok`
true. If `checks.configuration` is present, the backend is telling you which values are
still development defaults — and it will have refused to start, because production startup
is fail-closed.

---

## 3. Rolling deployment

Never stop the fleet and start a new one. The sequence, and the reason each step exists:

```
1. Build and tag       docker build -t helios-backend:$RELEASE backend
2. Run migrations      one-shot `migrate` service, before any new instance starts
3. For each replica, one at a time:
     a. start the new container
     b. wait for /api/health/ready to return 200      ← not "the container started"
     c. reload Nginx so it enters the upstream
     d. SIGTERM the old container
     e. it fails readiness immediately, drains, exits ← up to 45s
4. Confirm: no 5xx in the Nginx log for the window
```

One at a time. With three replicas, taking two down at once leaves a third carrying the
whole load, and a console training run on it will make the deployment look like an outage.

### Migrations and rolling deploys

During step 3 the **old release and the new release are both running against the same
database**. A migration must therefore be readable by code that has not been deployed yet.

| Safe | Unsafe |
|---|---|
| Add a nullable column | Drop a column still selected by the old release |
| Add a table | Rename a column |
| Add an index (`CONCURRENTLY` on PostgreSQL) | Add a `NOT NULL` column with no default |
| Backfill in a later migration | Change a column's type in place |

The pattern for removing a column takes three releases and that is not negotiable:

```
release 1   stop writing it; keep reading it
release 2   stop reading it
release 3   drop it
```

`alembic/script.py.mako` carries this note at the top of every generated migration, and CI
fails if the models and the migrations disagree.

---

## 4. High availability

Everything above still has three single points of failure. Removing them:

### PostgreSQL

Use a managed service — RDS Multi-AZ, Cloud SQL HA, Azure Flexible Server with zone
redundancy. Automatic failover, automated backups and PITR without operating any of it.

Self-managed equivalent: a primary with a streaming replica and an automatic failover
manager (Patroni, repmgr). The application needs no change — `DATABASE_URL` points at the
failover endpoint.

A read replica is genuinely useful here because the read/write ratio is lopsided: dashboard
listings, estimate reads and experiment listings vastly outnumber writes. Routing reads to
a replica is **not implemented** — it needs a session router in `app/db/base.py` — and it
is the right next step if the database becomes the bottleneck.

### Redis

Managed HA Redis (ElastiCache with Multi-AZ, Memorystore, Azure Cache) or Redis Sentinel
with at least three sentinels and one replica.

Understand what a Redis failure costs before sizing the effort: it fails **soft** for the
cache (upstream refetches, slower) and **hard** for sessions and rate limiting. Instances
that cannot reach it fail readiness and leave the pool, so the visible outcome is the fleet
draining itself — which is safer than serving unlimited unauthenticated traffic, and is the
reason readiness gates on Redis at all.

Redis is configured with `appendonly yes` and `volatile-lru`. That eviction policy is
deliberate: every key this application writes has a TTL, so `volatile-lru` evicts from
exactly that set. `allkeys-lru` would happily evict a live refresh token and sign somebody
out at random.

### Load balancer

At least two Nginx instances behind a floating IP (keepalived) or, preferably, a managed L7
load balancer — ALB, Cloud Load Balancing, Azure Application Gateway. Point its health check
at `/api/health/ready` for the backends, **not** at `/api/health/live`, or it will keep
routing to an instance that cannot reach its database.

### Summary

| Component | This compose file | HA replacement |
|---|---|---|
| PostgreSQL | one container | managed Multi-AZ, or primary + replica + Patroni |
| Redis | one container | managed HA, or Sentinel with 3 sentinels |
| Nginx | one container | ≥2 instances + floating IP, or a managed L7 LB |
| Backend | 3 containers, one host | *n* across ≥2 availability zones |
| Frontend | 2 containers, one host | *m* across ≥2 zones, or a static/edge deployment |

---

## 5. Kubernetes

The application is already shaped for it — stateless replicas, separate liveness and
readiness, `SIGTERM` draining, migrations as a discrete step. The mapping:

| Compose | Kubernetes |
|---|---|
| `backend1..3` | one `Deployment`, `replicas: 3` |
| `migrate` | a `Job`, or an `initContainer` with a leader election |
| `nginx` | an `Ingress` |
| `stop_grace_period: 60s` | `terminationGracePeriodSeconds: 60` |
| `/api/health/live` | `livenessProbe` |
| `/api/health/ready` | `readinessProbe` |
| `/api/health/startup` | `startupProbe` |
| `.env.production` | a `Secret`, mounted as environment |

`maxUnavailable: 0` with `maxSurge: 1` reproduces the one-at-a-time rollout above.

---

## 6. Configuration reference

Every variable, with what it does and what happens if it is wrong, is in
[`.env.example`](../.env.example). The startup check in
`backend/app/config.py::Settings.production_problems` is the executable version of that
file — it names each unsafe value and the failure it would cause, and refuses to start.

---

## 7. Operational runbook

| Symptom | First look | Likely cause |
|---|---|---|
| 502 from Nginx | `/api/health/ready` on each backend | all replicas failing readiness — check Redis and PostgreSQL |
| 503 from Nginx | Nginx error log | no upstream passing health checks |
| Everyone signed out at once | Redis logs; `helios_auth_events_total` | Redis restarted without persistence, or `JWT_SECRET` changed |
| Rate limits not applying | `helios_rate_limiter_degraded_total` | backends cannot reach Redis; they should also be failing readiness |
| Nobody receives email | `checks.email` in readiness | provider key expired, or sender not verified |
| Slow requests, no errors | traces; `helios_http_request_duration_seconds` by route | usually a cold weather cache or console training |
| `too many connections` | `SHOW POOLS` on PgBouncer | pool sizing; see `deploy/pgbouncer/pgbouncer.ini` |

Database recovery is its own document: [`BACKUP_AND_RECOVERY.md`](BACKUP_AND_RECOVERY.md).
