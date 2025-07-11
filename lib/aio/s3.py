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
import hmac
import logging
import mimetypes
import time
from collections.abc import Collection, Mapping
from types import TracebackType
from typing import NamedTuple, Self

import aiohttp
from yarl import URL

from .base import Destination, LogDriver
from .jsonutil import JsonError, JsonObject, get_nested, get_str
from .util import AsyncQueue, create_http_session

logger = logging.getLogger(__name__)


class S3Key(NamedTuple):
    access: str
    secret: str


class HttpRequest(NamedTuple):
    method: str
    url: URL
    headers: Mapping[str, str]
    data: bytes = b''


class HttpQueue:
    def __init__(self, session: aiohttp.ClientSession, s3_key: S3Key) -> None:
        self.session = session
        self._queue = AsyncQueue[HttpRequest]()
        self._task: asyncio.Task[None] | None = None
        self._level: int = logging.DEBUG
        self._s3_key = s3_key

    async def request_once(self, request: HttpRequest, checksum: str) -> None:
        # NB: Re-sign each attempt.  Time's arrow neither stands still nor reverses.
        headers = s3_sign(request.url, request.method, request.headers, checksum, self._s3_key)
        logger.log(self._level, '%s %s', request.method, request.url)
        async with self.session.request(request.method, request.url, data=request.data, headers=headers) as response:
            logger.debug('response %s %s %r', request.method, request.url, response)

    async def request(self, request: HttpRequest) -> None:
        checksum = hashlib.sha256(request.data).hexdigest()
        for attempt in range(5):
            try:
                return await self.request_once(request, checksum)
            except aiohttp.ClientResponseError as exc:
                if exc.status < 500:
                    raise  # We actually care about 4xx errors, but blindly retry 5xx.
            except aiohttp.ClientError:
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


def s3_sign(
    url: URL, method: str, headers: Mapping[str, str], checksum: str, keys: S3Key
) -> Mapping[str, str]:
    """Signs an AWS request using the AWS4-HMAC-SHA256 algorithm

    Returns a dictionary of extra headers which need to be sent along with the request.
    If the method is PUT then the checksum of the data to be uploaded must be provided.
    @headers, if given, are a dict of additional headers to be signed (eg: `x-amz-acl`)
    """
    amzdate = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    assert url.host is not None

    # Header canonicalisation demands all header names in lowercase
    headers = {key.lower(): value for key, value in headers.items()}
    headers.update({'host': url.host, 'x-amz-content-sha256': checksum, 'x-amz-date': amzdate})
    headers_str = ''.join(f'{k}:{v}\n' for k, v in sorted(headers.items()))
    headers_list = ';'.join(sorted(headers))

    credential_scope = f'{amzdate[:8]}/any/s3/aws4_request'
    signing_key = f'AWS4{keys.secret}'.encode('ascii')
    for item in credential_scope.split('/'):
        signing_key = hmac.new(signing_key, item.encode('ascii'), hashlib.sha256).digest()

    algorithm = 'AWS4-HMAC-SHA256'
    canonical_request = f'{method}\n{url.raw_path}\n{url.query_string}\n{headers_str}\n{headers_list}\n{checksum}'
    request_hash = hashlib.sha256(canonical_request.encode('ascii')).hexdigest()
    string_to_sign = f'{algorithm}\n{amzdate}\n{credential_scope}\n{request_hash}'
    signature = hmac.new(signing_key, string_to_sign.encode('ascii'), hashlib.sha256).hexdigest()
    headers['Authorization'] = (
        f'{algorithm} Credential={keys.access}/{credential_scope},SignedHeaders={headers_list},Signature={signature}'
    )

    return headers


class S3Destination(Destination, contextlib.AsyncExitStack):
    def __init__(self, session: aiohttp.ClientSession, url: URL, proxy_url: URL, key: S3Key) -> None:
        super().__init__()
        self.session = session
        self.location = url  # Used for S3 operations
        self.proxy_location = proxy_url  # Used for external links (GitHub status)
        self.key = key

    def url(self, filename: str) -> URL:
        return self.location / filename

    def has(self, filename: str) -> bool:
        raise NotImplementedError('use Index')

    def write(self, filename: str, data: bytes) -> None:
        content_type, content_encoding = mimetypes.guess_type(filename)
        headers = {**self.session.headers, 'Content-Type': content_type or 'text/plain; charset=utf-8'}
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
        try:
            access, secret = get_str(config, 'key').split()
            self.key = S3Key(access, secret)
        except (ValueError, JsonError):
            with get_nested(config, 'key') as key:
                self.key = S3Key(get_str(key, 'access'), get_str(key, 'secret'))

    def get_destination(self, slug: str) -> contextlib.AbstractAsyncContextManager[S3Destination]:
        quoted_slug = slug.replace('//', '--').replace(':', '-')
        return S3Destination(self.session, self.url / quoted_slug, self.proxy_url / quoted_slug, self.key)

    async def __aenter__(self) -> Self:
        headers = {'x-amz-acl': get_str(self.config, 'acl')}
        self.session = await self.enter_async_context(create_http_session(self.config, headers))
        return self
