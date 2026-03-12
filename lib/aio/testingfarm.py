# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.1-or-later

"""Testing Farm API client for remote job execution."""

import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from lib.aio.git import get_git_upstream
from lib.aio.jobcontext import JobContext
from lib.aio.jsonutil import JsonObject, get_dict, get_str, typechecked
from lib.directories import xdg_config_home

# Testing Farm API endpoint
TF_API_URL = 'https://api.dev.testing-farm.io/v0.1'


def get_request_url(request_id: str) -> str:
    return f'{TF_API_URL}/requests/{request_id}'


async def fetch_json(req: urllib.request.Request) -> JsonObject:
    def _do() -> JsonObject:
        with urllib.request.urlopen(req) as response:
            return typechecked(json.load(response), dict)

    return await asyncio.to_thread(_do)


async def get_request(request_id: str) -> JsonObject | None:
    """Fetch request status from Testing Farm API. Returns None on 404."""
    req = urllib.request.Request(get_request_url(request_id))
    try:
        result = await fetch_json(req)
        return result
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


async def wait_for_artifacts(request_id: str, timeout: float = 30) -> str | None:
    """Poll until run.artifacts is available.

    Returns the artifacts URL, or None if timeout reached or job failed.
    """

    async def poll() -> str | None:
        delay = 0.5
        while True:
            req = await get_request(request_id)
            if req is not None:
                if run := get_dict(req, 'run', None):
                    if artifacts := get_str(run, 'artifacts', None):
                        return artifacts
                if get_str(req, 'state', None) not in ('new', 'queued', 'running'):
                    return None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    try:
        return await asyncio.wait_for(poll(), timeout=timeout)
    except TimeoutError:
        return None


async def submit_to_testing_farm(
    ctx: JobContext,
    job: JsonObject,
    *,
    api_key: str | None = None,
    git_url_ref: tuple[str, str] | None = None,
    compose: str = 'Fedora-Rawhide',
) -> str:
    """Submit a job to Testing Farm for remote execution.

    Args:
        ctx: JobContext with configuration (will be serialized)
        job: Job specification as JSON object
        api_key: Testing Farm API key (default: from env/file)
        git_url_ref: Git repository URL and ref (default: from @{upstream})
        compose: Fedora compose to use (default: Fedora-Rawhide)

    Returns:
        Testing Farm request ID
    """
    if api_key is None:
        api_key = (
            os.environ.get('TESTING_FARM_API_TOKEN')
            or Path(xdg_config_home("cockpit-dev/testing-farm-token")).read_text().strip()
        )

    if git_url_ref is None:
        git_url_ref = await get_git_upstream()

    git_url, git_ref = git_url_ref
    config_json = json.dumps(ctx.serialize())
    job_json = json.dumps(job)

    # https://api.dev.testing-farm.io/docs#operation/request_a_new_test_v0_1_requests_post
    request = {
        'test': {
            'fmf': {
                'url': git_url,
                'ref': git_ref,
                'name': '/job-runner',
            }
        },
        'environments': [
            {
                'arch': 'x86_64',
                'os': {'compose': compose},
                'variables': {
                    'JOB_JSON': job_json,
                },
                'secrets': {
                    'JOB_RUNNER_CONFIG_JSON': config_json,
                },
                'hardware': {
                    'virtualization': {
                        'is-virtualized': True,
                        'is-supported': True,
                    }
                },
            }
        ],
        'settings': {
            'pipeline': {
                'timeout': 120,
            }
        },
    }

    req = urllib.request.Request(
        f'{TF_API_URL}/requests',
        data=json.dumps(request).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    result = await fetch_json(req)

    return get_str(result, 'id')
