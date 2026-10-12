"""Structured JSON logging (REQ-NFR-06). Player keys only; never emails, JWTs or secrets."""

from __future__ import annotations

import json
from typing import Any

_FORBIDDEN = ("email", "token", "jwt", "secret", "authorization", "cookie")


def log_line(event: str, **fields: Any) -> str:
    safe = {
        key: value
        for key, value in fields.items()
        if not any(bad in key.lower() for bad in _FORBIDDEN)
    }
    return json.dumps({"event": event, **safe}, separators=(",", ":"), default=str)


def log(event: str, **fields: Any) -> None:
    print(log_line(event, **fields))
