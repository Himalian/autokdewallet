#!/usr/bin/env python3
"""Unlock KWallet without a login password.

Instead of the D-Bus method ``pamOpen`` (removed from kwalletd in KDE
Frameworks 6.29.0), this reproduces exactly what ``pam_kwallet.so`` does:

  1. create a pipe and a listening AF_UNIX socket
  2. start the wallet daemon as  ``ksecretd --pam-login <pipeFd> <sockFd>``
     with ``PAM_KWALLET5_LOGIN`` pointing at the socket path
  3. write the 56-byte PBKDF2-SHA512 key into the pipe
  4. hand the session environment over the socket (the job normally done by
     ``pam_kwallet_init`` / the old startkde snippet)

The daemon then calls ``pamOpen`` on itself internally, so no D-Bus method
call is needed and nothing can be removed from under us again.

The process stays alive as the parent of the daemon so that systemd can
supervise it.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from calculate_hash import derive_kwallet_hash, get_tpm_password
from get_salt import load_binary_salt

# Must match KWALLET_PAM_KEYSIZE in pam_kwallet.c / PBKDF2_SHA512_KEYSIZE in ksecretd
KEYSIZE = 56

# Must match socketPrefix / envVar in pam_kwallet.c
SOCKET_PREFIX = "kwallet5"
ENV_VAR = "PAM_KWALLET5_LOGIN"

# ksecretd is the daemon that actually owns the wallet since the kwalletd split.
# kwalletd6 is only kept as a fallback for older installations.
DAEMON_CANDIDATES = ("ksecretd", "kwalletd6", "kwalletd5")

CONNECT_TIMEOUT = 10.0

# Keys that tell us Plasma has published the graphical session environment
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
        found = shutil.which(name) or (
            f"/usr/bin/{name}" if Path(f"/usr/bin/{name}").is_file() else None
        )
        if found:
            return found

    raise FileNotFoundError(
        "No wallet daemon found (tried: " + ", ".join(DAEMON_CANDIDATES) + ")"
    )


def build_socket_path() -> str:
    """Same path logic as pam_kwallet.c."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and Path(runtime_dir).is_dir():
        return f"{runtime_dir}/{SOCKET_PREFIX}.socket"
    # Fallback for sessions without XDG_RUNTIME_DIR
    return f"/tmp/{SOCKET_PREFIX}_{os.getlogin()}.socket"


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

    Plasma pushes DISPLAY / WAYLAND_DISPLAY / XDG_SESSION_TYPE etc. in there
    once the graphical session is up, which is later than this unit starts.
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

    ksecretd parks in waitForEnvironment() before it ever constructs its
    QApplication, so it is fine (and intended) to start it early and deliver
    the real session environment only once Plasma has published it. Returns
    whatever is available when the graphical keys appear or the timeout hits.
    """
    deadline = time.monotonic() + timeout
    while True:
        env = read_systemd_environment()
        if any(k in env for k in GRAPHICAL_ENV_KEYS):
            return env
        if time.monotonic() >= deadline:
            log("Graphical session environment did not appear in time, "
                "handing over what we have")
            return env
        time.sleep(0.25)


def environment_payload(sock_path: str, extra: dict[str, str] | None = None) -> bytes:
    """Serialise the session environment the way ksecretd expects it.

    ksecretd reads the connection line by line and putenv()s each line, so the
    format is plain ``KEY=VALUE\\n``. Values containing newlines would corrupt
    the stream, so they are skipped.
    """
    env = dict(os.environ)
    env.update(extra or {})
    env[ENV_VAR] = sock_path

    lines = []
    for key, value in env.items():
        if "\n" in value or "\0" in value or "=" in key:
            continue
        lines.append(f"{key}={value}")
    return ("\n".join(lines) + "\n").encode()


def send_environment(
    path: str, proc: subprocess.Popen, extra: dict[str, str] | None = None
) -> None:
    """Connect to the socket and hand over the environment."""
    deadline = time.monotonic() + CONNECT_TIMEOUT
    payload = environment_payload(path, extra)

    while True:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Wallet daemon exited early with code {proc.returncode}"
            )
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
        # 1) the daemon blocks in waitForHash() until it has all 56 bytes
        written = 0
        while written < len(key):
            written += os.write(write_fd, key[written:])
    finally:
        os.close(write_fd)
        del key, password

    # 2) then it blocks in waitForEnvironment() until we deliver the session
    #    env - so we can wait here for Plasma to publish the graphical bits
    extra = {}
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
    except Exception as err:  # noqa: BLE001 - top level reporting
        log(f"Failed to unlock the wallet: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
