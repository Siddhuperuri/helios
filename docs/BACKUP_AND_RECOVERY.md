# Backup and recovery

A backup nobody has restored is a hypothesis, not a backup. This document covers both
halves, and the second half is the one that matters.

---

## 1. What is actually at risk

| Store | Contents | If lost |
|---|---|---|
| **PostgreSQL** | accounts, OAuth links, estimates, experiments | **Unrecoverable.** Nobody's account exists; every saved estimate is gone |
| **Redis** | cache, rate limits, sessions, email tokens | Everyone signed out; caches cold; nothing permanent lost |
| Backend containers | nothing | — |
| Frontend containers | nothing | — |

Only PostgreSQL needs a recovery plan. That is the point of the whole state-externalisation
exercise: there is exactly one thing to protect, and everything else can be destroyed and
recreated.

Redis is configured with `appendonly yes` and `appendfsync everysec` so a restart does not
sign everybody out. That is a courtesy, not a durability guarantee — losing it is survivable
by design, and treating it as precious would be misplacing the effort.

---

## 2. Recovery objectives

| | Target | Achieved by |
|---|---|---|
| **RPO** — how much data may be lost | ≤ 5 minutes | WAL archiving |
| **RTO** — how long recovery may take | ≤ 1 hour | nightly base backup + WAL replay |

Nightly dumps alone give an RPO of "up to 24 hours", which for a product where somebody
just created an account and saved an estimate means telling them it never happened. WAL
archiving is what turns that into minutes.

---

## 3. How it is configured

`docker-compose.prod.yml` starts PostgreSQL with:

```
wal_level=replica
archive_mode=on
archive_command=test ! -f /var/lib/postgresql/wal_archive/%f && cp %p /var/lib/postgresql/wal_archive/%f
max_wal_senders=3
```

The `test ! -f` guard is not decoration: `archive_command` must **fail** rather than
overwrite if the target exists, because silently replacing an archived segment corrupts the
recovery chain in a way that is only discovered during a restore.

`max_wal_senders=3` is there so a streaming replica can be attached without a restart.

### Where the archive goes

Copying to a local volume protects against database corruption and accidental deletion. It
does **not** protect against losing the host, which is the failure most likely to end the
company. For anything real, ship both the base backups and the WAL segments off-host:

```bash
# archive_command for S3-compatible storage
archive_command = 'aws s3 cp %p s3://helios-wal/%f --only-show-errors'
```

Or use a purpose-built tool — pgBackRest or WAL-G — which handle retention, compression,
parallelism and verification rather than leaving them as things you meant to script.

---

## 4. Nightly base backup

```bash
#!/usr/bin/env bash
# deploy/postgres/backup.sh — run from cron at 02:00 UTC
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="/backups/base-${STAMP}"

# pg_basebackup, not pg_dump. A dump is a logical snapshot with no relationship to the WAL
# stream, so it cannot be a starting point for point-in-time recovery. A base backup can.
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_basebackup --pgdata="${DEST}" --format=tar --gzip --checkpoint=fast \
                --progress --wal-method=stream --username="${DB_USER}"

# Retention: 14 daily. Long enough to cover a corruption discovered after a weekend.
find /backups -maxdepth 1 -name 'base-*' -mtime +14 -exec rm -rf {} +

# A backup whose creation was not verified is not a backup.
if [ ! -s "${DEST}/base.tar.gz" ]; then
  echo "FAILED: ${DEST} is empty or missing" >&2
  exit 1
fi
echo "OK: ${DEST}"
```

A logical dump is still worth taking alongside it — it is the only form that survives a
PostgreSQL major-version change and the only one you can inspect without a server:

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump --username="${DB_USER}" --format=custom helios > "/backups/helios-${STAMP}.dump"
```

**Alert on the absence of a fresh backup**, not on the failure of the job. A cron job that
stops running produces no failure to alert on, which is exactly how backups quietly stop
for six months.

---

## 5. Restore

### 5a. Restore to the latest available state

```bash
docker compose -f docker-compose.prod.yml stop backend1 backend2 backend3
docker compose -f docker-compose.prod.yml stop postgres

# Keep the broken data directory. Do not delete it — if the restore fails, it may be the
# only remaining copy, and it is also the evidence for what went wrong.
mv /var/lib/postgresql/data /var/lib/postgresql/data.broken.$(date -u +%s)
mkdir -p /var/lib/postgresql/data

tar -xzf /backups/base-<STAMP>/base.tar.gz -C /var/lib/postgresql/data

cat > /var/lib/postgresql/data/postgresql.auto.conf <<'EOF'
restore_command = 'cp /var/lib/postgresql/wal_archive/%f %p'
EOF
touch /var/lib/postgresql/data/recovery.signal

docker compose -f docker-compose.prod.yml start postgres
# Watch it replay. It exits recovery when the archive is exhausted.
docker compose -f docker-compose.prod.yml logs -f postgres
```

### 5b. Point-in-time recovery

For the case this exists for: a bad migration or a mistaken `DELETE` at a known time.

```bash
cat > /var/lib/postgresql/data/postgresql.auto.conf <<'EOF'
restore_command = 'cp /var/lib/postgresql/wal_archive/%f %p'
recovery_target_time = '2026-08-22 14:22:00+00'
recovery_target_action = 'pause'
EOF
```

`recovery_target_action = 'pause'` stops at the target instead of promoting, so you can
connect read-only and confirm you picked the right instant **before** committing to it:

```sql
SELECT count(*) FROM users;
SELECT count(*) FROM estimates WHERE owner_id IS NOT NULL;
```

Satisfied:

```sql
SELECT pg_wal_replay_resume();
```

Then remove `recovery.signal`, restart, and bring the backends up.

### 5c. Afterwards

```bash
docker compose -f docker-compose.prod.yml exec backend1 \
  curl -fsS http://127.0.0.1:8000/api/health/ready

docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U "${DB_USER}" -d helios -c "SELECT version_num FROM alembic_version;"
```

The `alembic_version` check matters: the restored database must be at the migration the
running code expects. If the restore predates a migration, run `alembic upgrade head`
before starting the backends — the `migrate` service does this, so restarting the whole
stack handles it.

**Redis is not restored.** Everyone is signed out, caches are cold, the first estimate for
each location is slow again. All expected, none of it durable loss.

---

## 6. Restore testing

The part that is usually skipped, and the only part that establishes anything.

**Monthly**, restore the most recent base backup into a throwaway environment and check:

```bash
# 1. Restore into a scratch container, never into production
docker run -d --name helios-restore-test -e POSTGRES_PASSWORD=scratch postgres:16.4-bookworm
# ...extract the base backup and replay WAL as in §5a...

# 2. The schema is at the expected revision
psql -c "SELECT version_num FROM alembic_version;"

# 3. The data is there and internally consistent
psql -c "SELECT count(*) FROM users;"
psql -c "SELECT count(*) FROM estimates;"
psql -c "SELECT count(*) FROM estimates WHERE owner_id IS NOT NULL;"

# 4. Foreign keys survived — a restore that broke them would show up as orphaned rows
psql -c "SELECT count(*) FROM estimates e
         LEFT JOIN users u ON e.owner_id = u.id
         WHERE e.owner_id IS NOT NULL AND u.id IS NULL;"   -- must be 0

# 5. The application actually starts against it
DATABASE_URL=postgresql+psycopg://...scratch... python -m alembic upgrade head
```

Record the wall-clock time. That number is your real RTO, and it is usually larger than the
one in the plan.

**Quarterly**, do a full drill: restore to a point in time, bring a complete stack up
against it, sign in as a seeded account and open an estimate. This is what catches the
failure modes a `SELECT count(*)` cannot — a restored database whose `alembic_version` is
ahead of the deployed code, for instance.

---

## 7. Migration safety

A bad migration is the most likely reason to need any of this, and the cheapest thing to
prevent.

**Before applying one in production:**

```bash
# Read the SQL rather than trusting the Python.
python -m alembic upgrade head --sql

# Take a base backup immediately before. Cheap, and the difference between a five-minute
# rollback and a point-in-time recovery.
./deploy/postgres/backup.sh
```

**During a rolling deploy the old release and the new one both talk to this database.** The
constraint that follows is in [`DEPLOYMENT.md §3`](DEPLOYMENT.md) and is repeated at the top
of every generated migration file: add nullable, backfill, ship, remove three releases
later. CI fails if the models and the migrations disagree.

---

## 8. What is implemented, and what is documented

Being precise, because this is exactly the section where a document can drift from reality:

| | Status |
|---|---|
| WAL archiving configured | **Implemented** — in `docker-compose.prod.yml` |
| WAL archive volume | **Implemented** — `postgres_wal` |
| Backup directory mounted | **Implemented** — `deploy/postgres/backups` |
| Backup script | **Documented** (§4) — the script above is not committed or scheduled |
| Off-host archive shipping | **Documented** (§3) — local volume only as shipped |
| Restore procedure | **Documented** (§5) — not automated |
| Restore testing | **Documented** (§6) — not scheduled |
| Monitoring for stale backups | **Not implemented** |

The configuration that must be in place *before* an incident — WAL archiving, retention of
segments — is done. The operational cadence around it is written down but not automated,
because scheduling and alerting belong to whatever platform this is deployed on rather than
to a compose file.
