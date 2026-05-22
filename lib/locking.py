# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import fcntl
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def file_locked(path: Path) -> Iterator[None]:
    """Acquire an exclusive lockfile for the given path, with check-recheck for unlink safety."""
    lockpath = path.with_suffix(path.suffix + '.lock')
    waited = False
    for _attempt in range(10):
        with open(lockpath, 'w') as lockfile:
            try:
                fcntl.flock(lockfile, fcntl.LOCK_NB | fcntl.LOCK_EX)
            except BlockingIOError:
                if not waited:
                    sys.stderr.write(f'Waiting for concurrent download of {path.name}...\n')
                    waited = True
                fcntl.flock(lockfile, fcntl.LOCK_EX)
            # Verify we locked the file that's actually on disk, not a ghost inode
            try:
                if not Path(f'/proc/self/fd/{lockfile.fileno()}').samefile(lockpath):
                    continue
            except FileNotFoundError:
                logger.debug('lockfile %r was deleted under us, retrying', lockpath)
                continue
            logger.debug('acquired lock on %r', lockpath)
            try:
                yield
            finally:
                lockpath.unlink(missing_ok=True)
                logger.debug('released lock on %r', lockpath)
            break
    else:
        raise RuntimeError(f'unable to acquire lock on {lockpath}')
