import hashlib
import json
import re
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from yarl import URL

from lib.aio.base import SubjectSpecification
from lib.aio.github import GitHub
from lib.aio.jobcontext import JobContext
from lib.aio.jsonutil import JsonObject, JsonValue, json_merge_patch
from lib.aio.s3 import S3Key, S3LogDriver
from lib.aio.util import LRUCache


class GitHubService:
    CLONE_URL = URL('http://github.test/')
    API_URL = URL('http://api.github.test/')
    CONTENT_URL = URL('http://content.github.test/')
    TOKEN = 'token_ABCDEFG'
    USER_AGENT = __file__  # or any magic unique string

    db: JsonObject = {}  # noqa:RUF012  # JsonObject is immutable

    def __init__(self) -> None:
        self.resources: dict[URL, CallbackResult] = {}
        self.flakes: list[Exception | tuple[int, str]] = []
        self.hits = 0
        self.points = 0  # ie: GitHub rate-limiting "points"
        self.config: JsonObject = {
            'api-url': str(self.API_URL),
            'clone-url': str(self.CLONE_URL),
            'post': True,
            'token': self.TOKEN,
            'user-agent': self.USER_AGENT,
        }

    def assert_hits(self, expected_hits: int, expected_points: int) -> None:
        assert self.hits == expected_hits
        assert self.points == expected_points
        self.hits = self.points = 0

    def add(self, resource: str, *, etag: bool = False, mtime: bool = False, **kwargs: Any) -> None:
        headers = {}
        if etag:
            all_data = str(kwargs.get('body')) + ':' + str(kwargs.get('payload'))
            headers['etag'] = hashlib.sha256(all_data.encode()).hexdigest()
        if mtime:
            headers['last-modified'] = str(time.monotonic())  # accurate enough to change each time
        self.resources[self.API_URL / resource] = CallbackResult(headers=headers, **kwargs)

    def update(self, resource: str, value: JsonValue, *, etag: bool = True, mtime: bool = False) -> None:
        self.db = json_merge_patch(self.db, {resource: value})
        if resource in self.db:
            self.add(resource, body=json.dumps(self.db[resource]), etag=etag, mtime=mtime)
        else:
            del self.resources[self.API_URL / resource]

    def flake(self, flakes: Sequence[Exception | tuple[int, str]]) -> None:
        self.flakes.extend(flakes)

    async def post(self, url: URL, headers: dict[str, str], **kwargs: str) -> CallbackResult:
        raise NotImplementedError

    async def get(self, url: URL, headers: dict[str, str], **kwargs: str) -> CallbackResult:
        if self.flakes:
            flake = self.flakes.pop(0)
            if isinstance(flake, Exception):
                raise flake
            else:
                status, reason = flake
                return CallbackResult(status=status, reason=reason)

        self.hits += 1  # every request is a hit

        assert headers['User-Agent'] == self.USER_AGENT
        assert headers['Authorization'] == f'token {self.TOKEN}'
        assert url in self.resources

        result = self.resources[url]
        assert result.headers is not None  # because we add it ourselves
        # do etag/last-modified checks. in theory this needs to be
        # case-insensitive, but we use lowercase throughout.  if we return 304
        # then that doesn't impact our rate-limiting score.
        if (etag := result.headers.get('etag')) and headers.get('if-none-match') == etag:
            return CallbackResult(status=304, reason='Not Modified')
        if (lm := result.headers.get('last-modified')) and headers.get('if-modified-since') == lm:
            return CallbackResult(status=304, reason='Not Modified')

        self.points += 1  # "full strength" return, counts as rate-limit points
        return result


def test_lru_cache() -> None:
    cache = LRUCache[str, int](max_items=2)
    cache.add('a', 1)
    cache.add('b', 2)
    assert cache == {'a': 1, 'b': 2}
    cache.add('c', 3)
    assert cache == {'b': 2, 'c': 3}
    cache.add('d', 4)
    assert cache == {'c': 3, 'd': 4}
    cache.add('c', 3)  # refresh 'c' without value change
    assert cache == {'c': 3, 'd': 4}
    cache.add('e', 5)  # now 'd' should be evicted
    assert cache == {'c': 3, 'e': 5}
    cache.add('c', 300)  # refresh 'c' with value change
    assert cache == {'c': 300, 'e': 5}
    cache.add('f', 6)  # now 'e' should be evicted
    assert cache == {'c': 300, 'f': 6}
    cache.add('c', 3)  # refresh 'c' some more
    assert cache == {'c': 3, 'f': 6}
    cache.add('c', 3)
    assert cache == {'c': 3, 'f': 6}
    cache.add('f', 6)  # but now bump 'f' up again
    assert cache == {'c': 3, 'f': 6}
    cache.add('g', 7)  # 'c' should now be evicted
    assert cache == {'f': 6, 'g': 7}


@pytest.fixture
def service() -> Iterator[GitHubService]:
    server = GitHubService()
    with aioresponses() as mock:
        mock.post(re.compile(r''), callback=server.post, repeat=True)
        mock.get(re.compile(r''), callback=server.get, repeat=True)
        yield server


@pytest.fixture
async def api(service: GitHubService) -> AsyncIterator[GitHub]:
    async with GitHub(service.config) as github:
        yield github


async def test_github_404(service: GitHubService, api: GitHub) -> None:
    # Make sure 4xx errors get raised immediately without retries
    service.add('x', status=404, reason='Not Found')
    with pytest.raises(aiohttp.ClientResponseError, match=r'404.*Not Found'):
        assert await api.get('x') == {}
    service.assert_hits(1, 1)


async def test_github_api_flakes(service: GitHubService, api: GitHub) -> None:
    # Make sure 5xx errors and network issues get retries
    service.flake([(503, 'Busy'), aiohttp.ClientConnectionError()])
    service.update('x', {'a': 'b'}, etag=True)
    assert await api.get('x') == {'a': 'b'}


async def test_github_cache(service: GitHubService, api: GitHub) -> None:
    # verify fundamentals of caching behaviour
    service.update('x', {'a': 'b'}, etag=True)
    assert await api.get('x') == {'a': 'b'}
    service.assert_hits(1, 1)
    assert await api.get('x') == {'a': 'b'}
    service.assert_hits(1, 0)

    service.update('x', {'a': 'b'}, etag=True)
    assert await api.get('x') == {'a': 'b'}
    service.assert_hits(1, 0)

    service.update('x', {'a': 'c'}, etag=True)
    assert await api.get('x') == {'a': 'c'}
    service.assert_hits(1, 1)

    service.update('y', {'a': 'b'}, etag=False, mtime=True)
    assert await api.get('y') == {'a': 'b'}
    service.assert_hits(1, 1)
    assert await api.get('y') == {'a': 'b'}
    service.assert_hits(1, 0)

    service.update('y', {'a': 'b'}, etag=False, mtime=True)  # this changes the mtime, even with the same body
    assert await api.get('y') == {'a': 'b'}
    service.assert_hits(1, 1)

    service.update('y', {'a': 'c'}, etag=False, mtime=True)  # this changes the mtime, different body
    assert await api.get('y') == {'a': 'c'}
    service.assert_hits(1, 1)

    CACHE_SIZE = 128  # this is the default

    # fill the cache and evict 'x' and 'y'
    for i in range(CACHE_SIZE):
        service.update(f'n/{i}', {'n': i})
        assert await api.get(f'n/{i}') == {'n': i}
    service.assert_hits(CACHE_SIZE, CACHE_SIZE)

    # verify that our etag usage prevents us from getting more "points"
    for i in range(CACHE_SIZE):
        assert await api.get(f'n/{i}') == {'n': i}
    service.assert_hits(CACHE_SIZE, 0)

    # verify that our 'x' and 'y' score "points" now
    assert await api.get('x') == {'a': 'c'}
    assert await api.get('y') == {'a': 'c'}
    service.assert_hits(2, 2)

    # finally, re-read our n/[0 .. 127] items in the pathological order,
    # causing each one to be evicted just before we would have read it
    for i in range(CACHE_SIZE):
        assert await api.get(f'n/{i}') == {'n': i}
    service.assert_hits(CACHE_SIZE, CACHE_SIZE)


async def test_github_pr_lookup(service: GitHubService, api: GitHub) -> None:
    pull_nr = 123
    repo = 'owner/repo'
    sha = '89abcdef' * 5

    # open a PR
    service.update(f'repos/{repo}/pulls/{pull_nr}', {
        'state': 'open',
        'base': {'ref': 'main'},
        'head': {'sha': sha},
    })

    # Look up the sha in the PR via the REST API
    subject = await api.resolve_subject(SubjectSpecification({'repo': 'owner/repo', 'pull': pull_nr}))
    assert subject == (api, repo, sha, 'main')
    service.assert_hits(1, 1)

    # The next thing that happens is that we poll this API a lot
    for _ in range(100):
        assert await api.check_pr_changed(repo, pull_nr, subject.sha) is None
    # IMPORTANT: we should have used an etag each time, so no extra rate-limit points
    service.assert_hits(100, 0)

    # Close the PR and poll once more
    service.update(f'repos/{repo}/pulls/{pull_nr}', {'state': 'closed'})
    message = await api.check_pr_changed(repo, pull_nr, subject.sha)
    assert message and f'#{pull_nr} is closed' in message
    service.assert_hits(1, 1)  # etag changed, so this scores "points"

    # Re-open the PR, do a force-push, and poll once more
    service.update(f'repos/{repo}/pulls/{pull_nr}', {'state': 'open', 'head': {'sha': '12345678' * 5}})
    message = await api.check_pr_changed(repo, pull_nr, subject.sha)
    assert message and f'#{pull_nr} changed' in message
    service.assert_hits(1, 1)  # etag changed, so this scores "points"


async def test_config(tmp_path: Path) -> None:
    config_file = tmp_path / 'config'
    config_file.write_text('''
        [test]
        text = [{file="./abc"}]

        [forge.github]
        token=[{file="./github-token"}]

        [logs]
        driver='s3'
        s3.key=[{file="./s3-key"}]
    ''')
    (tmp_path / 'abc').write_text('xyz')
    (tmp_path / 'github-token').write_text('tok_ABCDEFG\n')
    (tmp_path / 's3-key').write_text('\n ACC\t SEC  \t \n')

    async with JobContext(config_file) as context:
        # make our lives easier with mypy for the following asserts
        config: Any = context.config

        # test override of built-in config
        assert config['logs']['driver'] == 's3'

        # test built-in config
        assert config['container']['command'] == ['podman']

        # test file loading
        assert config['test']['text'] == 'xyz'

        assert isinstance(context.forge, GitHub)
        assert context.forge.session.headers['Authorization'] == 'token tok_ABCDEFG'

        assert isinstance(context.logs, S3LogDriver)
        assert context.logs.key == S3Key('ACC', 'SEC')
