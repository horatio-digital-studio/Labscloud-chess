"""Configuration from Worker vars/secrets (or the dev server's equivalents)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PLAYER_KEYS: tuple[str, str] = ("harry", "partner")
ENVIRONMENTS = ("development", "staging", "production")

DEV_PLAYERS: dict[str, dict[str, str]] = {
    "harry": {"email": "harry@example.test", "name": "Harry"},
    "partner": {"email": "partner@example.test", "name": "Partner"},
}


class ConfigError(Exception):
    pass


def normalise_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class Player:
    key: str
    email: str
    default_name: str


@dataclass(frozen=True)
class PlayerDirectory:
    players: tuple[Player, Player]

    @classmethod
    def from_json(cls, raw: str) -> PlayerDirectory:
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ConfigError("PLAYERS_JSON is not valid JSON") from exc
        if not isinstance(data, dict) or set(data) != set(PLAYER_KEYS):
            raise ConfigError("PLAYERS_JSON must have exactly the keys 'harry' and 'partner'")
        players: list[Player] = []
        for key in PLAYER_KEYS:
            entry = data[key]
            if not isinstance(entry, dict):
                raise ConfigError(f"PLAYERS_JSON.{key} must be an object")
            email, name = entry.get("email"), entry.get("name")
            if not isinstance(email, str) or "@" not in email:
                raise ConfigError(f"PLAYERS_JSON.{key}.email is missing or invalid")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError(f"PLAYERS_JSON.{key}.name is missing")
            players.append(
                Player(key=key, email=normalise_email(email), default_name=name.strip()[:24])
            )
        if players[0].email == players[1].email:
            raise ConfigError("PLAYERS_JSON emails must differ")
        return cls(players=(players[0], players[1]))

    def by_email(self, email: str) -> Player | None:
        wanted = normalise_email(email)
        for player in self.players:
            if player.email == wanted:
                return player
        return None

    def by_key(self, key: str) -> Player | None:
        for player in self.players:
            if player.key == key:
                return player
        return None

    def opponent(self, key: str) -> Player:
        return self.players[1] if self.players[0].key == key else self.players[0]


@dataclass(frozen=True)
class Config:
    app_env: str
    public_url: str
    access_team_domain: str
    access_aud: str
    players: PlayerDirectory
    mail_from: str
    email_enabled: bool
    version: str
    commit: str

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def site_host(self) -> str:
        return self.public_url.split("://", 1)[-1].rstrip("/")

    @classmethod
    def from_env(cls, get: Callable[[str], Any]) -> Config:
        """Build from a getter returning the var/secret value, or None when unset."""

        def text(name: str, default: str = "") -> str:
            value = get(name)
            return default if value is None else str(value)

        app_env = text("APP_ENV", "production")
        if app_env not in ENVIRONMENTS:
            raise ConfigError(f"APP_ENV must be one of {ENVIRONMENTS}")
        players_raw = text("PLAYERS_JSON")
        if players_raw:
            players = PlayerDirectory.from_json(players_raw)
        elif app_env == "development":
            players = PlayerDirectory.from_json(json.dumps(DEV_PLAYERS))
        else:
            raise ConfigError("PLAYERS_JSON secret is required outside development")

        aud = text("ACCESS_AUD")
        team = text("ACCESS_TEAM_DOMAIN").rstrip("/")
        if app_env != "development" and (not aud or not team.startswith("https://")):
            raise ConfigError("ACCESS_AUD and ACCESS_TEAM_DOMAIN are required outside development")

        public_url = text("PUBLIC_URL", "http://localhost:8787").rstrip("/")
        return cls(
            app_env=app_env,
            public_url=public_url,
            access_team_domain=team,
            access_aud=aud,
            players=players,
            mail_from=text("MAIL_FROM", "chess@labscloud.uk"),
            email_enabled=text("EMAIL_ENABLED", "false").lower() == "true",
            version=text("VERSION", "0.0.0"),
            commit=text("COMMIT", "dev") or "dev",
        )
