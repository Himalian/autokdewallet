# AutoKDEWallet

**AutoKDEWallet** is a Python utility that automatically unlocks your KDE Wallet (KWallet) upon login using secure credentials stored in your system's TPM (Trusted Platform Module).

It eliminates the need to manually enter your wallet password every time you log in, while maintaining a high level of security by leveraging `systemd-creds` for hardware-bound encryption.

## How It Works

1.  **Secure Storage**: Your KWallet password is encrypted using `systemd-creds` and stored as `~/.autokdewallet/password.cred`. That directory is mode `0700`. The file can only be decrypted by your user on this hardware (bound to the TPM).
2.  **Automatic Unlock**: A systemd user service runs `python3 -m autokdewallet` before Plasma (`graphical-session-pre.target`).
3.  **Hash Derivation**: The script reads the encrypted password, retrieves your wallet's salt, and calculates the PBKDF2-SHA512 hash KWallet expects (50,000 iterations, 56 bytes).
4.  **ksecretd handshake**: Since KDE Frameworks 6.29, `kwalletd` no longer exposes the D-Bus `pamOpen` method. The script starts `ksecretd --pam-login`, writes the hash down the pipe, then sends the session environment over `kwallet5.socket`, which is what `pam_kwallet` does.

## Prerequisites

- **Linux with systemd** (v248 or newer recommended for `systemd-creds`).
- **KDE Plasma 6** with `ksecretd` (KDE Frameworks 6.29 or newer).
- **TPM 2.0** enabled in your BIOS/UEFI.
- **Python 3.10+** (stdlib only; `dbus-python` is not required).
- **Just** (command runner, optional but recommended).

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

Replace `YOUR_KWALLET_PASSWORD` with your real wallet password. The credential is written to `~/.autokdewallet/password.cred`, not into the clone.

```bash
just generate_password "YOUR_KWALLET_PASSWORD"
```

Or manually:

```bash
mkdir -p ~/.autokdewallet
chmod 700 ~/.autokdewallet
echo -n "YOUR_KWALLET_PASSWORD" | systemd-creds encrypt --user - ~/.autokdewallet/password.cred
chmod 600 ~/.autokdewallet/password.cred
```

> **Note**: `password.cred` is encrypted and bound to your TPM and user. It cannot be used on another machine.

### 4. Enable the Service

This enables the unit for the next login. It does not start it immediately, because starting it mid-session replaces the `ksecretd` Plasma already launched.

```bash
just enable
```

`just setup` runs install and enable together.

## Usage

With SDDM autologin, `pam_kwallet5.so` never receives a password and does not start `ksecretd`, so this service is the unlock path. If you later switch to a password login, comment out the `pam_kwallet5.so` lines in `/etc/pam.d/sddm`, or PAM and this service will both try to own `kwallet5.socket`.

Once `password.cred` exists and the unit is enabled, the service runs at the next login. To unlock the wallet in the current session after creating the credential:

```bash
systemctl --user start kwallet_auto_unlock.service
```

### Manual Testing

Run the unpacked runtime to verify the handshake works:

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
3.  **Verify TPM/Credentials**:
    Try decrypting the credential manually to ensure `systemd-creds` is working and the password is correct:
    ```bash
    systemd-creds decrypt --user ~/.autokdewallet/password.cred -
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
│       ├── credentials.py     # systemd-creds / TPM password retrieval
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
