# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.1-or-later

"""Testing Farm API client for remote job execution."""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from lib.aio.jobcontext import JobContext
from lib.aio.jsonutil import JsonObject
from lib.directories import xdg_config_home

# Testing Farm API endpoint
TF_API_URL = 'https://api.dev.testing-farm.io/v0.1'


def get_git_upstream() -> tuple[str, str]:
    """Get git URL and ref from upstream tracking branch.

    Returns:
        Tuple of (url, ref) from @{u}
    """
    # Get upstream in form "remote/branch"
    upstream = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', '@{u}'], capture_output=True, text=True, check=True
    ).stdout.strip()

    remote, _, branch = upstream.partition('/')
    url = subprocess.run(
        ['git', 'remote', 'get-url', remote], capture_output=True, text=True, check=True
    ).stdout.strip()

    return url, branch


def get_request(request_id: str) -> JsonObject | None:
    """Fetch request status from Testing Farm API. Returns None on 404."""
    url = f'{TF_API_URL}/requests/{request_id}'
    print(f'GET {url}')
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as response:
            result = json.load(response)
        print(f'  state={result.get("state")} run={result.get("run")}')
        return result
    except urllib.error.HTTPError as e:
        print(f'  HTTP {e.code}')
        if e.code == 404:
            return None
        raise


def wait_for_artifacts(request_id: str, timeout: float = 300) -> str | None:
    """Poll until run.artifacts is available.

    Returns the artifacts URL, or None if timeout reached or job failed.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = get_request(request_id)
        if req is not None:
            state = req.get('state')
            if state == 'error':
                return None
            if run := req.get('run'):
                if artifacts := run.get('artifacts'):
                    return artifacts
        time.sleep(0.5)
    return None


def submit_to_testing_farm(
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
        git_url_ref = get_git_upstream()

    git_url, git_ref = git_url_ref
    config_json = json.dumps(ctx.serialize())
    job_json = json.dumps(job)

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
        'settings': {'pipeline': {'timeout': 120}},
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
    with urllib.request.urlopen(req) as response:
        result = json.load(response)

    return result['id']
