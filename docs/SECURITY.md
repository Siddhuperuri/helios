# Security

What is protected, how, and what is deliberately not.

The previous release had almost no attack surface worth describing: no accounts, no
secrets, no personal data beyond what a visitor typed into a form. Adding authentication
changed that in one step, and this document is the account of what was done about it —
including the parts that are accepted risk rather than solved problems.

---

## 1. What is actually worth protecting

| Asset | Sensitivity | Exposure |
|---|---|---|
| Password hashes | high | PostgreSQL only; never leave the process |
| Refresh tokens | high | Redis, hashed; httpOnly cookie in the browser |
| `JWT_SECRET` | critical | anyone holding it can mint tokens for any account |
| OAuth client secrets | high | environment only; never in a URL or a log |
| Estimate contents | moderate | a location, an electricity bill, a system design |
| Email addresses | moderate | account enumeration is the specific risk |
| Weather data | none | public, keyless, and cached |

An estimate is "not nothing": it says where somebody lives and roughly what they earn.
That is why the identifier in its URL is 16 bytes from a cryptographic source rather than a
counter, and why the dashboard listing is scoped by ownership at the query rather than in
the interface.

---

## 2. Passwords

**Argon2id via `argon2-cffi`**, at the OWASP low-memory profile (19 MiB, t=2, p=1). Not
bcrypt, not PBKDF2, and not anything assembled here.

Three behaviours are easy to omit and all three are implemented:

- **Rehash on login.** Work factors rise over time. A hash written under old parameters is
  upgraded at the only moment the plaintext is available — a successful login.
- **Constant work on a missing account.** `verify_password` is called even when there is no
  user, against a dummy hash. Otherwise a missing account returns in microseconds and a
  real one in tens of milliseconds, which enumerates addresses by stopwatch.
- **Length, not composition.** Ten characters minimum and no character-class rules.
  Composition requirements measurably push people towards `Password1!`; NIST and OWASP both
  stopped recommending them.

The hash is never serialised. `User.to_dict()` has no branch that could include it, and a
test asserts the string does not appear anywhere in a session response.

---

## 3. Sessions

```
Access token    JWT, HS256, 15 min     Authorization header     not stored anywhere
Refresh token   32 random bytes, 30 d  httpOnly cookie          SHA-256 digest in Redis
```

**Why the access token is not stored:** verification is a signature check with no round
trip, so an authenticated request costs the same as an anonymous one. The price is that it
cannot be revoked early — hence fifteen minutes.

**Why the refresh token is stored hashed:** it must be revocable, and a dump of Redis must
not hand over working credentials. A plain SHA-256 is correct here, unlike for passwords:
the input is 32 bytes of uniform randomness, so there is nothing for a brute-force to be
faster at.

**Where the access token lives in the browser: memory only.** Never `localStorage`, where
any script on the page can read it and where it outlives the tab it was stolen from. A
reload loses it; the httpOnly refresh cookie survives and mints a new one.

### Rotation and reuse detection

Every refresh rotates. The old token is remembered for the remainder of its original
lifetime, and presenting one is treated as evidence of theft:

```
attacker steals refresh token R
user refreshes    → R rotates to R', R is remembered as spent
attacker presents R
                  → reuse detected → every session on the account revoked
```

Disruptive by design. The alternative is leaving an attacker holding a valid session.

### Revocation

| Event | Effect |
|---|---|
| Logout | this device only — signing out on a library computer must not sign out a phone |
| Logout everywhere | every session |
| Password reset | **every session**, unconditionally |
| Password change | every session except the one making the change |
| Refresh reuse detected | every session |

Password reset revoking everything is the security-critical one. A reset is what somebody
does when they believe an attacker has their account; leaving the attacker's thirty-day
refresh token working would make the whole exercise theatre.

---

## 4. Account enumeration

Registration, resend-verification and forgot-password all answer **identically** whether or
not the address is known — same status, same body, same cookies.

Registration is the one that took a design change. Returning a session on success and none
on a duplicate is a structural difference no amount of careful wording hides, so
`POST /api/auth/register` returns **no session at all**; the client immediately calls
`/api/auth/login` with the same credentials. A new account signs straight in. An existing
one with the wrong password gets login's generic refusal. An existing one with the right
password signs in, which is correct — that is the owner.

The test asserts the two responses are equal objects, not that the wording is careful,
because wording gets edited.

**Accepted residual:** an attacker can still distinguish addresses by timing the login
endpoint if the Argon2 cost differs measurably from the dummy-hash path. The dummy-hash
call uses the same parameters, which closes the gap to the noise floor of a network.

---

## 5. Cross-site request forgery

Only two endpoints authenticate by cookie — `/api/auth/refresh` and `/api/auth/logout` —
because only those two must work when the in-memory access token is gone. Everything else
carries a bearer header, which a cross-site request cannot set.

Those two are protected by a **signed double-submit token**:

```
helios_csrf cookie (readable by our page)  ==  X-CSRF-Token header
and the value carries an HMAC this application produced
```

`SameSite=Lax` is set as well but is not relied on alone: it does not separate sibling
subdomains, and browsers differ on what counts as a top-level navigation. Signing is what
plain double-submit lacks — it rejects a matching pair that something with cookie-write
access to a sibling subdomain planted.

The refresh cookie is scoped to `path=/api/auth`, so it is not attached to estimate or
analysis requests at all.

---

## 6. OAuth

**No silent account merging.** A provider asserting an address that already has a password
account is refused with `link_required`, and the user is told to sign in and link it from
settings. Automatic merging on a matching email means anyone who can get a provider to
assert an address inherits the account behind it.

**Only verified addresses are trusted.** Google's `email_verified` is checked; GitHub's
`/user/emails` is queried separately and only a **primary verified** address is accepted.
An unverified address is treated as no address at all.

**State, nonce and PKCE verifier live in Redis**, single-use, ten-minute TTL. This is not
only a cross-instance requirement — a state value that can be replayed is a CSRF hole in
the callback, and it must be single-use *fleet-wide*, not per-process.

**Redirects are allowlisted by origin.** Comparison is on scheme, host and port, never on a
string prefix — `https://helios.example.com.attacker.test` passes a prefix check. Anything
not allowlisted is replaced with the configured frontend origin rather than rejected, so a
stale bookmark lands on the site rather than an error.

**The token never travels in the URL.** A successful callback redirects with a single-use
ten-second code which the frontend exchanges by POST. A token in a query string ends up in
browser history, in the `Referer` of the next request, and in every proxy log en route.

**Unlinking cannot lock you out.** Removing the last authentication method is refused, and
the interface disables the button and explains why rather than reporting a failure
afterwards. Somebody who signed up with Google, never set a password, and disconnects
Google would have no way back in — password reset needs a password to reset to.

---

## 7. Authorization

The rule and the code are in one function, `_require_write_access` in
`app/api/routes/estimate.py`:

| | Anonymous estimate | Owned estimate |
|---|---|---|
| Read by link | yes | yes |
| Rename / edit / delete | yes | owner only |
| Appears in a dashboard | no | owner's only |

`GET /api/estimates` requires a session and filters by `owner_id` **in the query**. There is
no parameter that widens it; a test asserts that `?owner_id=`, `?all=true` and friends
return nothing rather than somebody else's rows.

Claiming an estimate only works on an unowned one, so holding a link to somebody's saved
estimate does not let you take it.

### Known, accepted: the analysis console is not owner-scoped

`/api/analysis/*` and `/api/experiments/*` are not filtered by owner. An analysis id is 16
random hex characters and lives in process memory; an experiment record holds a location,
a date range and model metrics.

That is a deliberate product decision — the console is a shared research workbench, and the
records are scientific rather than personal — and it is recorded here rather than left to be
discovered. `experiments.owner_id` is populated, so scoping it later is a query change, not
a migration. **If a deployment treats analysis locations as sensitive, this needs to change
first.**

---

## 8. Rate limiting

Counted in Redis, so it is one budget per client across every replica. An in-process
limiter would give a client one budget *per replica*, which with three replicas and
round-robin routing is the same as no limit.

| Bucket | Limit | Keyed by |
|---|---|---|
| general API | 60 / min | user id if signed in, else IP |
| login | 10 / 15 min | IP **and, separately,** the address being attempted |
| register | 5 / hour | IP |
| resend verification | 1 / 2 min | address |
| forgot password | 1 / 2 min | address |
| OAuth start / exchange | 20 / 5 min | IP |

Login is limited on both axes deliberately: per-IP stops one host working through many
accounts, per-account stops a botnet working on one account. A successful login clears the
budget, so somebody who mistypes their password nine times and then gets it right is not
locked out of their next login.

**Client identity is read correctly through the proxy.** `X-Forwarded-For` is a list a
client can prepend to, so the trusted entry is counted from the *right*, using
`SOLAR_TRUSTED_PROXY_HOPS`. Taking the leftmost — the common mistake — lets anybody choose
their own rate-limit identity with a header. The default is 0, so a directly exposed backend
ignores the header entirely.

**On Redis failure the limiter allows requests**, and this is a considered trade rather than
an oversight: an instance that cannot reach Redis also fails readiness and is drained within
seconds. Failing closed would return 429 to every user of a solar calculator during a Redis
blip. The event increments `helios_rate_limiter_degraded_total` and logs at error level.

---

## 9. Transport, CORS and headers

CORS is an **exact origin allowlist** with credentials enabled. `*` is rejected by the
startup check — with credentials it is both forbidden by the specification and a way to
hand any site a session.

In the shipped topology this barely matters, because Nginx serves the app and the API from
one origin and the requests are not cross-origin at all. That is also what makes the
`SameSite=Lax` cookie work.

Set on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy`, and `Strict-Transport-Security` — the last only when cookies are marked
secure, because sending HSTS from a plaintext dev server pins developers' browsers to HTTPS
for a host that does not serve it.

---

## 10. Injection

**SQL:** everything goes through SQLAlchemy's expression language with bound parameters.
The audit found exactly one `text()` call in the codebase, `SELECT 1` in the health probe,
with no interpolation. There is no string-built SQL anywhere.

**Command / code execution:** no `eval`, `exec`, `pickle`, `os.system` or `subprocess`
anywhere in `app/`.

**Path traversal:** the file-backed estimate store is gone, so the class of bug is gone
with it. The identifier validation survives anyway — it turns a malformed link into a clean
404 without a database round trip and bounds the length of what reaches a query.

**XSS:** React escapes by default and the application renders no user content as HTML. The
one `dangerouslySetInnerHTML` in the codebase is the pre-existing theme script in
`app/layout.tsx`, whose content is a compile-time constant. Email templates escape every
interpolated value with `html.escape`.

---

## 11. Secrets

Required: `JWT_SECRET`, `DB_PASSWORD`, `EMAIL_PROVIDER_API_KEY`, the four OAuth values.
None have a usable default; `.env.example` documents each with what it does and what
happens if it is wrong.

- **Never in the frontend.** Every `NEXT_PUBLIC_` variable is compiled into the browser
  bundle. The frontend's `.env.example` says so at the top and contains no secret.
- **Never in an image.** `.dockerignore` excludes `.env*`; nothing is baked in.
- **Never committed.** `.gitignore` ignores `.env*` and re-admits only `.env.example`. The
  previous rules listed `.env`, `.env.local` and `.env.*.local`, which left
  `.env.production` — the file holding the signing key and the database password —
  perfectly committable. That was found during this work and fixed.
- **Never in a log or an error report.** Log output is regex-redacted before it is written.
  Sentry events pass through a scrubber that walks headers, cookies, body, query string and
  frame locals.
- **Startup fails closed.** With `SOLAR_ENV=production`, a default `JWT_SECRET`, a SQLite
  URL, the in-process Redis stand-in, a non-delivering mail provider, an insecure cookie or
  a wildcard CORS origin each refuse to start, naming the problem and its consequence.

---

## 12. Audit results

Performed against the checklist in the brief.

| Check | Result |
|---|---|
| SQL injection | **Clean.** ORM throughout; one parameterless `text("SELECT 1")` |
| XSS | **Clean.** React escaping; no user-supplied HTML; templates escaped |
| CSRF | **Protected.** Signed double-submit on the two cookie-authenticated endpoints |
| CORS misconfiguration | **Protected.** Exact allowlist; `*` refused at startup |
| JWT misuse | **Protected.** Algorithm pinned; `typ`, `iss`, `aud`, `exp` all required |
| Refresh token theft | **Detected.** Rotation with reuse detection → family revocation |
| OAuth account takeover | **Protected.** No email-based merging; explicit linking only |
| Open redirect | **Protected.** Origin allowlist, exact match, not prefix |
| Credential leakage | **Protected.** Log redaction + Sentry scrubbing; no tokens in URLs |
| Password storage | **Protected.** Argon2id, per-password salt, rehash on login |
| Rate-limit bypass | **Protected.** Redis-backed; `X-Forwarded-For` counted from the right |
| IDOR | **Protected.** Ownership enforced server-side; tested from another account |
| Broken ownership checks | **Protected.** One function; tested for read, write and listing |
| Secret exposure | **Fixed.** `.gitignore` admitted `.env.production` — corrected |
| Unsafe file access | **Removed.** No file-backed store remains |
| Debug mode | **Clean.** No debug flags; errors return a request id, never a trace |
| Verbose production errors | **Clean.** Internal text logged, never returned |

Two findings were fixed during the work rather than merely noted:

1. **`.env.production` was not gitignored.** The rules enumerated three specific filenames
   and missed the one that holds every production secret.
2. **Registration was an enumeration oracle.** It returned a session for a new address and
   none for an existing one. Restructured; see §4.

Two accepted risks, both stated above rather than hidden: the analysis console is not
owner-scoped (§7), and the rate limiter fails open on a Redis outage (§8).

---

## 13. Reporting

Security issues should go to the maintainers privately rather than to a public tracker.
Include the `X-Request-ID` from the response if the report concerns a specific request — it
joins the Nginx log, the backend log and the trace for that one call.
