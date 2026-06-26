# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

from lib.github import GitHub


def _git(
    *args: str,
    config: Sequence[tuple[str, str]] = (),
    dry_run: bool = False,
) -> str:
    """Run a git command, logging and returning stdout."""
    cmd = ["git", *args]

    if dry_run:
        sys.stderr.write(f"# {shlex.join(cmd)}\n")
        return ''

    sys.stderr.write(f"+ {shlex.join(cmd)}\n")

    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    if config:
        env['GIT_CONFIG_COUNT'] = str(len(config))
        for i, (key, value) in enumerate(config):
            env[f'GIT_CONFIG_KEY_{i}'] = key
            env[f'GIT_CONFIG_VALUE_{i}'] = value

    # stdout is fully buffered when piped (eg. in GitHub Actions), so flush
    # both streams before spawning git to keep output in execution order
    sys.stdout.flush()
    sys.stderr.flush()

    return subprocess.check_output(cmd, env=env, text=True)


@contextlib.contextmanager
def temporary_checkout(url: str) -> Iterator[Path]:
    """Clone a repo into a temporary directory and chdir into it."""
    saved = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        _git("clone", "--", url, tmpdir)
        os.chdir(tmpdir)
        try:
            yield Path(tmpdir)
        finally:
            os.chdir(saved)


def get_current_head() -> str:
    """Return the current HEAD commit sha."""
    return _git("rev-parse", "HEAD").strip()


def describe() -> str:
    """Return the output of git describe."""
    return _git("describe").strip()


def shortlog(rev_range: str, *paths: str) -> str:
    """Return the output of git shortlog."""
    return _git("shortlog", rev_range, "--", *paths)


def detach_head(ref: str) -> None:
    """Detach HEAD at the given ref."""
    # Bail out if there are unstaged or staged changes — checkout --detach
    # would silently carry them across into whatever we commit next.
    _git("diff", "--exit-code", "HEAD", "--")
    _git("diff", "--cached", "--exit-code", "HEAD", "--")
    _git("checkout", "--detach", ref, "--")


def add(*paths: Path | str) -> None:
    """Stage files for commit."""
    _git("add", "--", *[str(p) for p in paths])


def rm(*paths: Path | str) -> None:
    """git-rm the given paths."""
    _git("rm", "--ignore-unmatch", "--", *[str(p) for p in paths])


def changes_staged() -> bool:
    """Check if there are staged changes."""
    try:
        _git("diff", "--cached", "--quiet", "--")
        return False
    except subprocess.CalledProcessError:
        return True


def commit(message: str, *, allow_empty: bool = False) -> None:
    """Commit staged changes.  Raises if nothing was staged, unless allow_empty."""
    _git("commit", *(["--allow-empty"] if allow_empty else []), "-m", message, "--")


def untracked(path: str) -> list[Path]:
    """List untracked files, respecting .gitignore."""
    return [Path(p) for p in _git("ls-files", "--others", "--exclude-standard", "--", path).splitlines()]


def push(remote: GitHub, topic: str, *, dry_run: bool = False) -> str:
    """Generate a branch name and pushes HEAD to the remote, returning the branch name."""
    branch = f'{topic}-{datetime.now(tz=timezone.utc):%Y%m%d-%H%M%S}'
    branch = re.sub(r'[^A-Za-z0-9]+', '-', branch)

    _git("push", "--", remote.remote, f"+HEAD:refs/heads/{branch}", config=remote.config(), dry_run=dry_run)

    return branch


def amend_and_forcepush(
    remote: GitHub, branch: str, *, closes: int | None = None, dry_run: bool = False
) -> None:
    """Amend the commit (optionally with a Closes trailer) and force-push.

    This is needed to trigger CI: PRs created with GITHUB_TOKEN don't
    generate workflow-triggering events, but a force-push via the deploy
    key (SSH) generates a pull_request:synchronize event attributed to
    the key owner.
    """
    if dry_run:
        return
    expected = get_current_head()
    trailer = ("--trailer", f"Closes: #{closes}") if closes is not None else ()
    _git("commit", "--amend", "--no-edit", "--allow-empty", *trailer, "--")
    _git("push", f"--force-with-lease=refs/heads/{branch}:{expected}",
         "--", remote.remote, f"HEAD:refs/heads/{branch}", config=remote.config())
