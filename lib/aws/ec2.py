# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import base64
import json
import logging
import sys
import time
import urllib.request
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..aio.jsonutil import (
    JsonError,
    JsonObject,
    JsonValue,
    get_nested,
    get_str,
    typechecked,
)

if TYPE_CHECKING:
    from types_boto3_ec2 import EC2Client
    from types_boto3_ec2.literals import InstanceStateNameType, InstanceTypeType
    from types_boto3_ec2.type_defs import InstanceTypeDef, TagTypeDef

from .account import (
    RUNNER_INSTANCE_SLUG_TAG,
    RUNNER_NAME_PREFIX,
    SSH_SECURITY_GROUP,
    TAGS,
)

logger = logging.getLogger(__name__)


# listing
def describe_runner_instances(
    ec2: EC2Client, *, slug: str = "*"
) -> Sequence[InstanceTypeDef]:
    logger.debug("describing instances with slug=%r", slug)
    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(
        Filters=[{"Name": f"tag:{RUNNER_INSTANCE_SLUG_TAG}", "Values": [slug]}]
    )
    result = [
        obj
        for page in pages
        for reservation in page["Reservations"]
        for obj in reservation.get("Instances", ())
    ]
    logger.debug("found %d instances", len(result))
    return result


def get_instance_slug(instance: InstanceTypeDef) -> str:
    return next(
        t["Value"]
        for t in instance.get("Tags", ())
        if t["Key"] == RUNNER_INSTANCE_SLUG_TAG
    )


def get_instance_ip(instance: InstanceTypeDef) -> str | None:
    return instance.get("PublicIpAddress")


def get_instance_state(instance: InstanceTypeDef) -> InstanceStateNameType:
    return instance["State"]["Name"]


# launching
def _ensure_nested_virt_support(ec2: EC2Client) -> None:
    # Debian carries an old botocore whose service model doesn't include the
    # CpuOptions.NestedVirtualization parameter.  The parameter is valid on the
    # AWS side, so we patch the client's model to include it.
    # This can be removed once the dispatcher runs on a distro with a current botocore.
    shapes = ec2._service_model._shape_resolver._shape_map  # type: ignore[attr-defined]
    if "NestedVirtualization" not in shapes["CpuOptionsRequest"]["members"]:
        logger.warning("patching CpuOptionsRequest to include NestedVirtualization")
        shapes["CpuOptionsRequest"]["members"]["NestedVirtualization"] = {
            "shape": "CpuOptionsNestedVirtualization"
        }
        shapes["CpuOptionsNestedVirtualization"] = {"type": "string"}


def string_contents(content: str) -> JsonObject:
    return {"source": f"data:;base64,{base64.b64encode(content.encode()).decode()}"}


def json_contents(obj: JsonValue) -> JsonObject:
    return string_contents(json.dumps(obj))


_fcos_ami_cache: tuple[str, str] | None = None


def find_fcos_ami(region: str) -> str:
    FCOS_STREAM_URL = "https://builds.coreos.fedoraproject.org/streams/stable.json"
    global _fcos_ami_cache

    today = time.strftime("%Y-%m-%d")
    if _fcos_ami_cache is None or _fcos_ami_cache[0] != today:
        try:
            logger.debug("fetching FCOS stream metadata for region %r", region)
            with urllib.request.urlopen(FCOS_STREAM_URL) as response:
                stream = typechecked(json.loads(response.read()), dict)

            with get_nested(stream, "architectures") as architectures:
                with get_nested(architectures, "x86_64") as x86_64:
                    with get_nested(x86_64, "images") as images:
                        with get_nested(images, "aws") as aws:
                            with get_nested(aws, "regions") as regions:
                                with get_nested(regions, region) as entry:
                                    ami = get_str(entry, "image")

            logger.debug("found FCOS AMI %r for region %r", ami, region)
            _fcos_ami_cache = (today, ami)

        except (OSError, json.JSONDecodeError, JsonError):
            if _fcos_ami_cache is None:
                raise
            logger.warning("failed to fetch FCOS stream metadata, using cached AMI %r",
                           _fcos_ami_cache[1], exc_info=True)

    return _fcos_ami_cache[1]


def resolve_security_group(ec2: EC2Client, name_or_id: str) -> str:
    if name_or_id.startswith("sg-"):
        return name_or_id
    response = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [name_or_id]}],
    )
    groups = response["SecurityGroups"]
    if not groups:
        sys.exit(f"security group not found: {name_or_id!r}")
    logger.debug("resolved security group %r to %r", name_or_id, groups[0]["GroupId"])
    return groups[0]["GroupId"]


def launch_instance(
    ec2: EC2Client,
    *,
    bots_url: str,
    job: JsonObject,
    job_config: JsonObject,
    instance_type: InstanceTypeType,
    systemd_timeout_min: int,
    ami: str | None = None,
    ssh_keys: Sequence[str] = (),
) -> str:
    _ensure_nested_virt_support(ec2)

    slug = job["slug"]
    assert isinstance(slug, str)

    ignition = {
        "ignition": {"version": "3.4.0"},
        "storage": {
            "files": [
                {
                    "path": "/etc/systemd/zram-generator.conf",
                    "contents": string_contents(
                        "[zram0]\n"
                        "zram-size = ram / 2\n"
                        "compression-algorithm = zstd\n"
                    ),
                    "mode": 0o644,
                },
                {
                    "path": "/etc/cockpit-ci/bots-url",
                    "contents": string_contents(bots_url),
                    "mode": 0o644,
                },
                {
                    "path": "/etc/cockpit-ci/job-runner.json",
                    "contents": json_contents(job_config),
                    "mode": 0o644,
                },
                {
                    "path": "/etc/cockpit-ci/job.json",
                    "contents": json_contents(job),
                    "mode": 0o644,
                },
                {
                    "path": "/usr/local/bin/run-job",
                    "contents": string_contents(r"""#!/bin/bash
                        set -euxo pipefail

                        maybe_sit() {
                            # If there are ssh keys configured, let the user inspect it
                            if [ -s /home/core/.ssh/authorized_keys.d/ignition ]; then
                                sleep 10m
                            fi
                        }
                        trap maybe_sit ERR

                        # Set SELinux permissive
                        setenforce 0

                        # Block IMDS — ignition is done, nobody needs it,
                        # and the container shouldn't have access
                        iptables -A OUTPUT --destination 169.254.169.254 -j REJECT

                        # Setup containers storage on local (fast) NVMe disk
                        instance_store_device=$(
                            lsblk -dpno NAME --filter 'MODEL=~"Instance Storage"'
                        )
                        mkfs.btrfs -f "$instance_store_device"
                        mount "$instance_store_device" /var/lib/containers

                        # Download bots and unpack it (we don't need git history)
                        bots_url="$(</etc/cockpit-ci/bots-url)"
                        curl -sSLf "${bots_url}" | tar xz --strip-components=1

                        # Download uv and install it into the cwd
                        curl -sSLf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=. sh

                        # Required for 'podman run --userns=auto'
                        tee -a /etc/sub{u,g}id <<< 'containers:2147483647:2147483648'

                        # Run the job using uv to install Python and deps
                        ./uv run \
                            --no-project \
                            --python 3.14 \
                            --with-requirements requirements.txt \
                            ./job-runner \
                                -F /etc/cockpit-ci/job-runner.json \
                                json "$(cat "$1")"
                        """),
                    "mode": 0o755,
                },
            ],
        },
        "systemd": {
            "units": [
                {
                    # SSH keys come from ignition, not IMDS.  run-job
                    # blocks IMDS via iptables, causing this to fail
                    # and delay boot with retries.
                    "name": "afterburn-sshkeys@core.service",
                    "mask": True,
                },
                {
                    "name": "run-job.service",
                    "enabled": True,
                    "contents": f"""\
                            [Unit]
                            Description=Run CI job
                            Wants=network-online.target
                            After=network-online.target
                            SuccessAction=poweroff-immediate
                            FailureAction=poweroff-immediate

                            [Service]
                            Type=oneshot
                            RuntimeDirectory=run-job
                            WorkingDirectory=/run/run-job
                            ExecStart=/usr/local/bin/run-job /etc/cockpit-ci/job.json
                            TimeoutStartSec={systemd_timeout_min}min
                            StandardOutput=journal+console

                            [Install]
                            WantedBy=multi-user.target
                        """,
                },
            ],
        },
        "passwd": {
            "users": [
                {
                    "name": "core",
                    "sshAuthorizedKeys": list(ssh_keys),
                }
            ],
        },
    }

    tags: Sequence[TagTypeDef] = [
        {"Key": k, "Value": v}
        for k, v in {
            **TAGS,
            "Name": f"{RUNNER_NAME_PREFIX}{slug}",
            RUNNER_INSTANCE_SLUG_TAG: slug,
        }.items()
    ]

    response = ec2.run_instances(
        ImageId=ami or find_fcos_ami(ec2.meta.region_name),
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        UserData=json.dumps(ignition),
        InstanceInitiatedShutdownBehavior="terminate",
        MetadataOptions={
            "HttpTokens": "required",
            "HttpPutResponseHopLimit": 1,
        },
        CpuOptions={"NestedVirtualization": "enabled"},
        PrivateDnsNameOptions={
            "HostnameType": "resource-name",
            "EnableResourceNameDnsARecord": True,
        },
        TagSpecifications=[
            {"ResourceType": "instance", "Tags": tags},
            {"ResourceType": "volume", "Tags": tags},
        ],
        SecurityGroupIds=[resolve_security_group(ec2, SSH_SECURITY_GROUP)]
        if ssh_keys
        else [],
    )
    instance_id = response["Instances"][0]["InstanceId"]
    logger.info("launched %r for %r", instance_id, slug)
    return instance_id
