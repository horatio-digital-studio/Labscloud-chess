from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from app.config import DEV_PLAYERS, Config, PlayerDirectory
from devserver.hub import Hub


class Clock:
    def __init__(self, start: int = 1_760_000_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


def make_config(**overrides: object) -> Config:
    base = {
        "app_env": "development",
        "public_url": "http://localhost:8787",
        "access_team_domain": "https://team.cloudflareaccess.com",
        "access_aud": "aud-tag",
        "players": PlayerDirectory.from_json(json.dumps(DEV_PLAYERS)),
        "mail_from": "chess@labscloud.uk",
        "email_enabled": False,
        "version": "0.1.0",
        "commit": "abc1234",
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def config() -> Config:
    return make_config()


@pytest.fixture
def hub_factory(clock: Clock) -> Callable[..., Hub]:
    def build(chooser: Callable[[list[str]], str] | None = None, **overrides: object) -> Hub:
        return Hub(
            make_config(**overrides), clock=clock, chooser=chooser or (lambda options: options[0])
        )

    return build


@pytest.fixture
def hub(hub_factory: Callable[..., Hub]) -> Hub:
    return hub_factory()
