from collections.abc import Callable

from pika import ConnectionParameters
from pika.channel import Channel


class AsyncioConnection:
    def __init__(
        self,
        parameters: ConnectionParameters | None = ...,
        *,
        on_open_callback: Callable[[AsyncioConnection], object] | None = ...,
        on_open_error_callback: Callable[[AsyncioConnection, Exception], object] | None = ...,
        on_close_callback: Callable[[AsyncioConnection, Exception], object] | None = ...,
    ) -> None: ...

    def channel(self, *, on_open_callback: Callable[[Channel], object]) -> None: ...

    def close(self) -> None: ...
