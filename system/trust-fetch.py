#!/usr/bin/env python3
"""Run the engine verifier fetched from the pinned GitHub remote.

The plugin-directory copy of this file is not trusted. enter-privileged
downloads it with stock curl, checks GitHub's blob digest with stock git, and
runs only the root-owned /run copy. This program then clones the pinned remote,
checks that HEAD matches that remote, and only then executes the fetched
bootstrap. It never reads the plugin directory.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile

ORIGIN = "https://github.com/jcarcinogen/omarchy-gaming-console.git"
AUTHENTICATED_COPY = "/run/omarchy-gaming-console-trust-fetch.py"


def authenticated_copy(path: str, uid: int, mode: int, is_symlink: bool) -> bool:
    return (
        path == AUTHENTICATED_COPY
        and not is_symlink
        and uid == 0
        and stat.S_ISREG(mode)
        and not (mode & 0o022)
    )


def assert_authenticated_copy() -> None:
    if os.geteuid() != 0:
        raise SystemExit("trust fetch must run as root")
    raw = sys.argv[0]
    if os.path.islink(raw) or os.path.realpath(raw) != AUTHENTICATED_COPY:
        raise SystemExit("trust fetch must be the root-owned /run copy")
    info = os.lstat(AUTHENTICATED_COPY)
    if not authenticated_copy(AUTHENTICATED_COPY, info.st_uid, info.st_mode, stat.S_ISLNK(info.st_mode)):
        raise SystemExit("trust fetch is not a root-owned regular file")


def git(*args: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["/usr/bin/git", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def fetch_and_exec(mode: str) -> None:
    assert_authenticated_copy()
    if mode not in {"install", "repair", "uninstall"}:
        raise SystemExit(64)
    dest = tempfile.mkdtemp(prefix="omarchy-gaming-console-trusted.", dir="/run")
    os.chmod(dest, 0o700)
    os.chown(dest, 0, 0)
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    git(
        "-c", "core.hooksPath=/dev/null",
        "-c", "protocol.file.allow=never",
        "clone", "--depth", "1", "--", ORIGIN, dest,
        env=env,
    )
    remote = git("-C", dest, "remote", "get-url", "origin", env=env)
    if remote != ORIGIN:
        raise SystemExit("refusing unpinned origin")
    head = git("-C", dest, "rev-parse", "HEAD", env=env)
    advertised = git("ls-remote", ORIGIN, "HEAD", env=env).split()
    if not advertised or head != advertised[0] or len(head) != 40:
        raise SystemExit("refusing clone that does not match the pinned remote")
    bootstrap = os.path.join(dest, "system", "privileged-bootstrap.py")
    if os.path.islink(bootstrap) or not os.path.isfile(bootstrap):
        raise SystemExit("refusing missing fetched verifier")
    os.execv(
        "/usr/bin/python3",
        ["/usr/bin/python3", "-I", bootstrap, mode, os.path.join(dest, "system")],
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: trust-fetch.py install|repair|uninstall")
    fetch_and_exec(sys.argv[1])


if __name__ == "__main__":
    main()
