from typing import Any


class S3Client:
    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: str | bytes,
        ContentType: str = ...,
        **kwargs: Any,
    ) -> Any: ...
