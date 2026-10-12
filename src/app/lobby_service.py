"""Lobby logic: display names, email preferences, the game index and stats.

The single Lobby Durable Object owns this data (docs/data-model.md §1). GameRoom is
authoritative for each game; the `games` table here is a summary index.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.config import PLAYER_KEYS, PlayerDirectory
from app.storage import Storage, split_statements
from chess_core.engine import TERMINAL_STATUSES

SCHEMA_VERSION = "1"
COOLDOWN_STEPS = (5, 10, 15, 30, 45, 60, 120, 240, 480, 720, 1440)
DEFAULT_COOLDOWN = 30
NAME_MAX = 24
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")  # C0, DEL and C1 controls

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_prefs (
  player            TEXT PRIMARY KEY CHECK (player IN ('harry', 'partner')),
  display_name      TEXT CHECK (display_name IS NULL OR length(display_name) BETWEEN 1 AND {NAME_MAX}),
  notify_invites    INTEGER NOT NULL DEFAULT 1,
  notify_your_move  INTEGER NOT NULL DEFAULT 1,
  cooldown_minutes  INTEGER NOT NULL DEFAULT {DEFAULT_COOLDOWN},
  last_nudged_at    INTEGER
);
CREATE TABLE IF NOT EXISTS games (
  id          TEXT PRIMARY KEY,
  white       TEXT NOT NULL CHECK (white IN ('harry', 'partner')),
  black       TEXT NOT NULL CHECK (black IN ('harry', 'partner')),
  status      TEXT NOT NULL,
  result      TEXT,
  ply         INTEGER NOT NULL DEFAULT 0,
  rematch_of  TEXT,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  CHECK (white <> black)
);
CREATE INDEX IF NOT EXISTS games_updated ON games (updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS games_rematch_of ON games (rematch_of) WHERE rematch_of IS NOT NULL
"""


class LobbyError(Exception):
    def __init__(self, code: str, status: int, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.status = status


def validate_name(raw: Any) -> str:
    """REQ-GAME-09: trimmed, 1–24 characters, no control characters."""
    if not isinstance(raw, str):
        raise LobbyError("BAD_REQUEST", 400, "name must be text")
    name = raw.strip()
    if not 1 <= len(name) <= NAME_MAX or _CONTROL.search(name):
        raise LobbyError("BAD_REQUEST", 400, "names need 1–24 characters")
    return name


@dataclass(frozen=True)
class NewGame:
    id: str
    white: str
    black: str
    rematch_of: str | None


class LobbyService:
    def __init__(self, storage: Storage, players: PlayerDirectory) -> None:
        self.storage = storage
        self.players = players
        self._migrated = False

    def migrate(self) -> None:
        if self._migrated:
            return

        def run() -> None:
            for statement in split_statements(SCHEMA):
                self.storage.execute(statement)
            self.storage.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                SCHEMA_VERSION,
            )
            for key in PLAYER_KEYS:
                self.storage.execute("INSERT OR IGNORE INTO player_prefs (player) VALUES (?)", key)

        self.storage.transaction(run)
        self._migrated = True

    # ------------------------------------------------------------- players
    def _prefs(self, player: str) -> dict[str, Any]:
        self.migrate()
        rows = self.storage.query("SELECT * FROM player_prefs WHERE player = ?", player)
        if not rows:
            raise LobbyError("NOT_A_PLAYER", 403)
        return rows[0]

    def display_name(self, player: str) -> str:
        stored = self._prefs(player).get("display_name")
        if stored:
            return str(stored)
        found = self.players.by_key(player)
        return found.default_name if found else player

    def names(self) -> dict[str, str]:
        return {key: self.display_name(key) for key in PLAYER_KEYS}

    def me(self, player: str) -> dict[str, Any]:
        prefs = self._prefs(player)
        return {
            "player": player,
            "name": self.display_name(player),
            "notify": {
                "invites": bool(prefs["notify_invites"]),
                "your_move": bool(prefs["notify_your_move"]),
                "cooldown_minutes": int(prefs["cooldown_minutes"]),
            },
        }

    def update_me(self, player: str, body: Any) -> dict[str, Any]:
        """PATCH /api/me (REQ-GAME-09, REQ-NOTIFY-06). All-or-nothing."""
        self._prefs(player)
        if not isinstance(body, dict) or not body or not set(body) <= {"name", "notify"}:
            raise LobbyError("BAD_REQUEST", 400, "expected name and/or notify")
        updates: dict[str, Any] = {}
        if "name" in body:
            updates["display_name"] = validate_name(body["name"])
        if "notify" in body:
            notify = body["notify"]
            if (
                not isinstance(notify, dict)
                or not notify
                or not set(notify)
                <= {
                    "invites",
                    "your_move",
                    "cooldown_minutes",
                }
            ):
                raise LobbyError("BAD_REQUEST", 400, "bad notify")
            for field, column in (("invites", "notify_invites"), ("your_move", "notify_your_move")):
                if field in notify:
                    if not isinstance(notify[field], bool):
                        raise LobbyError("BAD_REQUEST", 400, f"{field} must be true or false")
                    updates[column] = int(notify[field])
            if "cooldown_minutes" in notify:
                minutes = notify["cooldown_minutes"]
                if isinstance(minutes, bool) or minutes not in COOLDOWN_STEPS:
                    raise LobbyError("BAD_REQUEST", 400, "cooldown must be one of the timer steps")
                updates["cooldown_minutes"] = int(minutes)
        assignments = ", ".join(f"{column} = ?" for column in updates)
        self.storage.transaction(
            lambda: self.storage.execute(
                f"UPDATE player_prefs SET {assignments} WHERE player = ?",  # noqa: S608
                *updates.values(),
                player,
            )
        )
        return self.me(player)

    # --------------------------------------------------------------- games
    def plan_game(self, creator: str, colour: str, choose: Callable[[list[str]], str]) -> NewGame:
        """Decide colours for a new game; nothing is stored until record_game()."""
        self.migrate()
        if colour not in ("white", "black", "random"):
            raise LobbyError("BAD_REQUEST", 400, "colour must be white, black or random")
        if colour == "random":
            colour = choose(["white", "black"])
        opponent = self.players.opponent(creator).key
        white, black = (creator, opponent) if colour == "white" else (opponent, creator)
        return NewGame(id=str(uuid.uuid4()), white=white, black=black, rematch_of=None)

    def plan_rematch(self, old_game_id: str) -> NewGame | dict[str, Any]:
        """Colours swapped from the old game. Returns the existing game if already created."""
        self.migrate()
        existing = self.storage.query("SELECT * FROM games WHERE rematch_of = ?", old_game_id)
        if existing:
            return existing[0]
        old = self.storage.query("SELECT white, black FROM games WHERE id = ?", old_game_id)
        if not old:
            raise LobbyError("GAME_NOT_FOUND", 404)
        return NewGame(
            id=str(uuid.uuid4()),
            white=str(old[0]["black"]),
            black=str(old[0]["white"]),
            rematch_of=old_game_id,
        )

    def record_game(self, game: NewGame, now: int) -> dict[str, Any]:
        self.migrate()

        def run() -> None:
            self.storage.execute(
                "INSERT INTO games (id, white, black, status, result, ply, rematch_of, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', NULL, 0, ?, ?, ?)",
                game.id,
                game.white,
                game.black,
                game.rematch_of,
                now,
                now,
            )

        self.storage.transaction(run)
        return self.storage.query("SELECT * FROM games WHERE id = ?", game.id)[0]

    def upsert_summary(self, summary: dict[str, Any]) -> None:
        """Update the index from a GameRoom summary. An older summary arriving late
        (two overlapping handlers) never overwrites a newer one."""
        self.migrate()
        updated_at = int(summary["updated_at"])
        self.storage.transaction(
            lambda: self.storage.execute(
                "UPDATE games SET status = ?, result = ?, ply = ?, updated_at = ? "
                "WHERE id = ? AND updated_at <= ?",
                summary["status"],
                summary["result"],
                int(summary["ply"]),
                updated_at,
                summary["id"],
                updated_at,
            )
        )

    def delete_game(self, game_id: str) -> None:
        """Undo a reservation whose GameRoom could not be initialised."""
        self.migrate()
        self.storage.transaction(
            lambda: self.storage.execute("DELETE FROM games WHERE id = ?", game_id)
        )

    def game_summary_for(self, row: dict[str, Any], player: str) -> dict[str, Any]:
        names = self.names()
        you = "white" if row["white"] == player else "black"
        status = str(row["status"])
        ply = int(row["ply"])
        turn = "white" if ply % 2 == 0 else "black"
        return {
            "id": row["id"],
            "white": {"player": row["white"], "name": names[row["white"]]},
            "black": {"player": row["black"], "name": names[row["black"]]},
            "you": you,
            "status": status,
            "result": row["result"],
            "ply": ply,
            "your_turn": status == "active" and turn == you,
            "rematch_of": row["rematch_of"],
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
        }

    def list_games(self, player: str, status: str | None) -> list[dict[str, Any]]:
        self.migrate()
        if status not in (None, "active", "finished"):
            raise LobbyError("BAD_REQUEST", 400, "status must be active or finished")
        rows = self.storage.query(
            "SELECT * FROM games WHERE white = ? OR black = ? ORDER BY updated_at DESC, created_at DESC",
            player,
            player,
        )
        if status == "active":
            rows = [r for r in rows if r["status"] == "active"]
        elif status == "finished":
            rows = [r for r in rows if r["status"] in TERMINAL_STATUSES]
        return [self.game_summary_for(r, player) for r in rows]

    def stats(self) -> dict[str, Any]:
        self.migrate()
        totals = {key: {"wins": 0, "losses": 0, "draws": 0} for key in PLAYER_KEYS}
        rows = self.storage.query("SELECT white, black, result FROM games WHERE result IS NOT NULL")
        for row in rows:
            white, black, result = str(row["white"]), str(row["black"]), row["result"]
            if result == "1-0":
                totals[white]["wins"] += 1
                totals[black]["losses"] += 1
            elif result == "0-1":
                totals[black]["wins"] += 1
                totals[white]["losses"] += 1
            elif result == "1/2-1/2":
                totals[white]["draws"] += 1
                totals[black]["draws"] += 1
        return {"players": totals, "names": self.names(), "finished_games": len(rows)}

    # ------------------------------------------------------------ nudges
    def nudge_allowed(self, player: str, now: int) -> bool:
        """REQ-NOTIFY-02 throttle; records the nudge when allowed."""
        prefs = self._prefs(player)
        if not prefs["notify_your_move"]:
            return False
        last = prefs.get("last_nudged_at")
        if last is not None and now - int(last) < int(prefs["cooldown_minutes"]) * 60_000:
            return False
        self.storage.transaction(
            lambda: self.storage.execute(
                "UPDATE player_prefs SET last_nudged_at = ? WHERE player = ?", now, player
            )
        )
        return True

    def invites_enabled(self, player: str) -> bool:
        return bool(self._prefs(player)["notify_invites"])
