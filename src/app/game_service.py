"""Authoritative game logic for one GameRoom Durable Object (docs/data-model.md §2).

Every call reads what it needs from storage, so there is no in-memory state to lose
when the Durable Object hibernates (REQ-RT-06): each message is handled exactly as it
would be after a cold start.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from app.storage import Storage, split_statements, table_exists
from chess_core.engine import (
    COLOURS,
    STARTING_FEN,
    TERMINAL_STATUSES,
    Colour,
    PlayedMove,
    Position,
    initial_counts,
    other,
    position_key,
    win_for,
)
from chess_core.pgn import export_pgn
from chess_core.protocol import PROTOCOL_VERSION, ClientMessage

SCHEMA_VERSION = "1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS game (
  id               TEXT PRIMARY KEY,
  white            TEXT NOT NULL,
  black            TEXT NOT NULL,
  start_fen        TEXT NOT NULL,
  current_fen      TEXT NOT NULL,
  ply              INTEGER NOT NULL,
  status           TEXT NOT NULL,
  result           TEXT,
  draw_offer_from  TEXT,
  takeback_from    TEXT,
  rematch_white    INTEGER NOT NULL DEFAULT 0,
  rematch_black    INTEGER NOT NULL DEFAULT 0,
  rematch_game_id  TEXT,
  created_at       INTEGER NOT NULL,
  updated_at       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS moves (
  ply        INTEGER PRIMARY KEY,
  uci        TEXT NOT NULL,
  san        TEXT NOT NULL,
  fen_after  TEXT NOT NULL,
  by_colour  TEXT NOT NULL,
  played_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
  key    TEXT PRIMARY KEY,
  count  INTEGER NOT NULL
)
"""


class GameNotFound(Exception):
    pass


@dataclass(frozen=True)
class GameRow:
    id: str
    white: str
    black: str
    start_fen: str
    current_fen: str
    ply: int
    status: str
    result: str | None
    draw_offer_from: Colour | None
    takeback_from: Colour | None
    rematch_white: bool
    rematch_black: bool
    rematch_game_id: str | None
    created_at: int
    updated_at: int

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def colour_of(self, player: str) -> Colour | None:
        if player == self.white:
            return "white"
        if player == self.black:
            return "black"
        return None

    def player_of(self, colour: Colour) -> str:
        return self.white if colour == "white" else self.black

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GameRow:
        return cls(
            id=str(row["id"]),
            white=str(row["white"]),
            black=str(row["black"]),
            start_fen=str(row["start_fen"]),
            current_fen=str(row["current_fen"]),
            ply=int(row["ply"]),
            status=str(row["status"]),
            result=row["result"],
            draw_offer_from=cast("Colour | None", row["draw_offer_from"]),
            takeback_from=cast("Colour | None", row["takeback_from"]),
            rematch_white=bool(row["rematch_white"]),
            rematch_black=bool(row["rematch_black"]),
            rematch_game_id=row["rematch_game_id"],
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )


@dataclass
class Outcome:
    """What happened when a message was handled; the room decides what to send."""

    error: str | None = None
    changed: bool = False
    ended: bool = False
    moved: PlayedMove | None = None
    needs_rematch: bool = False
    rematch_ready: str | None = None


class GameService:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    # ------------------------------------------------------------------ setup
    def _migrate(self) -> None:
        for statement in split_statements(SCHEMA):
            self.storage.execute(statement)
        self.storage.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            SCHEMA_VERSION,
        )

    def exists(self) -> bool:
        if not table_exists(self.storage, "game"):
            return False
        return bool(self.storage.query("SELECT id FROM game LIMIT 1"))

    def init(
        self,
        game_id: str,
        white: str,
        black: str,
        names: dict[str, str],
        now: int,
        start_fen: str = STARTING_FEN,
    ) -> None:
        """Create the game (idempotent: a second call for the same game changes nothing)."""

        def run() -> None:
            self._migrate()
            if self.storage.query("SELECT id FROM game LIMIT 1"):
                return
            counts = initial_counts(start_fen)
            fen = Position(start_fen, counts).fen
            self.storage.execute(
                "INSERT INTO game (id, white, black, start_fen, current_fen, ply, status, result, "
                "draw_offer_from, takeback_from, rematch_white, rematch_black, rematch_game_id, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 0, 'active', NULL, NULL, NULL, "
                "0, 0, NULL, ?, ?)",
                game_id,
                white,
                black,
                fen,
                fen,
                now,
                now,
            )
            for key, count in counts.items():
                self.storage.execute("INSERT INTO positions (key, count) VALUES (?, ?)", key, count)
            self._store_names(names)

        self.storage.transaction(run)

    def set_names(self, names: dict[str, str]) -> None:
        if self.exists():
            self.storage.transaction(lambda: self._store_names(names))

    def _store_names(self, names: dict[str, str]) -> None:
        for player, name in names.items():
            self.storage.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                f"name:{player}",
                name,
            )

    # ----------------------------------------------------------------- reading
    def row(self) -> GameRow:
        if not table_exists(self.storage, "game"):
            raise GameNotFound
        rows = self.storage.query("SELECT * FROM game LIMIT 1")
        if not rows:
            raise GameNotFound
        return GameRow.from_row(rows[0])

    def moves(self) -> list[dict[str, Any]]:
        return self.storage.query("SELECT ply, uci, san, by_colour FROM moves ORDER BY ply")

    def counts(self) -> dict[str, int]:
        return {
            str(r["key"]): int(r["count"])
            for r in self.storage.query("SELECT key, count FROM positions")
        }

    def names(self, row: GameRow) -> dict[str, str]:
        stored = {
            str(r["key"])[5:]: str(r["value"])
            for r in self.storage.query("SELECT key, value FROM meta WHERE key LIKE 'name:%'")
        }
        return {
            player: stored.get(player, player.capitalize()) for player in (row.white, row.black)
        }

    def states(self, online: dict[str, bool]) -> dict[Colour, dict[str, Any]]:
        """Full `state` message for each colour (docs/protocol.md §4.1)."""
        row = self.row()
        position = Position(row.current_fen, self.counts())
        moves = self.moves()
        names = self.names(row)
        legal = position.legal_ucis() if row.status == "active" else []
        claimable = row.status == "active" and position.can_claim_draw()
        last = moves[-1] if moves else None
        base: dict[str, Any] = {
            "type": "state",
            "v": PROTOCOL_VERSION,
            "game_id": row.id,
            "players": {
                "white": {"player": row.white, "name": names[row.white]},
                "black": {"player": row.black, "name": names[row.black]},
            },
            "fen": row.current_fen,
            "ply": row.ply,
            "turn": position.turn,
            "moves": [{"uci": m["uci"], "san": m["san"]} for m in moves],
            "last_move": {"uci": last["uci"], "san": last["san"]} if last else None,
            "check": position.is_check,
            "status": row.status,
            "result": row.result,
            "draw_offer_from": row.draw_offer_from,
            "takeback_from": row.takeback_from,
            "rematch": {
                "white": row.rematch_white,
                "black": row.rematch_black,
                "game_id": row.rematch_game_id,
            },
            "online": {"white": bool(online.get("white")), "black": bool(online.get("black"))},
            "updated_at": row.updated_at,
        }
        out: dict[Colour, dict[str, Any]] = {}
        for colour in COLOURS:
            mine = colour == position.turn
            out[colour] = {
                **base,
                "you": colour,
                "legal": legal if mine else [],
                "can_claim_draw": claimable and mine,
            }
        return out

    def summary(self) -> dict[str, Any]:
        row = self.row()
        return {
            "id": row.id,
            "status": row.status,
            "result": row.result,
            "ply": row.ply,
            "updated_at": row.updated_at,
        }

    def pgn(self, site: str) -> str:
        row = self.row()
        names = self.names(row)
        return export_pgn(
            site=site,
            epoch_ms=row.created_at,
            white=names[row.white],
            black=names[row.black],
            sans=[str(m["san"]) for m in self.moves()],
            result=row.result,
        )

    # ---------------------------------------------------------------- actions
    def handle(self, colour: Colour, msg: ClientMessage, now: int) -> Outcome:
        """Apply one game action from `colour`. Never raises for player mistakes."""
        row = self.row()
        if msg.type == "rematch":
            return self._rematch(row, colour, now)
        if row.terminal:
            return Outcome(error="GAME_OVER")
        handler = {
            "move": self._move,
            "resign": self._resign,
            "draw_offer": self._draw_offer,
            "draw_accept": self._draw_accept,
            "draw_decline": self._draw_decline,
            "claim_draw": self._claim_draw,
            "takeback_request": self._takeback_request,
            "takeback_accept": self._takeback_accept,
            "takeback_decline": self._takeback_decline,
        }.get(msg.type)
        if handler is None:
            return Outcome(error="BAD_MESSAGE")
        return handler(row, colour, msg, now)

    def _update(self, now: int, **fields: Any) -> None:
        # Column names come from keyword arguments in this module, never from input.
        assignments = ", ".join(f"{name} = ?" for name in fields)
        self.storage.execute(
            f"UPDATE game SET {assignments}, updated_at = ?",  # noqa: S608
            *fields.values(),
            now,
        )

    def _move(self, row: GameRow, colour: Colour, msg: ClientMessage, now: int) -> Outcome:
        position = Position(row.current_fen, self.counts())
        if colour != position.turn:
            return Outcome(error="NOT_YOUR_TURN")
        if msg.ply != row.ply:
            return Outcome(error="STALE_PLY")
        uci = msg.uci or ""
        error = position.move_error(colour, uci)
        if error:
            return Outcome(error=error)
        played = position.play(uci)
        status, result = position.verdict()
        new_ply = row.ply + 1
        # A move clears any takeback request, and the draw offer if the mover was offered it.
        draw_offer = row.draw_offer_from if row.draw_offer_from == colour else None

        def write() -> None:
            self.storage.execute(
                "INSERT INTO moves (ply, uci, san, fen_after, by_colour, played_at) VALUES (?, ?, ?, ?, ?, ?)",
                new_ply,
                played.uci,
                played.san,
                played.fen_after,
                played.by_colour,
                now,
            )
            self.storage.execute(
                "INSERT INTO positions (key, count) VALUES (?, 1) "
                "ON CONFLICT(key) DO UPDATE SET count = count + 1",
                played.key_after,
            )
            self._update(
                now,
                current_fen=played.fen_after,
                ply=new_ply,
                status=status,
                result=result,
                draw_offer_from=None if status != "active" else draw_offer,
                takeback_from=None,
            )

        self.storage.transaction(write)
        return Outcome(changed=True, ended=status != "active", moved=played)

    def _resign(self, row: GameRow, colour: Colour, msg: ClientMessage, now: int) -> Outcome:
        self.storage.transaction(
            lambda: self._update(
                now,
                status="resigned",
                result=win_for(other(colour)),
                draw_offer_from=None,
                takeback_from=None,
            )
        )
        return Outcome(changed=True, ended=True)

    def _agree_draw(self, now: int) -> Outcome:
        self.storage.transaction(
            lambda: self._update(
                now,
                status="draw_agreed",
                result="1/2-1/2",
                draw_offer_from=None,
                takeback_from=None,
            )
        )
        return Outcome(changed=True, ended=True)

    def _draw_offer(self, row: GameRow, colour: Colour, msg: ClientMessage, now: int) -> Outcome:
        if row.draw_offer_from == colour:
            return Outcome(error="DRAW_ALREADY_OFFERED")
        if row.draw_offer_from == other(colour):
            return self._agree_draw(now)  # crossing offers (REQ-ACT-05)
        self.storage.transaction(lambda: self._update(now, draw_offer_from=colour))
        return Outcome(changed=True)

    def _draw_answer_error(self, row: GameRow, colour: Colour) -> str | None:
        if row.draw_offer_from is None:
            return "NO_DRAW_OFFER"
        if row.draw_offer_from == colour:
            return "OWN_DRAW_OFFER"
        return None

    def _draw_accept(self, row: GameRow, colour: Colour, msg: ClientMessage, now: int) -> Outcome:
        error = self._draw_answer_error(row, colour)
        if error:
            return Outcome(error=error)
        return self._agree_draw(now)

    def _draw_decline(self, row: GameRow, colour: Colour, msg: ClientMessage, now: int) -> Outcome:
        error = self._draw_answer_error(row, colour)
        if error:
            return Outcome(error=error)
        self.storage.transaction(lambda: self._update(now, draw_offer_from=None))
        return Outcome(changed=True)

    def _claim_draw(self, row: GameRow, colour: Colour, msg: ClientMessage, now: int) -> Outcome:
        position = Position(row.current_fen, self.counts())
        if colour != position.turn:
            return Outcome(error="NOT_YOUR_TURN")
        if not position.can_claim_draw():
            return Outcome(error="CANNOT_CLAIM")
        self.storage.transaction(
            lambda: self._update(
                now,
                status="draw_claimed",
                result="1/2-1/2",
                draw_offer_from=None,
                takeback_from=None,
            )
        )
        return Outcome(changed=True, ended=True)

    def _takeback_request(
        self, row: GameRow, colour: Colour, msg: ClientMessage, now: int
    ) -> Outcome:
        if row.takeback_from is not None:
            return Outcome(error="TAKEBACK_ALREADY_REQUESTED")
        mine = self.storage.query("SELECT ply FROM moves WHERE by_colour = ? LIMIT 1", colour)
        if not mine:
            return Outcome(error="TAKEBACK_NOT_AVAILABLE")
        self.storage.transaction(lambda: self._update(now, takeback_from=colour))
        return Outcome(changed=True)

    def _takeback_answer_error(self, row: GameRow, colour: Colour) -> str | None:
        if row.takeback_from is None:
            return "NO_TAKEBACK_REQUEST"
        if row.takeback_from == colour:
            return "OWN_TAKEBACK_REQUEST"
        return None

    def _takeback_accept(
        self, row: GameRow, colour: Colour, msg: ClientMessage, now: int
    ) -> Outcome:
        error = self._takeback_answer_error(row, colour)
        if error:
            return Outcome(error=error)
        requester = row.takeback_from
        last = self.storage.query(
            "SELECT MAX(ply) AS ply FROM moves WHERE by_colour = ?", requester
        )
        last_ply = last[0]["ply"] if last else None
        if last_ply is None:  # cannot happen: the request required a move; fail safe
            self.storage.transaction(lambda: self._update(now, takeback_from=None))
            return Outcome(changed=True)
        target = int(last_ply) - 1

        def undo() -> None:
            removed = self.storage.query("SELECT fen_after FROM moves WHERE ply > ?", target)
            for item in removed:
                key = position_key(str(item["fen_after"]))
                self.storage.execute("UPDATE positions SET count = count - 1 WHERE key = ?", key)
            self.storage.execute("DELETE FROM positions WHERE count <= 0")
            self.storage.execute("DELETE FROM moves WHERE ply > ?", target)
            if target == 0:
                fen = row.start_fen
            else:
                fen = str(
                    self.storage.query("SELECT fen_after FROM moves WHERE ply = ?", target)[0][
                        "fen_after"
                    ]
                )
            self._update(now, current_fen=fen, ply=target, takeback_from=None, draw_offer_from=None)

        self.storage.transaction(undo)
        return Outcome(changed=True)

    def _takeback_decline(
        self, row: GameRow, colour: Colour, msg: ClientMessage, now: int
    ) -> Outcome:
        error = self._takeback_answer_error(row, colour)
        if error:
            return Outcome(error=error)
        self.storage.transaction(lambda: self._update(now, takeback_from=None))
        return Outcome(changed=True)

    def _rematch(self, row: GameRow, colour: Colour, now: int) -> Outcome:
        if not row.terminal:
            return Outcome(error="REMATCH_NOT_AVAILABLE")
        if row.rematch_game_id:
            return Outcome(rematch_ready=row.rematch_game_id)
        votes = {"white": row.rematch_white, "black": row.rematch_black}
        votes[colour] = True
        if not (row.rematch_white if colour == "white" else row.rematch_black):
            column = "rematch_white" if colour == "white" else "rematch_black"
            self.storage.transaction(lambda: self._update(now, **{column: 1}))
        return Outcome(changed=True, needs_rematch=votes["white"] and votes["black"])

    def set_rematch_game(self, new_game_id: str, now: int) -> None:
        row = self.row()
        if row.rematch_game_id:
            return
        self.storage.transaction(lambda: self._update(now, rematch_game_id=new_game_id))

    # ------------------------------------------------------------ diagnostics
    def diag_move(self, uci: str, now: int) -> Outcome:
        """Staging-only CPU check: play `uci` for whichever side is to move."""
        row = self.row()
        position = Position(row.current_fen, self.counts())
        msg = ClientMessage(type="move", uci=uci, ply=row.ply)
        return self.handle(position.turn, msg, now)
