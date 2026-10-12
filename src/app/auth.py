"""Cloudflare Access JWT verification and player identification (REQ-AUTH-02..06)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.config import Config, Player
from app.rsa import b64url_decode, int_from_b64url, verify_rs256

CLOCK_SKEW_SECONDS = 60
MIN_REFETCH_INTERVAL_MS = 60_000
JWT_HEADER = "cf-access-jwt-assertion"
DEV_COOKIE = "dev_as"


class AuthError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


PublicKey = tuple[int, int]  # (n, e)


def parse_jwks(data: Any) -> dict[str, PublicKey]:
    """Extract RS256 keys by kid from an Access certs document."""
    keys: dict[str, PublicKey] = {}
    if not isinstance(data, dict):
        return keys
    entries = data.get("keys")
    if not isinstance(entries, list):
        return keys
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("kty") != "RSA" or entry.get("alg", "RS256") != "RS256":
            continue
        kid, n, e = entry.get("kid"), entry.get("n"), entry.get("e")
        if not (isinstance(kid, str) and isinstance(n, str) and isinstance(e, str)):
            continue
        try:
            keys[kid] = (int_from_b64url(n), int_from_b64url(e))
        except ValueError:
            continue
    return keys


@dataclass(frozen=True)
class UnverifiedToken:
    header: dict[str, Any]
    payload: dict[str, Any]
    signing_input: bytes
    signature: bytes


def split_token(token: str) -> UnverifiedToken:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise AuthError("UNAUTHORISED", "malformed token")
    try:
        header = json.loads(b64url_decode(parts[0]))
        payload = json.loads(b64url_decode(parts[1]))
        signature = b64url_decode(parts[2])
    except ValueError as exc:
        raise AuthError("UNAUTHORISED", "malformed token") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise AuthError("UNAUTHORISED", "malformed token")
    return UnverifiedToken(header, payload, f"{parts[0]}.{parts[1]}".encode("ascii"), signature)


def check_claims(payload: Mapping[str, Any], *, audience: str, issuer: str, now_s: float) -> str:
    """Validate aud/iss/exp/nbf and return the email claim."""
    aud = payload.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if audience not in audiences:
        raise AuthError("UNAUTHORISED", "wrong audience")
    if payload.get("iss") != issuer:
        raise AuthError("UNAUTHORISED", "wrong issuer")
    exp = payload.get("exp")
    if (
        not isinstance(exp, int | float)
        or isinstance(exp, bool)
        or exp + CLOCK_SKEW_SECONDS < now_s
    ):
        raise AuthError("UNAUTHORISED", "expired")
    nbf = payload.get("nbf")
    if nbf is not None and (
        not isinstance(nbf, int | float)
        or isinstance(nbf, bool)
        or nbf - CLOCK_SKEW_SECONDS > now_s
    ):
        raise AuthError("UNAUTHORISED", "not yet valid")
    email = payload.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise AuthError("UNAUTHORISED", "no email claim")
    return email


KeyFetcher = Callable[[], Awaitable[Any]]


@dataclass
class KeyCache:
    """Caches Access signing keys; refetches at most once a minute on an unknown kid."""

    fetch_jwks: KeyFetcher
    keys: dict[str, PublicKey] = field(default_factory=dict)
    fetched_at_ms: int | None = None

    async def key_for(self, kid: str, now_ms: int) -> PublicKey | None:
        if kid in self.keys:
            return self.keys[kid]
        if self.fetched_at_ms is not None and now_ms - self.fetched_at_ms < MIN_REFETCH_INTERVAL_MS:
            return None
        self.fetched_at_ms = now_ms
        try:
            fresh = parse_jwks(await self.fetch_jwks())
        except Exception:  # network trouble: keep old keys, fail this request closed
            return None
        if fresh:
            self.keys = fresh
        return self.keys.get(kid)


async def verify_access_token(token: str, config: Config, keys: KeyCache, now_ms: int) -> str:
    """Verify an Access JWT fully and return the email it asserts."""
    parsed = split_token(token)
    if parsed.header.get("alg") != "RS256":
        raise AuthError("UNAUTHORISED", "unsupported algorithm")
    kid = parsed.header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise AuthError("UNAUTHORISED", "no kid")
    key = await keys.key_for(kid, now_ms)
    if key is None:
        raise AuthError("UNAUTHORISED", "unknown signing key")
    n, e = key
    if not verify_rs256(parsed.signing_input, parsed.signature, n, e):
        raise AuthError("UNAUTHORISED", "bad signature")
    return check_claims(
        parsed.payload,
        audience=config.access_aud,
        issuer=config.access_team_domain,
        now_s=now_ms / 1000,
    )


async def identify(
    *,
    headers: Mapping[str, str],
    query: Mapping[str, str],
    cookies: Mapping[str, str],
    config: Config,
    keys: KeyCache,
    now_ms: int,
) -> tuple[Player, str | None]:
    """Return (player, dev_cookie_to_set).

    In development only, ``?as=harry|partner`` (or the ``dev_as`` cookie it sets)
    replaces the JWT (REQ-AUTH-06). Everywhere else the Access JWT is mandatory.
    """
    if config.is_development:
        wanted = query.get("as") or cookies.get(DEV_COOKIE)
        if wanted:
            player = config.players.by_key(wanted)
            if player is None:
                raise AuthError("NOT_A_PLAYER", "unknown dev player")
            return player, (wanted if query.get("as") else None)

    token = headers.get(JWT_HEADER)
    if not token:
        raise AuthError("UNAUTHORISED", "missing token")
    email = await verify_access_token(token, config, keys, now_ms)
    player = config.players.by_email(email)
    if player is None:
        raise AuthError("NOT_A_PLAYER", "email not on the player list")
    return player, None
