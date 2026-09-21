#!/usr/bin/env python3
"""Seal a reviewed engine snapshot and run only that root-owned copy.

Root executes this program from memory, via the stock /usr/bin/python3 -c
argument. It must not be pkexec'd by checkout path. Each payload is read once
through an O_NOFOLLOW descriptor, checked against the reviewed digest, and
written into a root-owned /run snapshot. install.sh and uninstall.sh then run
only from that snapshot.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
from pathlib import Path

EXPECTED = {
    "install.sh": "9c38aecd9319f26f1287824b5c8eaae7f81a5c010e02a24a450bd3e3e1c4a175",
    "omarchy-console-session": "fe73f4f816bb139391ebdf6ddb0fc3bca7d374ed115de8b485b756364c2bf5b7",
    "omarchy-console.desktop": "c46c565a65dc338062466b722a7505bdb0959fcc05d24f36b21023a6d7907bd8",
    "omarchy-switch-to-console": "1c3b62baea3870f40945783064f4c561799a5fc8762a05acc68226418a8c6e0b",
    "org.omarchy.gaming-console.policy": "ecf940f89b352ec38776096abcc2281f896a6a19ac9e8cdc2b02ab99c7844bcf",
    "ownership.manifest": "1d53f64af8b9e61486c9d6ac2880a292b004f540eefa9f1c81313c4dcd4a21ad",
    "steamos-select-branch": "ac2852f2bb8b67b84fa506133ab0184d9091d521fabc0f18235be1a1e98befdd",
    "steamos-session-select": "039894329a382dd6f11007faf73971dd53da8d498be853718a772c97ea03c460",
    "steamos-update": "ffec208fbc702284884f2e26095b8d49b9c98455c8bf1e3b7fc7049701c26741",
    "uninstall.sh": "10d2f4f6248e9c758f96aa0fc868c4714fa609400da8aba54f045a9c1bc7f97f",
}


class Refused(SystemExit):
    pass


def read_nofollow(dir_fd: int, name: str) -> bytes:
    if name != Path(name).name or name in {".", ".."} or "/" in name:
        raise Refused(f"unsafe payload name: {name}")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        raise Refused(f"payload cannot be opened without following a symlink: {name}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Refused(f"payload is not a regular file: {name}")
        data = os.read(fd, info.st_size + 1)
        again = os.fstat(fd)
        if len(data) != info.st_size or again.st_ino != info.st_ino or again.st_size != info.st_size:
            raise Refused(f"payload changed while reading: {name}")
        return data
    finally:
        os.close(fd)


def read_payload(source_dir: str) -> dict[str, bytes]:
    try:
        dir_fd = os.open(source_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise Refused("engine source directory cannot be opened without following a symlink") from exc
    try:
        files: dict[str, bytes] = {}
        for name, expected in EXPECTED.items():
            data = read_nofollow(dir_fd, name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise Refused(f"payload digest mismatch: {name}")
            files[name] = data
        return files
    finally:
        os.close(dir_fd)


def payload_digest(source_dir: Path) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in read_payload(str(source_dir)).items()}


def seal_snapshot(files: dict[str, bytes], stage_parent: Path) -> Path:
    stage_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="omarchy-gaming-console-stage.", dir=stage_parent))
    os.chmod(stage, 0o700)
    for name, data in files.items():
        fd = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        try:
            written = os.write(fd, data)
            if written != len(data):
                raise Refused(f"short write while sealing {name}")
        finally:
            os.close(fd)
        os.chmod(stage / name, 0o755 if name.endswith(".sh") else 0o644)
    return stage


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--check":
        read_payload(str(Path(__file__).resolve().parent))
        print("reviewed payload digest matches")
        return
    if os.geteuid() != 0:
        raise SystemExit("privileged bootstrap must run as root")
    if len(sys.argv) != 3 or sys.argv[1] not in {"install", "repair", "uninstall"}:
        raise SystemExit("Usage: privileged-bootstrap.py install|repair|uninstall SOURCE_DIR")
    mode, source = sys.argv[1], sys.argv[2]
    files = read_payload(source)
    stage = seal_snapshot(files, Path("/run"))
    os.chown(stage, 0, 0)
    for name in files:
        os.chown(stage / name, 0, 0)
    script = stage / ("uninstall.sh" if mode == "uninstall" else "install.sh")
    argv = ["/bin/bash", str(script)]
    if mode != "uninstall":
        argv.append(mode)
    os.execv("/bin/bash", argv)


if __name__ == "__main__":
    try:
        main()
    except Refused as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        raise SystemExit(78) from exc
