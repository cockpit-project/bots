# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import json
import logging
import sys
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from .aio.jsonutil import JsonObject
from .s3 import S3Key

if TYPE_CHECKING:
    from boto3.ec2 import EC2Client
    from boto3.sts import STSClient

logger = logging.getLogger(__name__)

ACCOUNT_ID = '727920394381'
DOWNLOAD_ROLE = f'arn:aws:iam::{ACCOUNT_ID}:role/{ACCOUNT_ID}-cockpit-ci-images-download'
LOGS_ROLE = f'arn:aws:iam::{ACCOUNT_ID}:role/cockpit-logs-write'
LOGS_BUCKET = 'cockpit-ci-logs'
LOGS_URL = f'https://{LOGS_BUCKET}.s3.us-east-1.amazonaws.com/'

FCOS_AWS_OWNER = '125523088429'
SECURITY_GROUP = 'cockpit-ci-ssh'
REGION = 'us-east-1'

TAGS: Mapping[str, str] = {
    'app-code': 'ARR-001',
    'cost-center': '700',
    'service-owner': 'cockpit',
    'service-phase': 'prod',
}


def assume_role(sts: STSClient, role_arn: str, policy: JsonObject | None = None) -> S3Key:
    session_name = role_arn.rsplit('/', 1)[-1]
    logger.debug('assuming role %r as %r', role_arn, session_name)
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
        **({'Policy': json.dumps(policy)} if policy is not None else {}),
    )
    creds = response['Credentials']
    logger.debug('got credentials expiring %s', creds['Expiration'])
    return S3Key(creds['AccessKeyId'], creds['SecretAccessKey'], creds['SessionToken'])


def string_contents(content: str) -> dict[str, str]:
    return {'source': f'data:;base64,{base64.b64encode(content.encode()).decode()}'}


def json_contents(obj: object) -> dict[str, str]:
    return string_contents(json.dumps(obj))


_fcos_ami_cache: tuple[str, str] | None = None


def find_fcos_ami(ec2: EC2Client) -> str:
    global _fcos_ami_cache
    today = time.strftime('%Y-%m-%d')
    if _fcos_ami_cache is not None and _fcos_ami_cache[0] == today:
        logger.debug('using cached FCOS AMI %s', _fcos_ami_cache[1])
        return _fcos_ami_cache[1]
    logger.debug('looking up latest FCOS AMI')
    response = ec2.describe_images(
        Owners=[FCOS_AWS_OWNER],
        Filters=[
            {'Name': 'name', 'Values': ['fedora-coreos-*']},
            {'Name': 'architecture', 'Values': ['x86_64']},
            {'Name': 'state', 'Values': ['available']},
        ],
    )
    images = sorted(response['Images'], key=lambda i: i['CreationDate'], reverse=True)
    if not images:
        sys.exit('no FCOS AMI found')
    logger.debug('found FCOS AMI %s (%s)', images[0]['ImageId'], images[0]['Name'])
    _fcos_ami_cache = (today, images[0]['ImageId'])
    return _fcos_ami_cache[1]


def resolve_security_group(ec2: EC2Client, name_or_id: str) -> str:
    if name_or_id.startswith('sg-'):
        return name_or_id
    response = ec2.describe_security_groups(
        Filters=[{'Name': 'group-name', 'Values': [name_or_id]}],
    )
    groups = response['SecurityGroups']
    if not groups:
        sys.exit(f'security group not found: {name_or_id!r}')
    logger.debug('resolved security group %r to %r', name_or_id, groups[0]['GroupId'])
    return groups[0]['GroupId']


def launch_instance(
    ec2: EC2Client,
    sts: STSClient,
    job: JsonObject,
    instance_type: str,
    timeout_min: int,
    *,
    ami: str | None = None,
    ssh_keys: Sequence[str] = (),
) -> str:
    slug = job['slug']
    assert isinstance(slug, str)

    ignition = {
        'ignition': {'version': '3.4.0'},
        'storage': {
            'files': [
                {
                    'path': '/etc/cockpit-ci/job-runner.json',
                    'contents': json_contents({
                        'logs': {
                            'driver': 's3',
                            's3': {
                                'url': LOGS_URL,
                                'key': assume_role(
                                    sts,
                                    LOGS_ROLE,
                                    policy={
                                        'Version': '2012-10-17',
                                        'Statement': [
                                            {
                                                'Effect': 'Allow',
                                                'Action': ['s3:PutObject', 's3:DeleteObject'],
                                                'Resource': f'arn:aws:s3:::{LOGS_BUCKET}/{slug}/*',
                                            }
                                        ],
                                    },
                                )._asdict(),
                                'acl': '',
                                'user-agent': 'job-runner (cockpit-project/bots)',
                            },
                        },
                        'container': {
                            'run-args': [
                                '--device=/dev/kvm',
                                '--userns=auto',
                                '--volume=/etc/cockpit-ci/s3-keys:/run/secrets/s3-keys:ro,z,U',
                                '--env=COCKPIT_S3_KEY_DIR=/run/secrets/s3-keys',
                            ],
                        },
                        'forge': {
                            'github': {
                                'post': False,
                            },
                        },
                    }),
                    'mode': 0o644,
                },
                {
                    'path': '/etc/cockpit-ci/s3-keys/amazonaws.com',
                    'contents': string_contents(str(assume_role(sts, DOWNLOAD_ROLE))),
                    'mode': 0o600,
                },
                {
                    'path': '/etc/cockpit-ci/job.json',
                    'contents': json_contents(job),
                    'mode': 0o644,
                },
                {
                    'path': '/etc/subuid',
                    'contents': string_contents('containers:2147483647:2147483648\n'),
                    'overwrite': True,
                    'mode': 0o644,
                },
                {
                    'path': '/etc/subgid',
                    'contents': string_contents('containers:2147483647:2147483648\n'),
                    'overwrite': True,
                    'mode': 0o644,
                },
                {
                    'path': '/usr/local/bin/run-job',
                    'contents': string_contents(r'''#!/bin/bash
                        set -euxo pipefail

                        maybe_sit() {
                            # If there are ssh keys configured, let the user to inspect it
                            if [ -s /home/core/.ssh/authorized_keys.d/ignition ]; then
                                sleep 10m
                            fi
                        }
                        trap maybe_sit ERR

                        instance_store_device=$(
                            lsblk -dpno NAME --filter 'MODEL=="Amazon EC2 NVMe Instance Storage"'
                        )
                        mkfs.btrfs -f "$instance_store_device"
                        mount "$instance_store_device" /var/lib/containers

                        # Download bots and unpack it (we don't need git history)
                        curl --silent --show-error --location --fail \
                            https://github.com/cockpit-project/bots/archive/main.tar.gz | \
                            tar xz --strip-components=1

                        # Download uv and install it into the cwd
                        curl --silent --show-error --location --fail \
                            https://astral.sh/uv/install.sh | \
                            UV_INSTALL_DIR=. sh

                        # Run the job using uv to install Python and deps
                        ./uv run \
                            --no-project \
                            --python 3.14 \
                            --with-requirements requirements.txt \
                            ./job-runner \
                                -F /etc/cockpit-ci/job-runner.json \
                                json "$(cat "$1")"
                        '''),
                    'mode': 0o755,
                },
            ],
        },
        'systemd': {
            'units': [
                {
                    'name': 'run-job.service',
                    'enabled': True,
                    'contents': f'''\
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
                            TimeoutStartSec={timeout_min}min
                            StandardOutput=journal+console

                            [Install]
                            WantedBy=multi-user.target
                        ''',
                },
            ],
        },
        'passwd': {
            'users': [
                {
                    'name': 'core',
                    'sshAuthorizedKeys': list(ssh_keys),
                }
            ],
        },
    }

    response = ec2.run_instances(
        ImageId=ami or find_fcos_ami(ec2),
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        UserData=json.dumps(ignition),
        InstanceInitiatedShutdownBehavior='terminate',
        CpuOptions={'NestedVirtualization': 'enabled'},
        TagSpecifications=[
            {
                'ResourceType': rt,
                'Tags': [{'Key': k, 'Value': v} for k, v in {
                        **TAGS, 'Name': f'cockpit-ci/{slug}', 'cockpit-ci-slug': slug,
                    }.items()],
            }
            for rt in ('instance', 'volume')
        ],
        **({'SecurityGroupIds': [resolve_security_group(ec2, SECURITY_GROUP)]} if ssh_keys else {}),
    )
    instance_id = response['Instances'][0]['InstanceId']
    logger.info('launched %r for %r', instance_id, slug)
    return instance_id
