# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Async git utilities."""

import asyncio
import subprocess


async def run_git(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        'git', *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode is not None
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, ['git', *args], stdout, stderr)
    return stdout.decode().strip()


async def get_git_upstream() -> tuple[str, str]:
    """Get git URL and ref from upstream tracking branch.

    Returns:
        Tuple of (url, ref) from @{u}
    """
    upstream = await run_git('rev-parse', '--abbrev-ref', '@{u}')
    remote, _, branch = upstream.partition('/')
    url = await run_git('remote', 'get-url', remote)
    return url, branch
