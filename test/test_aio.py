import hashlib
import json
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from yarl import URL

from lib.aio.base import SubjectSpecification
from lib.aio.github import GitHub
from lib.aio.jobcontext import JobContext
from lib.aio.jsonutil import JsonObject, JsonValue, json_merge_patch
from lib.aio.s3 import S3Key, S3LogDriver
from lib.aio.util import LRUCache


class MockResponse:
    """Stores response data for the mock server."""

    def __init__(self, *, status: int = 200, headers: dict[str, str] | None = None, body: str = '') -> None:
        self.status = status
        self.headers = headers or {}
        self.body = body


class GitHubService:
    CLONE_URL = URL('http://github.test/')
    API_URL = URL('http://api.github.test/')
    CONTENT_URL = URL('http://content.github.test/')
    TOKEN = 'token_ABCDEFG'
    USER_AGENT = __file__  # or any magic unique string

    db: JsonObject = {}  # noqa:RUF012  # JsonObject is immutable

    def __init__(self) -> None:
        self.resources: dict[str, MockResponse] = {}
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
        headers: dict[str, str] = {}
        if etag:
            all_data = str(kwargs.get('body')) + ':' + str(kwargs.get('payload'))
            headers['etag'] = hashlib.sha256(all_data.encode()).hexdigest()
        if mtime:
            headers['last-modified'] = str(time.monotonic())  # accurate enough to change each time

        status = kwargs.get('status', 200)
        body = kwargs.get('body', '')
        self.resources[str(self.API_URL / resource)] = MockResponse(status=status, headers=headers, body=body)

    def update(self, resource: str, value: JsonValue, *, etag: bool = True, mtime: bool = False) -> None:
        self.db = json_merge_patch(self.db, {resource: value})
        if resource in self.db:
            self.add(resource, body=json.dumps(self.db[resource]), etag=etag, mtime=mtime)
        else:
            del self.resources[str(self.API_URL / resource)]

    def flake(self, flakes: Sequence[Exception | tuple[int, str]]) -> None:
        self.flakes.extend(flakes)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        headers = dict(request.headers)

        if self.flakes:
            flake = self.flakes.pop(0)
            if isinstance(flake, Exception):
                raise flake
            else:
                status, _reason = flake
                return httpx.Response(status)

        self.hits += 1  # every request is a hit

        assert headers.get('user-agent') == self.USER_AGENT
        assert headers.get('authorization') == f'token {self.TOKEN}'
        assert url in self.resources, f'{url} not in {list(self.resources.keys())}'

        result = self.resources[url]
        # do etag/last-modified checks. in theory this needs to be
        # case-insensitive, but we use lowercase throughout.  if we return 304
        # then that doesn't impact our rate-limiting score.
        if (etag := result.headers.get('etag')) and headers.get('if-none-match') == etag:
            return httpx.Response(304)
        if (lm := result.headers.get('last-modified')) and headers.get('if-modified-since') == lm:
            return httpx.Response(304)

        self.points += 1  # "full strength" return, counts as rate-limit points
        return httpx.Response(result.status, headers=result.headers, content=result.body)


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
    with respx.mock:
        respx.route(host="api.github.test").mock(side_effect=server.handle_request)
        yield server


@pytest.fixture
async def api(service: GitHubService) -> AsyncIterator[GitHub]:
    async with GitHub('fakehub', service.config) as github:
        yield github


async def test_github_404(service: GitHubService, api: GitHub) -> None:
    # Make sure 4xx errors get raised immediately without retries
    service.add('x', status=404)
    with pytest.raises(httpx.HTTPStatusError, match=r'404'):
        assert await api.get('x') == {}
    service.assert_hits(1, 1)


async def test_github_api_flakes(service: GitHubService, api: GitHub) -> None:
    # Make sure 5xx errors and network issues get retries
    service.flake([(503, 'Busy'), httpx.ConnectError('connection failed')])
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
    service.update(
        f'repos/{repo}/pulls/{pull_nr}',
        {
            'state': 'open',
            'base': {'ref': 'main'},
            'head': {'sha': sha},
        },
    )

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

        assert isinstance(context._forges['github'], GitHub)
        assert context._forges['github'].session.headers['authorization'] == 'token tok_ABCDEFG'

        assert isinstance(context.logs, S3LogDriver)
        assert context.logs.key == S3Key('ACC', 'SEC')


async def test_secrets_expansion(tmp_path: Path) -> None:
    config_file = tmp_path / 'config.toml'
    config_file.write_text('''
        [secrets.external]
        s3-keys = '~/.config/s3-keys'
        github-token = '/etc/github-token'

        [container]
        command = ['podman']
        run-args = []
        default-image = 'ghcr.io/test:latest'

        [container.secrets]
        s3-keys = [
            '--volume=%{s3-keys}:/run/secrets/s3-keys:ro',
        ]
        github-token = [
            '--env=GITHUB_TOKEN_FILE=%{github-token}',
        ]

        [logs]
        driver = 'local'
        local.directory = '/tmp/logs'
    ''')

    home = Path.home()
    async with JobContext(config_file) as context:
        assert context.secrets_args == {
            's3-keys': (f'--volume={home}/.config/s3-keys:/run/secrets/s3-keys:ro',),
            'github-token': ('--env=GITHUB_TOKEN_FILE=/etc/github-token',),
        }


async def test_secrets_undefined_error(tmp_path: Path) -> None:
    config_file = tmp_path / 'config.toml'
    config_file.write_text('''
        [container]
        command = ['podman']
        run-args = []
        default-image = 'ghcr.io/test:latest'

        [container.secrets]
        bad = ['--volume=%{undefined}:/mnt']

        [logs]
        driver = 'local'
        local.directory = '/tmp/logs'
    ''')

    with pytest.raises(SystemExit, match=r"undefined secret '%\{undefined\}'"):
        async with JobContext(config_file):
            pass


async def test_inline_secrets(tmp_path: Path) -> None:
    config_file = tmp_path / 'config.toml'
    config_file.write_text('''
        [secrets.inline]
        github-token = 'ghp_secret123'
        s3-keys = {"linodeobjects.com" = "ABCD Zx2xPa"}

        [container]
        command = ['podman']
        run-args = []
        default-image = 'ghcr.io/test:latest'

        [container.secrets]
        github-token = ['-e=COCKPIT_GITHUB_TOKEN_FILE=/x', '-v=%{github-token}:/x']
        s3-keys = ['-e=COCKPIT_S3_KEY_DIR=/y', '-v=%{s3-keys}:/y']

        [logs]
        driver = 'local'
        local.directory = '/tmp/logs'
    ''')

    async with JobContext(config_file) as ctx:
        # Check github-token
        assert ctx.secrets_args['github-token'][0] == '-e=COCKPIT_GITHUB_TOKEN_FILE=/x'
        token_path = Path(ctx.secrets_args['github-token'][1].removeprefix('-v=').removesuffix(':/x'))
        assert token_path.read_text() == 'ghp_secret123'

        # Check s3-keys
        assert ctx.secrets_args['s3-keys'][0] == '-e=COCKPIT_S3_KEY_DIR=/y'
        s3_path = Path(ctx.secrets_args['s3-keys'][1].removeprefix('-v=').removesuffix(':/y'))
        assert (s3_path / 'linodeobjects.com').read_text() == 'ABCD Zx2xPa'

    # After context closes, temp files should be cleaned up
    assert not token_path.exists()
    assert not s3_path.exists()
    assert not token_path.parent.exists()


async def test_inline_path_nested_error(tmp_path: Path) -> None:
    config_file = tmp_path / 'config.toml'
    config_file.write_text('''
        [secrets.inline.mydir]
        subdir = { "../escape" = "bad" }

        [container]
        command = ['podman']
        run-args = []
        default-image = 'ghcr.io/test:latest'

        [container.secrets]

        [logs]
        driver = 'local'
        local.directory = '/tmp/logs'
    ''')

    with pytest.raises(
        SystemExit,
        match=r"attribute 'secrets': attribute 'inline': attribute 'mydir': "
              r"attribute 'subdir': invalid filename: '\.\./escape'",
    ):
        async with JobContext(config_file):
            pass


async def test_inline_path_invalid_type(tmp_path: Path) -> None:
    config_file = tmp_path / 'config.toml'
    config_file.write_text('''
        [secrets.inline]
        badvalue = 123

        [container]
        command = ['podman']
        run-args = []
        default-image = 'ghcr.io/test:latest'

        [container.secrets]

        [logs]
        driver = 'local'
        local.directory = '/tmp/logs'
    ''')

    with pytest.raises(
        SystemExit, match=r"attribute 'secrets': attribute 'inline': attribute 'badvalue': must be string or object"
    ):
        async with JobContext(config_file):
            pass


async def test_secrets_conflict_error(tmp_path: Path) -> None:
    config_file = tmp_path / 'config.toml'
    config_file.write_text('''
        [secrets.external]
        token = '/etc/token'

        [secrets.inline]
        token = 'inline-value'

        [container]
        command = ['podman']
        run-args = []
        default-image = 'ghcr.io/test:latest'

        [container.secrets]

        [logs]
        driver = 'local'
        local.directory = '/tmp/logs'
    ''')

    with pytest.raises(SystemExit, match=r"secret\(s\) defined in both 'external' and 'inline': token"):
        async with JobContext(config_file):
            pass
