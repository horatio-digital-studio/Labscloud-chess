# Requirements — labscloud-chess

**Status:** v1.1 — 12 October 2026 (Harry's decisions applied: names typed in by each player, abort removed, takebacks added, move-email switch with gap timer)
**Source documents:** `docs/architecture.md`, `docs/build-plan.md`
**Format:** EARS (Easy Approach to Requirements Syntax). Each requirement has a stable ID, a priority and how it is verified. Tests reference these IDs; `tests/traceability.json` maps every ID to its tests.

| EARS pattern | Shape |
|---|---|
| Ubiquitous | The system shall … |
| Event-driven | When *trigger*, the system shall … |
| State-driven | While *state*, the system shall … |
| Unwanted behaviour | If *condition*, then the system shall … |
| Optional feature | Where *feature is enabled*, the system shall … |

**Priority:** **M** = must for v0.1.0 (production launch) · **S** = should, v0.2.0 · **C** = could, backlog.
**Verified by:** **U** unit test · **I** integration test (CI, `pywrangler dev`) · **E** browser e2e (CI, Playwright) · **D** deployed check (staging) · **A** acceptance on phones (UAT script) · **R** review.

**Glossary**
- *Player*: one of the two people listed in the `PLAYERS_JSON` secret, identified internally by a stable **player key** (`harry` or `partner`), never by email.
- *`PLAYERS_JSON`*: `{"harry": {"email": "…", "name": "Harry"}, "partner": {"email": "…", "name": "…"}}`. Supersedes the shorter example in the build plan (H-05). `name` is only the starting display name; each player can change their own in the app (REQ-GAME-09).
- *Opponent*: the other player in a given game.
- *Side to move*: the colour whose turn it is.
- *Ply*: one half-move. `ply` = number of half-moves played so far.
- *Terminal status*: any status other than `waiting` or `active`.
- *Canonical UCI*: lower-case `from` + `to` square plus optional promotion letter, with castling written as the king's two-square move (`e1g1`, never `e1h1`).

---

## 1. Access and identity (AUTH)

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-AUTH-01 | When a request reaches `chess.labscloud.uk` or `chess-staging.labscloud.uk` without a valid Access session, Cloudflare Access shall require a one-time PIN sent to an allowed email before forwarding the request. | M | D, A |
| REQ-AUTH-02 | When the Worker receives any request other than `GET /healthz`, it shall verify the `Cf-Access-Jwt-Assertion` header: RS256 signature against the team's published signing keys (matched by `kid`), `aud` equal to the environment's AUD tag, `iss` equal to the team domain, and `exp` in the future. | M | U, D |
| REQ-AUTH-03 | If the JWT is missing, malformed, expired, wrongly signed, or has the wrong `aud` or `iss`, then the Worker shall respond `403` with error code `UNAUTHORISED` and shall not contact any Durable Object. | M | U |
| REQ-AUTH-04 | If the verified email does not match the `email` of any `PLAYERS_JSON` entry (case-insensitive comparison after trimming), then the Worker shall respond `403` with error code `NOT_A_PLAYER`. | M | U, I |
| REQ-AUTH-05 | When the JWT carries a `kid` the Worker has not cached, the Worker shall re-fetch the signing keys once before rejecting the token. (Access rotates keys every 6 weeks; the previous key stays valid for 7 days.) | M | U |
| REQ-AUTH-06 | While `APP_ENV` equals `development`, the Worker shall accept `?as=harry` or `?as=partner` (mapped to the `PLAYERS_JSON` entry with that key) in place of a JWT. In any other environment the `as` parameter shall be ignored. | M | U, I |
| REQ-AUTH-07 | When the Worker receives `GET /healthz`, it shall respond `200` with exactly `{ok, version, commit, env}` and no other data, without requiring a JWT. | M | U, D |
| REQ-AUTH-08 | If a WebSocket upgrade request's `Origin` header does not equal the environment's `PUBLIC_URL`, then the Worker shall respond `403` with `BAD_ORIGIN`. | M | U, I |
| REQ-AUTH-09 | The Worker shall pass player identity to Durable Objects only as the verified player key, never by forwarding client-supplied headers. | M | U, R |
| REQ-AUTH-10 | The Worker shall add `Content-Security-Policy` (self only, no inline script), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` and `Permissions-Policy` headers to every HTML response it generates. | M | U, E |
| REQ-AUTH-11 | The deployed Worker shall have `workers_dev` and `preview_urls` disabled, so it is reachable only through the Access-protected hostnames. | M | D |

## 2. Lobby and games (GAME)

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-GAME-01 | When a player creates a game choosing `white`, `black` or `random`, the system shall create a new game in which the creator has the chosen colour (or a uniformly random one) and the opponent has the other. | M | U, I |
| REQ-GAME-02 | The system shall allow any number of games to be active at once between the two players. | M | I |
| REQ-GAME-03 | When a player requests the game list, the system shall return that player's games ordered by most recently updated first, filterable by `active` or `finished`. | M | I |
| REQ-GAME-04 | The game list shall mark each active game where it is the requesting player's turn ("Your move"). | M | I, E |
| REQ-GAME-05 | When a player requests stats, the system shall return head-to-head wins, losses and draws for each player, counting only finished games with a result. | M | U, I |
| REQ-GAME-06 | When a player requests a game's PGN, the system shall return a PGN with headers Event, Site, Date, White, Black, Result, and the full move list, that re-parses to the identical move sequence. | M | U |
| REQ-GAME-07 | If a request references a game ID that does not exist, then the system shall respond `404` with `GAME_NOT_FOUND`. | M | I |
| REQ-GAME-08 | Game IDs shall be random UUID v4 strings; the system shall not expose sequential identifiers. | M | U |
| REQ-GAME-09 | When a player saves a name in the name box, the system shall store it as that player's display name (trimmed, 1–24 characters, no control characters) and use it everywhere names appear: lobby, board, PGN and emails. Until a name is saved, the `name` from `PLAYERS_JSON` is used. Invalid names are rejected with `BAD_REQUEST`. | M | U, I, E |

## 3. Chess rules and move handling (RULE)

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-RULE-01 | The system shall enforce standard FIDE chess rules as implemented by python-chess, including castling, en passant, promotion, check, checkmate and stalemate, as listed in `docs/rules-catalogue.md`. | M | U |
| REQ-RULE-02 | When a `move` message is received, the system shall validate in this order and return the first failing code: game not terminal (`GAME_OVER`), sender is side to move (`NOT_YOUR_TURN`), `ply` equals current ply (`STALE_PLY`), UCI matches `^[a-h][1-8][a-h][1-8][qrbn]?$` (`BAD_FORMAT`), UCI is a canonical legal move (`ILLEGAL_MOVE`). | M | U, I |
| REQ-RULE-03 | If a move is rejected, then the system shall leave the game state unchanged and send the `error` only to the WebSocket that sent the move. | M | U, I |
| REQ-RULE-04 | The system shall accept castling only in canonical king-move form (`e1g1`, `e1c1`, `e8g8`, `e8c8`) and reject king-takes-rook notation with `ILLEGAL_MOVE`. | M | U |
| REQ-RULE-05 | If a pawn reaches the last rank without a promotion letter, then the system shall reject the move with `ILLEGAL_MOVE`. | M | U |
| REQ-RULE-06 | When a move is accepted, the system shall persist it before broadcasting the new state. | M | I, R |
| REQ-RULE-07 | When an accepted move produces checkmate, stalemate, insufficient material, the 75-move rule or fivefold repetition, the system shall set the corresponding terminal status and result in the same state update, checking in that order. | M | U |
| REQ-RULE-08 | While the current position has occurred at least three times, or the halfmove clock is at least 100, the system shall report `can_claim_draw: true` to the side to move. | M | U |
| REQ-RULE-09 | When the side to move sends `claim_draw` while `can_claim_draw` is true, the system shall end the game with status `draw_claimed` and result `1/2-1/2`; otherwise it shall reply `CANNOT_CLAIM`. | M | U, I |
| REQ-RULE-10 | The system shall detect repetition from stored position counts, without replaying the move list on each move (see ADR-0007). | M | U, R |

*Deliberate simplification (REQ-RULE-08):* FIDE also lets a player claim by declaring a move that would cause the repetition or reach 50 moves. v1 only supports claiming in the current position; the player simply makes the move and then claims.

## 4. Game actions (ACT)

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-ACT-01 | While a game is `active`, when either player sends `resign` (on either player's turn), the system shall end the game with status `resigned` and award the win to the opponent. | M | U, I |
| REQ-ACT-02 | While a game is `active` and no draw offer is pending, when a player sends `draw_offer`, the system shall record the offer from that colour. If that player's own offer is already pending, it shall reply `DRAW_ALREADY_OFFERED`. | M | U, I |
| REQ-ACT-03 | When the player who did not make a pending draw offer sends `draw_accept`, the system shall end the game with status `draw_agreed` and result `1/2-1/2`. | M | U, I |
| REQ-ACT-04 | If a player sends `draw_accept` or `draw_decline` when no offer is pending, then the system shall reply `NO_DRAW_OFFER`; if the offering player tries to accept their own offer, it shall reply `OWN_DRAW_OFFER`. | M | U |
| REQ-ACT-05 | If a player sends `draw_offer` while the opponent's offer is pending, then the system shall treat it as `draw_accept`. | M | U, I |
| REQ-ACT-06 | When the player who received a pending draw offer makes a move or sends `draw_decline`, the system shall clear the offer. | M | U |
| REQ-ACT-08 | While a game has a terminal status, when each player has sent `rematch`, the system shall create one new game with colours swapped, link it with `rematch_of`, and send `rematch_ready {game_id}` to every connected socket of the old game. | M | I, E |
| REQ-ACT-09 | If a player sends `rematch` while the game is not terminal, then the system shall reply `REMATCH_NOT_AVAILABLE`. | M | U |
| REQ-ACT-10 | If any game action other than `rematch` is received while the game is terminal, then the system shall reply `GAME_OVER`. | M | U |
| REQ-ACT-11 | While a game is `active` and the sending player has made at least one move in it, when they send `takeback_request`, the system shall record a pending takeback request from that colour. If the player has no move to take back, it shall reply `TAKEBACK_NOT_AVAILABLE`; if any takeback request is already pending, `TAKEBACK_ALREADY_REQUESTED`. | M | U, I |
| REQ-ACT-12 | When the opponent of a pending takeback request sends `takeback_accept`, the system shall undo moves back to and including the requester's most recent move (one ply if it is the opponent's turn, two plies if it is the requester's turn), restore that position exactly (including castling rights, en passant and move counters), and clear any pending draw offer. | M | U, I |
| REQ-ACT-13 | When the opponent sends `takeback_decline`, or when either player makes a move, the system shall clear a pending takeback request. Accepting or declining with no request pending replies `NO_TAKEBACK_REQUEST`; answering your own request replies `OWN_TAKEBACK_REQUEST`. | M | U, I |
| REQ-ACT-14 | Moves that were taken back shall be removed from the move list, the PGN and the repetition counts, as if they had never been played. | M | U, I |

## 5. Real-time behaviour (RT)

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-RT-01 | When a move or action is accepted, the system shall send a full `state` message to every connected socket of that game. | M | I |
| REQ-RT-02 | When a client sends `hello`, the system shall reply with a full `state` snapshot regardless of `since_ply`. | M | I |
| REQ-RT-03 | The `legal` list in `state` shall contain the side to move's canonical legal moves only on that side's sockets, and shall be empty for the other side and for terminal games. | M | U, I |
| REQ-RT-04 | When a socket connects or disconnects, the system shall send `presence` to every remaining socket of that game. | M | I |
| REQ-RT-05 | The system shall allow one player to have several sockets open on the same game (e.g. phone and laptop); all of them shall receive every broadcast. | M | I |
| REQ-RT-06 | While the Durable Object has been evicted from memory, the system shall keep WebSockets connected and, on the next message, produce a state identical to the one before eviction. | M | I |
| REQ-RT-07 | When the opponent's move is accepted, the other player's browser shall show it within 1 second at p95 under normal mobile-data conditions. | M | A |
| REQ-RT-08 | If an inbound WebSocket message is not valid JSON, exceeds 1 KB, has an unknown `type`, or has unknown or missing fields, then the system shall reply `BAD_MESSAGE` and leave state unchanged. | M | U, I |
| REQ-RT-09 | If a client resends a move that was already accepted (same `ply`), then the system shall reply `STALE_PLY` and shall not apply it twice. | M | U, I |

## 6. Client behaviour (UI)

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-UI-01 | The board shall be oriented with the player's own colour at the bottom; a flip control shall swap orientation locally. | M | E |
| REQ-UI-02 | The board shall support both tap-then-tap and drag-and-drop move input. | M | E, A |
| REQ-UI-03 | When the player selects one of their pieces on their turn, the client shall highlight that piece's legal destinations using only the server-provided `legal` list. | M | E |
| REQ-UI-04 | When a move would promote, the client shall show a picker for queen, rook, bishop and knight before sending the move. | M | E |
| REQ-UI-05 | The client shall show the move list in SAN, the last move highlighted on the board, and the king highlighted when in check. | M | E |
| REQ-UI-06 | While the socket is not open and synced, the client shall show a "Reconnecting…" indicator and disable move input. | M | E |
| REQ-UI-07 | When the socket closes unexpectedly, or the page becomes visible again, or the browser goes online, the client shall reconnect with exponential back-off from 0.5 s to a maximum of 8 s with ±20% jitter, and send `hello` on every connect. | M | E |
| REQ-UI-08 | While a game page is visible, the client shall hold a Screen Wake Lock where the browser supports it and re-acquire it after the page becomes visible again. | S | A |
| REQ-UI-09 | Sounds shall be off by default; the player's sound choice shall be remembered on that device. | S | E |
| REQ-UI-10 | The layout shall work in portrait at 320–430 px width without horizontal scrolling, keep primary controls out of the top corners, and respect safe-area insets; it shall also work on desktop. | M | E, A |
| REQ-UI-11 | Resign shall require a confirmation step. | M | E |
| REQ-UI-12 | The board shall be operable by keyboard, and opponent moves shall be announced in an ARIA live region in SAN. | S | E |
| REQ-UI-13 | The site shall provide a web app manifest and icons so it can be added to the iPhone Home Screen. | S | A |
| REQ-UI-14 | The client shall never decide move legality or game outcome; it shall render only what the latest `state` says. | M | R |

## 7. Notifications (NOTIFY) — Phase 6

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-NOTIFY-01 | Where invite emails are enabled for the opponent, when a game is created, the system shall email the opponent an invite with a link to the game. | S | U, D |
| REQ-NOTIFY-02 | Where "your move" emails are enabled for the opponent, when a move is accepted and the opponent has no open socket on that game and no nudge was sent to them in the last 30 minutes (configurable per player), the system shall email them a "your move" message. | S | U, D |
| REQ-NOTIFY-03 | When a game reaches a terminal status, the system shall email both players the result and the PGN. | S | U, D |
| REQ-NOTIFY-04 | If sending an email fails, then the system shall log the failure and continue; the game state shall be unaffected. | S | U |
| REQ-NOTIFY-05 | The system shall send email only to the `email` addresses in `PLAYERS_JSON`, from `MAIL_FROM`, through the `EMAIL` binding restricted by `allowed_destination_addresses`. | S | U, R |
| REQ-NOTIFY-06 | The lobby shall give each player an on/off switch for invite emails, an on/off switch for "your move" emails, and a timer control setting the minimum gap between "your move" emails, from 5 minutes to 24 hours (steps: 5, 10, 15, 30, 45 min; 1, 2, 4, 8, 12, 24 h). The timer is disabled while the "your move" switch is off. | S | U, E |

## 8. Non-functional (NFR) and operations (OPS)

| ID | Requirement | Pri | Verified |
|---|---|---|---|
| REQ-NFR-01 | The system shall run entirely on free plans (Workers Free, Durable Objects SQLite, Zero Trust Free, Email Service to verified addresses, GitHub Free); no step shall require a paid plan. | M | R |
| REQ-NFR-02 | Every Worker and Durable Object invocation shall stay under the 10 ms Workers Free CPU limit, with a target of p95 ≤ 5 ms as observed in Workers metrics. | M | D |
| REQ-NFR-03 | The system shall not depend on the Raspberry Pi, the home network, or Harry's PC at runtime or in the build pipeline. | M | R |
| REQ-NFR-04 | All dependencies (Python packages, `workers-py`, `compatibility_date`, vendored JS) shall be pinned to exact versions recorded in the repo. | M | R |
| REQ-NFR-05 | Storage schema changes shall be additive only and recorded with an incremented `schema_version`; Durable Object classes shall never be renamed or deleted. | M | R |
| REQ-NFR-06 | Logs shall be structured JSON containing `event`, `game_id`, `ply` and `player` (the player key, not the email address); logs shall never contain JWTs or secrets. | M | U, R |
| REQ-NFR-07 | The client shall support current and previous major versions of iOS Safari, plus current Chrome, Firefox and Safari on desktop. | M | E, A |
| REQ-NFR-08 | The browser bundle shall have no runtime third-party requests: all JS, CSS, fonts, pieces and sounds are served from the Worker's static assets. | M | E, R |
| REQ-OPS-01 | When a deploy completes, CI shall call `/healthz` on the deployed hostname and fail the workflow unless `commit` matches the deployed commit. | M | D |
| REQ-OPS-02 | A manual workflow shall redeploy any previous tag to production. | M | D |
| REQ-OPS-03 | Production shall be deployed only from a `v*` tag; staging shall be deployed from every push to `main`. | M | R |

---

## Out of scope for v1

Clocks and time controls; more than two players; spectators; chat; ratings; engine analysis; chess variants; push notifications. Any of these becomes a new requirement with a new ID before work starts.

## Decisions log

| Date | Decision | Effect |
|---|---|---|
| 2026-10-12 | Each player types their own display name in the app. | REQ-GAME-09 added. |
| 2026-10-12 | No abort. | REQ-ACT-07 withdrawn; `abort`, `aborted` and `CANNOT_ABORT` removed from the protocol. |
| 2026-10-12 | Takebacks are in. | REQ-ACT-11 to REQ-ACT-14 added. |
| 2026-10-12 | "Your move" emails get an on/off switch plus a gap timer. | REQ-NOTIFY-06 rewritten. |

IDs are never reused: REQ-ACT-07 stays retired.
