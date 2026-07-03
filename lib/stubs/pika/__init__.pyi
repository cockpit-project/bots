import ssl
from typing import Any

from .channel import Channel
from .credentials import ExternalCredentials, PlainCredentials
from .spec import Basic


class SSLOptions:
    def __init__(self, context: ssl.SSLContext, *, server_hostname: str = ...) -> None: ...


class ConnectionParameters:
    def __init__(
        self,
        host: str = ...,
        port: int = ...,
        *,
        ssl_options: SSLOptions = ...,
        credentials: PlainCredentials | ExternalCredentials = ...,
    ) -> None: ...


class BasicProperties:
    def __init__(self, *, priority: int = ..., **kwargs: Any) -> None: ...


class BlockingChannel(Channel):
    def basic_get(self, queue: str, auto_ack: bool = ...) -> tuple[Basic.GetOk, BasicProperties, bytes] | tuple[None, None, None]: ...


class BlockingConnection:
    def __init__(self, parameters: ConnectionParameters = ...) -> None: ...
    def channel(self) -> BlockingChannel: ...
    def close(self) -> None: ...
    def process_data_events(self, time_limit: float = ...) -> None: ...
