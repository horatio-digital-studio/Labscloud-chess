"""RS256 (RSASSA-PKCS1-v1_5 with SHA-256) signature verification in pure Python.

Verification only needs one modular exponentiation with the small public exponent,
which is cheap, needs no third-party package, and runs identically in CPython tests
and in Pyodide. Signing is never done here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

# DER prefix of DigestInfo for SHA-256 (RFC 8017 §9.2, note 1).
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def b64url_decode(data: str) -> bytes:
    if not isinstance(data, str) or any(c not in _B64URL for c in data):
        raise ValueError("not base64url")
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


_B64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def int_from_b64url(data: str) -> int:
    return int.from_bytes(b64url_decode(data), "big")


def verify_rs256(signing_input: bytes, signature: bytes, n: int, e: int) -> bool:
    """Return True if ``signature`` is a valid RS256 signature over ``signing_input``."""
    if n <= 0 or e <= 1:
        return False
    k = (n.bit_length() + 7) // 8
    if k < 256 or len(signature) != k:  # require >= 2048-bit keys
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    digest = hashlib.sha256(signing_input).digest()
    t = _SHA256_DIGEST_INFO + digest
    ps_len = k - len(t) - 3
    if ps_len < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * ps_len + b"\x00" + t
    return hmac.compare_digest(em, expected)
