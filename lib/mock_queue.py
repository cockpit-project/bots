# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Collection, Iterable
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from pika import BasicProperties
    from pika.channel import Channel
    from pika.spec import Basic

    OnMessageCallback = Callable[[Channel, Basic.Deliver, BasicProperties | None, bytes], object]

logger = logging.getLogger(__name__)


class MockMethod:
    def __init__(self, delivery_tag: int) -> None:
        self.delivery_tag = delivery_tag


class MockChannel:
    def __init__(self, jobs: Iterable[str] | None = None) -> None:
        self._delivery_tag = 0
        self._consumers: dict[str, tuple[str, OnMessageCallback]] = {}
        self._unacked: int = 0
        self._prefetch_count: int = 0
        self._tag_counter: int = 0
        self._jobs = list(jobs) if jobs is not None else None

    def basic_qos(self,
                  prefetch_size: int = 0,
                  prefetch_count: int = 0,
                  global_qos: bool = False,
                  callback: Callable[..., object] | None = None) -> None:
        self._prefetch_count = prefetch_count
        logger.debug('mock qos prefetch_count=%r global=%r', prefetch_count, global_qos)
        if callback is not None:
            callback(None)

    def basic_consume(self,
                      queue: str,
                      on_message_callback: OnMessageCallback,
                      auto_ack: bool = False,
                      exclusive: bool = False,
                      consumer_tag: str | None = None,
                      arguments: object = None,
                      callback: Callable[..., object] | None = None) -> str:
        if consumer_tag is None:
            self._tag_counter += 1
            consumer_tag = f'mock-ctag-{self._tag_counter}'
        self._consumers[consumer_tag] = (queue, on_message_callback)
        logger.debug('mock consume queue=%r tag=%r', queue, consumer_tag)
        if callback is not None:
            callback(None)
        if self._jobs is not None:
            self._deliver_one()
        return consumer_tag

    def basic_cancel(self,
                     consumer_tag: str = '',
                     callback: Callable[..., object] | None = None) -> None:
        self._consumers.pop(consumer_tag, None)
        logger.debug('mock cancel tag=%r', consumer_tag)
        if callback is not None:
            callback(None)

    def basic_ack(self, delivery_tag: int = 0, multiple: bool = False) -> None:
        self._unacked -= 1
        logger.debug('mock ack %r (unacked=%r)', delivery_tag, self._unacked)
        if self._jobs is not None:
            self._deliver_one()

    def basic_reject(self, delivery_tag: int, requeue: bool = True) -> None:
        self._unacked -= 1
        logger.debug('mock reject %r (requeue=%r, unacked=%r)', delivery_tag, requeue, self._unacked)

    def _on_stdin(self) -> None:
        n = os.read(sys.stdin.fileno(), 4096).count(b'\n')
        for _ in range(n):
            self._deliver_one()

    def _deliver_one(self) -> None:
        if not self._consumers:
            logger.debug('mock stdin: no consumers, ignoring')
            return

        if self._prefetch_count and self._unacked >= self._prefetch_count:
            logger.debug('mock stdin: prefetch limit reached (%r), ignoring', self._unacked)
            return

        if self._jobs is not None:
            if not self._jobs:
                logger.debug('mock stdin: no more jobs')
                return
            body = self._jobs.pop(0).encode()
        else:
            slug = f'mock-{time.strftime("%H%M%S")}-{self._delivery_tag}'
            body = json.dumps({'job': {'repo': 'cockpit-project/bots', 'slug': slug}}).encode()

        self._delivery_tag += 1
        self._unacked += 1

        consumer_tag, (queue, cb) = next(iter(self._consumers.items()))
        logger.debug('mock deliver tag=%r via %r from queue %r', self._delivery_tag, consumer_tag, queue)
        cb(self, MockMethod(self._delivery_tag), None, body)  # type: ignore[arg-type]


class MockConnection:
    def __init__(self, channel: MockChannel) -> None:
        self._channel = channel

    def add_callback_threadsafe(self, callback: Callable[[], None]) -> None:
        asyncio.get_running_loop().call_soon(callback)


class DistributedQueue:
    def __init__(self, queues: Collection[str], jobs: Iterable[str] | None = None) -> None:
        self.queues = queues
        self.queue_counts: dict[str, int] = dict.fromkeys(queues, 0)
        self._jobs = jobs

    async def __aenter__(self) -> Self:
        self.channel = MockChannel(self._jobs)
        self.connection = MockConnection(self.channel)
        if self._jobs is None:
            asyncio.get_running_loop().add_reader(sys.stdin.fileno(), self.channel._on_stdin)
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._jobs is None:
            asyncio.get_running_loop().remove_reader(sys.stdin.fileno())
