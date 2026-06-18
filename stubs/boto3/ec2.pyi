from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, NotRequired, TypedDict


class Tag(TypedDict):
    Key: str
    Value: str


class InstanceState(TypedDict):
    Name: str


class Instance(TypedDict):
    InstanceId: str
    State: InstanceState
    Tags: Sequence[Tag]
    LaunchTime: datetime
    PublicIpAddress: NotRequired[str]
    PrivateIpAddress: NotRequired[str]


class Reservation(TypedDict):
    Instances: Sequence[Instance]


class DescribeInstancesResult(TypedDict):
    Reservations: Sequence[Reservation]


class Filter(TypedDict):
    Name: str
    Values: Sequence[str]


class TagSpecification(TypedDict):
    ResourceType: str
    Tags: Sequence[Tag]


class CpuOptions(TypedDict, total=False):
    NestedVirtualization: str


class EC2Client:
    def describe_instances(
        self,
        *,
        Filters: Sequence[Filter] = ...,
        InstanceIds: Sequence[str] = ...,
    ) -> DescribeInstancesResult: ...

    def describe_images(
        self,
        *,
        Owners: Sequence[str] = ...,
        Filters: Sequence[Filter] = ...,
    ) -> Mapping[str, Any]: ...

    def describe_security_groups(
        self,
        *,
        Filters: Sequence[Filter] = ...,
    ) -> Mapping[str, Any]: ...

    def run_instances(self, **kwargs: Any) -> Reservation: ...

    def terminate_instances(
        self,
        *,
        InstanceIds: Sequence[str],
    ) -> Mapping[str, Any]: ...
