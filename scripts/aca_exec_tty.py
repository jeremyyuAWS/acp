#!/usr/bin/env python3
"""Run one command on a PTY without forwarding the caller's stdin EOF.

Azure CLI's container-app exec command requires a terminal even when a command was supplied.
GitHub Actions has no terminal and its stdin is already closed.  `script(1)` creates a PTY but
also forwards that EOF, disconnecting Azure's websocket before the remote command completes.
This runner owns the PTY master until the child exits, drains its transcript, and never writes
the workflow's stdin into the session.
"""
from __future__ import annotations

import errno
import os
import pty
import select
import subprocess
import sys
import time


def main(argv: list[str]) -> int:
    command = argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        print("aca_exec_tty.py: command required", file=sys.stderr)
        return 2

    timeout = max(1, int(os.environ.get("ACP_ACA_EXEC_TIMEOUT_SECONDS", "90")))
    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
    finally:
        os.close(slave)

    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                print("ACA exec session timed out", file=sys.stderr)
                return 124
            readable, _, _ = select.select([master], [], [], min(1.0, remaining))
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:  # normal Linux PTY EOF
                        break
                    raise
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            elif process.poll() is not None:
                # The child exited without another readable byte.
                break
        return process.wait()
    finally:
        os.close(master)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
