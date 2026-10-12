"""Throwaway RSA keys and RS256 signing for auth tests (pure Python, deterministic)."""

from __future__ import annotations

import base64
import hashlib
import json
import random
from functools import lru_cache
from typing import Any

_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _is_probable_prime(n: int, rng: random.Random) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(24):
        a = rng.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        candidate = rng.getrandbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if _is_probable_prime(candidate, rng):
            return candidate


@lru_cache(maxsize=4)
def keypair(seed: int = 1, bits: int = 2048) -> tuple[int, int, int]:
    """Return (n, e, d)."""
    rng = random.Random(seed)
    e = 65537
    while True:
        p, q = _prime(bits // 2, rng), _prime(bits // 2, rng)
        n = p * q
        phi = (p - 1) * (q - 1)
        if p != q and n.bit_length() == bits and phi % e:
            return n, e, pow(e, -1, phi)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def int_b64url(value: int) -> str:
    return b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def jwk(kid: str, seed: int = 1) -> dict[str, Any]:
    n, e, _ = keypair(seed)
    return {
        "kid": kid,
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "e": int_b64url(e),
        "n": int_b64url(n),
    }


def sign(payload: dict[str, Any], kid: str = "k1", seed: int = 1, alg: str = "RS256") -> str:
    n, _, d = keypair(seed)
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    k = (n.bit_length() + 7) // 8
    t = _DIGEST_INFO + hashlib.sha256(signing_input.encode("ascii")).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    signature = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{signing_input}.{b64url(signature)}"
