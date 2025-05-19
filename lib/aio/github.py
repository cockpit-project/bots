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
import json
import logging
import platform
from collections.abc import Awaitable, Callable, Mapping
from typing import NamedTuple, Self

import aiohttp
from yarl import URL

from .base import Forge, Status, Subject, SubjectSpecification
from .jsonutil import JsonError, JsonObject, JsonValue, get_bool, get_dict, get_nested, get_str, typechecked
from .util import LRUCache, T, create_http_session

logger = logging.getLogger(__name__)


async def retry(func: Callable[[], Awaitable[T]]) -> T:
    for attempt in range(4):
        try:
            return await func()
        except aiohttp.ClientResponseError as exc:
            if exc.status < 500:
                raise
        except aiohttp.ClientError:
            pass

        # 1 → 2 → 4 → 8s delay
        await asyncio.sleep(2 ** attempt)

    # ...last attempt.
    return await func()


class CacheEntry(NamedTuple):
    conditions: Mapping[str, str]
    value: JsonValue


class GitHub(Forge, contextlib.AsyncExitStack):
    def __init__(self, config: JsonObject) -> None:
        super().__init__()
        self.cache = LRUCache[str, CacheEntry]()
        self.config = config
        self.clone = URL(get_str(config, 'clone-url'))
        self.api = URL(get_str(config, 'api-url'))
        self.content = URL(get_str(config, 'content-url'))
        self.dry_run = not get_bool(config, 'post')

    async def __aenter__(self) -> Self:
        headers = {}
        # token is mandatory if `post = true`
        if token := get_str(self.config, 'token', *((None,) if self.dry_run else ())):
            headers['Authorization'] = f'token {token.strip()}'

        self.session = await self.enter_async_context(create_http_session(self.config, headers))

        return self

    async def post(self, resource: str, body: JsonValue = None) -> JsonValue:
        if self.dry_run:
            logger.info('** Would post to %s: %s', resource, json.dumps(body, indent=4))
            return body

        async def post_once() -> JsonValue:
            async with self.session.post(self.api / resource, json=body) as response:
                logger.debug('response %r', response)
                return await response.json()

        return await retry(post_once)

    async def get(self, resource: str, parameters: Mapping[str, str] | None = None) -> JsonValue:
        async def get_once() -> JsonValue:
            headers = {**self.session.headers}
            cache_entry = self.cache.get(resource)
            if cache_entry is not None:
                headers.update(cache_entry.conditions)

            logger.debug('get %r %r %r', resource, parameters, cache_entry)
            async with self.session.get(self.api / resource % parameters, headers=headers) as response:
                condition_map = {'etag': 'if-none-match', 'last-modified': 'if-modified-since'}
                conditions = {c: response.headers[h] for h, c in condition_map.items() if h in response.headers}

                if cache_entry is not None and response.status == 304:
                    self.cache.add(resource, cache_entry)
                    logger.debug('  cache hit %r -- returning cached value', resource)
                    return cache_entry.value

                else:
                    value = await response.json()
                    logger.debug('  cache miss %r -- caching and returning %r', resource, conditions)
                    self.cache.add(resource, CacheEntry(conditions, value))
                    return value

        return await retry(get_once)

    async def get_obj(self, resource: str, parameters: Mapping[str, str] | None = None) -> JsonObject:
        return typechecked(await self.get(resource, parameters), dict)

    async def check_pr_changed(self, repo: str, pull_nr: int, expected_sha: str) -> str | None:
        try:
            pull = await self.get_obj(f'repos/{repo}/pulls/{pull_nr}')
            if get_str(pull, 'state') != 'open':
                return f'{repo}#{pull_nr} is closed'
            if get_str(get_dict(pull, 'head'), 'sha') != expected_sha:
                return f'{repo}#{pull_nr} changed'
        except JsonError as exc:
            return f'Unexpected error when parsing pull request: {exc}'
        except aiohttp.ClientError as exc:
            # might be transient, so don't kill the job on account of this...
            logger.warning('Error when polling for %s#%s: %r', repo, pull_nr, exc)
            return None
        else:
            return None

    async def open_issue(self, repo: str, issue: JsonObject) -> None:
        await self.post(f'repos/{repo}/issues', issue)

    async def read_file(self, subject: Subject, filename: str) -> str | None:
        async def read_once() -> str | None:
            try:
                async with self.session.get(self.content / subject.repo / subject.sha / filename) as response:
                    logger.debug('response %r', response)
                    return await response.text()
            except aiohttp.ClientResponseError as exc:
                if exc.status == 404:
                    return None
                raise

        return await retry(read_once)

    def get_status(self, repo: str, sha: str, context: str | None, location: URL) -> Status:
        return GitHubStatus(self, repo, sha, context, location)

    async def resolve_subject(self, spec: SubjectSpecification) -> Subject:
        if spec.pull is not None:
            pull = await self.get_obj(f'repos/{spec.repo}/pulls/{spec.pull}')
            return Subject(self, spec.repo,
                           # mypy needs some help here.  See https://github.com/python/mypy/issues/16659
                           spec.sha if spec.sha else get_str(get_dict(pull, 'head'), 'sha'),
                           spec.target or get_str(get_dict(pull, 'base'), 'ref'))

        elif spec.sha is not None:
            return Subject(self, spec.repo, spec.sha, spec.target)

        else:
            branch = spec.branch or get_str(await self.get_obj(f'repos/{spec.repo}'), 'default_branch')

            with get_nested(await self.get_obj(f'repos/{spec.repo}/git/refs/heads/{branch}'), 'object') as obj:
                return Subject(self, spec.repo, get_str(obj, 'sha'), spec.target)


class GitHubStatus(Status):
    def __init__(self, api: GitHub, repo: str, revision: str, context: str | None, link: URL) -> None:
        logger.debug('GitHubStatus(%r, %r, %r, %r)', repo, revision, context, link)
        self.api = api
        self.resource = f'repos/{repo}/statuses/{revision}'
        self.link = str(link)
        self.context = context

    async def post(self, state: str, description: str) -> None:
        logger.debug('POST statuses/%s %s %s', self.resource, state, description)
        if self.context is not None:
            await self.api.post(self.resource, {
                'context': self.context,
                'state': state,
                'description': f'{description} [{platform.node()}]',
                'target_url': self.link
            })
