"""Access JWT verification and identity (REQ-AUTH-02..06)."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import pytest

from app.auth import (
    AuthError,
    KeyCache,
    check_claims,
    identify,
    parse_jwks,
    split_token,
    verify_access_token,
)
from app.rsa import b64url_decode, int_from_b64url, verify_rs256
from tests.conftest import make_config
from tests.fixtures.jwt_keys import b64url, jwk, keypair, sign

TEAM = "https://team.cloudflareaccess.com"
AUD = "aud-tag"
NOW_MS = 1_760_000_000_000
NOW_S = NOW_MS // 1000


def claims(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "aud": [AUD],
        "iss": TEAM,
        "exp": NOW_S + 3600,
        "iat": NOW_S - 10,
        "nbf": NOW_S - 10,
        "email": "harry@example.test",
        "sub": "x",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


class Fetcher:
    def __init__(self, docs: list[Any]) -> None:
        self.docs = docs
        self.calls = 0

    async def __call__(self) -> Any:
        self.calls += 1
        doc = self.docs[min(self.calls - 1, len(self.docs) - 1)]
        if isinstance(doc, Exception):
            raise doc
        return doc


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def cache(*docs: Any) -> KeyCache:
    return KeyCache(Fetcher(list(docs) or [{"keys": [jwk("k1")]}]))


PROD = make_config(app_env="production", public_url="https://chess.labscloud.uk")


# --- rsa ---------------------------------------------------------------------------


def test_rsa_verifies_good_signature_and_rejects_tampering() -> None:
    token = sign(claims())
    head, body, sig = token.split(".")
    n, e, _ = keypair(1)
    signature = b64url_decode(sig)
    assert verify_rs256(f"{head}.{body}".encode(), signature, n, e)
    assert not verify_rs256(f"{head}.{body}x".encode(), signature, n, e)
    flipped = bytes([signature[0] ^ 1]) + signature[1:]
    assert not verify_rs256(f"{head}.{body}".encode(), flipped, n, e)
    assert not verify_rs256(f"{head}.{body}".encode(), signature[:-1], n, e)
    assert not verify_rs256(f"{head}.{body}".encode(), (n + 1).to_bytes(256, "big")[-256:], n, e)


def test_rsa_rejects_small_keys_and_bad_exponents() -> None:
    n, e, _ = keypair(1)
    assert not verify_rs256(b"x", b"\x00" * 256, n, 1)
    assert not verify_rs256(b"x", b"\x00" * 256, 0, e)
    small = (1 << 1023) + 1
    assert not verify_rs256(b"x", b"\x00" * 128, small, e)


def test_b64url_helpers() -> None:
    assert b64url_decode(b64url(b"\x00\xffhello")) == b"\x00\xffhello"
    assert int_from_b64url("AQAB") == 65537
    with pytest.raises(ValueError):
        b64url_decode("ab+/")
    with pytest.raises(ValueError):
        b64url_decode("a=b")


# --- jwks / split ----------------------------------------------------------------------


def test_parse_jwks_filters_bad_entries() -> None:
    doc = {
        "keys": [
            jwk("good"),
            {**jwk("ec"), "kty": "EC"},
            {**jwk("hs"), "alg": "HS256"},
            {"kid": "missing-n", "kty": "RSA", "e": "AQAB"},
            {**jwk("badn"), "n": "!!"},
            "junk",
        ]
    }
    assert set(parse_jwks(doc)) == {"good"}
    assert parse_jwks(None) == {}
    assert parse_jwks({"keys": "nope"}) == {}
    no_alg = {k: v for k, v in jwk("noalg").items() if k != "alg"}
    assert set(parse_jwks({"keys": [no_alg]})) == {"noalg"}


@pytest.mark.parametrize(
    "token", ["", "a.b", "a.b.c.d", "..", "!!.e30.AA", "e30.e30.!!", "W10.e30.AA"]
)
def test_split_token_malformed(token: str) -> None:
    with pytest.raises(AuthError) as info:
        split_token(token)
    assert info.value.code == "UNAUTHORISED"


# --- claims ------------------------------------------------------------------------------


def test_claims_accept_list_or_string_audience() -> None:
    assert check_claims(claims(), audience=AUD, issuer=TEAM, now_s=NOW_S) == "harry@example.test"
    assert (
        check_claims(claims(aud=AUD), audience=AUD, issuer=TEAM, now_s=NOW_S)
        == "harry@example.test"
    )


@pytest.mark.parametrize(
    "override",
    [
        {"aud": ["other"]},
        {"aud": None},
        {"iss": "https://evil.cloudflareaccess.com"},
        {"exp": NOW_S - 61},
        {"exp": None},
        {"exp": "soon"},
        {"exp": True},
        {"nbf": NOW_S + 61},
        {"nbf": "later"},
        {"email": None},
        {"email": "no-at-sign"},
    ],
)
def test_claims_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(AuthError):
        check_claims(claims(**override), audience=AUD, issuer=TEAM, now_s=NOW_S)


def test_claims_clock_skew_tolerated() -> None:
    check_claims(claims(exp=NOW_S - 59, nbf=NOW_S + 59), audience=AUD, issuer=TEAM, now_s=NOW_S)


# --- full verification ---------------------------------------------------------------------


def test_verify_good_token() -> None:
    config = make_config(access_aud=AUD, access_team_domain=TEAM)
    assert run(verify_access_token(sign(claims()), config, cache(), NOW_MS)) == "harry@example.test"


def test_verify_rejects_wrong_alg_missing_kid_unknown_key_and_wrong_signer() -> None:
    config = make_config(access_aud=AUD, access_team_domain=TEAM)
    bad_tokens = [
        sign(claims(), alg="HS256"),
        sign(claims(), alg="none"),
        sign(claims(), kid=""),
        sign(claims(), kid="unknown"),
        sign(claims(), kid="k1", seed=2),  # right kid, wrong private key
    ]
    for token in bad_tokens:
        with pytest.raises(AuthError):
            run(verify_access_token(token, config, cache(), NOW_MS))


def test_key_cache_refetches_once_a_minute_on_unknown_kid() -> None:
    fetcher = Fetcher([{"keys": [jwk("k1")]}, {"keys": [jwk("k2", seed=2)]}])
    keys = KeyCache(fetcher)
    assert run(keys.key_for("k1", NOW_MS)) is not None
    assert run(keys.key_for("k1", NOW_MS + 1)) is not None
    assert fetcher.calls == 1
    assert run(keys.key_for("k2", NOW_MS + 30_000)) is None  # throttled
    assert fetcher.calls == 1
    assert run(keys.key_for("k2", NOW_MS + 60_000)) is not None  # rotation picked up
    assert fetcher.calls == 2
    assert run(keys.key_for("k1", NOW_MS + 60_001)) is None  # old key dropped after rotation


def test_key_cache_keeps_keys_on_fetch_failure_or_empty_doc() -> None:
    fetcher = Fetcher([{"keys": [jwk("k1")]}, RuntimeError("network"), {"keys": []}])
    keys = KeyCache(fetcher)
    run(keys.key_for("k1", NOW_MS))
    assert run(keys.key_for("zz", NOW_MS + 60_000)) is None
    assert run(keys.key_for("k1", NOW_MS + 60_000)) is not None
    assert run(keys.key_for("zz", NOW_MS + 120_000)) is None
    assert run(keys.key_for("k1", NOW_MS + 120_000)) is not None


# --- identify ---------------------------------------------------------------------------------


def ident(
    config: Any,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Any:
    return run(
        identify(
            headers=headers or {},
            query=query or {},
            cookies=cookies or {},
            config=config,
            keys=cache(),
            now_ms=NOW_MS,
        )
    )


def prod_config(**overrides: Any) -> Any:
    return make_config(app_env="production", access_aud=AUD, access_team_domain=TEAM, **overrides)


def test_identify_with_jwt() -> None:
    player, dev_cookie = ident(prod_config(), headers={"cf-access-jwt-assertion": sign(claims())})
    assert player.key == "harry" and dev_cookie is None


def test_identify_email_case_insensitive() -> None:
    token = sign(claims(email="Partner@Example.TEST"))
    player, _ = ident(prod_config(), headers={"cf-access-jwt-assertion": token})
    assert player.key == "partner"


def test_identify_stranger_rejected() -> None:
    token = sign(claims(email="stranger@example.test"))
    with pytest.raises(AuthError) as info:
        ident(prod_config(), headers={"cf-access-jwt-assertion": token})
    assert info.value.code == "NOT_A_PLAYER"


def test_identify_missing_token() -> None:
    with pytest.raises(AuthError) as info:
        ident(prod_config())
    assert info.value.code == "UNAUTHORISED"


@pytest.mark.parametrize("env", ["staging", "production"])
def test_dev_bypass_ignored_outside_development(env: str) -> None:
    config = make_config(app_env=env, access_aud=AUD, access_team_domain=TEAM)
    for kwargs in ({"query": {"as": "harry"}}, {"cookies": {"dev_as": "harry"}}):
        with pytest.raises(AuthError) as info:
            ident(config, **kwargs)
        assert info.value.code == "UNAUTHORISED"


def test_dev_bypass_in_development() -> None:
    config = make_config()
    player, cookie = ident(config, query={"as": "partner"})
    assert player.key == "partner" and cookie == "partner"
    player, cookie = ident(config, cookies={"dev_as": "harry"})
    assert player.key == "harry" and cookie is None
    with pytest.raises(AuthError) as info:
        ident(config, query={"as": "mallory"})
    assert info.value.code == "NOT_A_PLAYER"


def test_development_still_accepts_jwt() -> None:
    config = make_config(access_aud=AUD, access_team_domain=TEAM)
    player, _ = ident(
        config, headers={"cf-access-jwt-assertion": sign(claims(email="partner@example.test"))}
    )
    assert player.key == "partner"


def test_unpadded_signature_variants_rejected() -> None:
    token = sign(claims())
    head, body, sig = token.split(".")
    padded = base64.urlsafe_b64encode(b64url_decode(sig)).decode()
    assert padded.endswith("=")  # 256 bytes always needs padding
    with pytest.raises(AuthError):
        run(verify_access_token(f"{head}.{body}.{padded}", prod_config(), cache(), NOW_MS))
