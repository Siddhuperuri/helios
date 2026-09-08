# Helios frontend.
#
# Three stages so that the runtime image carries neither the dev dependencies nor the
# source: install, build, then copy only what the server actually needs. Next's standalone
# output makes that last step exact — it traces the modules the server reaches and emits
# just those, which is a fraction of `node_modules`.
#
# Base images are pinned to an exact patch version, never to `latest` or to a floating
# minor. That is the minimum. A stronger pin is by digest — `node:20.18.1-bookworm-slim`
# is itself rebuilt periodically, so two builds a week apart can differ from identical
# source — and the way to adopt one is:
#
#     docker buildx imagetools inspect node:20.18.1-bookworm-slim --format '{{.Manifest.Digest}}'
#
# then append the resulting digest to the FROM lines. Digests are deliberately not
# committed here unresolved: a wrong one fails the build in a way that looks like a
# registry problem, and refreshing them is a reviewed change rather than a guess.

# ---------------------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------------------
FROM node:20.18.1-bookworm-slim AS deps

WORKDIR /app

# `npm ci` rather than `npm install`: it installs exactly what the lockfile records and
# fails if the lockfile and package.json disagree. A build that can silently resolve a
# different dependency tree than the one that was reviewed is not a reproducible build.
COPY package.json package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------
FROM node:20.18.1-bookworm-slim AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_ variables are compiled into the bundle, so they are build-time inputs
# rather than runtime configuration. Left empty on purpose: empty means "same origin",
# which is how the deployed topology works — Nginx routes /api/* to the backend cluster
# and everything else here, so the two share an origin and the refresh cookie travels.
ENV NEXT_PUBLIC_API_BASE="" \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production

RUN npm run build

# ---------------------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------------------
FROM node:20.18.1-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apt-get update \
 && apt-get install --no-install-recommends -y curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin helios

WORKDIR /app

# The standalone bundle plus the two asset trees it does not trace. Nothing else from the
# build stage reaches this image — no source, no dev dependencies, no build cache.
COPY --from=builder --chown=helios:helios /app/.next/standalone ./
COPY --from=builder --chown=helios:helios /app/.next/static ./.next/static

# There is deliberately no `public/` copy. This project has no static assets to serve from
# one — the icon set is drawn inline and the fonts are self-hosted by next/font, both of
# which end up in the traced bundle. A COPY of a directory that does not exist fails the
# build, so add the line back alongside the first asset rather than pre-emptively.

USER helios

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/ >/dev/null || exit 1

# The standalone output ships its own minimal server rather than invoking the Next CLI.
CMD ["node", "server.js"]
