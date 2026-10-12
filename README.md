# labscloud chess

Private two-player chess for Harry and his partner, played on `chess.labscloud.uk` while on FaceTime.

- **Stack:** Python Cloudflare Worker + Durable Objects (free plan), Cloudflare Access one-time-PIN login, a small vanilla-JS board. No TypeScript, no build step.
- **Deploys:** push to `main` → tests → `chess-staging.labscloud.uk`. Tag `vX.Y.Z` → tests → `chess.labscloud.uk`. Rollback is a manual workflow.
- **Start here:** `CLAUDE.md` (how the code is organised and the rules for changing it), `docs/README.md` (all specs), `docs/runbook.md` (operations, secrets).

```sh
uv sync && npm ci                 # tools (Python via uv, Wrangler via npm)
uv run ./scripts/check.sh         # lint, types, unit + contract + JS tests, coverage, traceability
uv run pytest tests/integration   # protocol tests against a local dev server
PYTHONPATH=src:. uv run python -m devserver.server --port 8787   # then open /api/me?as=harry once
```

Licences: the vendored python-chess core in `src/chess/` is GPL-3.0; the fonts in `public/fonts/` are SIL OFL 1.1.
