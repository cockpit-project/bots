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

import argparse
import asyncio
import codecs
import collections
import contextlib
import json
import logging
import ssl
from collections.abc import AsyncIterator, Collection, Coroutine, Hashable, Mapping, Sequence
from typing import Any, TypeVar

import aiohttp

from .jsonutil import JsonError, JsonObject, get_str, typechecked

logger = logging.getLogger(__name__)

# When mypy gets PEP 695 support: https://github.com/python/mypy/issues/15238
# type JsonValue = None | bool | int | float | Sequence[JsonValue] | Mapping[str, JsonValue]
K = TypeVar('K', bound=Hashable)
T = TypeVar('T')
V = TypeVar('V')


class AsyncQueue(collections.deque[T]):
    def __init__(self) -> None:
        self._nonempty = asyncio.Event()
        self._eof = False

    async def next(self) -> T | None:
        await self._nonempty.wait()
        return self[0] if self else None

    def done(self, item: T) -> None:
        assert self.popleft() is item
        if not self and not self._eof:
            self._nonempty.clear()

    def put(self, item: T) -> None:
        self.append(item)
        self._nonempty.set()

    def eof(self) -> None:
        self._nonempty.set()
        self._eof = True


# Simple LRU cache: when full, evict the least-recently `add()`-ed item.
class LRUCache(dict[K, V]):
    def __init__(self, max_items: int = 128) -> None:
        self.max_items = max_items

    def add(self, key: K, value: V) -> None:
        # In order to make sure the value gets inserted at the end, we need to
        # remove a previous value, otherwise it will just take its place.
        self.pop(key, None)
        self[key] = value
        while len(self) > self.max_items:
            oldest = next(iter(self))
            logger.debug('evicting cached data for %r', oldest)
            self.pop(oldest)


class KeyValueAction(argparse.Action):
    def __init__(self, option_strings: str, dest: str, **kwargs: Any) -> None:
        super().__init__(option_strings, dest, **kwargs, default={})

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None
    ) -> None:
        assert isinstance(values, str)
        key, eq, value = values.partition('=')
        if not eq:
            raise ValueError(f'--env parameter `{value}` must contain `=`')
        getattr(namespace, self.dest)[key] = value


class JsonObjectAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None
    ) -> None:
        assert isinstance(values, str)
        try:
            setattr(namespace, self.dest, typechecked(json.loads(values), dict))
        except (JsonError, json.JSONDecodeError) as exc:
            parser.error(f'invalid argument {self.dest}: {exc}')


async def gather_and_cancel(aws: Collection[Coroutine[None, None, None]]) -> None:
    tasks = {asyncio.create_task(coro) for coro in aws}

    try:
        (done,), tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        done.result()  # to raise the exception, if applicable
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def read_utf8(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    decoder = codecs.getincrementaldecoder('UTF-8')(errors='replace')
    while data := await stream.read(1 << 20):  # 1MB
        yield decoder.decode(data)
    yield decoder.decode(b'', final=True)


def create_http_session(config: JsonObject, headers: Mapping[str, str]) -> aiohttp.ClientSession:
    if cadata := get_str(config, 'ca', None):
        connector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cadata=cadata))
    else:
        connector = None

    headers = {
        'User-Agent': get_str(config, 'user-agent'),
        **headers,
    }

    return aiohttp.ClientSession(connector=connector, headers=headers, raise_for_status=True)
