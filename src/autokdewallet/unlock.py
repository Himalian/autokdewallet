#!/usr/bin/env python3
"""Unlock KWallet without a login password.

KDE Frameworks 6.29 removed the D-Bus ``pamOpen`` method this project used to
call. This script does what ``pam_kwallet.so`` does instead:

1. create a pipe and a listening AF_UNIX socket
2. start ``ksecretd --pam-login <pipe-fd> <socket-fd>`` with
   ``PAM_KWALLET5_LOGIN`` pointing at the socket
3. write the 56-byte PBKDF2-SHA512 key into the pipe
4. hand the session environment over the socket (the job ``pam_kwallet_init``
   normally does)

``ksecretd`` then calls ``pamOpen`` internally. The process stays alive as the
daemon's parent so systemd can supervise it.

This targets sessions (for example SDDM autologin) where pam_kwallet never
receives a password and does not start the daemon, so the unit has to do both
steps itself.
"""

from __future__ import annotations

import os
import pwd
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from .credentials import get_tpm_password
from .hashing import KEY_SIZE as KEYSIZE, derive_kwallet_hash
from .salt import load_binary_salt

# Must match socketPrefix / envVar in pam_kwallet.c.
SOCKET_PREFIX = "kwallet5"
ENV_VAR = "PAM_KWALLET5_LOGIN"

# ksecretd owns the wallet since the kwalletd split. kwalletd6 is only a
# fallback for older installations.
DAEMON_CANDIDATES = ("ksecretd", "kwalletd6", "kwalletd5")

# ksecretd reads environment lines with fgets() into a 1000-byte buffer.
ENV_LINE_MAX = 999

CONNECT_TIMEOUT = 10.0
GRAPHICAL_ENV_KEYS = ("WAYLAND_DISPLAY", "DISPLAY")
GRAPHICAL_ENV_TIMEOUT = 30.0


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def find_daemon() -> str:
    """Locate the wallet daemon binary."""
    override = os.environ.get("KWALLETD_BIN")
    if override:
        if not Path(override).is_file():
            raise FileNotFoundError(f"KWALLETD_BIN does not exist: {override}")
        return override

    for name in DAEMON_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
        candidate = Path("/usr/bin") / name
        if candidate.is_file():
            return str(candidate)

    raise FileNotFoundError(
        "No wallet daemon found (tried: " + ", ".join(DAEMON_CANDIDATES) + ")"
    )


def build_socket_path() -> str:
    """Same path logic as pam_kwallet.c."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and Path(runtime_dir).is_dir():
        return f"{runtime_dir}/{SOCKET_PREFIX}.socket"

    # User services have no controlling terminal, so getlogin() is unreliable.
    username = pwd.getpwuid(os.getuid()).pw_name
    return f"/tmp/{SOCKET_PREFIX}_{username}.socket"


def create_listening_socket(path: str) -> socket.socket:
    """Bind and listen on the AF_UNIX socket the daemon will accept() on."""
    if len(path.encode()) >= 108:  # sizeof(sockaddr_un.sun_path)
        raise OSError(f"Socket path too long for AF_UNIX: {path}")

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(5)
    srv.set_inheritable(True)
    return srv


def read_systemd_environment() -> dict[str, str]:
    """Read the systemd user manager environment block.

    Plasma pushes DISPLAY / WAYLAND_DISPLAY / XDG_SESSION_TYPE in there once
    the graphical session is up, which is later than this unit starts.
    """
    try:
        out = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    env: dict[str, str] = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if not sep or not key or "\n" in value:
            continue
        # systemd quotes values that contain specials; unwrap the simple case
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key] = value
    return env


def wait_for_graphical_env(timeout: float) -> dict[str, str]:
    """Block until the graphical session has published its environment.

    ksecretd parks in waitForEnvironment() before it constructs its
    QApplication, so it is fine to start it early and deliver the real
    session environment only once Plasma has published it.
    """
    deadline = time.monotonic() + timeout
    while True:
        env = read_systemd_environment()
        if any(k in env for k in GRAPHICAL_ENV_KEYS):
            return env
        if time.monotonic() >= deadline:
            log(
                "Graphical session environment did not appear in time, "
                "handing over what we have"
            )
            return env
        time.sleep(0.25)


def environment_payload(sock_path: str, extra: dict[str, str] | None = None) -> bytes:
    """Serialise the session environment the way ksecretd expects it.

    ksecretd reads the connection line by line and putenv()s each line, so
    the format is plain ``KEY=VALUE\\n``. Newlines or over-long lines would
    corrupt the stream, so they are skipped.
    """
    env = dict(os.environ)
    env.update(extra or {})
    env[ENV_VAR] = sock_path

    lines = []
    for key, value in env.items():
        if "\n" in value or "\0" in value or "=" in key:
            continue
        line = f"{key}={value}"
        if len(line.encode()) > ENV_LINE_MAX:
            continue
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def send_environment(
    path: str, proc: subprocess.Popen, extra: dict[str, str] | None = None
) -> None:
    """Connect to the socket and hand over the environment."""
    deadline = time.monotonic() + CONNECT_TIMEOUT
    payload = environment_payload(path, extra)

    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"Wallet daemon exited early with code {proc.returncode}")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5.0)
                client.connect(path)
                client.sendall(payload)
                client.shutdown(socket.SHUT_WR)
                return
        except (ConnectionRefusedError, FileNotFoundError, OSError) as err:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Could not hand the environment to the daemon: {err}"
                ) from err
            time.sleep(0.1)


def unlock(wait_for_session: bool = True) -> int:
    daemon = find_daemon()

    salt = load_binary_salt()
    password = get_tpm_password()
    key = derive_kwallet_hash(password, salt)
    if len(key) != KEYSIZE:
        raise ValueError(f"Derived key has {len(key)} bytes, expected {KEYSIZE}")

    sock_path = build_socket_path()
    srv = create_listening_socket(sock_path)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(read_fd, True)

    env = dict(os.environ)
    # Without this variable ksecretd ignores --pam-login entirely.
    env[ENV_VAR] = sock_path

    argv = [daemon, "--pam-login", str(read_fd), str(srv.fileno())]
    log(f"Starting {' '.join(argv)}")

    try:
        proc = subprocess.Popen(
            argv,
            env=env,
            pass_fds=(read_fd, srv.fileno()),
            close_fds=True,
        )
    finally:
        os.close(read_fd)
        srv.close()  # the daemon holds its own copy of the listening socket

    try:
        # The daemon blocks in waitForHash() until it has all 56 bytes.
        written = 0
        while written < len(key):
            written += os.write(write_fd, key[written:])
    finally:
        os.close(write_fd)
        del key, password

    # Then it blocks in waitForEnvironment() until we deliver the session
    # env, so we can wait here for Plasma to publish the graphical bits.
    extra: dict[str, str] = {}
    if wait_for_session:
        extra = wait_for_graphical_env(GRAPHICAL_ENV_TIMEOUT)
    send_environment(sock_path, proc, extra)

    # connect() succeeds against the listen backlog even if the daemon already
    # died, so confirm it is actually still there before claiming success.
    try:
        rc = proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise RuntimeError(f"Wallet daemon exited during handshake with code {rc}")

    log(f"Handshake complete, wallet daemon running as PID {proc.pid}")

    # Stay alive so systemd supervises the daemon through this unit.
    return proc.wait()


def main() -> int:
    wait_for_session = (
        "--no-wait" not in sys.argv
        and os.environ.get("AUTOKDEWALLET_NO_WAIT", "") not in ("1", "true", "yes")
    )
    try:
        return unlock(wait_for_session=wait_for_session)
    except KeyboardInterrupt:
        return 130
    except subprocess.CalledProcessError as err:
        log(f"Failed to decrypt password.cred: {err}")
        log("Create it with: just generate_password \"YOUR_KWALLET_PASSWORD\"")
        return 1
    except Exception as err:  # noqa: BLE001 - top level reporting
        log(f"Failed to unlock the wallet: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
