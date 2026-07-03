# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import botocore.exceptions

from ..aio.jsonutil import typechecked
from .account import CI_RUNNER_REGION, DISPATCHER_PARAMS
from .dispatcher import load_parameters, prepare_and_launch
from .ec2 import get_instance_ip

if TYPE_CHECKING:
    from types_boto3_ec2 import EC2Client
    from types_boto3_ec2.literals import InstanceStateNameType
    from types_boto3_ec2.type_defs import InstanceTypeDef as Instance

logger = logging.getLogger(__name__)


def watch_instance(
    ec2: EC2Client,
    instance_id: str,
    *,
    start: float = 0,
    wait_for_state: InstanceStateNameType = "terminated",
) -> Instance:
    prev_state: InstanceStateNameType | None = None
    while True:
        try:
            response = ec2.describe_instances(InstanceIds=[instance_id])
            info = response["Reservations"][0]["Instances"][0]
            state = info["State"]["Name"]
        except botocore.exceptions.ClientError as exc:
            # https://docs.aws.amazon.com/ec2/latest/devguide/eventual-consistency.html
            if exc.response["Error"]["Code"] != "InvalidInstanceID.NotFound":
                raise
            if time.clock_gettime(time.CLOCK_BOOTTIME) - start < 30:
                time.sleep(2.5)
                continue

            sys.exit(f"instance {instance_id} not found after 30s")

        if state in ("terminated", "stopped") and wait_for_state != state:
            sys.exit(
                f"instance {instance_id} reached {state} waiting for {wait_for_state}"
            )

        if info and state != prev_state:
            parts: list[str] = [state]
            if ip := get_instance_ip(info):
                parts.append(f"public={ip}")
            if private_ip := info.get("PrivateIpAddress"):
                parts.append(f"private={private_ip}")
            print(" ".join(parts))
            prev_state = state

        if info and state == wait_for_state:
            return info

        time.sleep(2.5)


def wait_for_ssh(info: Instance) -> str:
    dns = info.get("PublicDnsName", "")
    while True:
        try:
            with socket.create_connection((dns, 22), timeout=1):
                return dns
        except OSError:
            time.sleep(1)


def terminate_and_wait(ec2: EC2Client, instance_id: str) -> None:
    ec2.terminate_instances(InstanceIds=[instance_id])
    watch_instance(ec2, instance_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    # fmt: off
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--ami", help="FCOS AMI ID (default: latest)")
    parser.add_argument("--bots-url", help="Bots download URL",
        default="https://github.com/cockpit-project/bots/archive/ec3-thingy.tar.gz")
    parser.add_argument("--instance-type", default="m8id.4xlarge")
    parser.add_argument("--ssh-key", type=Path,
        help="Additional SSH public key file to authorize for the core user")
    parser.add_argument("--parameters", default=f"ssm:{DISPATCHER_PARAMS}/",
        help="Parameter source: ssm:PREFIX, json:DATA, or dir:PATH")
    parser.add_argument("job_json", nargs="?",
        help="Job specification as JSON string (default: shell)")
    # fmt: on
    args = parser.parse_args()

    if args.job_json is None:
        args.job_json = json.dumps({
            "slug": "shell",
            "repo": "cockpit-project/bots",
            "command": ["/usr/bin/sleep", "1h", "50m"],
        })

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    ssh_keys: list[str] = []
    if args.ssh_key:
        ssh_key_text = args.ssh_key.read_text()
        if "PRIVATE KEY" in ssh_key_text:
            sys.exit("No.")
        ssh_keys.extend(ssh_key_text.strip().splitlines())

    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    sts = boto3.client("sts", region_name=CI_RUNNER_REGION)

    params = load_parameters(args.parameters)

    job = typechecked(json.loads(args.job_json), dict)

    with contextlib.ExitStack() as stack:
        key_dir = stack.enter_context(tempfile.TemporaryDirectory())
        key_path = f"{key_dir}/id"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key_path],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        ssh_keys.append(Path(f"{key_path}.pub").read_text().strip())

        instance_id = prepare_and_launch(
            ec2,
            sts,
            job=job,
            params=params,
            bots_url=args.bots_url,
            instance_type=args.instance_type,
            post=False,
            ami=args.ami,
            ssh_keys=ssh_keys,
        )
        print(f"launched {instance_id}")
        stack.callback(terminate_and_wait, ec2, instance_id)

        info = watch_instance(
            ec2,
            instance_id,
            start=time.clock_gettime(time.CLOCK_BOOTTIME),
            wait_for_state="running",
        )
        print("waiting for ssh...")
        dns = wait_for_ssh(info)
        ssh_cmd = [
            "ssh",
            "-Fnone",
            "-oKnownHostsCommand=/bin/echo %H %t %K",
            f"-i{key_path}",
            f"core@{dns}",
        ]
        print(f"\nInstance is online and accessible via ssh:\n  {shlex.join(ssh_cmd)}\n")
        subprocess.run(ssh_cmd)


if __name__ == "__main__":
    main()
