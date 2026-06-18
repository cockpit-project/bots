import ssl
from typing import Any

from .channel import Channel
from .credentials import ExternalCredentials, PlainCredentials


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


class BlockingConnection:
    def __init__(self, parameters: ConnectionParameters = ...) -> None: ...
    def channel(self) -> Channel: ...
    def close(self) -> None: ...
