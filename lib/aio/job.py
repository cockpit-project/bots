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
import itertools
import json
import logging
import os
import platform
import sys
import tempfile
import textwrap
import traceback
from pathlib import Path
from typing import Never

from ..constants import BOTS_DIR
from .base import Forge, Subject, SubjectSpecification
from .jobcontext import JobContext
from .jsonutil import JsonObject, get_dict, get_int, get_object, get_str, get_str_map, get_strv
from .s3streamer import Index, LogStreamer
from .spawn import run, spawn
from .util import gather_and_cancel, read_utf8

logger = logging.getLogger(__name__)


class Failure(Exception):
    pass


class Job:
    def __init__(self, obj: JsonObject) -> None:
        # test subject specification
        self.subject = SubjectSpecification(obj)

        # test specification
        self.container = get_str(obj, 'container', None)
        self.command_subject = get_object(obj, 'command_subject', SubjectSpecification, None)
        self.secrets = get_strv(obj, 'secrets', ())
        self.command = get_strv(obj, 'command', None)
        self.env = get_str_map(obj, 'env', {})
        self.timeout = get_int(obj, 'timeout', 120)

        # reporting
        self.context = get_str(obj, 'context', None)
        self.slug = get_str(obj, 'slug', None)
        self.title = get_str(obj, 'title', None)
        self.report = get_dict(obj, 'report', None)


async def timeout_minutes(minutes: float) -> Never:
    await asyncio.sleep(60 * minutes)
    raise Failure(f'Timeout after {minutes} minutes')


async def poll_pr(api: Forge, repo: str, pull_nr: int, expected_sha: str) -> Never:
    while True:
        if reason := await api.check_pr_changed(repo, pull_nr, expected_sha):
            raise Failure(reason)
        await asyncio.sleep(60)


async def run_container(job: Job, subject: Subject, ctx: JobContext, log: LogStreamer) -> None:
    with tempfile.TemporaryDirectory() as tmpdir_path:
        tmpdir = Path(tmpdir_path)
        cidfile = tmpdir / 'cidfile'
        attachments = tmpdir / 'attachments'

        container_image = (
            job.container or
            await ctx.forge.read_file(subject, '.cockpit-ci/container') or
            ctx.default_image
        ).strip()

        log.write(f'Using container image: {container_image}\n')

        args = [
            *ctx.container_cmd, 'run',
            # we run arbitrary commands in that container, which aren't prepared for being pid 1; reap zombies
            '--init',
            *ctx.container_run_args,
            f'--cidfile={cidfile}',
            *(f'--env={k}={v}' for k, v in job.env.items()),
            '--env=TEST_ATTACHMENTS=/var/tmp/attachments',
            f'--env=COCKPIT_CI_LOG_URL={log.url}',
            *itertools.chain.from_iterable(args for name, args in ctx.secrets_args.items() if name in job.secrets),

            container_image,

            # we might be using podman-remote, so we can't --volume this:
            'python3', '-c', Path(f'{BOTS_DIR}/checkout-and-run').read_text(),  # lulz
            f'--revision={subject.sha}'
        ]
        if subject.rebase:
            args.append(f'--rebase={subject.rebase}')
        args.append(f'{subject.clone_url}')

        if job.command:
            args.append('--')
            args.extend(job.command)

        async with spawn(args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT) as container:
            try:
                # Log data until we hit EOF
                assert container.stdout is not None
                async for block in read_utf8(container.stdout):
                    log.write(block)
                    if ctx.debug:
                        if os.isatty(1):
                            sys.stdout.write(f'\033[34m{block}\033[0m')  # da ba dee, da ba di...
                        else:
                            sys.stdout.write(block)

                # We don't know yet if the container was ever actually created.
                # We can't rely on the exit status, since it's also non-zero if
                # the container ran successfully but the job returned non-zero.
                # We can use the existence of the cidfile, however.  By now
                # (important: after we got EOF in the loop above), if the
                # container got created, the cidfile will have also been
                # created.  If not, this was a container creation failure, which
                # is an internal error, not a Failure.  Be noisy about it.
                try:
                    cid = cidfile.read_text().strip()
                except FileNotFoundError as exc:
                    raise RuntimeError('Failed to create container') from exc

                # Upload all attachments
                # TODO: live updates
                # TODO: invent async tarfile for StreamReader
                await run([*ctx.container_cmd, 'cp', '--', f'{cid}:/var/tmp/attachments/.', f'{attachments}'])
                for file in attachments.rglob('*'):
                    with contextlib.suppress(IsADirectoryError):
                        log.index.write(str(file.relative_to(attachments)), file.read_bytes())

                if returncode := await container.wait():
                    raise Failure(f'Container exited with code {returncode}')

            finally:
                await run([*ctx.container_cmd, 'rm', '--force', '--time=0', f'--cidfile={tmpdir}/cidfile'],
                          stderr=asyncio.subprocess.STDOUT,
                          stdout=asyncio.subprocess.DEVNULL)  # don't show container ID output


async def run_job(job: Job, ctx: JobContext) -> None:
    subject = await ctx.forge.resolve_subject(job.subject)
    title = job.title or f'{job.context}@{job.subject.repo}#{subject.sha[:12]}'
    slug = job.slug or f'{job.subject.repo}/{job.context or "-"}/{subject.sha[:12]}'

    async with ctx.logs.get_destination(slug) as destination:
        index = Index(destination)
        log = LogStreamer(index)

        status = ctx.forge.get_status(job.subject.repo, subject.sha, job.context, log.url)
        logger.info('Log: %s', log.url)

        try:
            log.start(
                f'{title}\n\n'
                f'Running on: {platform.node()}\n\n'
                f'Job({json.dumps(job, default=lambda obj: obj.__dict__, indent=4)})\n\n'
            )
            await status.post('pending', 'In progress')

            if job.command_subject is not None:
                command_subject = await ctx.forge.resolve_subject(job.command_subject)
            else:
                command_subject = subject
            tasks = {run_container(job, command_subject, ctx, log)}

            if job.timeout:
                tasks.add(timeout_minutes(job.timeout))

            if job.subject.pull is not None:
                tasks.add(poll_pr(ctx.forge, job.subject.repo, job.subject.pull, subject.sha))

            await gather_and_cancel(tasks)

        except Failure as exc:
            log.write(f'\n*** Failure: {exc}\n')
            await status.post('failure', str(exc))

            if job.report is not None:
                issue = {
                    "title": f"{job.context} failed",
                    "body": textwrap.dedent(f"""
                        The job `{job.context}` failed on commit {subject.sha}.

                        Log: {log.url}
                    """).lstrip(),
                    **job.report
                }
                await ctx.forge.open_issue(job.subject.repo, issue)

        except asyncio.CancelledError:
            await status.post('error', 'Cancelled')
            log.write('*** Job cancelled\n')
            raise

        except BaseException as exc:
            # ie: bug in this program, but let's be helpful
            await status.post('error', 'Internal error')
            log.write('\n\n' + '\n'.join(traceback.format_exception(exc)) + '\n')
            raise

        else:
            await status.post('success', 'Success')
            log.write('\n\nJob ran successfully.  :)\n')

        finally:
            log.close()
            index.sync()
