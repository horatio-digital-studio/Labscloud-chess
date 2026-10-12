"""WebSocket protocol v1: strict parsing of client messages, builders for server messages.

The contract is docs/protocol.md and docs/protocol.schema.json; contract tests check
that everything built here validates against the schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024

SIMPLE_TYPES = frozenset(
    {
        "resign",
        "draw_offer",
        "draw_accept",
        "draw_decline",
        "claim_draw",
        "takeback_request",
        "takeback_accept",
        "takeback_decline",
        "rematch",
        "ping",
    }
)

ERROR_MESSAGES: dict[str, str] = {
    "UNAUTHORISED": "Please sign in again.",
    "NOT_A_PLAYER": "This account isn't one of the two players.",
    "BAD_ORIGIN": "Request from an unexpected origin.",
    "UPGRADE_REQUIRED": "This address only accepts WebSocket connections.",
    "BAD_REQUEST": "The request wasn't valid.",
    "GAME_NOT_FOUND": "No game with that ID.",
    "NOT_FOUND": "Not found.",
    "METHOD_NOT_ALLOWED": "Method not allowed.",
    "INTERNAL": "Something went wrong.",
    "BAD_MESSAGE": "That message wasn't understood.",
    "GAME_OVER": "This game has finished.",
    "NOT_YOUR_TURN": "It's not your move.",
    "STALE_PLY": "That move was based on an old position.",
    "BAD_FORMAT": "That move isn't written correctly.",
    "ILLEGAL_MOVE": "That move isn't allowed.",
    "CANNOT_CLAIM": "A draw can't be claimed right now.",
    "DRAW_ALREADY_OFFERED": "You've already offered a draw.",
    "NO_DRAW_OFFER": "There's no draw offer to answer.",
    "OWN_DRAW_OFFER": "You can't answer your own draw offer.",
    "REMATCH_NOT_AVAILABLE": "Rematch is available when the game ends.",
    "TAKEBACK_NOT_AVAILABLE": "There's no move of yours to take back.",
    "TAKEBACK_ALREADY_REQUESTED": "A takeback is already waiting for an answer.",
    "NO_TAKEBACK_REQUEST": "There's no takeback to answer.",
    "OWN_TAKEBACK_REQUEST": "You can't answer your own takeback request.",
}


class ProtocolError(Exception):
    """A client message that must be answered with BAD_MESSAGE."""

    code = "BAD_MESSAGE"


@dataclass(frozen=True)
class ClientMessage:
    type: str
    uci: str | None = None
    ply: int | None = None
    since_ply: int | None = None


def _is_int(value: Any) -> bool:
    # bool is a subclass of int in Python; JSON true/false must not pass as numbers.
    return isinstance(value, int) and not isinstance(value, bool)


def parse_client_message(raw: str | bytes) -> ClientMessage:
    """Parse and strictly validate one client message (REQ-RT-08)."""
    if isinstance(raw, bytes | bytearray):
        if len(raw) > MAX_MESSAGE_BYTES:
            raise ProtocolError("too large")
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("not utf-8") from exc
    elif isinstance(raw, str):
        text = raw
        if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ProtocolError("too large")
    else:
        raise ProtocolError("not text")

    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("not json") from exc
    if not isinstance(data, dict):
        raise ProtocolError("not an object")

    msg_type = data.get("type")
    if not isinstance(msg_type, str):
        raise ProtocolError("missing type")
    keys = set(data)

    if msg_type == "hello":
        if not keys <= {"type", "since_ply"}:
            raise ProtocolError("unknown field")
        if "since_ply" not in data:
            return ClientMessage(type="hello")
        # Optional, but when present it must be an integer ≥ 0 (null is not allowed).
        since = data["since_ply"]
        if not (_is_int(since) and since >= 0):
            raise ProtocolError("bad since_ply")
        return ClientMessage(type="hello", since_ply=since)

    if msg_type == "move":
        if keys != {"type", "uci", "ply"}:
            raise ProtocolError("move needs exactly type, uci, ply")
        uci, ply = data["uci"], data["ply"]
        if not isinstance(uci, str) or len(uci) > 16:
            raise ProtocolError("bad uci")
        if not (_is_int(ply) and ply >= 0):
            raise ProtocolError("bad ply")
        return ClientMessage(type="move", uci=uci, ply=ply)

    if msg_type in SIMPLE_TYPES:
        if keys != {"type"}:
            raise ProtocolError("unknown field")
        return ClientMessage(type=msg_type)

    raise ProtocolError("unknown type")


def dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)


def error_message(code: str, in_reply_to: str | None) -> dict[str, Any]:
    return {
        "type": "error",
        "v": PROTOCOL_VERSION,
        "code": code,
        "message": ERROR_MESSAGES.get(code, "Something went wrong."),
        "in_reply_to": in_reply_to,
    }


def presence_message(online: dict[str, bool]) -> dict[str, Any]:
    return {"type": "presence", "v": PROTOCOL_VERSION, "online": dict(online)}


def rematch_ready_message(game_id: str) -> dict[str, Any]:
    return {"type": "rematch_ready", "v": PROTOCOL_VERSION, "game_id": game_id}


def pong_message(now_ms: int) -> dict[str, Any]:
    return {"type": "pong", "v": PROTOCOL_VERSION, "t": now_ms}
