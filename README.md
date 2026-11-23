# AutoKDEWallet

**AutoKDEWallet** is a Python utility that unlocks a password-protected KDE Wallet (KWallet) upon login using a user-scoped `systemd-creds` credential.

It targets the default `kdewallet` when that wallet uses Blowfish encryption with PBKDF2-SHA512. GPG-backed wallets use a different unlock path and are not supported. `systemd-creds` may bind the credential to the TPM, depending on its key selection on the host.

## How It Works

1.  **Secure Storage**: Your KWallet password is encrypted using `systemd-creds --user` and stored as `~/.autokdewallet/password.cred`. That directory is mode `0700`. The credential is scoped to your user and machine; TPM binding depends on the key type selected by `systemd-creds` and is not enforced by this utility.
2.  **Automatic Unlock**: A systemd user service runs `python3 -m autokdewallet` before Plasma (`graphical-session-pre.target`).
3.  **Hash Derivation**: The script reads the encrypted password, retrieves your wallet's salt, and calculates the PBKDF2-SHA512 hash KWallet expects (50,000 iterations, 56 bytes).
4.  **ksecretd handshake**: Since KDE Frameworks 6.29, `kwalletd` no longer exposes the D-Bus `pamOpen` method. The script starts `ksecretd --pam-login`, writes the hash down the pipe, then sends the session environment over `kwallet5.socket`, which is what `pam_kwallet` does.

## Prerequisites

- **Linux with systemd 256 or newer** (`systemd-creds --user` was added in v256).
- **KDE Plasma 6** with `ksecretd` (KDE Frameworks 6.29 or newer).
- **A password-backed `kdewallet` using Blowfish and PBKDF2-SHA512**. GPG-backed wallets cannot be unlocked with the PAM password hash used here.
- **TPM 2.0** enabled in your BIOS/UEFI if hardware binding is required; functional unlocking can also use a host-key credential.
- **Python 3.10+** (stdlib only; `dbus-python` is not required).
- **Just** for the documented install and enable recipes.

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Himalian/autokdewallet.git
cd autokdewallet
```

Use `just -l` to see all available commands.

```bash
just -l
```

### 2. Install the Runtime

`just install` copies the `autokdewallet` package from `src/` into `~/.autokdewallet`, removes scripts left behind by the old flat layout, and installs `systemd/kwallet_auto_unlock.service` as a user unit. The service always runs from `~/.autokdewallet`, so the clone can live anywhere.

If `password.cred` is still in the clone, install moves it into `~/.autokdewallet` and does not overwrite a credential already there.

```bash
just install
```

### 3. Generate Encrypted Credentials

The credential is written to `~/.autokdewallet/password.cred`, not into the clone. To keep the password out of shell history and process arguments, enter it at a hidden prompt in your local terminal:

```bash
python3 - <<'PY'
from getpass import getpass
from pathlib import Path
import subprocess

password = getpass("KWallet password: ")
if password != getpass("Repeat password: "):
    raise SystemExit("Passwords do not match")
path = Path.home() / ".autokdewallet/password.cred"
subprocess.run(
    ["systemd-creds", "encrypt", "--user", "-", str(path)],
    input=password.encode(),
    check=True,
)
path.chmod(0o600)
PY
```

The recipe also accepts the password as a **positional** argument, but doing so exposes it in process arguments and possibly shell history:

```bash
just generate_password "YOUR_KWALLET_PASSWORD"
```

The current password reader strips leading and trailing whitespace from the decrypted value. Use a wallet password without those characters. `systemd-creds` selects the encryption key automatically; on a TPM-capable system it can use both the TPM and a host key, but it can also fall back to a host key alone.

### 4. Enable the Service

This enables the unit for the next login. It does not start it immediately because another `ksecretd` may already own the current session. Check the service and wallet after the next login.

```bash
just enable
```

`just setup` runs install and enable together; use it only after `password.cred` exists.

## Usage

With display-manager autologin (for example, SDDM or Plasma Login), `pam_kwallet5.so` does not receive a login password, so this service provides the unlock path. If you switch to a password login where PAM unlocks KWallet, disable this service before the next login so that PAM and the service do not both try to start the wallet daemon. Check the PAM configuration for your actual display manager rather than assuming an SDDM path.

Once `password.cred` exists and the unit is enabled, the service runs at the next login. Do not start it in a graphical session where `ksecretd` is already running.

```bash
systemctl --user status kwallet_auto_unlock.service
```

### Manual Testing

Run the installed runtime only in a session where no wallet daemon is already running. In an active Plasma session, use the next login and the service logs to verify the handshake instead:

```bash
just run
# or
cd ~/.autokdewallet && python3 -m autokdewallet
```

Add `--no-wait` (or `AUTOKDEWALLET_NO_WAIT=1`) to hand over the environment immediately instead of waiting for Plasma to publish the graphical session variables.

### Cleaning Up

To remove Python cache files:

```bash
just clean
```

## Development

The project uses a `src/` layout and has no third-party runtime dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
just test
```

`just install` deploys the package to `~/.autokdewallet`; the checkout itself is never imported by the service.

## Troubleshooting

If your wallet does not unlock automatically:

1.  **Check Service Status**:
    ```bash
    systemctl --user status kwallet_auto_unlock.service
    ```
2.  **Check Logs**:
    ```bash
    journalctl --user -u kwallet_auto_unlock.service
    ```
3.  **Verify credential decryption**:
    Check that `systemd-creds` can decrypt the credential without displaying the password. This does not prove that it matches the wallet password:
    ```bash
    systemd-creds decrypt --user ~/.autokdewallet/password.cred - >/dev/null
    ```
4.  **Check the salt**:
    ```bash
    cd ~/.autokdewallet && python3 -m autokdewallet.salt
    ```

## Project Layout

```
.
├── AGENTS.md                  # agent/project instructions (GEMINI.md is a symlink)
├── README.md
├── justfile                   # install, enable, run, test, clean
├── pyproject.toml             # package metadata and entry point
├── src/
│   └── autokdewallet/
│       ├── __init__.py        # version
│       ├── __main__.py        # python -m autokdewallet
│       ├── credentials.py     # systemd-creds password retrieval
│       ├── hashing.py         # PBKDF2-SHA512 derivation
│       ├── salt.py            # KWallet salt reader
│       └── unlock.py          # ksecretd PAM handshake
├── systemd/
│   └── kwallet_auto_unlock.service
└── tests/
    ├── test_hashing.py
    ├── test_salt.py
    └── test_unlock.py
```
