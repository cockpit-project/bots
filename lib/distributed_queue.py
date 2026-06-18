# Copyright (C) 2019-2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import ssl
from collections.abc import Collection
from pathlib import Path
from typing import Self

import pika
import pika.credentials
import pika.exceptions

logging.getLogger("pika").propagate = False

__all__ = (
    'BASELINE_PRIORITY',
    'DEFAULT_AMQP_SERVER',
    'DEFAULT_SECRETS_DIR',
    'MAX_PRIORITY',
    'DistributedQueue',
    'make_connection_params',
)

BASELINE_PRIORITY = 5
MAX_PRIORITY = 9
# see https://github.com/cockpit-project/cockpituous/blob/main/tasks/cockpit-tasks-webhook.yaml
DEFAULT_SECRETS_DIR = Path('/run/secrets/webhook')

# main deployment on CentOS CI
DEFAULT_AMQP_SERVER = 'amqp-cockpit.apps.ocp.cloud.ci.centos.org:443'
# fallback deployment on AWS
# DEFAULT_AMQP_SERVER = 'ec2-3-228-126-27.compute-1.amazonaws.com:5671'

QUEUE_ARGUMENTS = {
    'rhel': {
        "x-max-priority": MAX_PRIORITY,
    },
    'public': {
        "x-max-priority": MAX_PRIORITY,
    },
    'statistics': {
        "x-max-priority": MAX_PRIORITY,
        "x-single-active-consumer": True,
    },
}


def make_connection_params(
    amqp_server: str,
    secrets_dir: Path | None = None,
) -> pika.ConnectionParameters:
    if secrets_dir is None:
        # Try looking in the XDG_RUNTIME_DIR instead.  Nice for local hacking.
        secrets_dir = DEFAULT_SECRETS_DIR
        if runtime_dir := os.environ.get('XDG_RUNTIME_DIR'):
            local = Path(runtime_dir) / 'ci-secrets/webhook'
            if local.is_dir():
                secrets_dir = local

    if amqp_server == 'localhost':
        return pika.ConnectionParameters(
            'localhost',
            5672,
            credentials=pika.credentials.PlainCredentials('guest', 'guest'),
        )

    try:
        host, port = amqp_server.split(':')
    except ValueError as exc:
        raise ValueError('Please format amqp_server as host:port') from exc

    context = ssl.create_default_context(cafile=secrets_dir / 'ca.pem')
    context.load_cert_chain(
        keyfile=secrets_dir / 'amqp-client.key',
        certfile=secrets_dir / 'amqp-client.pem',
    )
    context.check_hostname = False
    return pika.ConnectionParameters(
        host,
        int(port),
        ssl_options=pika.SSLOptions(context, server_hostname=host),
        credentials=pika.credentials.ExternalCredentials(),
    )


class DistributedQueue:
    def __init__(
        self,
        amqp_server: str,
        queues: Collection[str],
        secrets_dir: Path | None = None,
        passive: bool = False,
    ):
        self.address = amqp_server
        self.queues = queues
        self.passive = passive
        self.params = make_connection_params(amqp_server, secrets_dir)

    def __enter__(self) -> Self:
        self.connection = pika.BlockingConnection(self.params)
        self.channel = self.connection.channel()
        self.queue_counts: dict[str, int] = {}

        for queue in self.queues:
            try:
                result = self.channel.queue_declare(
                    queue=queue,
                    durable=True,
                    passive=self.passive,
                    arguments=QUEUE_ARGUMENTS.get(queue, None),
                )
                assert result.method.message_count is not None
                self.queue_counts[queue] = result.method.message_count
            except pika.exceptions.ChannelClosedByBroker as e:
                if e.reply_code == 404 and self.passive:
                    # queue does not exist, that's ok
                    self.channel = self.connection.channel()
                    continue

                # everything else is unexpected
                raise

        return self

    def __exit__(self, *_args: object) -> None:
        self.connection.close()
