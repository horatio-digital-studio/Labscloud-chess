# Progress log — labscloud-chess

Newest session first. Each entry: what was done, decisions, what's next, open questions, last CI result. Keep entries short; detail belongs in commits, PRs and ADRs.

---

## Session 2026-10-12 (3) — Build, verify, audit, fix, re-verify

**Decision from Harry:** design option A "Clubroom". Build everything from the docs.

**Built**
- Backend: pure services in `src/app/` (web routing + auth gate, Access JWT verification in pure Python RS256, game service with takebacks/draws/rematch, room and lobby cores, email templates), thin Durable Object glue checked against the SDK source, `devserver/` stand-in for local tests.
- Frontend (option A): lobby, board page, diagnostics page; hand-rolled board with tap, drag, promotion picker, keyboard and screen-reader support; self-hosted fonts; PWA manifest and icons.
- CI/CD: `ci.yml` (fast gates, integration against the dev server and `pywrangler dev`, Chromium + WebKit e2e with screenshots, bundle dry-run), `deploy-staging.yml`, `deploy-prod.yml`, `rollback.yml`, reusable `_deploy.yml`; actions pinned by SHA, Wrangler pinned in `package-lock.json`.

**Verified in the workspace:** 412 unit + contract tests (97 % branch coverage), 26 JS tests, 11 integration tests against the dev server, 19 browser tests in Chromium, ruff, pyright (0 errors), traceability (83 requirements, 0 problems), actionlint clean. PGN output round-tripped through python-chess's reader on 300 random games.

**Audit (two independent reviewers, backend and frontend) → fixed, each with a regression test**
- Backend: production deploy could fall back to the staging AUD; CSRF on `POST /api/games` (Access cookie is `SameSite=None`) → same-origin JSON guard; lobby game index could stay stale after a failed summary call → resync on `hello` + ordering guard; overlapping rematch requests could create two rooms → reserve the index row first; names stale in PGN/snapshot; `since_ply: null` accepted; C1 control characters in names; logs missing `game_id`/`ply`.
- Frontend: "Sending…" cleared by unrelated states; takeback outline on the wrong move; board unusable via screen-reader activate; focus lost on re-render (keyboard resign impossible); signed-out pill overflowing at 320 px; iOS audio unlock; promotion focus and 320 px overflow; misleading name-save error; signed-out shown as "not found"; no WebSocket connect timeout; font caching.
- Found by my own tests before the audit: a1 was rendered light (square-colour parity bug); `/game.html` asset fetch would 307 under `html_handling` (now fetches `/game`).

**Not verifiable here (needs CI or Harry)**
- `pywrangler dev`/real Pyodide runtime (blocked in the workspace) — first CI run is the proof for `src/entry.py`, `game_room.py`, `lobby.py`, `glue.py`.
- WebKit e2e; deploys; Access login; phone UAT.

**Next**
1. Harry sends the GitHub repo name (H-01) → push → read the first CI run and fix anything the real runtime shows.
2. Harry completes H-02…H-05 (secrets) → first staging deploy.

**CI:** not run yet (no repo).

---

## Session 2026-10-12 (2) — Harry's decisions + design options

**Decisions from Harry**
- Display names: each player types their own in a name box (REQ-GAME-09; `PATCH /api/me` takes `name`; stored in the Lobby).
- Abort dropped (REQ-ACT-07 retired; `abort`, `aborted`, `CANNOT_ABORT`, `can_abort` removed).
- Takebacks in, with the opponent's agreement (REQ-ACT-11 to 14, ADR-0011). One ply undone if it's the opponent's turn, two if they've already replied. Restored from stored FENs, no replay; checked against python-chess on 47,177 random move/takeback steps, zero mismatches.
- "Your move" emails: on/off switch plus a gap timer, 5 min to 24 h in fixed steps (REQ-NOTIFY-06).

**Done**
- Requirements (now 83), protocol + schema (re-validated, including new negative cases), data model, UI spec, tasks, test plan (P7, E2E-16 to 18) and traceability updated.
- Design canvas *labscloud chess — UI options*: four static directions, each a lobby + game screen: A Clubroom, B Midnight, C Broadsheet, D Sunday.

**Next**
1. Harry picks a direction (D-01), or a mix.
2. Harry completes H-01 to H-03 and sends the repo name.
3. Claude records the chosen look's tokens in `docs/ui-spec.md` §7, then starts Phase 0.

**Open questions**
- Which design option (A–D)?

**CI:** not set up yet.

---

## Session 2026-10-12 — planning documents (no code yet)

**Done**
- Architecture (`docs/architecture.md`) and build plan (`docs/build-plan.md`) agreed in principle.
- Supporting documents written: `CLAUDE.md`, requirements (79 IDs), protocol + JSON Schema, data model, test plan + traceability, platform notes, rules catalogue + fixture file, UI spec, runbook, email copy, ADRs 0001–0010, this log, task list, changelog.
- Rules catalogue machine-verified against python-chess 1.11.2: 55 positions + 9 wrapper cases, zero mismatches. Three of my first-draft expectations were wrong and were caught by the check (K+N v K is insufficient material; the first queen-promotion "stalemate" was actually mate; R×R left K+R v K, which is sufficient).
- JSON Schema validated: every example in `protocol.md` passes; invalid examples (extra field, unknown type, missing `ply`, bad error code, bad colour) fail as intended.
- Repetition-by-FEN-key approach checked against python-chess on 77,044 positions, zero mismatches (basis for ADR-0007).

**Decisions made in this session**
- Player identity stored as keys `harry`/`partner`, never email (data model §5). `PLAYERS_JSON` format changed accordingly; supersedes build-plan H-05 example.
- Castling accepted only as `e1g1`-style UCI: python-chess would otherwise also accept `e1h1` (catalogue W08).
- `can_claim_draw` is current-position only (REQ-RULE-08), not python-chess's "claim by next move".
- `/game/*` must run the Worker first (SPA fallback would otherwise serve `index.html`).
- Hibernation tested by running the whole integration suite a second time with a development-only forced-rebuild switch.

**Next**
1. Harry reviews `docs/requirements.md` (four open questions at the end), `docs/protocol.md` and `docs/ui-spec.md`.
2. Harry completes H-01 to H-03 and sends the repo name.
3. Claude starts Phase 0 (T-001 to T-007).

**Open questions**
- Partner's display name.
- ~~Keep or drop `abort`~~ → dropped (see next session).
- Takebacks: confirm out of scope.
- 30-minute nudge cooldown OK?

**CI:** not set up yet.
