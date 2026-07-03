# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import contextlib
import logging
import os
import ssl
from collections.abc import Mapping, Sequence
from typing import Self

import pika
import pika.credentials
from pika import BasicProperties
from pika.adapters.asyncio_connection import AsyncioConnection
from pika.channel import Channel
from pika.spec import Basic

logger = logging.getLogger(__name__)


def _make_connection_params(credentials: Mapping[str, str]) -> pika.ConnectionParameters:
    host, port = credentials['amqp-server'].split(':')

    if host == 'localhost':
        return pika.ConnectionParameters(
            host,
            int(port),
            credentials=pika.credentials.PlainCredentials('guest', 'guest'),
        )

    with contextlib.ExitStack() as stack:

        def memfd(name: str) -> str:
            fd = os.memfd_create(name)
            stack.callback(os.close, fd)
            os.write(fd, credentials[name].encode())
            return f'/proc/self/fd/{fd}'

        context = ssl.create_default_context(cafile=memfd('ca.pem'))
        context.load_cert_chain(
            keyfile=memfd('amqp-client.key'),
            certfile=memfd('amqp-client.pem'),
        )
        context.check_hostname = False

    return pika.ConnectionParameters(
        host,
        int(port),
        ssl_options=pika.SSLOptions(context, server_hostname=host),
        credentials=pika.credentials.ExternalCredentials(),
    )


class Queue:
    def __init__(
        self, credentials: Mapping[str, str], queues: Sequence[str], consumer_priority: int | None = None,
    ) -> None:
        self._params = _make_connection_params(credentials)
        self._queues = tuple(queues)
        self._consumer_priority = consumer_priority
        self._consumer_tags = tuple[str, ...]()
        self._messages = asyncio.Queue[tuple[int, bytes] | Exception]()
        self._connection: AsyncioConnection | None = None
        self._channel: Channel | None = None

    async def __aenter__(self) -> Self:
        init_done: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        def on_channel_closed(channel: Channel, reason: Exception) -> None:
            logger.error('AMQP channel closed: %r %r', channel, reason)
            self.close(reason)

        def on_channel_opened(channel: Channel) -> None:
            logger.debug('AMQP channel opened')
            self._channel = channel
            channel.add_on_close_callback(on_channel_closed)
            channel.basic_qos(prefetch_count=1, global_qos=True)
            for queue in self._queues:
                logger.debug('declaring queue %r', queue)
                channel.queue_declare(queue, durable=True, arguments={"x-max-priority": 9})
            init_done.set_result(None)

        def on_connection_open(connection: AsyncioConnection) -> None:
            logger.debug('AMQP connection opened %r', connection)
            self._connection = connection
            connection.channel(on_open_callback=on_channel_opened)

        def on_connection_open_error(connection: AsyncioConnection, error: Exception) -> None:
            logger.error('AMQP connection failed: %r %r', connection, error)
            init_done.set_exception(error)

        def on_connection_closed(connection: AsyncioConnection, reason: Exception) -> None:
            logger.error('AMQP closed: %r %r', connection, reason)
            # We might get the close before or after we finished initializing
            if not init_done.done():
                init_done.set_exception(reason)
            else:
                self.close(reason)

        AsyncioConnection(
            self._params,
            on_open_callback=on_connection_open,
            on_open_error_callback=on_connection_open_error,
            on_close_callback=on_connection_closed,
        )

        try:
            await init_done
        except Exception:
            self._connection = None
            self._channel = None
            raise
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.close()

    def close(self, reason: Exception | None = None) -> None:
        self._channel = None
        self._consumer_tags = ()
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if reason is not None:
            self._messages.put_nowait(reason)

    async def next_message(self) -> tuple[int, bytes]:
        self.start_deliveries()
        message = await self._messages.get()
        if isinstance(message, Exception):
            raise message
        return message

    def ack(self, delivery_tag: int) -> None:
        if self._channel is not None:
            self._channel.basic_ack(delivery_tag)
            logger.debug('acked tag=%r', delivery_tag)

    def start_deliveries(self) -> None:
        if self._consumer_tags or self._channel is None:
            return
        arguments = {'x-priority': self._consumer_priority} if self._consumer_priority is not None else None
        self._consumer_tags = tuple(
            self._channel.basic_consume(queue, on_message_callback=self._on_message, arguments=arguments)
            for queue in self._queues
        )
        logger.debug('consuming tags=%r', self._consumer_tags)

    def stop_deliveries(self) -> None:
        if self._channel is not None:
            for tag in self._consumer_tags:
                self._channel.basic_cancel(tag)
                logger.debug('cancelled consumer tag=%r', tag)
        self._consumer_tags = ()

    def _on_message(
        self, _channel: Channel, method: Basic.Deliver, _properties: BasicProperties | None, body: bytes
    ) -> None:
        logger.debug('received message tag=%r', method.delivery_tag)
        self._messages.put_nowait((method.delivery_tag, body))
