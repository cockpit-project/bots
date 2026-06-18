from collections.abc import Callable
from typing import Any

from pika import BasicProperties
from pika.frame import Method
from pika.spec import Basic


class Channel:
    def queue_declare(
        self,
        queue: str,
        *,
        durable: bool = ...,
        passive: bool = ...,
        arguments: dict[str, Any] | None = ...,
    ) -> Method: ...

    def basic_publish(
        self,
        exchange: str,
        routing_key: str,
        body: str | bytes,
        *,
        properties: BasicProperties = ...,
    ) -> None: ...

    def basic_qos(
        self,
        *,
        prefetch_size: int = ...,
        prefetch_count: int = ...,
        global_qos: bool = ...,
        callback: Callable[..., object] | None = ...,
    ) -> None: ...

    def basic_consume(
        self,
        queue: str,
        *,
        on_message_callback: Callable[[Channel, Basic.Deliver, BasicProperties | None, bytes], object] = ...,
        auto_ack: bool = ...,
    ) -> str: ...

    def basic_cancel(self, consumer_tag: str) -> None: ...

    def basic_ack(self, delivery_tag: int) -> None: ...

    def basic_reject(self, delivery_tag: int, *, requeue: bool = ...) -> None: ...
