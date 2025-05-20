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

import functools
import http.client
import json
import logging
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Collection, Container, Mapping, Sequence
from http import HTTPStatus
from ssl import SSLEOFError
from types import EllipsisType
from typing import Any, TypedDict, TypeVar

from lib.aio.jsonutil import JsonObject, JsonValue, get_dict, get_dictv, get_str, typechecked
from lib.directories import xdg_cache_home, xdg_config_home
from lib.testmap import is_valid_context

from . import cache

__all__ = (
    'NOT_TESTED',
    'NOT_TESTED_DIRECT',
    'NO_TESTING',
    'TESTING',
    'Checklist',
    'GitHub',
    'GitHubError',
)

TESTING = "Testing in progress"
NO_TESTING = "Manual testing required"

# if the webhook receives a pull request event, it will create a status for each
# context with NOT_TESTED as description
# the subsequent status events caused by the webhook creating the statuses, will
# be ignored by the webhook as it only handles NOT_TESTED_DIRECT as described
# below
NOT_TESTED = "Not yet tested"
# if the webhook receives a status event with NOT_TESTED_DIRECT as description,
# it will publish a test task to the queue (used to trigger specific contexts)
NOT_TESTED_DIRECT = "Not yet tested (direct trigger)"

ISSUE_TITLE_IMAGE_REFRESH = "Image refresh for {0}"

_T = TypeVar('_T')
_DT = TypeVar('_DT')


class Logger:
    def __init__(self, directory: str):
        hostname = socket.gethostname().split(".")[0]
        month = time.strftime("%Y%m")
        self.path = os.path.join(directory, f"{hostname}-{month}.log")

        os.makedirs(directory, exist_ok=True)

    # Yes, we open the file each time
    def write(self, value: str) -> None:
        with open(self.path, 'a') as f:
            f.write(value)


class Response(TypedDict):
    status: int
    reason: str
    headers: Mapping[str, str]
    data: str


class GitHubError(RuntimeError):
    """Raise when getting an error from the GitHub API

    We used to raise `RuntimeError` before. Subclass from that, so that client
    code depending on it continues to work.
    """

    def __init__(self, url: str, response: Response):
        self.url = url
        self.data = response.get('data', "")
        self.status = response.get('status')
        self.reason = response.get('reason')

    def __str__(self) -> str:
        result = (f'Error accessing {self.url}\n'
                  f'  Status: {self.status}\n'
                  f'  Reason: {self.reason}\n'
                  f'  Response: {self.data}')

        if self.status == 401:
            result += ('\n\nPlease ensure that your github-token is configured '
                       'with the appropriate permissions.  See bots/README.md')

        return result


def get_repo() -> str | None:
    res = subprocess.check_output(['git', 'config', '--default=', 'cockpit.bots.github-repo'])
    return res.decode('utf-8').strip() or None


def get_origin_repo() -> str | None:
    try:
        res = subprocess.check_output(["git", "remote", "get-url", "origin"])
    except subprocess.CalledProcessError:
        return None
    url = res.decode('utf-8').strip()
    m = re.fullmatch(r"(git@github.com:|https://github.com/)(.*?)(\.git)?", url)
    if m:
        return m.group(2).rstrip("/")
    raise RuntimeError("Not a GitHub repo: %s" % url)


class GitHub:
    def __init__(
        self,
        base: str | None = None,
        cacher: cache.Cache[Response] | None = None,
        repo: str | None = None,
        remote: str | None = None
    ):
        if repo is not None:
            self.repo = repo
        if remote is not None:
            self.remote = remote
        if base is not None:
            self.base = base

        self.conn: http.client.HTTPConnection | None = None
        self.token = None
        self.debug = False
        try:
            with open(xdg_config_home('cockpit-dev', 'github-token', envvar='COCKPIT_GITHUB_TOKEN_FILE')) as f:
                self.token = f.read().strip()
        except FileNotFoundError:
            try:
                with open(xdg_config_home('github-token')) as f:
                    self.token = f.read().strip()
            except FileNotFoundError:
                # fall back to GitHub's CLI token
                try:
                    with open(xdg_config_home("gh/config.yml")) as f:
                        match = re.search(r'oauth_token:\s*(\S+)', f.read())
                    if match:
                        self.token = match.group(1)
                except FileNotFoundError:
                    # token not found anywhere, so only reading operations are available
                    pass

        # default cache directory
        if not cacher:
            cacher = cache.Cache(xdg_cache_home('github'))

        self.cache = cacher

        # Create a log for debugging our GitHub access
        self.log = Logger(self.cache.directory)
        self.log.write("")

    @functools.cached_property
    def remote(self) -> str:
        repo = os.environ.get("GITHUB_BASE", None) or get_repo()

        if repo:
            return f'https://github.com/{repo}'
        else:
            return 'origin'

    @functools.cached_property
    def repo(self) -> str:
        repo = os.environ.get("GITHUB_BASE", None) or get_repo() or get_origin_repo()
        if not repo:
            raise RuntimeError('Could not determine the github repository:\n'
                               '  - some commands accept a --repo argument\n'
                               '  - you can set the GITHUB_BASE environment variable\n'
                               '  - you can set git config cockpit.bots.github-repo\n'
                               '  - otherwise, the "origin" remote from the current checkout is used')

        return repo

    @functools.cached_property
    def base(self) -> str:
        netloc = os.environ.get("GITHUB_API", "https://api.github.com")
        return f"{netloc}/repos/{self.repo}"

    @functools.cached_property
    def url(self) -> urllib.parse.ParseResult:
        return urllib.parse.urlparse(self.base)

    def qualify(self, resource: str | None) -> str:
        if resource is None:
            return self.url.path
        return urllib.parse.urljoin(f"{self.url.path}/", resource)

    def request(
        self, method: str, resource: str | None, data: str = "", headers: Mapping[str, str] = {}
    ) -> Response:
        all_headers = {**headers, "User-Agent": "Cockpit Tests"}
        if self.token:
            all_headers["Authorization"] = "token " + self.token

        for retry in range(5):
            if not self.conn:
                if self.url.scheme == 'http':
                    self.conn = http.client.HTTPConnection(self.url.netloc)
                else:
                    self.conn = http.client.HTTPSConnection(self.url.netloc)
                self.conn.set_debuglevel(1 if self.debug else 0)

            try:
                self.conn.request(method, self.qualify(resource), data, all_headers)
                response = self.conn.getresponse()
                if response.status != HTTPStatus.BAD_GATEWAY:
                    # success!
                    break
            except (ConnectionResetError, http.client.BadStatusLine, OSError, SSLEOFError) as e:
                logging.warning("Transient error during GitHub request, attempt #%s: %s", retry, e)

            self.conn = None
            time.sleep(2 ** retry)
        else:
            raise OSError("Repeated failure to talk to GitHub API, giving up")

        heads = {}
        for (header, value) in response.getheaders():
            heads[header.lower()] = value
        self.log.write(
            f'{self.url.netloc} - - [{time.asctime()}] "{method} {resource} HTTP/1.1" {response.status} -\n')
        return {
            "status": response.status,
            "reason": response.reason,
            "headers": heads,
            "data": response.read().decode('utf-8')
        }

    def _get(
        self, cast: Callable[[JsonValue], _T], resource: str | None = None, default: _DT | EllipsisType = ...
    ) -> _T | _DT:
        headers = {}
        qualified = self.qualify(resource)
        cached = self.cache.read(qualified)
        if cached:
            if self.cache.current(qualified):
                return json.loads(cached['data'] or "null")
            etag = cached['headers'].get("etag", None)
            modified = cached['headers'].get("last-modified", None)
            if etag:
                headers['If-None-Match'] = etag
            elif modified:
                headers['If-Modified-Since'] = modified
        response = self.request("GET", resource, "", headers)
        if response['status'] == 404 and not isinstance(default, EllipsisType):
            return default
        elif cached and response['status'] == 304:  # Not modified
            self.cache.write(qualified, cached)
            return cast(json.loads(cached['data'] or "null"))
        elif response['status'] < 200 or response['status'] >= 300:
            raise GitHubError(self.qualify(resource), response)
        else:
            self.cache.write(qualified, response)
            return cast(json.loads(response['data'] or "null"))

    def get(self, resource: str | None = None) -> Any:
        return self._get(lambda v: v, resource, None)

    def get_obj(self, resource: str | None = None, default: _DT | EllipsisType = ...) -> JsonObject | _DT:
        return self._get(lambda v: typechecked(v, dict), resource, default)

    def get_objv(self, resource: str | None = None, default: _DT | EllipsisType = ...) -> Sequence[JsonObject] | _DT:
        return self._get(lambda v: tuple(typechecked(item, dict) for item in typechecked(v, list)), resource, default)

    def post(self, resource: str, data: JsonValue, accept: Container[int] = ()) -> JsonValue:
        response = self.request("POST", resource, json.dumps(data), {"Content-Type": "application/json"})
        status = response['status']
        if (status < 200 or status >= 300) and status not in accept:
            raise GitHubError(self.qualify(resource), response)
        self.cache.mark()
        return json.loads(response['data'])

    def put(self, resource: str, data: JsonValue, accept: Container[int] = ()) -> JsonValue:
        response = self.request("PUT", resource, json.dumps(data), {"Content-Type": "application/json"})
        status = response['status']
        if (status < 200 or status >= 300) and status not in accept:
            raise GitHubError(self.qualify(resource), response)
        self.cache.mark()
        if response['data']:
            return json.loads(response['data'])
        else:
            return None

    def delete(self, resource: str, accept: Container[int] = ()) -> JsonValue:
        response = self.request("DELETE", resource, "", {"Content-Type": "application/json"})
        status = response['status']
        if (status < 200 or status >= 300) and status not in accept:
            raise GitHubError(self.qualify(resource), response)
        self.cache.mark()
        if response['data']:
            return json.loads(response['data'])
        else:
            return None

    def patch(self, resource: str, data: JsonValue, accept: Container[int] = ()) -> JsonValue:
        response = self.request("PATCH", resource, json.dumps(data), {"Content-Type": "application/json"})
        status = response['status']
        if (status < 200 or status >= 300) and status not in accept:
            raise GitHubError(self.qualify(resource), response)
        self.cache.mark()
        return json.loads(response['data'])

    def statuses(self, revision: str) -> Mapping[str, JsonObject]:
        result: dict[str, JsonObject] = {}
        page = 1
        count = 100
        while count == 100:
            data = self.get_obj(f"commits/{revision}/status?page={page}&per_page={count}")
            count = 0
            page += 1
            for status in get_dictv(data, "statuses", ()):
                context = get_str(status, "context")
                if is_valid_context(context, self.repo) and context not in result:
                    result[context] = status
                count += 1
        return result

    def all_statuses(self, revision: str) -> Sequence[JsonObject]:
        result: list[JsonObject] = []
        page = 1
        count = 100
        while count == 100:
            data = self.get_objv(f"commits/{revision}/statuses?page={page}&per_page={count}")
            count = 0
            page += 1
            result += data
            count = len(data)
        return result

    def pulls(self, state: str = 'open', since: float | None = None) -> Sequence[JsonObject]:
        result = []
        page = 1
        count = 100
        while count == 100:
            pulls = self.get_objv(f"pulls?page={page}&per_page={count}&state={state}&sort=created&direction=desc", [])
            count = 0
            page += 1
            for pull in pulls:
                # Check that the pulls are past the expected date
                if since:
                    closed = get_str(pull, 'closed_at', None)
                    if closed and since > time.mktime(time.strptime(closed, "%Y-%m-%dT%H:%M:%SZ")):
                        continue
                    created = get_str(pull, 'created_at', None)
                    if not closed and created and since > time.mktime(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")):
                        continue

                result.append(pull)
                count += 1
        return result

    # The since argument is seconds since the issue was last time modified
    def issues(
        self, labels: Collection[str] = ("bot",), state: str = "open", since: float | None = None
    ) -> Sequence[JsonObject]:
        result: list[JsonObject] = []
        page = 1
        count = 100
        label = ",".join(labels)
        if since:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
            sincestr = f"&since={now}"
        else:
            sincestr = ""

        while count == 100:
            req = f"issues?labels={label}&state={state}&page={page}&per_page={count}{sincestr}"
            issues = self.get_objv(req)

            page += 1
            count = len(issues)
            result += issues
        return result

    def issue_comments(self, number: int) -> Sequence[JsonObject]:
        result: list[JsonObject] = []
        page = 1
        count = 100
        while count == 100:
            comments = self.get_objv(f"issues/{number}/comments?page={page}&per_page={count}")
            count = 0
            page += 1
            if comments:
                result += comments
                count = len(comments)
        return result

    def get_head(self, pr: int) -> str | None:
        pull = self.get_obj(f"pulls/{pr}", {})
        return get_str(get_dict(pull, "head", {}), "sha", None)


class Checklist:
    # NB: GitHub sends `body: null` for issues with empty bodies
    def __init__(self, body: str | None):
        self.process(body or '')

    @staticmethod
    def format_line(item: str, check: bool | str) -> str:
        if isinstance(check, bool):
            return f' * [{" x"[check]}] {item}'  # ' * [ ] item' or ' * [x] item'
        else:
            return f' * [ ] {check}: {item}'  # eg ' * [ ] FAIL: item'

    @staticmethod
    def parse_line(line: str) -> tuple[str | None, str | bool | None]:
        match = re.fullmatch(r'[*-] \[(?P<checked>[ xX])\]\s+((?P<status>[A-Z]+):\s+)?(?P<item>.+)', line.strip())
        if match is None:
            return None, None
        return match['item'], match['status'] or match['checked'] in 'xX'

    def process(self, body: str, items: Mapping[str, str | bool] = {}) -> None:
        self.items = {}
        lines = []
        items = dict(items)
        for line in body.splitlines():
            item, check = self.parse_line(line)
            if item:
                if item in items:
                    check = items[item]
                    del items[item]
                    line = self.format_line(item, check)
                self.items[item] = check
            lines.append(line)
        for item, check in items.items():
            lines.append(self.format_line(item, check))
            self.items[item] = check
        self.body = "\n".join(lines)

    def check(self, item: str, checked: str | bool = True) -> None:
        self.process(self.body, {item: checked})

    def add(self, item: str) -> None:
        self.process(self.body, {item: False})

    def checked(self) -> Mapping[str, str | bool]:
        result = {}
        for item, check in self.items.items():
            if check:
                result[item] = check
        return result
