# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from datetime import timedelta
from typing import TYPE_CHECKING

from ..aio.jsonutil import JsonObject, JsonValue
from ..s3 import S3Key
from .account import (
    ACCOUNT_ID,
    IMAGE_DOWNLOAD_ROLE,
    IMAGE_UPLOAD_ROLE,
    LOGS_BUCKET,
    LOGS_URL,
    LOGS_WRITE_ROLE,
)

if TYPE_CHECKING:
    from types_boto3_sts import STSClient

logger = logging.getLogger(__name__)


def assume_role(
    sts: STSClient,
    name: str,
    policy: JsonObject | None = None,
    duration: timedelta = timedelta(hours=1),
) -> S3Key:
    logger.debug("assuming role %r", name)
    if policy is not None:
        response = sts.assume_role(
            RoleArn=f"arn:aws:iam::{ACCOUNT_ID}:role/{name}",
            RoleSessionName=name,
            Policy=json.dumps(policy),
            DurationSeconds=int(duration.total_seconds()),
        )
    else:
        response = sts.assume_role(
            RoleArn=f"arn:aws:iam::{ACCOUNT_ID}:role/{name}",
            RoleSessionName=name,
            DurationSeconds=int(duration.total_seconds()),
        )
    creds = response["Credentials"]
    logger.debug("got credentials expiring %s", creds["Expiration"])
    return S3Key(creds["AccessKeyId"], creds["SecretAccessKey"], creds["SessionToken"])


def provide_secrets(
    sts: STSClient,
    secrets: Sequence[str],
    params: Mapping[str, str] = {},
    duration: timedelta = timedelta(hours=1),
) -> Iterator[tuple[str, JsonValue]]:

    logger.debug("providing secrets %r with duration %r", secrets, duration)

    if "image-upload" in secrets:
        yield (
            "image-upload",
            str(assume_role(sts, IMAGE_UPLOAD_ROLE, duration=duration)),
        )

    if "image-download" in secrets:
        yield (
            "image-download",
            str(assume_role(sts, IMAGE_DOWNLOAD_ROLE, duration=duration)),
        )

    if "github-token" in secrets:
        yield "github-token", params["github-token"]

    if "fedora-wiki" in secrets:
        yield "fedora-wiki", params["fedora-wiki"]

    if "fedora-wiki-staging" in secrets:
        yield "fedora-wiki-staging", params["fedora-wiki-staging"]


def job_runner_config(
    slug: str,
    sts: STSClient,
    *,
    secrets: Sequence[str] = (),
    params: Mapping[str, str],
    post: bool = False,
    credential_duration: timedelta,
) -> JsonObject:
    logger.debug(
        "building job-runner config for %r (credential_duration=%r)",
        slug,
        credential_duration,
    )
    return {
        "container": {
            "run-args": [
                # don't run as actual root
                # "--userns=auto",
                # TODO: need to either share the userns or netns, otherwise
                # multicast UDP won't work (which is how multiple VMs talk to
                # each other).  Let's use --network=host for now.
                # "--network=host",
                # general resource limits
                "--device=/dev/kvm",
                "--memory=56g",
                "--pids-limit=16384",
                "--shm-size=1024m",
                # /tmp on tmpfs
                "--tmpfs=/tmp:size=32g",
                "--env=TEST_OVERLAY_DIR=/tmp",
                # identity
                "--env=GIT_COMMITTER_NAME=Cockpituous",
                "--env=GIT_COMMITTER_EMAIL=cockpituous@cockpit-project.org",
                "--env=GIT_AUTHOR_NAME=Cockpituous",
                "--env=GIT_AUTHOR_EMAIL=cockpituous@cockpit-project.org",
            ],
            "secrets": {
                "github-token": [
                    "--env=COCKPIT_GITHUB_TOKEN_FILE=/run/secrets/github-token",
                    "--volume=%{github-token}:/run/secrets/github-token:ro,Z,U",
                ],
                "image-download": [
                    "--env=COCKPIT_S3_KEY_DIR=/run/secrets/s3",
                    "--volume=%{image-download}:/run/secrets/s3/amazonaws.com:ro,Z,U",
                ],
                "image-upload": [
                    "--env=COCKPIT_S3_KEY_DIR=/run/secrets/s3",
                    "--volume=%{image-upload}:/run/secrets/s3/amazonaws.com:ro,Z,U",
                ],
                "fedora-wiki": [
                    "--volume=%{fedora-wiki}:/run/secrets/fedora-wiki.json:ro,Z,U",
                    "--env=COCKPIT_FEDORA_WIKI_TOKEN=/run/secrets/fedora-wiki.json",
                ],
                "fedora-wiki-staging": [
                    "--volume=%{fedora-wiki-staging}:/run/secrets/fedora-wiki-staging.json:ro,Z,U",
                    "--env=COCKPIT_FEDORA_WIKI_STAGING_TOKEN=/run/secrets/fedora-wiki-staging.json",
                ],
            },
        },
        "forge": {
            "github": {
                "post": post,
                "token": params["github-token"],
            }
        },
        "logs": {
            "attach-journal": True,
            "driver": "s3",
            "s3": {
                "url": LOGS_URL,
                "acl": "",
                "user-agent": "job-runner (cockpit-project/bots)",
                "key": str(
                    assume_role(
                        sts,
                        LOGS_WRITE_ROLE,
                        duration=credential_duration,
                        policy={
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:PutObject", "s3:DeleteObject"],
                                    "Resource": f"arn:aws:s3:::{LOGS_BUCKET}/{slug}/*",
                                }
                            ],
                        },
                    )
                ),
            },
        },
        "secrets": {
            "inline": dict(
                provide_secrets(sts, secrets, params, duration=credential_duration)
            ),
        },
    }
