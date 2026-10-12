# Test plan — labscloud-chess

**Status:** v1 draft — 12 October 2026
**Companions:** `docs/requirements.md` (what), `tests/traceability.json` (which test proves which requirement), `docs/rules-catalogue.md` (chess fixtures).

## 1. Principles

1. **Every requirement is proven by at least one named test** listed in `tests/traceability.json`. A requirement with no passing test is not done.
2. **Tests come first or alongside.** For a bug, the first commit is a failing test that reproduces it.
3. **Tests are never deleted, skipped or weakened to make code pass.** If a test looks wrong, stop and raise it with Harry. A test may change only with a stated reason in the PR.
4. **No hidden retries.** A flaky test is fixed or quarantined with a linked GitHub issue; CI never silently re-runs failures.
5. **The pure core is tested where it's cheapest.** Anything that doesn't need Cloudflare is a unit test that runs in seconds in Claude's workspace.
6. **Test the contract from both sides.** The server's output and the client's expectations are both checked against `docs/protocol.schema.json`.

## 2. Layers

| Layer | Folder | Tools | Runs where | What it covers |
|---|---|---|---|---|
| Unit | `tests/unit/` | pytest, hypothesis | Workspace + CI | `chess_core` (rules wrapper, repetition, status, PGN), protocol parsing, auth (JWT verification with a locally generated key), email rendering, throttle logic. |
| Contract | `tests/contract/` | pytest, jsonschema | Workspace + CI | Golden JSON fixtures for every message type validate against the schema; protocol module output validates; every error code has a producing test. |
| Integration | `tests/integration/` | pytest, `websockets`, `httpx`, `pywrangler dev` | CI | Real Worker + Durable Objects + SQLite in the local runtime, using the dev auth bypass. |
| End-to-end | `tests/e2e/` | pytest-playwright (Chromium + **WebKit**) | CI | Two browser contexts playing each other; desktop and iPhone-sized viewports. WebKit is the closest CI proxy for iPhone Safari. |
| Deployed | CI after deploy; `/diag` on phone | curl, browser | Staging, production | `/healthz` commit check; CPU-budget replay (S-04); real Access login. |
| Acceptance | — | UAT script | Two iPhones, FaceTime on | Feel, latency, reconnect after app switching, PIN emails. |

```text
tests/
├── fixtures/
│   ├── positions.py          # verified rules catalogue (generated; do not hand-edit)
│   ├── games.py              # complete PGN games for replay tests
│   ├── messages/             # golden JSON per message type
│   └── jwt_keys.py           # throwaway RSA key pair + JWK builder for auth tests
├── unit/
├── contract/
├── integration/
│   └── conftest.py           # starts pywrangler dev, waits for /healthz, tears down
├── e2e/
│   └── conftest.py           # two-player browser fixture
└── traceability.json
```

## 3. Commands

| Command | Where | What |
|---|---|---|
| `uv run ./scripts/check.sh` | workspace, CI | ruff check, ruff format --check, pyright, `pytest tests/unit tests/contract` with a 95 % coverage gate, `node --test tests/js`, traceability check |
| `uv run pytest tests/integration` | workspace, CI | Starts the Python dev server (`devserver/`) on a free port and runs the protocol suite against it |
| `BASE_URL=http://localhost:8787 uv run pytest tests/integration` | CI | The same suite against `pywrangler dev` (the real Python Workers runtime) |
| `E2E_BROWSERS=chromium,webkit BASE_URL=… uv run pytest tests/e2e` | CI | Playwright, both engines; screenshots to `$E2E_ARTIFACTS`. Locally: `CHROMIUM_PATH=/path/to/chromium uv run pytest tests/e2e` |

## 4. Strategies for the hard parts

### 4.1 Chess rules
- `tests/unit/test_rules_catalogue.py` is parametrised over every entry in `tests/fixtures/positions.py`. For each: build the position, apply the moves, assert every expectation against **our** `ChessGame` (not python-chess directly), including `after_move`.
- `tests/unit/test_wrapper_cases.py` is parametrised over `WRAPPER_CASES` (turn → ply → format → legality order).
- Full-game fixtures: Scholar's mate, Fool's mate, a 100+ ply real game ending in a draw by agreement, a game reaching the 75-move rule.

### 4.2 Property-based tests (hypothesis)
Each runs at least 500 random legal games per CI run:
- P1: applying any legal move never raises, and the FEN after each move equals a replay from scratch.
- P2: `apply` never accepts a move outside the legal UCI set (random strings, random squares, random promotion letters).
- P3: our repetition count from `positions` equals `board.is_repetition(3)` and `is_fivefold_repetition()` at every ply.
- P4: building `ChessGame.from_storage(current_fen, counts)` mid-game gives the same `legal`, `status`, `check` and `can_claim_draw` as the live object.
- P5: PGN export re-parses to the identical move list.
- P6: protocol `parse(to_json(msg)) == msg` for every generated client message; any mutation that adds a field fails with `BAD_MESSAGE`.
- P7: random games with random accepted takebacks (one or two plies): restored FEN, legal moves and repetition answers equal python-chess after `board.pop()`. (Pre-checked in the workspace on 47,177 steps, zero mismatches; ADR-0011.)

### 4.3 Hibernation safety (REQ-RT-06)
Eviction can't be forced on demand in local dev. **Decision (12 Oct 2026):** instead of a `FORCE_REBUILD` switch, there is no in-memory state to rebuild. `GameService`, `GameRoomCore` and `LobbyCore` read everything they need from SQLite and socket attachments on every message, so every message already takes the "after eviction" path. This is proved by:
- `tests/unit/test_room.py::test_eviction_gives_identical_state` (the dev hub throws away every core object and rebuilds from the same SQLite) and the property test P4 (a fresh `GameService` over the same storage gives identical states);
- `tests/integration/test_live.py::test_reconnect_gets_identical_state` against both the dev server and `pywrangler dev`.
- `test_restart_mid_game`: kill and restart `pywrangler dev` mid-game (local SQLite persists), reconnect both clients, compare the snapshot with the one before restart.

### 4.4 Auth (REQ-AUTH-*)
- Unit tests generate an RSA key pair in `tests/fixtures/jwt_keys.py`, sign tokens, and inject a fake key-set fetcher. Cases: valid; no header; malformed; bad signature; expired; `nbf` in future; wrong `aud`; wrong `iss`; unknown `kid` then refetch succeeds; unknown `kid` after refetch → reject; valid token for a non-player email; email case/whitespace normalisation.
- `test_dev_bypass_ignored_outside_development`: with `APP_ENV` = `staging` and `production`, `?as=harry` without a JWT returns `403 UNAUTHORISED`.
- Deployed: Harry checks that an incognito visit to staging shows the Access login, and that `/healthz` is the only path reachable without it.

### 4.5 Concurrency and races
- Two sockets for the same player both receive every broadcast (REQ-RT-05).
- Double submit: send the same `move` twice back-to-back → first accepted, second `STALE_PLY`, ply advanced once (REQ-RT-09).
- Crossing draw offers: both players send `draw_offer` at the same time → exactly one `draw_agreed` (REQ-ACT-05).
- Rematch votes arriving together create exactly one new game (REQ-ACT-08).
- Move arriving after resignation → `GAME_OVER`.
- A move sent while the opponent is accepting a takeback: whichever arrives first wins; the other gets `STALE_PLY` (or clears the request), and both clients converge on the same `state`.
- Takeback request then the requester's opponent moves: request cleared, no undo.

### 4.6 End-to-end scenarios

| ID | Scenario | Viewports | Requirements |
|---|---|---|---|
| E2E-01 | Harry creates a game (white), partner opens it from the lobby, Scholar's mate by tap-tap; both see checkmate and result | desktop, iPhone | GAME-01/04, UI-02/05, RT-01 |
| E2E-02 | Castling by drag, en passant by tap | desktop | UI-02, RULE-01 |
| E2E-03 | Promotion: picker appears, choose knight, board shows knight | iPhone | UI-04 |
| E2E-04 | Illegal drop snaps back; nothing sent | desktop | UI-03, UI-14 |
| E2E-05 | Legal-target highlights appear only on your turn | iPhone | UI-03, RT-03 |
| E2E-06 | Resign needs confirmation; cancelling does nothing | iPhone | UI-11, ACT-01 |
| E2E-07 | Draw offer → decline → offer → accept | desktop | ACT-02/03/06 |
| E2E-08 | Go offline 10 s mid-game (`context.set_offline`), opponent moves meanwhile, back online → "Reconnecting…" then correct board, no duplicate moves | iPhone | UI-06/07, RT-02 |
| E2E-09 | Rematch: both click, both navigate to the new game with colours swapped | desktop | ACT-08 |
| E2E-10 | Lobby shows "Your move" on the right games, and the head-to-head score after results | desktop | GAME-03/04/05 |
| E2E-11 | Portrait 320, 375, 390 and 430 px wide: no horizontal scroll, controls visible | iPhone sizes | UI-10 |
| E2E-12 | Sound off by default; turning it on survives reload | desktop | UI-09 |
| E2E-13 | Keyboard-only move; opponent move announced in the live region | desktop | UI-12 |
| E2E-14 | No requests leave the origin (Playwright request log) | both | NFR-08 |
| E2E-15 | CSP and security headers present on HTML | desktop | AUTH-10 |
| E2E-16 | Takeback: request → opponent sees banner → Allow → both boards back one move, move list shorter; then request → Decline | iPhone | ACT-11/12/13/14 |
| E2E-17 | Change display name in the lobby; opponent sees the new name after refresh; invalid names rejected | desktop | GAME-09 |
| E2E-18 | Move-email switch off disables the gap timer; timer steps through its values and persists | iPhone | NOTIFY-06 |

Each e2e run uploads screenshots of every scenario's final state as CI artefacts, attached to the PR for visual review.

### 4.7 CPU budget (REQ-NFR-02)
- `scripts/bench_engine.py` reports CPython timings for the hot path and rebuild (workspace baseline: hot path 0.08 ms median; see `platform-notes.md` §9).
- S-04 on staging: `/diag` replays a stored 150-ply game move by move against a throwaway GameRoom with forced rebuild on every message (worst case), then Harry checks Workers metrics for *Exceeded CPU Time Limits* = 0 and notes p95 CPU time. Repeated before each production tag.

## 5. Coverage gates (CI fails below these)

| Scope | Gate |
|---|---|
| `src/chess_core/` | ≥ 95% branch coverage |
| `src/` overall (unit + contract) | ≥ 85% line coverage |
| Error codes | Every code in `docs/protocol.md` §6 produced by at least one test |
| Requirements | Every **M** requirement has `status: passing` in `traceability.json` before `v0.1.0`; every **S** before `v0.2.0` |

A script `scripts/check_traceability.py` (T-005) reads `traceability.json`, confirms every REQ ID in `requirements.md` appears, and that each listed test exists in the collected pytest node IDs. CI fails on any gap.

## 6. CI pipeline

```text
PR / push ──► lint + types + unit + contract  (≈1 min)
          ──► traceability check
          ──► integration (normal)   ┐
          ──► integration (forced rebuild) ├─ parallel jobs (≈3–5 min)
          ──► e2e chromium + webkit  ┘   (only when src/ or public/ changed)
          ──► pywrangler deploy --dry-run
main      ──► all of the above ──► deploy staging ──► /healthz commit check
tag v*    ──► all of the above ──► deploy production ──► /healthz commit check
```

## 7. Acceptance (phones)

Run the UAT script in `docs/build-plan.md` Part E before every production tag. Record date, devices, network and outcome in `docs/progress.md`. Any failure becomes a GitHub issue using the bug template, and a failing test before the fix.

## 8. What is deliberately not tested

- python-chess's own move generation in general (it has its own extensive suite). We test the catalogue situations and our wrapper.
- Cloudflare Access's PIN flow itself (vendor-owned). We test that our Worker rejects anything without a valid token.
- Email deliverability beyond "arrives in both inboxes" on staging.
