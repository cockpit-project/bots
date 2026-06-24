import asyncio
import os
from pathlib import Path
from test.simhub import SimHub
from typing import AsyncIterator

import pytest


@pytest.fixture
async def simhub(tmpdir_factory: pytest.TempdirFactory) -> AsyncIterator[SimHub]:
    async with SimHub(Path(tmpdir_factory.mktemp('simhub'))) as hub:
        await hub.clone('cockpit-project/bots', os.getcwd())
        yield hub


async def test_simhub(simhub: SimHub, tmp_path: Path) -> None:
    job_runner_toml = tmp_path / 'job-runner.toml'

    job_runner_toml.write_text(f'''
    [container]
    run-args = [
        "--network=host"
    ]

    [forge.github]
    api-url="{simhub.api}"
    clone-url="{simhub.api}"
    content-url="{simhub.api}"
    token=""
    ''')
    proc = await asyncio.create_subprocess_exec('./job-runner', f'-F{job_runner_toml}', '--debug', 'run', 'cockpit-project/bots')
    await proc.wait()
    print('bzzt')
