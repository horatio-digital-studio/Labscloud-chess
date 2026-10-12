# Data model — labscloud-chess

**Status:** v1.1 — 12 October 2026 (editable names, takebacks, no abort). Supersedes architecture §6 where they differ (changes listed at the end).

Two kinds of SQLite-backed Durable Object hold all data. Nothing else stores state; the Worker is stateless and the browser stores only its sound preference.

| Object | Instances | Addressed by |
|---|---|---|
| `Lobby` | exactly one | `getByName("lobby")` |
| `GameRoom` | one per game | `getByName(<game uuid>)` |

**Rules for every table**
- Player identity is stored as the **player key** (`harry` / `partner`), never as an email address. Emails live only in the `PLAYERS_JSON` secret. Renaming someone or changing an address is then a secret update, not a data migration.
- Times are epoch milliseconds (`INTEGER`).
- Booleans are `INTEGER` 0/1.
- Every object has a `meta` table with `schema_version`. Migrations are additive, run in the constructor, idempotent (`CREATE … IF NOT EXISTS`, guarded `ALTER TABLE … ADD COLUMN`), and bump the version (REQ-NFR-05).

---

## 1. `Lobby`

```sql
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- INSERT OR IGNORE INTO meta VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS player_prefs (
  player            TEXT PRIMARY KEY CHECK (player IN ('harry', 'partner')),
  display_name      TEXT CHECK (display_name IS NULL OR length(display_name) BETWEEN 1 AND 24),
                                                -- NULL = use the PLAYERS_JSON default (REQ-GAME-09)
  notify_invites    INTEGER NOT NULL DEFAULT 1,
  notify_your_move  INTEGER NOT NULL DEFAULT 1,
  cooldown_minutes  INTEGER NOT NULL DEFAULT 30
                    CHECK (cooldown_minutes IN (5, 10, 15, 30, 45, 60, 120, 240, 480, 720, 1440)),
  last_nudged_at    INTEGER                     -- epoch ms, NULL = never
);

CREATE TABLE IF NOT EXISTS games (
  id          TEXT PRIMARY KEY,                  -- uuid4
  white       TEXT NOT NULL CHECK (white IN ('harry', 'partner')),
  black       TEXT NOT NULL CHECK (black IN ('harry', 'partner')),
  status      TEXT NOT NULL,
  result      TEXT,                              -- '1-0' | '0-1' | '1/2-1/2' | NULL
  ply         INTEGER NOT NULL DEFAULT 0,
  rematch_of  TEXT,                              -- game id or NULL
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  CHECK (white <> black)
);
CREATE INDEX IF NOT EXISTS games_updated ON games (updated_at DESC);
```

**Ownership:** the Lobby's `games` table is a **summary index** for the lobby page and stats. `GameRoom` is authoritative. After every state change, GameRoom calls the Lobby to upsert `(id, status, result, ply, updated_at)`. If that call fails, the lobby is briefly stale; the next change fixes it, and the game itself is unaffected.

**Stats (REQ-GAME-05)** are computed by query, not stored:
```sql
SELECT white, black, result FROM games
WHERE result IS NOT NULL;
```

## 2. `GameRoom`

```sql
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game (
  id               TEXT PRIMARY KEY,   -- exactly one row per object
  white            TEXT NOT NULL,      -- player key
  black            TEXT NOT NULL,      -- player key
  start_fen        TEXT NOT NULL,
  current_fen      TEXT NOT NULL,
  ply              INTEGER NOT NULL,
  status           TEXT NOT NULL,
  result           TEXT,
  draw_offer_from  TEXT,               -- 'white' | 'black' | NULL
  takeback_from    TEXT,               -- 'white' | 'black' | NULL (pending request)
  rematch_white    INTEGER NOT NULL DEFAULT 0,
  rematch_black    INTEGER NOT NULL DEFAULT 0,
  rematch_game_id  TEXT,
  created_at       INTEGER NOT NULL,
  updated_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS moves (
  ply        INTEGER PRIMARY KEY,      -- 1-based: the move that made ply N
  uci        TEXT NOT NULL,
  san        TEXT NOT NULL,
  fen_after  TEXT NOT NULL,
  by_colour  TEXT NOT NULL,
  played_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
  key    TEXT PRIMARY KEY,             -- first four FEN fields
  count  INTEGER NOT NULL
);
```

### 2.1 Why `positions` exists (ADR-0007)

Repetition rules need to know how often the current position has occurred. python-chess answers that by walking the move history, which is the most CPU-expensive operation in the game (measured ~1.8 ms median in CPython for 131 plies, slower under Wasm). Instead we keep a count per **position key**:

```text
key = " ".join(board.fen().split()[:4])
      # placement, side to move, castling rights, en-passant square (only when a legal ep exists)
```

This was checked against python-chess's own `is_repetition(3)` / `is_fivefold_repetition()` on 77,044 positions with zero mismatches (`docs/platform-notes.md` §10).

**On game creation** the starting position's key is inserted with `count = 1`. Forgetting this makes threefold repetition of the starting position need four occurrences (catalogue I01 catches it).

### 2.2 Writing an accepted move

All of this runs synchronously with no `await` in between, so it commits atomically. If more than one statement turns out to need explicit grouping, use `ctx.storage.transactionSync`.

1. `INSERT INTO moves (ply, uci, san, fen_after, by_colour, played_at)`
2. `INSERT INTO positions (key, count) VALUES (?, 1) ON CONFLICT(key) DO UPDATE SET count = count + 1`
3. `UPDATE game SET current_fen = ?, ply = ?, status = ?, result = ?, draw_offer_from = ?, updated_at = ?`
4. Then broadcast `state`. (The output gate holds outgoing messages until the writes are confirmed.)

### 2.2a Applying an accepted takeback (REQ-ACT-12, ADR-0011)

Let `n` = plies to undo (1 if it is the opponent's turn, 2 if it is the requester's turn) and `target = ply - n`. Synchronously, with no `await`:

1. For each removed row (`ply > target`): decrement `positions` for `key(fen_after)`, deleting rows that reach 0.
2. `DELETE FROM moves WHERE ply > ?` (target).
3. `current_fen` = `fen_after` of the move at `target`, or `start_fen` when `target = 0`. The stored FEN restores castling rights, en passant and both move counters exactly; no replay.
4. `UPDATE game SET current_fen = ?, ply = ?, takeback_from = NULL, draw_offer_from = NULL, updated_at = ?`.
5. Upsert the Lobby summary, then broadcast `state`.

Checked in the workspace against python-chess `board.pop()` over 47,177 random moves and takebacks (one and two plies): position, legal moves and repetition answers matched every time.

### 2.3 Rebuilding after hibernation

`ChessGame.from_storage(current_fen, position_counts)`: build the board from `current_fen` (one FEN parse), and load the `positions` map. **No move replay.** `moves` is read only to render the move list and PGN, a cheap `SELECT` with no chess computation.

### 2.4 Deriving `state` fields

| Field | Source |
|---|---|
| `fen`, `ply`, `status`, `result`, `draw_offer_from`, `takeback_from` | `game` row |
| `turn`, `check`, `legal` | board built from `current_fen` |
| `moves`, `last_move` | `SELECT uci, san FROM moves ORDER BY ply` |
| `can_claim_draw` | side to move, `status == active`, and (`halfmove_clock >= 100` or `positions[key(current)] >= 3`) |
| `rematch` | `rematch_white`, `rematch_black`, `rematch_game_id` |
| `online` | `getWebSockets()` attachments: is any socket's `colour` white/black |
| `players` | `game.white` / `game.black` keys → display names from the Lobby (`player_prefs.display_name`, else `PLAYERS_JSON`). GameRoom caches them in memory and refreshes them from the Lobby on every `hello`, so a renamed player shows up after the other side reconnects or refreshes. |

## 3. Socket attachments

Each accepted WebSocket carries (≤ 16 KB limit, we use ~40 bytes):
```json
{"player": "harry", "colour": "white"}
```
stored as a JSON string with `serializeAttachment`. Tag on `acceptWebSocket`: the colour (if Python tag support is confirmed in S-02).

## 4. Secrets and vars (not data, listed for completeness)

| Name | Kind | Example |
|---|---|---|
| `PLAYERS_JSON` | secret | `{"harry": {"email": "…", "name": "Harry"}, "partner": {"email": "…", "name": "…"}}` |
| `ACCESS_AUD` | secret | per-environment AUD tag |
| `ACCESS_TEAM_DOMAIN` | var | `https://<team>.cloudflareaccess.com` |
| `APP_ENV` | var | `development` / `staging` / `production` |
| `PUBLIC_URL` | var | `https://chess-staging.labscloud.uk` |
| `MAIL_FROM` | var | `chess@labscloud.uk` |
| `VERSION`, `COMMIT` | var (set by CI) | `0.1.0`, `3f2c1ab` |

## 5. Changes from architecture §6

| Change | Reason |
|---|---|
| Emails → player keys in all tables | No PII in storage or logs; address changes need no migration. |
| `players` table → `player_prefs` keyed by player | Identity and names live in `PLAYERS_JSON`; only preferences are data. |
| Added `positions` table | Repetition without replay (ADR-0007). |
| `rematch_votes` JSON → two integer columns + `rematch_game_id` | Simpler, checkable with SQL constraints. |
| Added `meta.schema_version` to both objects | Additive migrations (REQ-NFR-05). |
| Display names editable by each player (`player_prefs.display_name`) | Harry's decision, 12 Oct: each player types their own name. `PLAYERS_JSON.name` is only the default. |
| `takeback_from` column + takeback procedure (§2.2a) | Takebacks added (REQ-ACT-11 to 14). |
| `aborted` status removed | Abort dropped. |
