# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Testing Farm API client for remote job execution."""

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Self

import httpx

from lib.aio import git
from lib.aio.jobcontext import JobContext
from lib.aio.jsonutil import JsonObject, get_dict, get_str, typechecked
from lib.directories import xdg_config_home

logger = logging.getLogger(__name__)

# Testing Farm API endpoint
TF_API_URL = 'https://api.dev.testing-farm.io/v0.1'


class TestingFarmClient(contextlib.AsyncExitStack):
    client: httpx.AsyncClient | None = None

    def __init__(self, *, api_url: str = TF_API_URL, api_key: str | None = None) -> None:
        """Create a client for communication with the Testing Farm API.

        Args (optional):
            api_url: the base URL of the API
            api_key: the API key, if we have it (or use `TESTING_FARM_API_TOKEN`
                     or `~/.config/cockpit-dev/testing-farm-token` otherwise.
        """
        super().__init__()
        if api_key is None:
            api_key = (
                os.environ.get('TESTING_FARM_API_TOKEN')
                or Path(xdg_config_home("cockpit-dev/testing-farm-token")).read_text().strip()
            )
        self.api_url = api_url
        self.api_key = api_key

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.client = await self.enter_async_context(httpx.AsyncClient())
        logger.debug("TestingFarmClient initialized with api_url=%r", self.api_url)
        return self

    def get_request_url(self, request_id: str) -> str:
        return f'{self.api_url}/requests/{request_id}'

    async def get_request(self, request_id: str) -> JsonObject | None:
        """Fetch request status from Testing Farm API. Returns None on 404."""
        assert self.client is not None

        url = self.get_request_url(request_id)
        logger.debug("GET %r", url)
        response = await self.client.get(url)
        logger.debug("GET %r → %r", url, response.status_code)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        result = typechecked(response.json(), dict)
        logger.debug("GET %r → state=%r", url, result.get('state'))
        return result

    async def wait_for_artifacts(self, request_id: str, timeout: float = 30) -> str | None:
        """Poll until run.artifacts is available.

        Returns the artifacts URL, or None if timeout reached or job failed.
        See https://issues.redhat.com/browse/TFT-4379
        """
        logger.debug("wait_for_artifacts: polling request_id=%r timeout=%r", request_id, timeout)

        async def poll() -> str | None:
            delay = 0.5
            while True:
                req = await self.get_request(request_id)
                if req is not None:
                    if run := get_dict(req, 'run', None):
                        if artifacts := get_str(run, 'artifacts', None):
                            logger.debug("wait_for_artifacts: got artifacts=%r", artifacts)
                            return artifacts
                    state = get_str(req, 'state', None)
                    if state not in ('new', 'queued', 'running'):
                        logger.debug("wait_for_artifacts: terminal state=%r, no artifacts", state)
                        return None
                logger.debug("wait_for_artifacts: sleeping %r seconds", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

        try:
            return await asyncio.wait_for(poll(), timeout=timeout)
        except TimeoutError:
            logger.debug("wait_for_artifacts: timed out after %r seconds", timeout)
            return None

    async def submit_job(
        self,
        ctx: JobContext,
        job: JsonObject,
        *,
        git_url_ref: tuple[str, str] | None = None,
        compose: str = 'Fedora-Rawhide',
    ) -> str:
        """Submit a job to Testing Farm for remote execution.

        Args:
            ctx: JobContext with configuration (will be serialized)
            job: Job specification as JSON object
            git_url_ref: Git repository URL and ref (default: from @{upstream})
            compose: Fedora compose to use (default: Fedora-Rawhide)

        Returns:
            Testing Farm request ID
        """
        assert self.client is not None

        if git_url_ref is None:
            git_url_ref = await git.get_git_upstream()

        git_url, git_ref = git_url_ref
        logger.debug("submit_job: git_url=%r git_ref=%r", git_url, git_ref)
        logger.debug("submit_job: job=%r", job)

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

        url = f'{self.api_url}/requests'
        logger.debug("POST %r", url)
        response = await self.client.post(
            url,
            json=request,
            headers={'Authorization': f'Bearer {self.api_key}'},
        )
        logger.debug("POST %r → %r", url, response.status_code)
        response.raise_for_status()
        request_id = get_str(typechecked(response.json(), dict), 'id')
        logger.debug("submit_job: request_id=%r", request_id)
        return request_id
