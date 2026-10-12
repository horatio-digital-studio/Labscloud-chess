"""Strict client message parsing and server message builders (REQ-RT-08)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chess_core.protocol import (
    ERROR_MESSAGES,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    SIMPLE_TYPES,
    ClientMessage,
    ProtocolError,
    dumps,
    error_message,
    parse_client_message,
    pong_message,
    presence_message,
    rematch_ready_message,
)


def test_parse_move() -> None:
    assert parse_client_message('{"type":"move","uci":"e2e4","ply":0}') == ClientMessage(
        "move", "e2e4", 0
    )


def test_parse_move_bytes() -> None:
    assert parse_client_message(b'{"type":"move","uci":"e7e8q","ply":12}').uci == "e7e8q"


def test_parse_hello_variants() -> None:
    assert parse_client_message('{"type":"hello"}') == ClientMessage("hello")
    assert parse_client_message('{"type":"hello","since_ply":4}').since_ply == 4


@pytest.mark.parametrize("kind", sorted(SIMPLE_TYPES))
def test_parse_simple(kind: str) -> None:
    assert parse_client_message(json.dumps({"type": kind})) == ClientMessage(kind)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[]",
        '"move"',
        "null",
        "{}",
        '{"type":7}',
        '{"type":"dance"}',
        '{"type":"move","uci":"e2e4"}',
        '{"type":"move","ply":0}',
        '{"type":"move","uci":"e2e4","ply":0,"extra":1}',
        '{"type":"move","uci":"e2e4","ply":-1}',
        '{"type":"move","uci":"e2e4","ply":1.5}',
        '{"type":"move","uci":"e2e4","ply":true}',
        '{"type":"move","uci":"e2e4","ply":"0"}',
        '{"type":"move","uci":5,"ply":0}',
        '{"type":"move","uci":"' + "a" * 17 + '","ply":0}',
        '{"type":"resign","reason":"bored"}',
        '{"type":"hello","since_ply":-1}',
        '{"type":"hello","since_ply":false}',
        '{"type":"hello","since_ply":null}',
        '{"type":"hello","name":"x"}',
        '{"type":"abort"}',
    ],
)
def test_parse_rejects(raw: str) -> None:
    with pytest.raises(ProtocolError):
        parse_client_message(raw)


def test_long_but_malformed_uci_is_left_to_engine() -> None:
    # Up to 16 characters passes parsing; the engine answers BAD_FORMAT, so the
    # player sees a specific error rather than BAD_MESSAGE.
    assert parse_client_message('{"type":"move","uci":"castle","ply":0}').uci == "castle"


def test_size_limit() -> None:
    padding = " " * (MAX_MESSAGE_BYTES - len('{"type":"ping"}'))
    assert parse_client_message('{"type":"ping"}' + padding).type == "ping"
    with pytest.raises(ProtocolError):
        parse_client_message('{"type":"ping"}' + padding + " ")
    with pytest.raises(ProtocolError):
        parse_client_message(('{"type":"ping"}' + padding + " ").encode())


def test_size_limit_counts_utf8_bytes() -> None:
    body = '{"type":"ping"}' + " " * 10
    text = body + "é" * ((MAX_MESSAGE_BYTES - len(body)) // 2 + 1)
    with pytest.raises(ProtocolError):
        parse_client_message(text)


def test_invalid_utf8_and_non_text() -> None:
    with pytest.raises(ProtocolError):
        parse_client_message(b"\xff\xfe")
    with pytest.raises(ProtocolError):
        parse_client_message(42)  # type: ignore[arg-type]


def test_deep_nesting_rejected_not_crash() -> None:
    with pytest.raises(ProtocolError):
        parse_client_message("[" * 600 + "]" * 600)


def test_error_message_shape() -> None:
    message = error_message("ILLEGAL_MOVE", "move")
    assert message == {
        "type": "error",
        "v": PROTOCOL_VERSION,
        "code": "ILLEGAL_MOVE",
        "message": ERROR_MESSAGES["ILLEGAL_MOVE"],
        "in_reply_to": "move",
    }
    assert error_message("WHATEVER", None)["message"] == "Something went wrong."


def test_builders() -> None:
    assert presence_message({"white": True, "black": False})["online"] == {
        "white": True,
        "black": False,
    }
    assert rematch_ready_message("abc") == {"type": "rematch_ready", "v": 1, "game_id": "abc"}
    assert pong_message(5) == {"type": "pong", "v": 1, "t": 5}


def test_dumps_compact_and_unicode() -> None:
    assert dumps({"a": "½"}) == '{"a":"½"}'


def test_error_messages_are_british_and_complete() -> None:
    schema = json.loads(Path("docs/protocol.schema.json").read_text(encoding="utf-8"))
    codes = set(schema["$defs"]["error_code"]["enum"])
    assert codes == set(ERROR_MESSAGES)
    assert "UNAUTHORISED" in codes
