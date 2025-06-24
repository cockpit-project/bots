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

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def spawn(args: Sequence[str], **kwargs: Any) -> AsyncIterator[asyncio.subprocess.Process]:
    logger.debug('spawn(%r)', args)
    process = await asyncio.create_subprocess_exec(*args, **kwargs)
    pid = process.pid
    logger.debug('spawn: pid %r', pid)
    try:
        yield process
    finally:
        logger.debug('spawn: waiting for pid %r', pid)
        status = await process.wait()
        logger.debug('spawn: pid %r exited, %r', pid, status)


async def run(args: Sequence[str], **kwargs: Any) -> int:
    logger.debug('run(%r)', args)
    process = await asyncio.create_subprocess_exec(*args, **kwargs)
    pid = process.pid
    logger.debug('run: waiting for pid %r', pid)
    status = await process.wait()
    logger.debug('run: pid %r exited, %r', pid, status)
    return status
