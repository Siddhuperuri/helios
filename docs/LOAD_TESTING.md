# Load testing and capacity

Three backends and two frontends is a **starting point, not a derived answer**. This
document is how to replace it with a measured one.

---

## 1. Why two profiles

The workloads differ by three orders of magnitude, and averaging them produces a number
that describes neither.

| | Consumer path | Analysis console |
|---|---|---|
| Typical request | 1–15 s | 10–40 s |
| Bound by | upstream weather fetch, then I/O | **CPU**, single-threaded |
| Cache behaviour | shared and warm; most requests hit | every run is distinct |
| Concurrency ceiling | connections | **cores** |
| Who does it | most visitors | a handful of researchers |
| Sheddable | no — it is the product | yes, briefly |

Running them together in one profile hides the finding that matters: **the console can
saturate the fleet at a concurrency the consumer path shrugs off.** Keeping them separate is
what surfaces it.

```bash
loadtest/consumer.py    # the calculator, anonymous and signed-in
loadtest/console.py     # analysis creation and interrogation
```

---

## 2. Running them

```bash
pip install -r backend/requirements-dev.txt   # brings in locust
```

### Consumer

```bash
cd loadtest
locust -f consumer.py --host https://helios.example.com \
       --headless --users 100 --spawn-rate 10 --run-time 10m \
       --csv results/consumer-100u
```

Or `make load-test` for the interactive web UI.

### Console

```bash
cd loadtest
locust -f console.py --host https://helios.example.com \
       --headless --users 6 --spawn-rate 1 --run-time 15m \
       --csv results/console-6u
```

**Six users, not sixty.** Each request occupies a worker for tens of seconds; a hundred
concurrent console users is not a stress test, it is a denial of service against your own
fleet, and the resulting numbers describe a system in collapse rather than a system under
load.

Both profiles fail the run on their thresholds — 1% errors / 20 s p95 for the consumer path,
2% / 120 s for the console — so either can gate a pipeline rather than producing a report
nobody reads.

---

## 3. What to measure, and where it comes from

Latency and error rate come from Locust. Everything else has to be collected alongside it,
and the point of the exercise is the *relationship* between them.

| Signal | Source | What it tells you |
|---|---|---|
| p50 / p95 / p99 | Locust, or `helios_http_request_duration_seconds` | the shape, not the average |
| Error rate | Locust; `helios_http_requests_total{status=~"5.."}` | when the fleet ran out of capacity |
| 429 rate | `helios_rate_limited_total` | the limiter working, **not** an error |
| CPU per replica | `docker stats`, cAdvisor | the console's real ceiling |
| RSS per replica | same | analysis LRU growth |
| DB pool | `helios_db_pool_connections{state="checkedout"}` | whether PgBouncer is sized right |
| PgBouncer | `SHOW POOLS` / `SHOW STATS` | `cl_waiting > 0` means clients are queuing |
| Redis | `redis-cli INFO stats`, `--latency` | shared-store saturation |
| Cache hit rate | `helios_estimates_total` vs upstream fetches in the log | how warm the fleet is |

**Read p95, not the mean.** The consumer distribution is bimodal — a cache hit returns in
milliseconds, a cold location takes ten seconds — and the mean sits in a gap where no real
request lives.

**Do not count 429s as errors.** Being rate limited is the system defending itself. Both
profiles mark them as successes deliberately; counting them would make the error-rate graph
meaningless at exactly the load where it matters.

---

## 4. Method

### Step 1 — baseline a single replica

Scale to one backend and find where it breaks:

```bash
docker compose -f docker-compose.prod.yml up -d --scale backend1=1
# stop backend2 and backend3, and remove them from the Nginx upstream
```

Ramp 10 → 20 → 50 → 100 users, ten minutes each. Record the point where p95 crosses your
budget or errors appear. That is **one replica's capacity**, and it is the only number the
rest of the arithmetic can be built on.

### Step 2 — confirm it scales

Bring all three back and repeat at 3×. Throughput should rise close to linearly; if it does
not, the backends are not the bottleneck and you have found something more interesting —
usually PgBouncer sizing or Redis.

### Step 3 — size the console separately

Run the console profile alone, 1 → 2 → 4 → 8 users. Watch CPU per replica. The ceiling is
roughly *cores per replica × replicas*, because each request is single-threaded and
CPU-bound throughout its 10–40 seconds.

### Step 4 — run both at once

The realistic case, and the one that produces the finding. Consumer at your expected peak,
console at 2–4 users. If consumer p95 degrades materially, the two workloads need
separating — see §6.

### Step 5 — derive the fleet

```
replicas = ceil(peak_rps / single_replica_rps) × headroom
```

Use `headroom = 1.5` at minimum. It covers a replica lost to a rolling deploy, a node
failure, and the fact that peak traffic is not the peak you measured.

---

## 5. Sizing the rest of the stack

**PgBouncer.** `default_pool_size` is real connections to PostgreSQL, and it is *not*
`replicas × pool_size` — that would defeat the reason PgBouncer exists. Start at 20, watch
`SHOW POOLS`:

- `cl_waiting > 0` sustained → raise `default_pool_size`
- `sv_idle` consistently high → lower it; those are connections PostgreSQL is paying for

**PostgreSQL.** This workload is small-transaction and read-heavy. Watch `checkedout` and
whether p95 rises with connection count rather than with request rate. If reads dominate,
a read replica is the next move — the routing is **not implemented**, and
[`DEPLOYMENT.md §4`](DEPLOYMENT.md) says where it would go.

**Redis.** Memory is dominated by the weather cache: a two-year hourly payload is roughly
1–3 MB, and entries live 30 days. Estimate `distinct locations × 2 MB × request variants`
and set `maxmemory` above it. `volatile-lru` evicts only keys with a TTL, which is every key
this application writes.

**Frontend.** Almost certainly not the bottleneck — it serves a static bundle and a handful
of server-rendered routes. Two replicas is availability, not throughput.

---

## 6. When to move the console off the request path

The console runs training inside the request. That is the remaining architectural weakness,
and the load test is how you decide when it stops being tolerable. Any of these is the
signal:

- consumer p95 degrades when console users appear
- console p95 exceeds two minutes at expected concurrency
- CPU sits above 80% on every replica during a console run
- the fleet has to be sized for the console rather than for the calculator

The move is a queue — Celery on the existing Redis — and the API is already shaped for it:
`helios_analysis_jobs` is exported by state, `proxy_read_timeout` is 300 s, and the
`202 + status` transition is additive. See
[`PRODUCTION_ARCHITECTURE.md §7`](PRODUCTION_ARCHITECTURE.md).

---

## 7. Reporting a run

Record enough that somebody can disagree with the conclusion:

```markdown
## Consumer, 2026-08-22

Topology     3 × backend (2 vCPU, 2 GB), 2 × frontend, PgBouncer 20, Redis 1 GB
Profile      consumer.py, 100 users, 10/s spawn, 10 min
Cache        warm (third consecutive run)

RPS          — sustained
p50 / p95 / p99  — / — / —
Error rate   —
429 rate     —
CPU peak     — % per replica
DB checkedout  — peak
PgBouncer cl_waiting  — peak
Redis mem    —

Conclusion   n replicas support — RPS at p95 < — s.
Bottleneck   —
```

The topology and cache state lines are what make a run reproducible. A p95 from a cold cache
and a p95 from a warm one are different measurements of different systems.

---

## 8. Status

**No capacity numbers appear in this repository, and that is deliberate.** Publishing
figures produced on a laptop, against SQLite, with no Nginx and a cold cache, would be worse
than publishing none — they would be quoted.

The load profiles are written, runnable, and encode the thresholds. The measurements have to
come from the deployment being sized, on its own hardware, against its own data.

Until then, three backends and two frontends is a **starting point that the application does
not depend on** — the counts live in `docker-compose.prod.yml` and nothing in the code knows
them.
