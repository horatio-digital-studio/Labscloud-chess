"""Configuration parsing (REQ-AUTH-01, REQ-OPS-*)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.config import Config, ConfigError, PlayerDirectory

GOOD = {
    "harry": {"email": " Harry@Example.com ", "name": "Harry"},
    "partner": {"email": "p@example.com", "name": "P"},
}


def env(**values: Any) -> Any:
    return values.get


def test_player_directory_normalises_and_looks_up() -> None:
    directory = PlayerDirectory.from_json(json.dumps(GOOD))
    assert directory.by_email("HARRY@example.com").key == "harry"  # type: ignore[union-attr]
    assert directory.by_email("nobody@example.com") is None
    assert directory.by_key("partner").default_name == "P"  # type: ignore[union-attr]
    assert directory.by_key("mallory") is None
    assert directory.opponent("harry").key == "partner"
    assert directory.opponent("partner").key == "harry"


def test_long_default_name_truncated() -> None:
    data = json.loads(json.dumps(GOOD))
    data["harry"]["name"] = "H" * 40
    assert PlayerDirectory.from_json(json.dumps(data)).by_key("harry").default_name == "H" * 24  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"harry": GOOD["harry"]}),
        json.dumps({**GOOD, "eve": GOOD["harry"]}),
        json.dumps({**GOOD, "partner": "p@example.com"}),
        json.dumps({**GOOD, "partner": {"email": "nope", "name": "P"}}),
        json.dumps({**GOOD, "partner": {"email": "p@example.com", "name": "  "}}),
        json.dumps({**GOOD, "partner": {"email": "harry@example.com", "name": "P"}}),
    ],
)
def test_player_directory_rejects(raw: str) -> None:
    with pytest.raises(ConfigError):
        PlayerDirectory.from_json(raw)


def test_from_env_development_defaults() -> None:
    config = Config.from_env(env(APP_ENV="development"))
    assert config.is_development
    assert config.players.by_key("harry") is not None
    assert config.email_enabled is False
    assert config.public_url == "http://localhost:8787"
    assert config.site_host == "localhost:8787"
    assert config.commit == "dev"


def test_from_env_production_requires_secrets() -> None:
    with pytest.raises(ConfigError):
        Config.from_env(env(APP_ENV="production"))
    with pytest.raises(ConfigError):
        Config.from_env(env(APP_ENV="production", PLAYERS_JSON=json.dumps(GOOD)))
    with pytest.raises(ConfigError):
        Config.from_env(
            env(
                APP_ENV="production",
                PLAYERS_JSON=json.dumps(GOOD),
                ACCESS_AUD="a",
                ACCESS_TEAM_DOMAIN="team.com",
            )
        )


def test_from_env_default_is_production_not_development() -> None:
    with pytest.raises(ConfigError):
        Config.from_env(env())


def test_from_env_production_full() -> None:
    config = Config.from_env(
        env(
            APP_ENV="production",
            PLAYERS_JSON=json.dumps(GOOD),
            ACCESS_AUD="aud",
            ACCESS_TEAM_DOMAIN="https://team.cloudflareaccess.com/",
            PUBLIC_URL="https://chess.labscloud.uk/",
            EMAIL_ENABLED="TRUE",
            COMMIT="",
            VERSION="1.2.3",
        )
    )
    assert not config.is_development
    assert config.access_team_domain == "https://team.cloudflareaccess.com"
    assert config.public_url == "https://chess.labscloud.uk"
    assert config.site_host == "chess.labscloud.uk"
    assert config.email_enabled is True
    assert config.commit == "dev" and config.version == "1.2.3"


def test_unknown_app_env_rejected() -> None:
    with pytest.raises(ConfigError):
        Config.from_env(env(APP_ENV="prod"))
