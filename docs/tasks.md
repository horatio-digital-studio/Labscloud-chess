# Tasks — labscloud-chess

**Source:** `docs/build-plan.md` Part C. This is the live checklist; tick items only when the Definition of Done (build plan Part D) is met. One task per branch and PR: `task/T-0xx-short-name`.

**Legend:** `[ ]` not started · `[~]` built and passing every check in Claude's workspace, waiting for its first green CI run (then ticked) · `[x]` done.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done · **H-** = Harry's setup step.

---

## Harry's setup

- [ ] **H-01** Empty private repo `labscloud-chess` created; `owner/repo` sent to Claude
- [ ] **H-02** Cloudflare API token (Edit Cloudflare Workers template, scoped to account + `labscloud.uk`)
- [ ] **H-03** GitHub secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
- [ ] **H-04** Zero Trust org + one-time PIN + two Access apps (staging, production) + `/healthz` Bypass policy; send AUD tags, team domain, service-token availability
- [ ] **H-05** GitHub secrets `ACCESS_AUD_STAGING`, `ACCESS_AUD_PROD`, `PLAYERS_JSON` (format in `docs/data-model.md` §4)
- [ ] **H-06** Email Routing on `labscloud.uk` (after checking MX), both addresses verified as destinations
- [ ] **H-07** UAT on phones at each milestone
- [ ] **D-01** Pick a visual direction (A Clubroom, B Midnight, C Broadsheet, D Sunday) on the *labscloud chess — UI options* canvas; Claude then records its tokens in `docs/ui-spec.md` §7

## Phase 0 — Foundations

- [~] **T-001** Scaffold with `uv` + `pywrangler init`; pin Python, `workers-py`, `chess==1.11.2`, `compatibility_date`; commit `uv.lock` · NFR-04
- [~] **T-002** ruff, pyright (strict on `src/chess_core`), pytest + pytest-cov + hypothesis, pre-commit; `scripts/check.sh` · —
- [~] **T-003** Commit these docs into `docs/` and `CLAUDE.md` at repo root · —
- [~] **T-004** `/healthz` → `{ok, version, commit, env}`; `VERSION`/`COMMIT` vars injected by CI · AUTH-07
- [~] **T-005** `ci.yml`: lint, types, unit, contract, traceability check (`scripts/check_traceability.py`), integration (dev server + `pywrangler dev`), e2e, `deploy --dry-run` · OPS-03
- [~] **T-006** `deploy-staging.yml` (push to `main`), `deploy-prod.yml` (`v*` tags), `rollback.yml`; secrets uploaded with `deploy --secrets-file`; `/healthz` commit check; `workers_dev: false`, `preview_urls: false` · OPS-01/02/03, AUTH-11
- [~] **T-007** Bug-report issue form + PR template with DoD checklist · —
- [ ] **M0** `chess-staging.labscloud.uk/healthz` shows the latest commit, deployed by CI

## Phase 1 — Spikes (each ends in an ADR update)

- [ ] **S-01** python-chess bundles and imports in Pyodide; `/healthz?probe=chess` → 20 · ADR-0004
- [ ] **S-02** Python DO + hibernating WebSocket echo; confirm `get_websockets` vs `getWebSockets`, tag arguments, and Python RPC to DOs · ADR-0002
- [ ] **S-03** Access JWT RS256 verify via WebCrypto from Python · ADR-0003
- [ ] **S-04** CPU budget: `/diag` 150-ply replay with forced rebuild; zero *Exceeded CPU*; record p95 · ADR-0007, NFR-02
- [ ] **S-05** Email binding send from Python to one verified address (after H-06) · ADR-0008
- [ ] **M1** All spikes pass; `platform-notes.md` [Inferred] lines resolved

## Phase 2 — Chess core (pure Python)

- [~] **T-010** Rules catalogue in place (`tests/fixtures/positions.py` — **already written and verified**, see `docs/rules-catalogue.md`) and the parametrised tests that use it · RULE-01
- [~] **T-011** `ChessGame`: `apply` (validation order), `legal_moves` (canonical strings), status order, `can_claim_draw` (REQ-RULE-08 definition), repetition counts, `from_storage` · RULE-02…10, RT-09
- [~] **T-012** Protocol module: dataclasses, strict `parse`, `to_json`; contract tests against `protocol.schema.json`; golden fixtures · RT-08
- [~] **T-013** PGN export · GAME-06
- [~] **T-014** Property tests P1–P7 (`docs/test-plan.md` §4.2) · RULE-10, RT-06, ACT-12/14
- [ ] **M2** Chess core green in CI, coverage gates met

## Phase 3 — Server

- [~] **T-020** `entry.py` router + `auth.py`; `run_worker_first` = `/api/*`, `/ws/*`, `/game/*`, `/healthz`, `/diag*`; `/game/*` served via `ASSETS.fetch(".../game")`; security headers; Origin check · AUTH-02…10
- [~] **T-021** `GameRoom` part 1: schema + `meta`, init (start position counted once), accept socket + attachment, `hello`, `move`, broadcast, presence, rebuild (no in-memory state, so no `FORCE_REBUILD` switch; test-plan §4.3) · RULE-03/06, RT-01…06/09
- [~] **T-022** `GameRoom` part 2: resign, draw offer/accept/decline, claim, takebacks (ADR-0011), rematch · ACT-01…14 (ACT-07 retired), RULE-09
- [~] **T-023** `Lobby`: display names, prefs, create game, list, stats, summary upsert from GameRoom · GAME-01…09
- [~] **T-024** REST endpoints per `docs/protocol.md` §2 · GAME-*, AUTH-07
- [~] **T-025** Resilience + race tests (restart mid-game, double submit, crossing offers, move racing a takeback, simultaneous rematch, two sockets per player) · RT-05/06/09, ACT-05/08/12/13
- [~] **T-026** Structured logging (player key, never email/JWT) + `observability` on · NFR-06
- [ ] **M3** Scripted two-player game passes against staging (`/diag`, or CI if service tokens exist)

## Phase 4 — Frontend

- [x] **T-030** ~~Vendor `cm-chessboard`~~ superseded: hand-rolled board, self-hosted fonts (ADR-0005 revised) · NFR-08
- [~] **T-031** Lobby page incl. name box (states in `docs/ui-spec.md` §3) · GAME-03/04/05/09
- [~] **T-032** Board page incl. takeback banners (states in `docs/ui-spec.md` §4) · UI-01…05, UI-11, UI-14, ACT-11…13
- [~] **T-033** WebSocket client state machine + reconnect · UI-06/07
- [~] **T-034** Wake lock, sounds, vibration, safe areas, PWA manifest + icons · UI-08/09/10/13
- [~] **T-035** Playwright e2e E2E-01…15 (Chromium + WebKit), screenshots as artefacts
- [~] **T-036** Accessibility (keyboard, live region, screen-reader activation done; **axe scan still to add**) · UI-12
- [ ] **M4** UAT passed on two iPhones with FaceTime

## Phase 5 — Launch

- [ ] **T-040** Production config; tag `v0.1.0` · OPS-01
- [ ] **T-041** Both players log in and play one full game on production
- [ ] **T-042** `docs/runbook.md` verified by Harry on a phone
- [ ] **M5** Live at `chess.labscloud.uk`

## Phase 6 — Email

- [~] **T-050** (code and tests done; the `send_email` binding is added to `wrangler.jsonc` in Phase 6, after H-06) `notify.py` + templates from `docs/email-copy.md`; snapshot tests · NOTIFY-01/03/05
- [~] **T-051** Throttle rules + failure handling · NOTIFY-02/04
- [~] **T-052** Email switches + move-email gap timer in the lobby · NOTIFY-06
- [ ] **M6** Tag `v0.2.0`

## Phase 7 — Backlog (unprioritised)

- [ ] Clocks via DO alarms (needs new requirements)
- [ ] Captured pieces + material count
- [ ] Board/piece themes
- [ ] Stockfish WASM post-game analysis (client-side)
- [ ] Web Push for the installed PWA
- [ ] Weekly PGN archive
- [ ] Puzzles
