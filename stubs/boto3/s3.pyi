class S3Client:
    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: str | bytes,
        ContentType: str = ...,
    ) -> object: ...
