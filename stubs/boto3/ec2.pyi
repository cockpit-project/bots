from collections.abc import Sequence
from datetime import datetime
from typing import NotRequired, TypedDict


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


class MetadataOptions(TypedDict, total=False):
    HttpTokens: str
    HttpPutResponseHopLimit: int


class Image(TypedDict):
    ImageId: str
    Name: str
    CreationDate: str


class DescribeImagesResult(TypedDict):
    Images: Sequence[Image]


class SecurityGroup(TypedDict):
    GroupId: str
    GroupName: str


class DescribeSecurityGroupsResult(TypedDict):
    SecurityGroups: Sequence[SecurityGroup]


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
    ) -> DescribeImagesResult: ...

    def describe_security_groups(
        self,
        *,
        Filters: Sequence[Filter] = ...,
    ) -> DescribeSecurityGroupsResult: ...

    def run_instances(
        self,
        *,
        ImageId: str,
        InstanceType: str,
        MinCount: int,
        MaxCount: int,
        UserData: str = ...,
        InstanceInitiatedShutdownBehavior: str = ...,
        MetadataOptions: MetadataOptions = ...,
        CpuOptions: CpuOptions = ...,
        TagSpecifications: Sequence[TagSpecification] = ...,
        SecurityGroupIds: Sequence[str] = ...,
    ) -> Reservation: ...

    def terminate_instances(
        self,
        *,
        InstanceIds: Sequence[str],
    ) -> object: ...
