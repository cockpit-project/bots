# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import logging
import sys
from collections.abc import AsyncIterator

from yarl import URL

from .base import Log, LogDriver
from .jsonutil import JsonObject

logger = logging.getLogger(__name__)


class StdoutLog(Log):
    url = URL('about:blank')

    def start(self, data: str) -> None:
        self.write(data)

    def write(self, data: str) -> None:
        sys.stdout.write(data)
        sys.stdout.flush()

    def write_attachment(self, filename: str, data: bytes) -> None:
        logger.debug('Ignoring attachment %r (%d bytes)', filename, len(data))

    def close(self) -> None:
        pass


class StdoutLogDriver(LogDriver, contextlib.AsyncExitStack):
    def __init__(self, config: JsonObject) -> None:
        super().__init__()

    @contextlib.asynccontextmanager
    async def get_log(self, slug: str) -> AsyncIterator[Log]:
        yield StdoutLog()
