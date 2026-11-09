"""Read the salt of KWallet's ``kdewallet`` wallet."""

from __future__ import annotations

from pathlib import Path

# Default salt path of KWallet's ``kdewallet`` wallet.
KWALLET_DEFAULT_SALT_PATH: Path = Path.home() / ".local/share/kwalletd/kdewallet.salt"

SALT_SIZE = 56


def load_binary_salt(salt_path: Path = KWALLET_DEFAULT_SALT_PATH) -> bytes:
    """Read the binary salt from the KWallet wallet directory."""
    if not salt_path.exists():
        raise FileNotFoundError(f"Salt file not found: {salt_path}")

    salt = salt_path.read_bytes()
    if len(salt) != SALT_SIZE:
        raise ValueError(
            f"Expected a {SALT_SIZE}-byte salt at {salt_path}, got {len(salt)} bytes"
        )
    return salt


if __name__ == "__main__":
    current = load_binary_salt()
    print(f"Salt path: {KWALLET_DEFAULT_SALT_PATH}")
    print(f"Salt: {current.hex()}")
