#!/usr/bin/env python3

import argparse
import asyncio
import contextlib
import email
import hashlib
import logging
import os
import socket
import subprocess
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Self

from aiohttp import web
from aiohttp.helpers import ETag
from aiohttp.typedefs import Handler
from yarl import URL

from lib.aio.jsonutil import JsonObject, get_str

# routing tables for 'api', 'clone' and 'raw' endpoints
api = web.RouteTableDef()
clone = web.RouteTableDef()
raw = web.RouteTableDef()


@web.middleware
async def conditions(request: web.Request, handler: Handler) -> web.StreamResponse:
    response = await handler(request)
    if response.etag and request.if_none_match and response.etag == request.if_none_match:
        return web.Response(status=304)
    if (response.last_modified and request.if_modified_since and request.if_modified_since <= response.last_modified):
        return web.Response(status=304)
    return response


class Repository:
    def __init__(self, gitdir: Path, issues: Sequence[JsonObject] = ()) -> None:
        self.gitdir = gitdir
        self.issues = list(issues)

    async def git(self, *cmd: str, **kwargs) -> str:
        proc = await asyncio.create_subprocess_exec('git', *cmd, stdout=subprocess.PIPE, cwd=self.gitdir)
        return (await proc.communicate())[0].decode()

    def issue(self, nr: int | str) -> JsonObject:
        return self.issues[int(nr)]


class SimHub(contextlib.AsyncExitStack):
    def __init__(self, path: Path | None = None, addr: str = 'localhost', port: int = 0) -> None:
        super().__init__()

        self.path = path or Path(self.enter_context(tempfile.TemporaryDirectory()))
        self.repos = dict[str, Repository]()

        self.app = web.Application(middlewares=[conditions])
        self.app['simhub'] = self
        self.app.add_routes(clone)
        self.app.add_routes(api)
        self.app.add_routes(raw)

        self.listener = socket.socket()
        self.listener.bind((addr, port))
        addr, port = self.listener.getsockname()

        self.api = URL.build(scheme='http', host=addr, port=port, path='/')

    async def __aenter__(self) -> Self:
        self.listener.listen()

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.push_async_callback(self.runner.cleanup)

        self.site = web.SockSite(self.runner, self.listener)
        await self.site.start()

        return self

    def get_repo(self, owner: str, name: str) -> Repository:
        return self.repos[f'{owner}/{name}']

    async def clone(self, name: str, clone_from: str, issues: Sequence[JsonObject] = ()) -> None:
        repo = Repository(self.path / name)
        repo.gitdir.mkdir(parents=True)
        await repo.git('clone', '--bare', '--mirror', clone_from, str(repo.gitdir))
        (repo.gitdir / 'git-daemon-export-ok').touch()
        self.repos[name] = repo


# Request helpers which reach inside of SimHub
def simhub(request: web.Request) -> SimHub:
    simhub = request.app['simhub']
    assert isinstance(simhub, SimHub)
    return simhub


def repository(request: web.Request) -> Repository:
    return simhub(request).get_repo(request.match_info['owner'], request.match_info['repo'])


def json_response(obj: JsonObject) -> web.Response:
    response = web.json_response(obj)
    response.etag = ETag(hashlib.sha256(str(obj).encode()).hexdigest())
    if last_modified := get_str(obj, '.last-modified', None):
        response.last_modified = datetime.fromisoformat(last_modified)
    return response


# API endpoints
@api.get(r'/repos/{owner}/{repo}')
async def get_repo(request: web.Request) -> web.Response:
    output = await repository(request).git('symbolic-ref', '--short', 'HEAD')
    return json_response({'default_branch': output.strip()})


@api.get(r'/repos/{owner}/{repo}/git/refs/heads/{branch}')
async def get_branch(request: web.Request) -> web.Response:
    output = await repository(request).git('rev-parse', f'refs/heads/{request.match_info["branch"]}')
    return json_response({'object': {'sha': output.strip()}})


@api.get(r'/repos/{owner}/{repo}/issues/{nr:\d+}')
async def get_issue(request: web.Request) -> web.Response:
    return json_response(repository(request).issues[int(request.match_info['nr'])])


@api.get(r'/repos/{owner}/{repo}/pulls/{nr:\d+}')
async def get_pull(request: web.Request) -> web.Response:
    return json_response(repository(request).issues[int(request.match_info['nr'])])


# clone endpoint
@clone.post('/{owner}/{repo}/git-upload-pack')
@clone.get('/{owner}/{repo}/info/refs')
async def git_http_backend(request: web.Request) -> web.Response:
    proc = await asyncio.create_subprocess_exec(
        'git', 'http-backend', stdin=subprocess.PIPE, stdout=subprocess.PIPE, env={
            **os.environ,
            'REQUEST_METHOD': request.method,
            'PATH_INFO': request.path,
            'QUERY_STRING': request.query_string,
            'GIT_PROTOCOL': request.headers.get('git-protocol', ''),
            'CONTENT_TYPE': request.headers.get('content-type', ''),
            'GIT_PROJECT_ROOT': str(simhub(request).path)
        }
    )
    data = await request.read() if request.method == 'POST' else b''
    stdout, _ = await proc.communicate(data)
    headers, _, body = stdout.partition(b'\r\n\r\n')
    message = email.parser.BytesParser().parsebytes(headers, headersonly=True)
    status, _, reason = message.get('Status', '200 OK').partition(' ')
    return web.Response(status=int(status), reason=reason, headers=dict(message), body=body)

    return await repository(request).http_backend(request)


# raw endpoint
@raw.get('/{owner}/{repo}/{ref:[^{}/:]+}/{path:[^{}:]+}')
async def get_raw(request: web.Request) -> web.Response:
    objname = request.match_info['ref'] + ':' + request.match_info['path']
    return web.Response(text=await repository(request).git('cat-file', '-p', objname))


async def main() -> None:
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser(description="Serve a single git repository via HTTP")
    parser.add_argument('--addr', '-a', default='127.0.0.1', help="Address to bind to")
    parser.add_argument('--port', '-p', type=int, default=0, help="Port number to bind to")
    args = parser.parse_args()

    async with SimHub(addr=args.addr, port=args.port) as simhub:
        print(simhub.api)
        await asyncio.sleep(86400)


if __name__ == '__main__':
    asyncio.run(main())
