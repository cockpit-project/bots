from typing import TypedDict


class Credentials(TypedDict):
    AccessKeyId: str
    SecretAccessKey: str
    SessionToken: str
    Expiration: str


class AssumeRoleResponse(TypedDict):
    Credentials: Credentials


class STSClient:
    def assume_role(
        self,
        *,
        RoleArn: str,
        RoleSessionName: str,
        Policy: str = ...,
    ) -> AssumeRoleResponse: ...
