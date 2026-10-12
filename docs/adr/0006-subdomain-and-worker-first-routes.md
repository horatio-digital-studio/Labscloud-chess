# ADR-0006: Serve on `chess.labscloud.uk` with Worker-first routes

**Status:** Accepted
**Date:** 2026-10-12

## Context
The apex `labscloud.uk` is served by the Pi through a Cloudflare Tunnel. Static assets are served without invoking the Worker unless configured otherwise, and the SPA fallback would answer `/game/{id}` with `index.html`.

## Decision
Use Worker Custom Domains `chess.labscloud.uk` (production) and `chess-staging.labscloud.uk` (staging). Set `run_worker_first` to `/api/*`, `/ws/*`, `/game/*`, `/healthz` and `/diag*`. The Worker answers `/game/*` with `ASSETS.fetch("https://assets.local/game.html")` after JWT verification. `workers_dev` and `preview_urls` are off.

## Consequences
- Separate Access apps, cookies and certificates per hostname; no interplay with the Pi tunnel.
- Free Universal SSL covers one level of subdomain, which these are.
- CSS, JS and icons are still served straight from assets (fast, free) but remain behind Access.

## Alternatives considered
- `labscloud.uk/chess` path route: works, but every URL, cookie and Access rule must carry the prefix, and a misconfigured route could shadow the Pi's site.
