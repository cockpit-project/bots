# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import respx

from lib.constants import BOTS_DIR

GITHUB_API = 'https://api.github.com/'
TF_HOST = 'api.dev.testing-farm.io'


class MockGitHub:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if request.method == 'GET':
            if path == '/repos/cockpit-project/bots':
                return httpx.Response(200, json={'default_branch': 'main'})
            if path == '/repos/cockpit-project/bots/git/refs/heads/main':
                return httpx.Response(200, json={'object': {'sha': 'abc123def456'}})
            if path == '/repos/cockpit-project/bots/pulls/99':
                return httpx.Response(200, json={
                    'head': {'sha': 'pr99sha12345'},
                    'base': {'ref': 'main'},
                })
            return httpx.Response(404)

        if request.method == 'POST':
            body = json.loads(request.content)
            self.posts.append((path, body))
            return httpx.Response(201, json={'id': 999})

        return httpx.Response(405)


class MockTestingFarm:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.request_id = 'tf-request-12345'

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if request.method == 'POST' and path == '/v0.1/requests':
            body = json.loads(request.content)
            self.requests.append(body)
            return httpx.Response(200, json={'id': self.request_id})

        if request.method == 'GET' and path == f'/v0.1/requests/{self.request_id}':
            return httpx.Response(200, json={
                'state': 'running',
                'run': {'artifacts': 'https://artifacts.test/12345'},
            })

        return httpx.Response(404)


@pytest.fixture
def issue_comment_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader('issue_comment', os.path.join(BOTS_DIR, 'issue-comment'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    config = tmp_path / 'config.toml'
    config.write_text(f'''
        [forge.github]
        api-url = '{GITHUB_API}'
        clone-url = 'http://github.test/'
        post = true
        token = 'test-token'

        [logs]
        driver = 'local'
        local.directory = '{tmp_path / "logs"}'

        [container]
        command = ['podman']
        run-args = []
        default-image = 'ghcr.io/test:latest'

        [container.secrets]
        github-token = []
        image-upload = []

        [secrets.inline]
        github-token = 'ghp_test'
        image-upload = 'upload-key'
    ''')
    return config


@pytest.fixture
def event_file(tmp_path: Path) -> Path:
    return tmp_path / 'event.json'


@pytest.fixture
def mocks(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[MockGitHub, MockTestingFarm]:
    github = MockGitHub()
    tf = MockTestingFarm()
    monkeypatch.setenv('JOB_RUNNER_CONFIG', str(config_file))
    monkeypatch.setenv('TESTING_FARM_API_TOKEN', 'test-tf-token')

    async def fake_get_git_upstream() -> tuple[str, str]:  # noqa: RUF029
        return ('https://github.com/cockpit-project/bots', 'main')

    monkeypatch.setattr('lib.aio.git.get_git_upstream', fake_get_git_upstream)
    return github, tf


async def test_issue_comment_on_issue(
    issue_comment_module: ModuleType,
    event_file: Path,
    mocks: tuple[MockGitHub, MockTestingFarm],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github, tf = mocks

    event_file.write_text(json.dumps({
        'repository': {'full_name': 'cockpit-project/bots'},
        'issue': {'number': 42},
        'comment': {
            'id': 12345,
            'body': '/image-refresh foonux',
            'user': {'login': 'cockpit-project'},
        },
    }))

    monkeypatch.setattr('time.strftime', lambda _: '20260317-120000')

    with respx.mock:
        respx.route(host='api.github.com').mock(side_effect=github.handle)
        respx.route(host=TF_HOST).mock(side_effect=tf.handle)

        result = await issue_comment_module.main(['event', str(event_file)])

    assert result == 0

    # Check Testing Farm was called
    assert len(tf.requests) == 1
    tf_req = tf.requests[0]
    assert tf_req['test']['fmf']['name'] == '/job-runner'
    job = json.loads(tf_req['environments'][0]['variables']['JOB_JSON'])
    assert job['repo'] == 'cockpit-project/bots'
    assert job['sha'] == 'abc123def456'
    assert job['pull'] is None
    assert job['context'] == 'image-refresh/foonux'
    assert job['command'] == ['./image-refresh', '--verbose', '--issue=42', 'foonux']

    # Check GitHub comment was posted
    assert len(github.posts) == 1
    path, body = github.posts[0]
    assert path == '/repos/cockpit-project/bots/issues/42/comments'
    assert 'Testing Farm link:' in body['body']
    assert 'image-refresh/foonux' in body['body']


async def test_issue_comment_on_pr(
    issue_comment_module: ModuleType,
    event_file: Path,
    mocks: tuple[MockGitHub, MockTestingFarm],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github, tf = mocks

    event_file.write_text(json.dumps({
        'repository': {'full_name': 'cockpit-project/bots'},
        'issue': {
            'number': 99,
            'pull_request': {'url': 'https://api.github.com/repos/cockpit-project/bots/pulls/99'},
        },
        'comment': {
            'id': 67890,
            'body': '/image-refresh barnux',
            'user': {'login': 'cockpit-project'},
        },
    }))

    monkeypatch.setattr('time.strftime', lambda _: '20260317-120000')

    with respx.mock:
        respx.route(host='api.github.com').mock(side_effect=github.handle)
        respx.route(host=TF_HOST).mock(side_effect=tf.handle)

        result = await issue_comment_module.main(['event', str(event_file)])

    assert result == 0

    # Check Testing Farm was called with PR sha
    assert len(tf.requests) == 1
    job = json.loads(tf.requests[0]['environments'][0]['variables']['JOB_JSON'])
    assert job['sha'] == 'pr99sha12345'
    assert job['pull'] == 99
    assert job['context'] == 'image-refresh/barnux'

    # Check comment posted to the PR
    assert len(github.posts) == 1
    path, _ = github.posts[0]
    assert path == '/repos/cockpit-project/bots/issues/99/comments'


async def test_issue_comment_user_not_in_allowlist(
    issue_comment_module: ModuleType,
    event_file: Path,
    mocks: tuple[MockGitHub, MockTestingFarm],
) -> None:
    github, tf = mocks

    event_file.write_text(json.dumps({
        'repository': {'full_name': 'cockpit-project/bots'},
        'issue': {'number': 42},
        'comment': {
            'id': 12345,
            'body': '/image-refresh foonux',
            'user': {'login': 'randomuser'},
        },
    }))

    with respx.mock:
        respx.route(host='api.github.com').mock(side_effect=github.handle)
        respx.route(host=TF_HOST).mock(side_effect=tf.handle)

        result = await issue_comment_module.main(['event', str(event_file)])

    assert result == 1
    assert len(tf.requests) == 0
    assert len(github.posts) == 0


async def test_issue_comment_not_image_refresh(
    issue_comment_module: ModuleType,
    event_file: Path,
    mocks: tuple[MockGitHub, MockTestingFarm],
) -> None:
    github, tf = mocks

    event_file.write_text(json.dumps({
        'repository': {'full_name': 'cockpit-project/bots'},
        'issue': {'number': 42},
        'comment': {
            'id': 12345,
            'body': 'just a regular comment',
            'user': {'login': 'cockpit-project'},
        },
    }))

    with respx.mock:
        respx.route(host='api.github.com').mock(side_effect=github.handle)
        respx.route(host=TF_HOST).mock(side_effect=tf.handle)

        result = await issue_comment_module.main(['event', str(event_file)])

    assert result == 1
    assert len(tf.requests) == 0
    assert len(github.posts) == 0


async def test_issue_comment_empty_image(
    issue_comment_module: ModuleType,
    event_file: Path,
    mocks: tuple[MockGitHub, MockTestingFarm],
) -> None:
    github, tf = mocks

    event_file.write_text(json.dumps({
        'repository': {'full_name': 'cockpit-project/bots'},
        'issue': {'number': 42},
        'comment': {
            'id': 12345,
            'body': '/image-refresh ',
            'user': {'login': 'cockpit-project'},
        },
    }))

    with respx.mock:
        respx.route(host='api.github.com').mock(side_effect=github.handle)
        respx.route(host=TF_HOST).mock(side_effect=tf.handle)

        result = await issue_comment_module.main(['event', str(event_file)])

    assert result == 1
    assert len(tf.requests) == 0
    assert len(github.posts) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
