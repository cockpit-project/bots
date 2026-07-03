# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Desired-state definitions for cockpit CI AWS infrastructure.

Defines sync_* functions that create-or-update IAM policies, roles, users,
instance profiles, S3 buckets, EC2 resources, and SSM parameters from the
constants in account.py.  Safe to run repeatedly — existing resources are
updated in place, nothing is deleted.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path

from ..aio.jsonutil import JsonObject

from .account import (
    ACCOUNT_ID,
    CI_IMAGES_BUCKETS,
    CI_RUNNER_REGION,
    DISPATCHER_ASG,
    DISPATCHER_NAME,
    DISPATCHER_PARAMS,
    DISPATCHER_ROLE,
    IMAGE_DOWNLOAD_ROLE,
    IMAGE_UPLOAD_ROLE,
    LOGS_BUCKET,
    LOGS_REGION,
    LOGS_WRITE_ROLE,
    REDHAT_SSO_IMAGE_DOWNLOAD_MAX_SESSION,
    REDHAT_SSO_IMAGE_DOWNLOAD_ROLE,
    REDHAT_SSO_SAML_PROVIDER_ARN,
    RUNNER_INSTANCE_SLUG_TAG,
    RUNNER_NAME_PREFIX,
    SSH_SECURITY_GROUP,
    TAGS,
)
from .ensure_resource import (
    check_unmanaged,
    ensure_auto_scaling_group,
    ensure_bucket,
    ensure_instance_profile,
    ensure_launch_template,
    ensure_parameter,
    ensure_policy,
    ensure_role,
    ensure_security_group,
    ensure_user,
)


def allow(
    action: str | Sequence[str],
    resource: str | Sequence[str],
    condition: JsonObject | None = None,
) -> JsonObject:
    return {
        'Effect': 'Allow',
        'Action': action,
        'Resource': resource,
        **({'Condition': condition} if condition is not None else {}),
    }


def trust(
    action: str,
    principal: JsonObject,
    condition: JsonObject | None = None,
) -> JsonObject:
    return {
        'Effect': 'Allow',
        'Principal': principal,
        'Action': action,
        **({'Condition': condition} if condition is not None else {}),
    }


def sync_iam() -> None:
    print("\n## IAM")
    via_sts_assume_role = trust(
        "sts:AssumeRole", {"AWS": f"arn:aws:iam::{ACCOUNT_ID}:root"}
    )

    # Managed policies

    # Download any image (mostly useful for RHEL as the others are public)
    policy_images_download = ensure_policy(
        "cockpit-ci-images-download",
        [
            allow(
                "s3:GetObject",
                [f"arn:aws:s3:::{name}/*" for name in CI_IMAGES_BUCKETS],
            ),
        ],
    )

    # Upload, enumerate, and prune images
    policy_images_upload = ensure_policy(
        "cockpit-ci-images-upload",
        [
            allow(
                # image-refresh calls image-prune which needs to enumerate the bucket
                "s3:ListBucket",
                [f"arn:aws:s3:::{name}" for name in CI_IMAGES_BUCKETS],
            ),
            allow(
                [
                    "s3:PutObject",  # actually upload images
                    "s3:PutObjectAcl",  # TODO: maybe remove this?
                    "s3:DeleteObject",  # image-prune
                ],
                [f"arn:aws:s3:::{name}/*" for name in CI_IMAGES_BUCKETS],
            ),
        ],
    )

    # Write to the logs bucket
    policy_logs_write = ensure_policy(
        "cockpit-ci-logs-write",
        [
            allow(
                ["s3:PutObject", "s3:DeleteObject"],
                f"arn:aws:s3:::{LOGS_BUCKET}/*",
            ),
        ],
    )

    # Dispatch CI jobs: EC2 lifecycle, S3 logs, STS, SSM, KMS
    policy_dispatcher = ensure_policy(
        "cockpit-ci-dispatcher",
        [
            # RunInstances requires separate statements: one for
            allow(
                # Allow creating runner instances only if they are tagged
                # according to corporate policy, are named as we expect,
                # and are tagged with cockpit-ci-slug.
                "ec2:RunInstances",
                [
                    f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:instance/*",
                    f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:volume/*",
                ],
                condition={
                    "StringEquals": {
                        f"aws:RequestTag/{key}": value for key, value in TAGS.items()
                    },
                    "StringLike": {
                        "aws:RequestTag/Name": f"{RUNNER_NAME_PREFIX}*",
                        f"aws:RequestTag/{RUNNER_INSTANCE_SLUG_TAG}": "*",
                    },
                },
            ),
            allow(
                # We have two separate goals here
                "ec2:RunInstances",
                [
                    # These three are consumed
                    f"arn:aws:ec2:{CI_RUNNER_REGION}::image/*",
                    f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:security-group/*",
                    f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:subnet/*",
                    #
                    # We create this, but can't add tags to it.  See
                    # https://github.com/aws/aws-cli/issues/2865
                    f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:network-interface/*",
                ],
            ),
            allow(
                # We need to have this permission to write the tags on
                # instances and volumes.
                "ec2:CreateTags",
                [
                    f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:instance/*",
                    f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:volume/*",
                ],
                condition={
                    # But restricted to being done via our RunInstances
                    "StringEquals": {"ec2:CreateAction": "RunInstances"}
                },
            ),
            #
            # The dispatcher terminates instances that have been running too long
            allow(
                "ec2:TerminateInstances",
                f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:instance/*",
                condition={
                    "StringLike": {f"aws:ResourceTag/{RUNNER_INSTANCE_SLUG_TAG}": "*"},
                },
            ),
            #
            # Read-only information required by the dispatcher
            allow(
                [
                    "ec2:DescribeInstances",
                    "ec2:DescribeImages",
                    "ec2:DescribeSecurityGroups",
                ],
                "*",
            ),
            #
            # Used by the dispatcher for dashboard.html
            allow("s3:PutObject", f"arn:aws:s3:::{LOGS_BUCKET}/*"),
            #
            # This is how the dispatcher mints scoped tokens for the runners
            allow(
                "sts:AssumeRole",
                [
                    ensure_role(
                        IMAGE_DOWNLOAD_ROLE,
                        via_sts_assume_role,
                        managed_policies=[policy_images_download],
                        max_session_duration=timedelta(hours=6),
                    ),
                    ensure_role(
                        IMAGE_UPLOAD_ROLE,
                        via_sts_assume_role,
                        managed_policies=[policy_images_download, policy_images_upload],
                        max_session_duration=timedelta(hours=6),
                    ),
                    ensure_role(
                        LOGS_WRITE_ROLE,
                        via_sts_assume_role,
                        managed_policies=[policy_logs_write],
                        max_session_duration=timedelta(hours=6),
                    ),
                ],
            ),
            #
            # This is how the dispatcher gains access to SSM parameters
            # (amqp server address) and secrets (github-token, amqp tls
            # client certificate, etc.)  We also need to authorize kms to
            # decrypt SecureString secrets for us, but only if it's invoked
            # via SSM.
            allow(
                ["ssm:GetParameter", "ssm:GetParametersByPath"],
                f"arn:aws:ssm:{CI_RUNNER_REGION}:{ACCOUNT_ID}:parameter{DISPATCHER_PARAMS}*",
            ),
            allow(
                "kms:Decrypt",
                f"arn:aws:kms:{CI_RUNNER_REGION}:{ACCOUNT_ID}:alias/aws/ssm",
                condition={
                    "StringEquals": {
                        "kms:ViaService": f"ssm.{CI_RUNNER_REGION}.amazonaws.com",
                    },
                    "StringLike": {
                        "kms:EncryptionContext:PARAMETER_ARN":
                        #
                        f"arn:aws:ssm:{CI_RUNNER_REGION}:{ACCOUNT_ID}:parameter{DISPATCHER_PARAMS}/*",
                    },
                },
            ),
        ],
    )

    # Manual operations via infractl
    policy_infractl = ensure_policy(
        "cockpit-ci-infractl",
        [
            allow(
                [
                    "ec2:DescribeInstances",
                    "autoscaling:DescribeAutoScalingGroups",
                ],
                "*",
            ),
            allow(
                ["ec2:TerminateInstances", "ec2:GetConsoleOutput"],
                f"arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}:instance/*",
                condition={
                    "StringLike": {"aws:ResourceTag/Name": "cockpit-ci/*"},
                },
            ),
            allow(
                "autoscaling:SetDesiredCapacity",
                f"arn:aws:autoscaling:{CI_RUNNER_REGION}:{ACCOUNT_ID}:autoScalingGroup:*:autoScalingGroupName/{DISPATCHER_ASG}",
            ),
            allow(
                "ssm:PutParameter",
                [
                    f"arn:aws:ssm:{CI_RUNNER_REGION}:{ACCOUNT_ID}:parameter/cockpit-ci/dispatcher-url",
                    f"arn:aws:ssm:{CI_RUNNER_REGION}:{ACCOUNT_ID}:parameter{DISPATCHER_PARAMS}/runner-url",
                ],
            ),
        ],
    )

    # Roles
    ensure_role(
        DISPATCHER_ROLE,
        trust(
            "sts:AssumeRole", {"Service": "ec2.amazonaws.com"}
        ),  # acquire via EC2 instance profile
        managed_policies=[policy_dispatcher],
    )
    ensure_role(
        REDHAT_SSO_IMAGE_DOWNLOAD_ROLE,
        trust(  # acquire via SAML federation from RedHat SSO
            "sts:AssumeRoleWithSAML",
            {"Federated": REDHAT_SSO_SAML_PROVIDER_ARN},
            condition={
                "StringEquals": {"SAML:aud": "https://signin.aws.amazon.com/saml"},
            },
        ),
        managed_policies=[policy_images_download],
        max_session_duration=REDHAT_SSO_IMAGE_DOWNLOAD_MAX_SESSION,
    )

    # Users
    ensure_user(
        # This is a testing account.  It can do anything that the others can.
        "cockpit-ci",
        managed_policies=[
            policy_dispatcher,
            policy_images_download,
            policy_images_upload,
            policy_logs_write,
        ],
    )
    ensure_user(
        "cockpit-ci-infractl",
        managed_policies=[policy_infractl],
    )

    # Instance profiles
    ensure_instance_profile(DISPATCHER_ROLE, DISPATCHER_ROLE)


def sync_s3() -> None:
    print("\n## S3")
    # Images buckets — public read except RHEL images
    for name, region in CI_IMAGES_BUCKETS.items():
        ensure_bucket(
            name,
            region,
            block_public_policy=False,
            restrict_public_buckets=False,
            policy=[
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "NotResource": f"arn:aws:s3:::{name}/rhel*",
                }
            ],
        )

    # Logs bucket — public read on everything, expire after 90 days
    ensure_bucket(
        LOGS_BUCKET,
        LOGS_REGION,
        block_public_policy=False,
        restrict_public_buckets=False,
        policy=[
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{LOGS_BUCKET}/*",
            }
        ],
        lifecycle={
            "Rules": [
                {
                    "ID": "expire-after-90-days",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "Expiration": {"Days": 90},
                }
            ],
        },
    )


def sync_ec2() -> None:
    print("\n## EC2")
    sg_id = ensure_security_group(
        SSH_SECURITY_GROUP,
        "SSH access for cockpit CI instances",
        region=CI_RUNNER_REGION,
        ingress=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }
        ],
    )

    ssh_authorized_keys = Path(__file__).parent / "authorized_keys"
    launch_template_id = ensure_launch_template(
        "cockpit-ci-dispatcher",
        region=CI_RUNNER_REGION,
        instance_name=DISPATCHER_NAME,
        image_id="resolve:ssm:/aws/service/debian/release/trixie/latest/amd64",
        instance_type="t3.medium",
        security_group_ids=[sg_id],
        iam_instance_profile=DISPATCHER_ROLE,
        user_data="#cloud-config\n"
        + json.dumps({
            "ssh_authorized_keys": ssh_authorized_keys.read_text().splitlines(),
            "packages": [
                "git",
                "python3-boto3",
                "python3-httpx",
                "python3-pika",
                "python3-yarl",
            ],
            "write_files": [
                # {
                #     'path': '/usr/local/bin/poweroff-stale-instance',
                #     'permissions': '0755',
                #     'content': r"""#!/bin/sh
                #         awk '{exit !($1 < 86400)}' /proc/uptime || poweroff -f
                #     """,
                # },
                {
                    "path": "/usr/local/bin/dispatcher",
                    "permissions": "0755",
                    "content": r"""#!/bin/bash
                        set -euxo pipefail

                        bots_url="${1-$(
                            aws ssm get-parameter \
                                --name /cockpit-ci/dispatcher-url \
                                --query Parameter.Value --output text
                        )}"

                        mkdir "${RUNTIME_DIRECTORY}/bots"
                        cd "${RUNTIME_DIRECTORY}/bots"

                        curl -sSLf "${bots_url}" | tar xz --strip-components=1
                        exec python3 -m lib.aws.dispatcher
                    """,
                },
                {
                    "path": "/usr/local/lib/systemd/system/dispatcher.service",
                    "content": r"""
                        [Unit]
                        Description=Cockpit CI Dispatcher
                        Wants=network-online.target
                        After=network-online.target
                        # FailureAction=poweroff-immediate
                        # StartLimitAction=poweroff-immediate
                        StartLimitBurst=3
                        StartLimitIntervalSec=60

                        [Service]
                        Type=exec
                        DynamicUser=yes
                        RuntimeDirectory=dispatcher
                        WorkingDirectory=/run/dispatcher
                        ExecStart=/usr/local/bin/dispatcher
                        # ExecStopPost=+/usr/local/bin/poweroff-stale-instance
                        Restart=on-failure
                        RestartSec=30
                        RestartPreventExitStatus=5
                    """,
                },
            ],
            "runcmd": [
                ["systemctl", "daemon-reload"],
                ["systemctl", "enable", "--now", "dispatcher.service"],
            ],
        }),
    )

    ensure_auto_scaling_group(
        DISPATCHER_ASG,
        region=CI_RUNNER_REGION,
        min_size=0,
        max_size=1,
        desired_capacity=1,  # see infractl dispatcher up/down
        launch_template=launch_template_id,
    )


def update_bots_urls(cockpit_bots_url: str, *, dispatcher: bool = True, runner: bool = True) -> None:
    if dispatcher:
        ensure_parameter("/cockpit-ci/dispatcher-url", cockpit_bots_url)
    if runner:
        ensure_parameter(f"{DISPATCHER_PARAMS}/runner-url", cockpit_bots_url)


def sync_ssm(*, cockpit_bots_url: str, secrets: Mapping[str, str]) -> None:
    print("\n## SSM")
    ensure_parameter(
        f"{DISPATCHER_PARAMS}/amqp-server",
        "amqp-cockpit.apps.ocp.cloud.ci.centos.org:443",
    )
    update_bots_urls(cockpit_bots_url)
    ensure_parameter(f"{DISPATCHER_PARAMS}/max-active", "50")
    ensure_parameter(f"{DISPATCHER_PARAMS}/max-awaiting-logs", "20")
    for name, value in sorted(secrets.items()):
        ensure_parameter(
            f"{DISPATCHER_PARAMS}/{name}", value, param_type="SecureString"
        )


def sync_infra(*, cockpit_bots_url: str, secrets: Mapping[str, str]) -> set[str]:
    sync_iam()
    sync_s3()
    sync_ec2()
    sync_ssm(cockpit_bots_url=cockpit_bots_url, secrets=secrets)
    return check_unmanaged()
