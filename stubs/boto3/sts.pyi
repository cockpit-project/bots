from collections.abc import Mapping
from typing import Any


class STSClient:
    def assume_role(
        self,
        *,
        RoleArn: str,
        RoleSessionName: str,
        Policy: str = ...,
        **kwargs: Any,
    ) -> Mapping[str, Any]: ...
