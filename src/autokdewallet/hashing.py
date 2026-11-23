"""KWallet-compatible PBKDF2-SHA512 key derivation."""

from __future__ import annotations

import hashlib

# PBKDF2 parameters from KWallet's src/runtime/kwalletbackend/kwalletbackend.h:
# PBKDF2_SHA512_ITERATIONS = 50000, PBKDF2_SHA512_KEYSIZE = 56.
ITERATIONS = 50_000
KEY_SIZE = 56
HASH_ALGO = "sha512"


def derive_kwallet_hash(password: bytes, salt: bytes) -> bytes:
    """Derive the 56-byte key KWallet's PAM interface expects."""
    return hashlib.pbkdf2_hmac(HASH_ALGO, password, salt, ITERATIONS, KEY_SIZE)
