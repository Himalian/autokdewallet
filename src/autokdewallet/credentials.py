"""Read the wallet password from systemd credentials (TPM-backed)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# `just install` and `just generate_password` keep the runtime here.
RUNTIME_DIR = Path.home() / ".autokdewallet"
DEFAULT_CRED_FILE = RUNTIME_DIR / "password.cred"


def get_tpm_password(cred_file: str | Path = DEFAULT_CRED_FILE) -> bytes:
    """Return the wallet password stored in a systemd credential.

    When a unit uses ``SetCredentialEncrypted=``, systemd decrypts the
    credential into ``$CREDENTIALS_DIRECTORY/password``. Otherwise fall back
    to decrypting the file with ``systemd-creds``.
    """
    creds_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if creds_dir:
        cred_path = Path(creds_dir) / "password"
        if cred_path.exists():
            return cred_path.read_bytes().strip()

    result = subprocess.run(
        ["systemd-creds", "decrypt", "--user", str(cred_file), "-"],
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()
