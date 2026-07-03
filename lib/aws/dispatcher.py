# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import botocore.exceptions
import httpx

from ..aio.amqp import Queue
from ..aio.jsonutil import JsonObject, get_int, get_str, get_strv
from .account import CI_RUNNER_REGION, DISPATCHER_PARAMS, LOGS_BUCKET, LOGS_URL
from .ec2 import (
    describe_runner_instances,
    get_instance_ip,
    get_instance_slug,
    get_instance_state,
    launch_instance,
)
from .jobconfig import job_runner_config

if TYPE_CHECKING:
    from types_boto3_ec2 import EC2Client
    from types_boto3_ec2.literals import InstanceStateNameType, InstanceTypeType
    from types_boto3_sts import STSClient

logger = logging.getLogger(__name__)


def load_parameters(source: str) -> dict[str, str]:
    if source.startswith("ssm:"):
        prefix = source.removeprefix("ssm:")
        ssm = boto3.client("ssm", region_name=CI_RUNNER_REGION)
        paginator = ssm.get_paginator("get_parameters_by_path")
        pages = paginator.paginate(Path=prefix, WithDecryption=True, Recursive=True)
        return {
            param["Name"].removeprefix(prefix): param["Value"]
            for page in pages
            for param in page["Parameters"]
        }

    if source.startswith("json:"):
        return json.loads(source.removeprefix("json:"))

    if source.startswith("dir:"):
        return {
            p.name: p.read_text()
            for p in sorted(Path(source.removeprefix("dir:")).iterdir())
            if p.is_file()
        }

    raise ValueError(f"unknown parameter source: {source!r}")


def prepare_and_launch(
    ec2: EC2Client,
    sts: STSClient,
    *,
    job: JsonObject,
    params: Mapping[str, str],
    bots_url: str,
    instance_type: InstanceTypeType,
    post: bool,
    ssh_keys: Sequence[str] = (),
    ami: str | None = None,
) -> str:
    slug = get_str(job, "slug")
    job_timeout_min = min(get_int(job, "timeout", 120), MAX_JOB_TIMEOUT_MIN)

    # Three layers of timeouts, each giving the previous layer headroom:
    #  - job_timeout_min: how long the job runs before job-runner kills it
    #  - systemd_timeout_min: job timeout + 15 min for setup (download, uv, etc.)
    #  - credential_duration: job timeout + 30 min so credentials outlive the unit
    # The instance hard kill (MAX_AGE_MIN) must be >= credential_duration.
    systemd_timeout_min = job_timeout_min + 15
    credential_duration = timedelta(minutes=job_timeout_min + 30)
    logger.debug(
        "preparing job %r: timeout=%r systemd=%r credentials=%r",
        slug,
        job_timeout_min,
        systemd_timeout_min,
        credential_duration,
    )

    return launch_instance(
        ec2,
        bots_url=bots_url,
        job={**job, "timeout": job_timeout_min},
        job_config=job_runner_config(
            slug,
            sts,
            secrets=get_strv(job, "secrets", ()),
            params=params,
            post=post,
            credential_duration=credential_duration,
        ),
        instance_type=instance_type,
        systemd_timeout_min=systemd_timeout_min,
        ami=ami,
        ssh_keys=ssh_keys,
    )


@dataclass
class Instance:
    instance_id: str
    slug: str
    state: "InstanceStateNameType"
    launch_time: datetime
    ip: str | None

    def to_json(self) -> JsonObject:
        return {
            "slug": self.slug,
            "state": self.state,
            "launch_time": self.launch_time.isoformat(),
            "ip": self.ip,
        }


class Job:
    def __init__(self) -> None:
        self.launched_instance: str | None = None
        self.observed_instances = set[str]()
        self.logs_visible: bool | None = None
        self.human: str | None = None

    def should_check_logs(self, instances: Mapping[str, Instance]) -> bool:
        if self.logs_visible is None:
            return True
        if self.logs_visible:
            return False
        return any(
            instances.get(iid) is not None and instances[iid].state == "running"
            for iid in self.observed_instances
        )

    def to_json(self) -> JsonObject:
        return {
            "launched_instance": self.launched_instance,
            "observed_instances": sorted(self.observed_instances),
            "logs_visible": self.logs_visible,
            "human": self.human,
        }


MAX_JOB_TIMEOUT_MIN = 120
MAX_AGE_MIN = MAX_JOB_TIMEOUT_MIN + 30


class Dispatcher:
    def __init__(
        self,
        params: Mapping[str, str],
        ssh_keys: Sequence[str] = (),
    ) -> None:
        self.params = params
        self.ssh_keys = ssh_keys
        self.instances: dict[str, Instance] = {}
        self.jobs: defaultdict[str, Job] = defaultdict(Job)
        self.logs_pending = asyncio.Event()
        self.can_take_job = asyncio.Event()

    def check_capacity(self) -> bool:
        # "Active" counts as:
        #  - any observed instance either pending or running
        #  - a job which has entered the system but hasn't been started
        #  - a job which has been started but not yet observed
        n_active = sum((
            sum(
                1
                for inst in self.instances.values()
                if inst.state in ("pending", "running")
            ),
            sum(1 for job in self.jobs.values() if not job.observed_instances),
        ))
        n_awaiting_logs = sum(
            job.should_check_logs(self.instances) for job in self.jobs.values()
        )

        max_active = int(self.params.get("max-active", "50"))
        max_awaiting_logs = int(self.params.get("max-awaiting-logs", "20"))
        capacity = min(max_active - n_active, max_awaiting_logs - n_awaiting_logs)
        if capacity > 0:
            self.can_take_job.set()
        return capacity > 0

    async def ensure_job_running(
        self, message: JsonObject, ec2: EC2Client, sts: STSClient
    ) -> None:
        job_json = message["job"]
        assert isinstance(job_json, dict)
        slug = job_json["slug"]
        assert isinstance(slug, str)
        job = self.jobs[slug]
        job.human = get_str(message, "human", None)
        loop = asyncio.get_running_loop()

        backoff = 15.0
        while not job.launched_instance and not job.observed_instances:
            try:
                job.launched_instance = await loop.run_in_executor(
                    None,
                    lambda: prepare_and_launch(
                        ec2,
                        sts,
                        job=job_json,
                        params=self.params,
                        bots_url=self.params["runner-url"],
                        instance_type="m8id.4xlarge",
                        post=True,
                        ssh_keys=self.ssh_keys,
                    ),
                )
                self.logs_pending.set()

            except botocore.exceptions.ClientError as e:
                code = e.response["Error"]["Code"]
                if code not in (
                    "InsufficientInstanceCapacity",
                    "RequestLimitExceeded",
                    "ServiceUnavailable",
                ):
                    raise
                logger.warning(
                    "launch failed for %r: %s, backing off %rs", slug, code, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    async def ec2_launcher(self) -> None:
        ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
        sts = boto3.client("sts", region_name=CI_RUNNER_REGION)

        async with Queue(self.params, queues=["public"], consumer_priority=10) as queue:
            while await self.can_take_job.wait():
                delivery_tag, body = await queue.next_message()

                message = json.loads(body)
                logger.info("got job %r", message.get("job", {}).get("slug"))
                await self.ensure_job_running(message, ec2, sts)

                if not self.check_capacity():
                    self.can_take_job.clear()
                    queue.stop_deliveries()

                queue.ack(delivery_tag)

    async def s3_observer(self) -> None:
        http = httpx.AsyncClient()

        while await self.logs_pending.wait():
            unchecked = [
                (s, j)
                for s, j in self.jobs.items()
                if j.should_check_logs(self.instances)
            ]
            if not unchecked:
                self.logs_pending.clear()
                continue

            for slug, job in unchecked:
                try:
                    resp = await http.head(f"{LOGS_URL}{slug}/log.html", timeout=5.0)
                    job.logs_visible = resp.is_success
                    if resp.is_success:
                        logger.info("logs visible for %r", slug)
                except httpx.HTTPError:
                    job.logs_visible = False

            self.check_capacity()

            await asyncio.sleep(10)

    async def scan_instances(self, ec2: "EC2Client") -> None:
        loop = asyncio.get_running_loop()

        all_instances = await loop.run_in_executor(None, describe_runner_instances, ec2)

        self.instances = {
            obj["InstanceId"]: Instance(
                instance_id=obj["InstanceId"],
                slug=get_instance_slug(obj),
                state=get_instance_state(obj),
                launch_time=obj["LaunchTime"].astimezone(timezone.utc),
                ip=get_instance_ip(obj),
            )
            for obj in all_instances
        }

        now = datetime.now(timezone.utc)

        for inst in self.instances.values():
            job = self.jobs[inst.slug]
            job.observed_instances.add(inst.instance_id)
            if job.should_check_logs(self.instances):
                self.logs_pending.set()

        overdue = [
            inst.instance_id
            for inst in self.instances.values()
            if inst.state in ("pending", "running")
            and (now - inst.launch_time).total_seconds() > MAX_AGE_MIN * 60
        ]
        if overdue:
            logger.warning("terminating overdue instances: %r", overdue)
            await loop.run_in_executor(
                None,
                lambda: ec2.terminate_instances(InstanceIds=overdue),
            )

        for slug in [
            s
            for s, j in self.jobs.items()
            if j.observed_instances and not j.observed_instances & self.instances.keys()
        ]:
            logger.info("pruning job %r", slug)
            del self.jobs[slug]

    async def ec2_observer(self) -> None:
        ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)

        while True:
            await self.scan_instances(ec2)

            self.check_capacity()

            await asyncio.sleep(5)

    def to_json(self) -> JsonObject:
        return {
            "instances": {iid: inst.to_json() for iid, inst in self.instances.items()},
            "jobs": {slug: job.to_json() for slug, job in self.jobs.items()},
        }


async def main() -> None:
    parser = argparse.ArgumentParser(description="EC2 CI job dispatcher")
    # fmt: off
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=3)
    parser.add_argument("--parameters", default=f"ssm:{DISPATCHER_PARAMS}/",
        help="Parameter source: ssm:PREFIX, json:DATA, or dir:PATH")
    parser.add_argument("--ssh-key", type=Path,
        help="SSH public key file to authorize for the core user")
    parser.add_argument("--param", action="append", default=[],
        help="Override a parameter: --param key=value")
    # fmt: on
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    loop = asyncio.get_running_loop()
    s3 = boto3.client("s3", region_name=CI_RUNNER_REGION)

    def _upload_logs(key: str, body: str, mimetype: str) -> None:
        logger.info("uploading %s/%s (%s)", LOGS_BUCKET, key, mimetype)
        s3.put_object(Bucket=LOGS_BUCKET, Key=key, Body=body, ContentType=mimetype)

    dashboard = Path(__file__).parent / "dashboard.html"
    await loop.run_in_executor(
        None, _upload_logs, dashboard.name, dashboard.read_text(), "text/html"
    )

    params = load_parameters(args.parameters)
    for override in args.param:
        key, _, value = override.partition("=")
        logger.debug("overriding parameter %r=%r", key, value)
        params[key] = value

    ssh_keys = args.ssh_key.read_text().strip().splitlines() if args.ssh_key else ()
    dispatcher = Dispatcher(params=params, ssh_keys=ssh_keys)

    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    await dispatcher.scan_instances(ec2)
    logger.info("initial scan: %d instances", len(dispatcher.instances))

    # The dispatcher does four things pretty much all the time:
    #  - querying status of existing runners (the `ec2_observer` task)
    #  - listening for jobs to arrive from the queue and spawning EC2 instances
    #    (the `ec2_launcher` task)
    #  - querying S3 to see what logs are available (`s3_observer` task)
    #  - periodically updating the summary.json, from the main task
    #
    # The EC2 and S3 observers both influence how many "free slots" the
    # dispatcher has for accepting new jobs.  See `.check_capacity()`.
    async with asyncio.TaskGroup() as tg:
        tg.create_task(dispatcher.ec2_launcher())
        tg.create_task(dispatcher.ec2_observer())
        tg.create_task(dispatcher.s3_observer())

        prev_summary = ""
        while True:
            summary = json.dumps(dispatcher.to_json(), default=str, indent=4)
            if summary != prev_summary:
                await loop.run_in_executor(
                    None, _upload_logs, "summary.json", summary, "application/json"
                )
                prev_summary = summary

            await asyncio.sleep(args.poll_interval)


if __name__ == "__main__":
    asyncio.run(main())
