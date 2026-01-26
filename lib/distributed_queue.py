# This file is part of Cockpit.
#
# Copyright (C) 2019 Red Hat, Inc.
#
# Cockpit is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# Cockpit is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Cockpit; If not, see <http://www.gnu.org/licenses/>.

# Shared GitHub code. When run as a script, we print out info about
# our GitHub interacition.

import logging
import os
import ssl
from collections.abc import Collection
from types import TracebackType
from typing import Any, Self

import pika
import pika.exceptions

logging.getLogger("pika").propagate = False

__all__ = (
    'BASELINE_PRIORITY',
    'DEFAULT_AMQP_SERVER',
    'DEFAULT_SECRETS_DIR',
    'MAX_PRIORITY',
    'DistributedQueue',
)

BASELINE_PRIORITY = 5
MAX_PRIORITY = 9
# see https://github.com/cockpit-project/cockpituous/blob/main/tasks/cockpit-tasks-webhook.yaml
DEFAULT_SECRETS_DIR = '/run/secrets/webhook'
# main deployment on CentOS CI
DEFAULT_AMQP_SERVER = 'amqp-cockpit.apps.ocp.cloud.ci.centos.org:443'
# fallback deployment on AWS
# DEFAULT_AMQP_SERVER = 'ec2-3-228-126-27.compute-1.amazonaws.com:5671'

arguments = {
    'rhel': {
        "x-max-priority": MAX_PRIORITY
    },
    'public': {
        "x-max-priority": MAX_PRIORITY
    },
    'statistics': {
        "x-max-priority": MAX_PRIORITY,
        "x-single-active-consumer": True,
    },
}


class DistributedQueue:
    def __init__(
        self, amqp_server: str, queues: Collection[str], secrets_dir: str = DEFAULT_SECRETS_DIR, **kwargs: Any
    ):
        """connect to some AMQP queues

        amqp_server should be formatted as host:port

        queues should be a list of strings with the names of queues, each queue
        will be declared. Any extra arguments in **kwargs will be passed to queue_declare().
        In particular, with passive=True queues which don't already exist will not be created.

        secrets_dir can be passed for enviroments where the AMQP secrets are not
        in DEFAULT_SECRETS_DIR.

        After queue declarations, their current lengths are stored in self.queue_counts,
        a dict mapping all existing queue names to the number of queue entries. Non-existing
        queues are not included in the dict.
        """

        # Try looking in the XDG_RUNTIME_DIR instead.  Nice for local hacking.
        if not os.path.isdir(secrets_dir) and secrets_dir.startswith('/run'):
            if runtime_dir := os.environ.get('XDG_RUNTIME_DIR'):
                user_secrets = secrets_dir.replace('/run', runtime_dir)
                if os.path.isdir(user_secrets):
                    secrets_dir = user_secrets

        if amqp_server == 'localhost':
            params = pika.ConnectionParameters(
                'localhost', 5672, credentials=pika.credentials.PlainCredentials('guest', 'guest')
            )
        else:
            try:
                host, port = amqp_server.split(':')
            except ValueError as exc:
                raise ValueError('Please format amqp_server as host:port') from exc

            context = ssl.create_default_context(cafile=os.path.join(secrets_dir, 'ca.pem'))
            context.load_cert_chain(keyfile=os.path.join(secrets_dir, 'amqp-client.key'),
                                    certfile=os.path.join(secrets_dir, 'amqp-client.pem'))
            context.check_hostname = False
            params = pika.ConnectionParameters(host, int(port),
                                               ssl_options=pika.SSLOptions(context, server_hostname=host),
                                               credentials=pika.credentials.ExternalCredentials())

        self.address = amqp_server
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        self.queue_counts: dict[str, int] = {}

        for queue in queues:
            try:
                result = self.channel.queue_declare(queue=queue, arguments=arguments.get(queue, None), **kwargs)
                assert result.method.message_count is not None
                self.queue_counts[queue] = result.method.message_count
            except pika.exceptions.ChannelClosedByBroker as e:
                if e.reply_code == 404 and kwargs.get('passive'):
                    # queue does not exist, that's ok
                    self.channel = self.connection.channel()
                    continue

                # everything else is unexpected
                raise e

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _type: type[BaseException], value: BaseException | None, traceback: TracebackType) -> None:
        self.connection.close()
