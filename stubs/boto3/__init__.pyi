from typing import Literal, overload

from .ec2 import EC2Client
from .s3 import S3Client
from .sts import STSClient


@overload
def client(service_name: Literal["ec2"], *, region_name: str = ..., **kwargs: object) -> EC2Client: ...
@overload
def client(service_name: Literal["s3"], *, region_name: str = ..., **kwargs: object) -> S3Client: ...
@overload
def client(service_name: Literal["sts"], *, region_name: str = ..., **kwargs: object) -> STSClient: ...
@overload
def client(service_name: str, *, region_name: str = ..., **kwargs: object) -> object: ...
