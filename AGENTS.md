# autokdewallet

A Python utility for automatically unlocking a password-protected KDE Wallet (KWallet) using a user-scoped `systemd-creds` credential.

## Project Overview

The `autokdewallet` project unlocks the default wallet (`kdewallet`) when it uses password-based Blowfish encryption with PBKDF2-SHA512. It derives the password hash and feeds it to `ksecretd --pam-login`, because the D-Bus `pamOpen` method was removed in KDE Frameworks 6.29. GPG-backed wallets use a different unlock path and are not supported by this utility.

### Key Technologies

- **Python 3.10+**: Core logic for hash derivation and the `ksecretd` PAM handshake. Stdlib only; no third-party runtime dependencies.
- **ksecretd**: Started as `ksecretd --pam-login <pipe-fd> <socket-fd>` with `PAM_KWALLET5_LOGIN` set. The 56-byte hash goes down the pipe; the session environment goes over `$XDG_RUNTIME_DIR/kwallet5.socket`.
- **systemd-creds**: Encrypts and decrypts the user-scoped wallet password credential. Its automatic key selection can bind the credential to the TPM, but the utility does not require or verify TPM binding. The `--user` option requires systemd 256 or newer.
- **Systemd User Services**: The unit is `Type=simple`, wanted by `graphical-session-pre.target`, and stays alive as `ksecretd`'s parent.

## Architecture

- **`src/autokdewallet/__main__.py`**: Entry point for `python3 -m autokdewallet`; delegates to `unlock.main()`.
- **`src/autokdewallet/unlock.py`**: Orchestration. Retrieves the password, loads the salt, derives the hash, starts `ksecretd`, completes the PAM handshake, and stays alive as the daemon's parent.
- **`src/autokdewallet/credentials.py`**: Reads the wallet password from `$CREDENTIALS_DIRECTORY/password` when systemd provided it, otherwise decrypts `~/.autokdewallet/password.cred` with `systemd-creds`.
- **`src/autokdewallet/hashing.py`**: PBKDF2-SHA512 parameters (50,000 iterations, 56-byte key) matching KWallet's `kwalletbackend.h`.
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
   just generate_password "your_actual_wallet_password"
   ```
   This positional argument creates `~/.autokdewallet/password.cred`, but also exposes the password in the command line and possibly shell history. See `README.md` for a hidden-input alternative. The current password reader strips leading and trailing whitespace, so those characters cannot be part of the wallet password.

3. **Enable the user service**:
   ```bash
   just enable
   ```

### Manual Execution

Only run these commands when no wallet daemon is already running in the session; otherwise use the service at the next login.

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
- **Security**: `password.cred` is encrypted for the current user and system, with TPM binding depending on the key type chosen by `systemd-creds`. Never commit it (`.gitignore` covers `*.cred`).
- **KWallet Version**: Plasma 6 / kwallet >= 6.29 (`ksecretd`) with a password-backed Blowfish/PBKDF2 wallet. Older daemons are best-effort fallbacks; GPG wallets are unsupported.
- **Hash Parameters**: Iterations and key size are strictly defined by KWallet (`PBKDF2_SHA512_ITERATIONS` 50000, `PBKDF2_SHA512_KEYSIZE` 56). Do not change them without matching KWallet.
- **Docs**: `AGENTS.md` is the canonical instruction file; `GEMINI.md` is a symlink to it.
