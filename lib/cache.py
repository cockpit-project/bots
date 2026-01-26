# This file is part of Cockpit.
#
# Copyright (C) 2015 Red Hat, Inc.
#
# Cockpit is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# Cockpit is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Cockpit; If not, see <http://www.gnu.org/licenses/>.

# Shared GitHub code. When run as a script, we print out info about
# our GitHub interacition.

import json
import os
import stat
import sys
import tempfile
import time
import urllib.parse
from typing import Generic, TypeVar

__all__ = (
    'Cache',
)

_T = TypeVar('_T')


class Cache(Generic[_T]):
    def __init__(self, directory: str, lag: int | None = None):
        self.directory = directory
        self.pruned = False

        # Default to zero lag when command on command line
        if lag is None:
            if os.isatty(0):
                lag = 0
            else:
                lag = 60

        # The lag tells us how long to assume cached data is "current"
        self.lag = lag

        # The mark tells us that stuff before this time is not "current"
        self.marked: float = 0

    # Prune old expired data from the cache directory
    def prune(self) -> None:
        try:
            entries = os.scandir(self.directory)
        except FileNotFoundError:
            # it's OK if the cache directory was deleted
            return

        oldest = time.time() - 7 * 86400  # discard files older than one week
        for entry in entries:
            if entry.is_file() and entry.stat().st_mtime < oldest:
                try:
                    os.remove(entry.path)
                except FileNotFoundError:
                    # maybe it got pruned by another process
                    pass
                except OSError as exc:
                    sys.stderr.write(f"Failed to remove GitHub cache item {entry.path}: {exc}\n")

    # Read a resource from the cache or return None
    def read(self, resource: str) -> _T | None:
        path = os.path.join(self.directory, urllib.parse.quote(resource, safe=''))
        try:
            with open(path) as fp:
                return json.load(fp)
        except (OSError, ValueError):
            return None

    # Write a resource to the cache in an atomic way
    def write(self, resource: str, contents: _T) -> None:
        path = os.path.join(self.directory, urllib.parse.quote(resource, safe=''))
        os.makedirs(self.directory, exist_ok=True)
        (fd, temp) = tempfile.mkstemp(dir=self.directory)
        with os.fdopen(fd, 'w') as fp:
            json.dump(contents, fp)
        os.chmod(temp, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        os.rename(temp, path)
        if not self.pruned:
            self.pruned = True
            self.prune()

    # Tell the cache that stuff before this time is not "current"
    def mark(self, mtime: float | None = None) -> None:
        if mtime is None:
            mtime = time.time()
        self.marked = mtime

    # Check if a given resource in the cache is "current" or not
    def current(self, resource: str) -> bool:
        path = os.path.join(self.directory, urllib.parse.quote(resource, safe=''))
        try:
            mtime = os.path.getmtime(path)
            return mtime > self.marked and mtime > (time.time() - self.lag)
        except OSError:
            return False
