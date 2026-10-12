# CLAUDE.md — labscloud-chess

Private two-player chess for Harry and his partner at `chess.labscloud.uk`. Python Worker + Durable Objects on Cloudflare's free tier, Cloudflare Access one-time-PIN login, vanilla-JS board in the browser. Built entirely from Claude's workspace → GitHub → GitHub Actions → Cloudflare; **nothing runs on Harry's PC or the Raspberry Pi.** British English in all prose, UI text and docs.

## Read first, every session

1. `docs/progress.md` — where we are, what's next, open questions.
2. `docs/tasks.md` — the checklist; work on one task ID at a time.
3. Then, as the task needs: `docs/requirements.md` (what), `docs/protocol.md` + `docs/protocol.schema.json` (contract), `docs/data-model.md`, `docs/platform-notes.md` (**the only trusted source for Cloudflare/Pyodide APIs**), `docs/test-plan.md`, `docs/ui-spec.md`, `docs/rules-catalogue.md`, `docs/adr/`.

Investigate the actual files before answering questions about the code or changing it. Don't rely on memory of earlier sessions.

## Commands

| Purpose | Command |
|---|---|
| All fast gates (lint, format check, types, unit + contract tests, coverage, traceability) | `uv run ./scripts/check.sh` |
| Integration tests (dev server; CI also runs them against `pywrangler dev` via `BASE_URL`) | `uv run pytest tests/integration` |
| Browser tests (CI runs Chromium + WebKit) | `CHROMIUM_PATH=… uv run pytest tests/e2e` locally; `E2E_BROWSERS=chromium,webkit BASE_URL=…` in CI |
| Local dev server | `PYTHONPATH=src:. uv run python -m devserver.server --port 8787`, then open `/api/me?as=harry` once |
| Bundle check | `uv run pywrangler deploy --dry-run` |

The workspace may not be able to run `pywrangler dev` (restricted network). Then push and read CI results; never claim an integration or e2e test passed without seeing it pass.

## Layout

```text
src/entry.py          Worker entry: config, key cache, web.handle, WebSocket hand-off → GameRoom
src/game_room.py      GameRoom Durable Object (thin glue → app.room.GameRoomCore)
src/lobby.py          Lobby Durable Object (thin glue → app.lobby_core.LobbyCore)
src/glue.py           Pyodide/SDK adapters: DO SQLite storage, sockets, RPC over stub.fetch
src/app/              PURE PYTHON services, no Cloudflare imports:
                      web.py (routing, auth gate, REST, upgrade checks), auth.py + rsa.py (Access JWT),
                      config.py, game_service.py (one game in SQLite), room.py (WebSocket behaviour),
                      lobby_service.py + lobby_core.py (names, prefs, index, stats, emails),
                      notify.py (email copy), storage.py, log.py
src/chess_core/       PURE PYTHON rules wrapper, protocol parser/builders, PGN writer
src/chess/            vendored python-chess 1.11.2 core (GPL-3.0; ADR-0004) — don't edit
devserver/            CPython stand-in for the Workers runtime (hub.py) + aiohttp server (server.py)
public/               index.html, game.html, diag.html, css/, js/ (ES modules), fonts/, icons/, _headers
tests/                unit/, contract/, integration/, e2e/, js/ (node:test), fixtures/, traceability.json
scripts/              check.sh (all fast gates), check_traceability.py
docs/                 specs, ADRs, progress
```

## Engineering rules (and why)

- **`chess_core` never imports `workers`, `js` or `pyodide`.** That keeps the hardest logic testable in plain CPython in seconds.
- **The server is authoritative.** The browser renders the latest `state` and never decides legality or outcome; anything else can be cheated or drift.
- **Hibernation-safe.** In-memory state disappears whenever the Durable Object is evicted, so every handler must work from SQLite + socket attachments alone. Nothing is cached in memory at all, so every message already takes the post-eviction path (test-plan §4.3).
- **CPU-aware.** Workers Free allows 10 ms CPU per invocation. Never replay the move list on the hot path; use `current_fen` + the `positions` counts (ADR-0007).
- **Canonical UCI only.** Check moves against the set of `m.uci()` strings, because python-chess also accepts `e1h1` for castling.
- **Module top level is side-effect free.** Python Workers snapshot memory at deploy, so no network, randomness, clock reads or `env` access at import time.
- **Consume SQL cursors before any `await`** (`.toArray()`), because cursors held across `await` lose isolation.
- **Identity is the verified JWT only.** Never trust client headers; store and log player keys (`harry`/`partner`), never email addresses, JWTs or secrets.
- **Development-only switches** (`?as=` bypass, `/diag`, `/api/diag/move`) are honoured only outside production (`?as=` only in development), and tests prove they're ignored otherwise.
- **State-changing REST requests** must be same-origin JSON (`web._write_guard`); Access's cookie is `SameSite=None`.
- **Migrations are additive.** Never rename or delete a Durable Object class or column; bump `meta.schema_version`.
- **Pin everything.** Exact versions in `uv.lock` and `package-lock.json` (Wrangler), a fixed `compatibility_date`, GitHub Actions by commit SHA, self-hosted fonts with their versions and licences.
- **Minimal scope.** Build what the task's acceptance criteria require. No speculative options, abstractions, or features outside `docs/requirements.md`.
- **Verify platform claims.** If an API isn't in `docs/platform-notes.md` with [Docs] or [Tested] evidence, check the current Cloudflare docs or prove it with a test, then add it there before relying on it.

## Workflow per task

1. Read the task's requirements and the relevant spec sections.
2. State a short plan in the PR description.
3. Write or extend tests (they should fail first), then implement.
4. `uv run ./scripts/check.sh` green in the workspace.
5. Commit on `task/T-0xx-name`, push, open a PR, wait for CI, fix until green.
6. Update `tests/traceability.json` statuses, tick `docs/tasks.md`, add a `docs/progress.md` entry; write or update an ADR if a decision changed.

## Definition of Done

Acceptance criteria met and traced to REQ IDs · tests written first and all green in CI (unit, contract, JS, integration vs dev server and `pywrangler dev`, e2e, dry-run) · no tests removed or weakened · coverage gates met · versions pinned · docs updated · for UI changes, CI screenshots reviewed and staging `/healthz` shows the commit.

## Stop and ask Harry when

- A requirement is ambiguous or contradicts another document.
- A test seems wrong, or passing it would need a hack or a hard-coded value.
- A spike misses its exit criterion (don't apply the fallback silently).
- An action is hard to undo or visible to others: production deploy/tag, deleting data, force-push, changing Access, DNS, Email Routing or secrets.
- Anything would cost money.

## Never

- Delete, skip or weaken a test to get green.
- Deploy to production without Harry saying "ship it".
- Put secrets, emails or JWTs in code, logs, fixtures or commits.
- Add a runtime request to a third-party domain from the browser.
- Add TypeScript, a JS bundler or a JS chess-rules library.
