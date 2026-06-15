# Copyright (C) 2022-2024 Red Hat, Inc.
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
import hashlib
import logging
import mimetypes
from collections.abc import Collection, Mapping
from types import TracebackType
from typing import NamedTuple, Self

import httpx
from yarl import URL

from ..s3 import S3Key, s3_sign
from .base import Destination, LogDriver
from .jsonutil import JsonError, JsonObject, get_nested, get_str
from .util import AsyncQueue, create_http_session

logger = logging.getLogger(__name__)


class HttpRequest(NamedTuple):
    method: str
    url: URL
    headers: Mapping[str, str]
    data: bytes = b''


class HttpQueue:
    def __init__(self, session: httpx.AsyncClient, s3_key: S3Key) -> None:
        self.session = session
        self._queue = AsyncQueue[HttpRequest]()
        self._task: asyncio.Task[None] | None = None
        self._level: int = logging.DEBUG
        self._s3_key = s3_key

    async def request_once(self, request: HttpRequest, checksum: str) -> None:
        # NB: Re-sign each attempt.  Time's arrow neither stands still nor reverses.
        assert request.url.host is not None
        headers = s3_sign(
            request.url.host, request.url.raw_path, request.url.query_string,
            request.method, request.headers, checksum, self._s3_key,
        )
        logger.log(self._level, '%s %s', request.method, request.url)
        response = await self.session.request(request.method, str(request.url), content=request.data, headers=headers)
        response.raise_for_status()
        logger.debug('response %s %s %r', request.method, request.url, response)

    async def request(self, request: HttpRequest) -> None:
        checksum = hashlib.sha256(request.data).hexdigest()
        for attempt in range(5):
            try:
                return await self.request_once(request, checksum)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise  # We actually care about 4xx errors, but blindly retry 5xx.
            except httpx.HTTPError:
                pass  # That's DNS, connection, etc. errors.  Always retry those.

            # 1 → 4 → 16 → 64 → 256s
            await asyncio.sleep(4 ** attempt)

        # last attempt — return the exception (...or pass)
        return await self.request_once(request, checksum)

    async def run_queue(self) -> None:
        while request := await self._queue.next():
            await self.request(request)
            self._queue.done(request)

    def request_soon(self, request: HttpRequest) -> None:
        assert self._queue is not None
        self._queue.put(request)

    async def __aenter__(self) -> Self:
        self._task = asyncio.create_task(self.run_queue())
        return self

    async def __aexit__(self,
                        exc_type: type[BaseException] | None,
                        exc_value: BaseException | None,
                        traceback: TracebackType | None) -> None:
        assert self._task

        if items := len(self._queue):
            logger.info('Waiting for %r queued HTTP requests to complete...', items)
            self._level = logging.INFO  # make the rest of the output a bit louder

        self._queue.eof()
        await self._task

    def s3_put(self, url: URL, body: bytes, headers: Mapping[str, str]) -> None:
        self.request_soon(HttpRequest('PUT', url, headers, body))

    def s3_delete(self, url: URL) -> None:
        self.request_soon(HttpRequest('DELETE', url, {}))


class S3Destination(Destination, contextlib.AsyncExitStack):
    def __init__(self, session: httpx.AsyncClient, url: URL, proxy_url: URL, key: S3Key, acl: str) -> None:
        super().__init__()
        self.session = session
        self.location = url  # Used for S3 operations
        self.proxy_location = proxy_url  # Used for external links (GitHub status)
        self.key = key
        self.acl = acl

    def url(self, filename: str) -> URL:
        return self.location / filename

    def has(self, filename: str) -> bool:
        raise NotImplementedError('use Index')

    def write(self, filename: str, data: bytes) -> None:
        content_type, content_encoding = mimetypes.guess_type(filename)
        headers: dict[str, str] = {'Content-Type': content_type or 'text/plain; charset=utf-8'}
        # Only set ACL header if acl is non-empty (AWS BucketOwnerEnforced buckets don't allow ACLs)
        if self.acl:
            headers['x-amz-acl'] = self.acl
        if content_encoding:
            headers['Content-Encoding'] = content_encoding

        self.queue.s3_put(self.url(filename), data, headers)

    def delete(self, filenames: Collection[str]) -> None:
        # to do: multi-object delete API
        for filename in filenames:
            self.queue.s3_delete(self.url(filename))

    async def __aenter__(self) -> Self:
        self.queue = await self.enter_async_context(HttpQueue(self.session, self.key))
        return self


class S3LogDriver(LogDriver, contextlib.AsyncExitStack):
    def __init__(self, config: JsonObject) -> None:
        super().__init__()
        self.config = config
        self.url = URL(get_str(config, 'url'))
        # proxy_url is optional, not needed for public S3 buckets
        self.proxy_url = URL(get_str(config, 'proxy_url', str(self.url)))
        self.acl = get_str(config, 'acl')
        try:
            self.key = S3Key(*get_str(config, 'key').split())
        except (TypeError, JsonError):
            with get_nested(config, 'key') as key:
                self.key = S3Key(get_str(key, 'access'), get_str(key, 'secret'),
                                get_str(key, 'token', '') or None)

    def get_destination(self, slug: str) -> contextlib.AbstractAsyncContextManager[S3Destination]:
        quoted_slug = slug.replace('//', '--').replace(':', '-')
        return S3Destination(self.session, self.url / quoted_slug, self.proxy_url / quoted_slug, self.key, self.acl)

    async def __aenter__(self) -> Self:
        self.session = await self.enter_async_context(create_http_session(self.config))
        return self
