# Protocol — labscloud-chess

**Status:** v1.1 — 12 October 2026 (abort removed; takebacks and editable names added)
**Protocol version:** `1` (sent as `v` in every server message)
**Machine-readable contract:** `docs/protocol.schema.json` (JSON Schema 2020-12). The Python protocol module and the e2e tests both validate against it; if this page and the schema disagree, the schema wins and this page is fixed.

The browser and server talk in two ways:
- **REST over HTTPS** for the lobby: listing, creating, stats, PGN.
- **One WebSocket per open game page** for live play.

All endpoints sit behind Cloudflare Access except `GET /healthz`. Every request is identified by the verified Access JWT (REQ-AUTH-02); the browser never sends its identity in a body or header.

---

## 1. Conventions

- JSON, UTF-8, `snake_case` keys.
- Colours are `"white"` or `"black"`. Player keys are `"harry"` or `"partner"`.
- Times are integer **epoch milliseconds** (UTC).
- UCI moves are lower-case canonical: `e2e4`, `e7e8q`, castling as `e1g1` / `e1c1` / `e8g8` / `e8c8` (REQ-RULE-04).
- Moves in SAN appear only in server output, for display. Clients never send SAN.
- Unknown fields are **rejected** in client messages (REQ-RT-08) and **must be ignored** by clients in server messages, so the server can add fields without breaking older pages.

---

## 2. REST API

Base URL: the environment's `PUBLIC_URL` (`https://chess.labscloud.uk` or `https://chess-staging.labscloud.uk`).

Error bodies always have this shape, with a code from §6:

```json
{ "error": { "code": "GAME_NOT_FOUND", "message": "No game with that ID." } }
```

### 2.1 `GET /healthz` — no auth (Access Bypass policy)

```json
{ "ok": true, "version": "0.1.0", "commit": "3f2c1ab", "env": "staging" }
```
Nothing else, ever (REQ-AUTH-07).

### 2.2 `GET /api/me`

```json
{
  "player": "harry",
  "name": "Harry",
  "notify": { "invites": true, "your_move": true, "cooldown_minutes": 30 }
}
```
`name` is the player's display name: whatever they last saved in the name box, or the `PLAYERS_JSON` default (REQ-GAME-09). The player's own email is deliberately not returned; the page doesn't need it.

### 2.3 `PATCH /api/me`

Request: `name`, and/or any subset of `notify`.
```json
{ "name": "Harry", "notify": { "your_move": true, "cooldown_minutes": 60 } }
```
- `name`: string, trimmed, 1–24 characters, no control characters (REQ-GAME-09).
- `invites`, `your_move`: boolean.
- `cooldown_minutes`: one of 5, 10, 15, 30, 45, 60, 120, 240, 480, 720, 1440 (the gap timer's steps, REQ-NOTIFY-06).

Response: the full `/api/me` object. Invalid body → `400 BAD_REQUEST`.

### 2.4 `GET /api/games?status=active|finished`

`status` is optional; omitted means all. Ordered by `updated_at` descending (REQ-GAME-03).

```json
{
  "games": [
    {
      "id": "7d3c9a2e-5b1f-4c8e-9a0d-2f6b8e1c4a77",
      "white": { "player": "harry", "name": "Harry" },
      "black": { "player": "partner", "name": "Partner" },
      "you": "white",
      "status": "active",
      "result": null,
      "ply": 14,
      "your_turn": true,
      "rematch_of": null,
      "created_at": 1760287200000,
      "updated_at": 1760290800000
    }
  ]
}
```
`finished` means any terminal status.

### 2.5 `POST /api/games`

Request:
```json
{ "colour": "random" }
```
`colour` ∈ `white | black | random` is the **creator's** colour (REQ-GAME-01).

Response `201`:
```json
{ "game": { "...": "same object as one entry of GET /api/games" }, "url": "/game/7d3c9a2e-5b1f-4c8e-9a0d-2f6b8e1c4a77" }
```
Side effect (Phase 6): invite email to the opponent if they have invites on.

### 2.6 `GET /api/games/{id}`

A full `state` object exactly as in §4.1, for page load before the socket opens or if WebSockets are blocked. Unknown ID → `404 GAME_NOT_FOUND`.

### 2.7 `GET /api/games/{id}/pgn`

`200`, `Content-Type: application/x-chess-pgn; charset=utf-8`, `Content-Disposition: attachment; filename="labscloud-chess-YYYY-MM-DD-<first 8 of id>.pgn"`.

```text
[Event "labscloud-chess"]
[Site "chess.labscloud.uk"]
[Date "2026.10.12"]
[White "Harry"]
[Black "Partner"]
[Result "1-0"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0
```
Result is `*` while the game is active. Taken-back moves never appear (REQ-ACT-14).

### 2.8 `GET /api/stats`

```json
{
  "players": {
    "harry":   { "wins": 4, "losses": 3, "draws": 1 },
    "partner": { "wins": 3, "losses": 4, "draws": 1 }
  },
  "names": { "harry": "Harry", "partner": "Partner" },
  "finished_games": 8
}
```
Counts every finished game (REQ-GAME-05). `names` are the current display names (REQ-GAME-09), so the lobby can label the head-to-head before any game exists.

### 2.9 `GET /ws/games/{id}` — WebSocket upgrade

Requirements for the upgrade to succeed, checked by the Worker before contacting the Durable Object:
1. Valid Access JWT for a player (else `403 UNAUTHORISED` / `NOT_A_PLAYER`).
2. `Origin` equals `PUBLIC_URL` (else `403 BAD_ORIGIN`).
3. `Upgrade: websocket` header (else `426 UPGRADE_REQUIRED`).
4. Game exists (else `404 GAME_NOT_FOUND`).

After the upgrade the client must send `hello` first.

### 2.10 Status codes used

`200`, `201`, `101` (upgrade), `400 BAD_REQUEST`, `403` (`UNAUTHORISED`, `NOT_A_PLAYER`, `BAD_ORIGIN`), `404` (`GAME_NOT_FOUND`, `NOT_FOUND`), `405 METHOD_NOT_ALLOWED`, `426 UPGRADE_REQUIRED`, `500 INTERNAL`.

### 2.11 Cross-site request forgery guard (all `POST`/`PATCH`)

Cloudflare Access's `CF_Authorization` cookie is `SameSite=None`, so another site could make a signed-in browser send a form here. After authentication, every state-changing request must therefore:
- carry no `Origin`, or an `Origin` equal to `PUBLIC_URL` (else `403 BAD_ORIGIN`);
- carry no `Sec-Fetch-Site`, or `same-origin` / `none` (else `403 BAD_ORIGIN`);
- have `Content-Type: application/json` (parameters such as `; charset=utf-8` allowed; else `400 BAD_REQUEST`).

Browsers always send `Origin` on cross-site `POST`s, so the page itself (same-origin `fetch` with a JSON body) passes and a hostile form does not.

---

## 3. WebSocket: client → server

Every message is a JSON object with `type`. Maximum size 1 KB. Anything else gets `BAD_MESSAGE` (REQ-RT-08).

| `type` | Fields | When valid | Errors it can produce |
|---|---|---|---|
| `hello` | `since_ply` (int ≥ 0, optional, informational only) | Any time; must be the first message | — |
| `move` | `uci` (string), `ply` (int ≥ 0) | Game active, your turn | `GAME_OVER`, `NOT_YOUR_TURN`, `STALE_PLY`, `BAD_FORMAT`, `ILLEGAL_MOVE` |
| `resign` | — | Game active (either turn) | `GAME_OVER` |
| `draw_offer` | — | Game active | `GAME_OVER`, `DRAW_ALREADY_OFFERED` |
| `draw_accept` | — | Opponent's offer pending | `GAME_OVER`, `NO_DRAW_OFFER`, `OWN_DRAW_OFFER` |
| `draw_decline` | — | Opponent's offer pending | `GAME_OVER`, `NO_DRAW_OFFER`, `OWN_DRAW_OFFER` |
| `claim_draw` | — | Your turn and `can_claim_draw` | `GAME_OVER`, `NOT_YOUR_TURN`, `CANNOT_CLAIM` |
| `takeback_request` | — | Game active, you have made a move, none pending | `GAME_OVER`, `TAKEBACK_NOT_AVAILABLE`, `TAKEBACK_ALREADY_REQUESTED` |
| `takeback_accept` | — | Opponent's request pending | `GAME_OVER`, `NO_TAKEBACK_REQUEST`, `OWN_TAKEBACK_REQUEST` |
| `takeback_decline` | — | Opponent's request pending | `GAME_OVER`, `NO_TAKEBACK_REQUEST`, `OWN_TAKEBACK_REQUEST` |
| `rematch` | — | Game terminal | `REMATCH_NOT_AVAILABLE` |
| `ping` | — | Any time | — |

Examples:
```json
{ "type": "hello", "since_ply": 14 }
{ "type": "move", "uci": "e7e8q", "ply": 37 }
{ "type": "draw_offer" }
```

**`move` validation order** (REQ-RULE-02): `GAME_OVER` → `NOT_YOUR_TURN` → `STALE_PLY` → `BAD_FORMAT` → `ILLEGAL_MOVE`. The first failing check decides the code. The legality check compares the submitted string with the set of canonical UCI strings of legal moves (not `chess.Move in board.legal_moves`, which would also accept `e1h1`; see `docs/rules-catalogue.md` W08).

**Draw-offer rules** (REQ-ACT-02 to 06):
- An offer is pending from at most one colour.
- Offering while the opponent's offer is pending counts as accepting it.
- The offer is cleared when the player it was made to moves or declines. The offering player making a move does not clear it.
- An accepted takeback also clears any pending draw offer.

**Takeback rules** (REQ-ACT-11 to 14):
- Either player may ask to take back their own most recent move, on either player's turn, while the game is active.
- Only one takeback request can be pending at a time. Any move by either player cancels it.
- On `takeback_accept`: if it is the opponent's turn, one ply is undone; if it is the requester's turn (the opponent has already replied), two plies are undone. The board, castling rights, en passant square, move counters, move list and repetition counts return exactly to that earlier position, and both sides receive a new `state` with the lower `ply`.
- Clients must treat `ply` as possibly going down; anything keyed on it (move list scroll, last-move highlight) is re-derived from the new `state`.

---

## 4. WebSocket: server → client

Every server message has `type` and `v: 1`.

### 4.1 `state` — the single source of truth

Sent: in reply to `hello`; to every socket after any accepted move or action (REQ-RT-01). Each `state` is complete; clients replace their whole view with it and never patch.

```json
{
  "type": "state",
  "v": 1,
  "game_id": "7d3c9a2e-5b1f-4c8e-9a0d-2f6b8e1c4a77",
  "you": "black",
  "players": {
    "white": { "player": "harry", "name": "Harry" },
    "black": { "player": "partner", "name": "Partner" }
  },
  "fen": "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4",
  "ply": 7,
  "turn": "black",
  "moves": [
    { "uci": "e2e4", "san": "e4" }, { "uci": "e7e5", "san": "e5" },
    { "uci": "d1h5", "san": "Qh5" }, { "uci": "b8c6", "san": "Nc6" },
    { "uci": "f1c4", "san": "Bc4" }, { "uci": "g8f6", "san": "Nf6" },
    { "uci": "h5f7", "san": "Qxf7#" }
  ],
  "last_move": { "uci": "h5f7", "san": "Qxf7#" },
  "legal": [],
  "check": true,
  "status": "checkmate",
  "result": "1-0",
  "draw_offer_from": null,
  "can_claim_draw": false,
  "takeback_from": null,
  "rematch": { "white": false, "black": false, "game_id": null },
  "online": { "white": true, "black": true },
  "updated_at": 1760290800000
}
```

| Field | Type | Meaning |
|---|---|---|
| `you` | colour | Colour of the receiving socket's player. |
| `fen` | string | Current position (python-chess `board.fen()`). |
| `ply` | int | Half-moves played. The next `move` must send this value. |
| `turn` | colour | Side to move (also derivable from `fen`). |
| `moves` | array | Full move history, oldest first. |
| `last_move` | object/null | Last entry of `moves`, or `null` at ply 0. |
| `legal` | string[] | Canonical UCI legal moves, **only** when `you == turn` and status is `active`; otherwise `[]` (REQ-RT-03). Sorted. |
| `check` | bool | Side to move is in check. |
| `status` | enum | See §5. |
| `result` | `"1-0"`, `"0-1"`, `"1/2-1/2"`, `null` | `null` while active. |
| `draw_offer_from` | colour/null | Pending draw offer. |
| `can_claim_draw` | bool | True only on the side-to-move's sockets when REQ-RULE-08 holds. |
| `takeback_from` | colour/null | Pending takeback request (who asked). |
| `rematch` | object | Votes per colour, and the new `game_id` once created. |
| `online` | object | Whether each colour has at least one open socket. |
| `updated_at` | int | Epoch ms of the last state change. |

### 4.2 `presence`

Sent to all sockets when any socket connects or disconnects (REQ-RT-04).
```json
{ "type": "presence", "v": 1, "online": { "white": true, "black": false } }
```

### 4.3 `error`

Sent **only** to the socket whose message caused it (REQ-RULE-03). The game state is unchanged.
```json
{ "type": "error", "v": 1, "code": "STALE_PLY", "message": "That move was based on an old position.", "in_reply_to": "move" }
```
`in_reply_to` is the offending message's `type`, or `null` if the message couldn't be parsed. On `STALE_PLY` the client should send `hello` to resync.

### 4.4 `rematch_ready`

Sent to every socket of the old game when both players have voted (REQ-ACT-08). Clients navigate to `/game/{game_id}`.
```json
{ "type": "rematch_ready", "v": 1, "game_id": "0b6a…" }
```

### 4.5 `pong`

Reply to `ping`.
```json
{ "type": "pong", "v": 1, "t": 1760290800000 }
```
Protocol-level WebSocket ping frames are answered automatically by Cloudflare without waking the Durable Object; `ping`/`pong` messages are only for the client's own latency display and liveness check.

---

## 5. Status and result

Checked after every accepted move, **in this order** (REQ-RULE-07):

| Order | `status` | Ends game | `result` |
|---|---|---|---|
| 1 | `checkmate` | yes | winner's score (`1-0` if Black is mated) |
| 2 | `stalemate` | yes | `1/2-1/2` |
| 3 | `insufficient_material` | yes | `1/2-1/2` |
| 4 | `seventyfive_moves` | yes | `1/2-1/2` |
| 5 | `fivefold_repetition` | yes | `1/2-1/2` |
| — | `active` | no | `null` |

Set by actions:

| `status` | Trigger | `result` |
|---|---|---|
| `resigned` | `resign` | win for the non-resigning colour |
| `draw_agreed` | `draw_accept`, or crossing offers | `1/2-1/2` |
| `draw_claimed` | `claim_draw` | `1/2-1/2` |

`waiting` is reserved and not used in v1 (both players exist from creation).

---

## 6. Error codes

| Code | Channel | HTTP | Meaning | Requirement |
|---|---|---|---|---|
| `UNAUTHORISED` | REST, upgrade | 403 | Missing or invalid Access JWT. | REQ-AUTH-03 |
| `NOT_A_PLAYER` | REST, upgrade | 403 | Valid JWT but email not in `PLAYERS_JSON`. | REQ-AUTH-04 |
| `BAD_ORIGIN` | upgrade, REST writes | 403 | `Origin` ≠ `PUBLIC_URL` (upgrade), or a cross-site `POST`/`PATCH` (§2.11). | REQ-AUTH-08 |
| `UPGRADE_REQUIRED` | upgrade | 426 | `/ws/…` requested without `Upgrade: websocket`. | — |
| `BAD_REQUEST` | REST | 400 | Body invalid against the schema. | — |
| `GAME_NOT_FOUND` | REST, upgrade | 404 | No game with that ID. | REQ-GAME-07 |
| `NOT_FOUND` | REST | 404 | Unknown `/api/…` route. | — |
| `METHOD_NOT_ALLOWED` | REST | 405 | Wrong method for the route. | — |
| `INTERNAL` | REST, WS | 500 | Unexpected server error (logged with a request ID). | — |
| `BAD_MESSAGE` | WS | — | Not JSON, > 1 KB, unknown `type`, unknown or missing fields. | REQ-RT-08 |
| `GAME_OVER` | WS | — | Action other than `rematch` on a terminal game. | REQ-ACT-10 |
| `NOT_YOUR_TURN` | WS | — | `move` or `claim_draw` by the side not to move. | REQ-RULE-02 |
| `STALE_PLY` | WS | — | `move.ply` ≠ current ply (includes resends). | REQ-RULE-02, REQ-RT-09 |
| `BAD_FORMAT` | WS | — | UCI fails the regex. | REQ-RULE-02 |
| `ILLEGAL_MOVE` | WS | — | Well-formed but not a canonical legal move. | REQ-RULE-02/04/05 |
| `CANNOT_CLAIM` | WS | — | `claim_draw` when not claimable. | REQ-RULE-09 |
| `DRAW_ALREADY_OFFERED` | WS | — | Repeat offer from the same colour. | REQ-ACT-02 |
| `NO_DRAW_OFFER` | WS | — | Accept/decline with no offer pending. | REQ-ACT-04 |
| `OWN_DRAW_OFFER` | WS | — | Accept/decline your own offer. | REQ-ACT-04 |
| `REMATCH_NOT_AVAILABLE` | WS | — | `rematch` before the game ends. | REQ-ACT-09 |
| `TAKEBACK_NOT_AVAILABLE` | WS | — | Takeback requested by a player with no move to take back. | REQ-ACT-11 |
| `TAKEBACK_ALREADY_REQUESTED` | WS | — | A takeback request is already pending. | REQ-ACT-11 |
| `NO_TAKEBACK_REQUEST` | WS | — | Accept/decline with no takeback pending. | REQ-ACT-13 |
| `OWN_TAKEBACK_REQUEST` | WS | — | Accept/decline your own takeback request. | REQ-ACT-13 |

---

## 7. Ordering and delivery guarantees

1. A Durable Object processes one message at a time, so moves for a game are totally ordered.
2. An accepted move is written to SQLite **before** the `state` broadcast; the runtime's output gate holds outgoing messages until the write is confirmed (REQ-RULE-06).
3. Every `state` is a full snapshot, so a lost or reordered message is repaired by the next `state` or by sending `hello`.
4. A client must not send a second `move` until it has received a `state` with a higher `ply` (or an `error`). The UI disables input while a move is in flight.
5. **Every deploy disconnects all WebSockets** (the platform restarts Durable Objects). Clients reconnect automatically (REQ-UI-07); no game state is lost.

## 8. Close codes

| Code | Sent by | Meaning | Client action |
|---|---|---|---|
| 1000 | either | Normal close (page left). | none |
| 1001 | server/platform | Going away (deploy, restart). | reconnect |
| 1008 | server | Policy violation (e.g. identity no longer valid). | reload page (triggers Access login if needed) |
| 1011 | server | Internal error. | reconnect with back-off |
| other / none | network | Connection dropped. | reconnect with back-off |

## 9. Versioning

- `v` is `1`. Adding fields to server messages or adding new message types does **not** change `v`; clients ignore what they don't know.
- Removing or changing the meaning of a field, or tightening a client-message rule, increments `v`. The server keeps the old behaviour available until the open pages have reloaded; with two users, a deploy plus a page refresh is enough.
