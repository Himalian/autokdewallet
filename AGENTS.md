# autokdewallet

A Python utility for automatically unlocking KDE Wallet (KWallet) using TPM-backed credentials via `systemd-creds`.

## Project Overview

The `autokdewallet` project provides a seamless login experience for KDE users by automatically unlocking the default wallet (`kdewallet`) with a password securely stored in the system's TPM. It derives the PBKDF2-SHA512 hash and feeds it to `ksecretd --pam-login`, because the D-Bus `pamOpen` method was removed in KDE Frameworks 6.29.

### Key Technologies

- **Python 3.10+**: Core logic for hash derivation and the `ksecretd` PAM handshake. Stdlib only; no third-party runtime dependencies.
- **ksecretd**: Started as `ksecretd --pam-login <pipe-fd> <socket-fd>` with `PAM_KWALLET5_LOGIN` set. The 56-byte hash goes down the pipe; the session environment goes over `$XDG_RUNTIME_DIR/kwallet5.socket`.
- **systemd-creds**: Encrypts and decrypts the wallet password using the TPM.
- **Systemd User Services**: The unit is `Type=simple`, wanted by `graphical-session-pre.target`, and stays alive as `ksecretd`'s parent.

## Architecture

- **`src/autokdewallet/__main__.py`**: Entry point for `python3 -m autokdewallet`; delegates to `unlock.main()`.
- **`src/autokdewallet/unlock.py`**: Orchestration. Retrieves the password, loads the salt, derives the hash, starts `ksecretd`, completes the PAM handshake, and stays alive as the daemon's parent.
- **`src/autokdewallet/credentials.py`**: Reads the wallet password from `$CREDENTIALS_DIRECTORY/password` when systemd provided it, otherwise decrypts `~/.autokdewallet/password.cred` with `systemd-creds`.
- **`src/autokdewallet/hashing.py`**: PBKDF2-SHA512 parameters (50,000 iterations, 56-byte key) matching KWallet's `kwalletbackend.cpp`.
- **`src/autokdewallet/salt.py`**: Reads and validates the binary salt from `~/.local/share/kwalletd/kdewallet.salt`.
- **`systemd/kwallet_auto_unlock.service`**: User unit; `WorkingDirectory=%h/.autokdewallet` and `ExecStart=/usr/bin/python3 -u -m autokdewallet`.
- **`tests/`**: Stdlib `unittest` suite for hashing, salt loading, and environment serialization.

`just install` copies the package to `~/.autokdewallet`; the service runs that copy, not the git checkout. `just generate_password` writes `~/.autokdewallet/password.cred`.

## Building and Running

The project uses `just` as a command runner.

### Initial Setup

1. **Install the runtime**:
   ```bash
   just install
   ```

2. **Generate credentials**:
   ```bash
   just generate_password password="your_actual_wallet_password"
   ```
   This creates `~/.autokdewallet/password.cred`.

3. **Enable the user service**:
   ```bash
   just enable
   ```

### Manual Execution

```bash
just run
# or, from the installed runtime:
cd ~/.autokdewallet && python3 -m autokdewallet --no-wait
```

### Testing

```bash
just test
# equivalent to:
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### Cleanup

```bash
just clean
```

## Development Conventions

- **Layout**: `src/` layout with an installable `autokdewallet` package. Keep runtime code under `src/autokdewallet/`; keep the unit under `systemd/`.
- **Dependencies**: Python standard library only. Do not add `dbus-python`; D-Bus is no longer used.
- **Security**: `password.cred` is encrypted for the current user/hardware. Never commit it (`.gitignore` covers `*.cred`).
- **KWallet Version**: Plasma 6 / kwallet >= 6.29 (`ksecretd`). Older daemons are best-effort fallbacks.
- **Hash Parameters**: Iterations and key size are strictly defined by KWallet (`PBKDF2_SHA512_ITERATIONS` 50000, `PBKDF2_SHA512_KEYSIZE` 56). Do not change them without matching KWallet.
- **Docs**: `AGENTS.md` is the canonical instruction file; `GEMINI.md` is a symlink to it.
