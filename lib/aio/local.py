# Copyright (C) 2024 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import contextlib
import logging
import os
from collections.abc import AsyncIterator, Collection
from pathlib import Path

from yarl import URL

from .base import Destination, LogDriver
from .jsonutil import JsonObject, get_str

logger = logging.getLogger(__name__)


class LocalDestination(Destination):
    def __init__(self, directory: Path, location: URL) -> None:
        logger.debug('LocalDestination(%r, %r)', directory, location)
        self.dir = directory
        self.location = location
        os.makedirs(self.dir, exist_ok=True)

    def has(self, filename: str) -> bool:
        return (self.dir / filename).exists()

    def write(self, filename: str, data: bytes) -> None:
        logger.debug('Write %s', self.dir / filename)
        (self.dir / filename).write_bytes(data)

    def delete(self, filenames: Collection[str]) -> None:
        for filename in filenames:
            logger.debug('Delete %s', self.dir / filename)
            (self.dir / filename).unlink()


class LocalLogDriver(LogDriver, contextlib.AsyncExitStack):
    def __init__(self, config: JsonObject) -> None:
        super().__init__()
        self.directory = Path(get_str(config, 'dir')).expanduser()
        self.link = URL(get_str(config, 'link'))

    @contextlib.asynccontextmanager
    async def get_destination(self, slug: str) -> AsyncIterator[Destination]:
        yield LocalDestination(self.directory / slug, self.link / slug)
