# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from lib.github import GitHub

logger = logging.getLogger(__name__)


def _git(
    *args: str,
    config: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> str:
    """Run a git command, logging and returning stdout."""
    cmd = ["git", *args]
    logger.debug("+ %s", shlex.join(cmd))

    if dry_run:
        print('\n** Would', shlex.join(cmd))
        return ''

    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    if config:
        env['GIT_CONFIG_COUNT'] = str(len(config))
        for i, (key, value) in enumerate(config.items()):
            env[f'GIT_CONFIG_KEY_{i}'] = key
            env[f'GIT_CONFIG_VALUE_{i}'] = value

    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, env=env, text=True)
    sys.stderr.write(output)
    return output


def add(*paths: Path | str) -> None:
    """Stage files for commit."""
    _git("add", "--", *[str(p) for p in paths])


def commit(message: str, *, allow_empty: bool = False, dry_run: bool = False) -> None:
    """Commit staged changes. Returns True if a commit was created."""
    _git("commit", *(["--allow-empty"] if allow_empty else []), "-m", message, "--")


def push(remote: GitHub, topic: str, *, dry_run: bool = False) -> str:
    """Generate a branch name and pushes HEAD to the remote, returning the branch name."""
    branch = f'{topic}-{datetime.now(tz=timezone.utc):%Y%m%d-%H%M%S}'
    branch = re.sub(r'[^A-Za-z0-9]+', '-', branch)

    _git("push", "--", remote.remote, f"+HEAD:refs/heads/{branch}", config=remote.config(), dry_run=dry_run)

    return branch
