# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for ensuring a particular state of AWS resources.

Provides ensure_* functions that create-or-update AWS resources: try to
create (suppressing "already exists"), then unconditionally update to the
desired state.
"""

import base64
import contextlib
import fnmatch
import json
from collections.abc import Iterator, Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import boto3
from botocore.exceptions import ClientError

from ..aio.jsonutil import JsonObject
from ..ansi import RED, RESET
from .account import (
    ACCOUNT_ID,
    CI_RUNNER_REGION,
    RESOURCES_QUERY,
    RUNNER_NAME_PREFIX,
    TAGS,
    UNMANAGED_RESOURCES,
)

if TYPE_CHECKING:
    from types_boto3_autoscaling.type_defs import LaunchTemplateSpecificationTypeDef
    from types_boto3_autoscaling.type_defs import TagTypeDef as ASGTag
    from types_boto3_ec2.literals import InstanceTypeType
    from types_boto3_ec2.type_defs import IpPermissionTypeDef as IpPermission
    from types_boto3_ec2.type_defs import RequestLaunchTemplateDataTypeDef
    from types_boto3_s3.literals import BucketLocationConstraintType
    from types_boto3_s3.type_defs import BucketLifecycleConfigurationTypeDef
    from types_boto3_ssm.literals import ParameterTypeType

managed_arns: set[str] = set()


# --- ARN helpers ---


def role_arn(name: str) -> str:
    return f'arn:aws:iam::{ACCOUNT_ID}:role/{name}'


def policy_document(statements: Sequence[JsonObject]) -> str:
    return json.dumps({'Version': '2012-10-17', 'Statement': statements}, sort_keys=True)


@contextlib.contextmanager
def _suppress(
    code: str,
    on_success: str = 'created',
    on_suppress: str = 'already exists',
) -> Iterator[None]:
    try:
        yield
    except ClientError as exc:
        if exc.response['Error']['Code'] != code:
            raise
        print(f'    - {on_suppress}')
    else:
        print(f'    - {on_success}')


def ensure_policy(name: str, statements: Sequence[JsonObject]) -> str:
    iam = boto3.client('iam')
    arn = f'arn:aws:iam::{ACCOUNT_ID}:policy/{name}'

    print(f'  - policy {name}')
    with _suppress('EntityAlreadyExists'):
        iam.create_policy(
            PolicyName=name,
            PolicyDocument=policy_document(statements),
            Tags=[{'Key': k, 'Value': v} for k, v in TAGS.items()],
        )

    # AWS limits policies to 5 versions; delete non-defaults to make room
    # before adding ours, then clean up the old default afterwards.
    versions = iam.list_policy_versions(PolicyArn=arn)['Versions']
    old_default = next(v['VersionId'] for v in versions if v['IsDefaultVersion'])
    for v in versions:
        if not v['IsDefaultVersion']:
            iam.delete_policy_version(PolicyArn=arn, VersionId=v['VersionId'])
    iam.create_policy_version(PolicyArn=arn, PolicyDocument=policy_document(statements), SetAsDefault=True)
    iam.delete_policy_version(PolicyArn=arn, VersionId=old_default)
    print('    - synced')

    managed_arns.add(arn)
    return arn


def ensure_role(
    name: str,
    trust_policy: JsonObject,
    managed_policies: Sequence[str],
    *,
    max_session_duration: timedelta = timedelta(hours=1),
) -> str:
    iam = boto3.client('iam')
    arn = role_arn(name)
    trust_json = policy_document([trust_policy])

    print(f'  - role {name}')
    with _suppress('EntityAlreadyExists'):
        iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=trust_json,
            Tags=[{'Key': k, 'Value': v} for k, v in TAGS.items()],
        )

    iam.update_assume_role_policy(RoleName=name, PolicyDocument=trust_json)
    iam.update_role(RoleName=name, MaxSessionDuration=int(max_session_duration.total_seconds()))
    iam.tag_role(RoleName=name, Tags=[{'Key': k, 'Value': v} for k, v in TAGS.items()])

    attached_resp = iam.list_attached_role_policies(RoleName=name)
    attached_arns = {p['PolicyArn'] for p in attached_resp['AttachedPolicies']}

    desired_arns = set(managed_policies)
    for pa in desired_arns - attached_arns:
        print(f'    - attaching {pa}')
        iam.attach_role_policy(RoleName=name, PolicyArn=pa)
    for pa in attached_arns - desired_arns:
        print(f'    - detaching {pa}')
        iam.detach_role_policy(RoleName=name, PolicyArn=pa)
    print('    - synced')

    managed_arns.add(arn)
    return arn


def ensure_user(
    name: str,
    managed_policies: Sequence[str],
) -> str:
    iam = boto3.client('iam')
    arn = f'arn:aws:iam::{ACCOUNT_ID}:user/{name}'

    print(f'  - user {name}')
    with _suppress('EntityAlreadyExists'):
        iam.create_user(UserName=name, Tags=[{'Key': k, 'Value': v} for k, v in TAGS.items()])

    iam.tag_user(UserName=name, Tags=[{'Key': k, 'Value': v} for k, v in TAGS.items()])

    attached_resp = iam.list_attached_user_policies(UserName=name)
    attached_arns = {p['PolicyArn'] for p in attached_resp['AttachedPolicies']}

    desired_arns = set(managed_policies)
    for pa in desired_arns - attached_arns:
        print(f'    - attaching {pa}')
        iam.attach_user_policy(UserName=name, PolicyArn=pa)
    for pa in attached_arns - desired_arns:
        print(f'    - detaching {pa}')
        iam.detach_user_policy(UserName=name, PolicyArn=pa)

    for ip_name in iam.list_user_policies(UserName=name)['PolicyNames']:
        print(f'    - deleting inline policy {ip_name}')
        iam.delete_user_policy(UserName=name, PolicyName=ip_name)
    print('    - synced')

    managed_arns.add(arn)
    return arn


def ensure_security_group(
    name: str,
    description: str,
    *,
    region: str,
    ingress: Sequence[IpPermission] = (),
) -> str:
    ec2 = boto3.client('ec2', region_name=region)

    print(f'  - security group {name}')
    with _suppress('InvalidGroup.Duplicate'):
        ec2.create_security_group(
            GroupName=name,
            Description=description,
            TagSpecifications=[
                {
                    'ResourceType': 'security-group',
                    'Tags': [{'Key': k, 'Value': v} for k, v in TAGS.items()],
                }
            ],
        )

    desc = ec2.describe_security_groups(
        Filters=[{'Name': 'group-name', 'Values': [name]}],
    )
    group_id = desc['SecurityGroups'][0]['GroupId']
    ec2.create_tags(Resources=[group_id], Tags=[{'Key': k, 'Value': v} for k, v in TAGS.items()])

    current_perms = desc['SecurityGroups'][0]['IpPermissions']
    if current_perms:
        ec2.revoke_security_group_ingress(GroupId=group_id, IpPermissions=current_perms)
    if ingress:
        ec2.authorize_security_group_ingress(GroupId=group_id, IpPermissions=list(ingress))
    print('    - synced')

    managed_arns.add(f'arn:aws:ec2:{region}:{ACCOUNT_ID}:security-group/{group_id}')
    return group_id


def ensure_instance_profile(name: str, role_name: str) -> str:
    iam = boto3.client('iam')

    print(f'  - instance profile {name}')
    with _suppress('EntityAlreadyExists'):
        iam.create_instance_profile(InstanceProfileName=name, Tags=[{'Key': k, 'Value': v} for k, v in TAGS.items()])

    resp = iam.get_instance_profile(InstanceProfileName=name)
    existing_roles = {r['RoleName'] for r in resp['InstanceProfile']['Roles']}
    if role_name not in existing_roles:
        print(f'    - adding role {role_name}')
        iam.add_role_to_instance_profile(InstanceProfileName=name, RoleName=role_name)
    for extra in existing_roles - {role_name}:
        print(f'    - removing role {extra}')
        iam.remove_role_from_instance_profile(InstanceProfileName=name, RoleName=extra)
    print('    - synced')

    arn = f'arn:aws:iam::{ACCOUNT_ID}:instance-profile/{name}'
    managed_arns.add(arn)
    return arn


def ensure_bucket(
    name: str,
    region: BucketLocationConstraintType | Literal['us-east-1'],
    *,
    policy: Sequence[JsonObject],
    block_public_acls: bool = True,
    ignore_public_acls: bool = True,
    block_public_policy: bool = True,
    restrict_public_buckets: bool = True,
    lifecycle: BucketLifecycleConfigurationTypeDef | None = None,
) -> str:
    s3 = boto3.client('s3', region_name=region)

    print(f'  - bucket {name} ({region})')
    # us-east-1 can't be specified as a LocationConstraint:
    # https://github.com/boto/boto3/issues/125
    with _suppress('BucketAlreadyOwnedByYou'):
        if region != 'us-east-1':
            s3.create_bucket(Bucket=name, CreateBucketConfiguration={'LocationConstraint': region})
        else:
            s3.create_bucket(Bucket=name)

    # Tags
    s3.put_bucket_tagging(Bucket=name, Tagging={'TagSet': [{'Key': k, 'Value': v} for k, v in TAGS.items()]})

    # Ownership controls (disable ACLs)
    s3.put_bucket_ownership_controls(
        Bucket=name,
        OwnershipControls={'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]},
    )

    # Public access block
    s3.put_public_access_block(
        Bucket=name,
        PublicAccessBlockConfiguration={
            'BlockPublicAcls': block_public_acls,
            'IgnorePublicAcls': ignore_public_acls,
            'BlockPublicPolicy': block_public_policy,
            'RestrictPublicBuckets': restrict_public_buckets,
        },
    )

    # Bucket policy
    s3.put_bucket_policy(
        Bucket=name,
        Policy=policy_document(policy),
    )

    # Lifecycle
    if lifecycle is not None:
        s3.put_bucket_lifecycle_configuration(
            Bucket=name,
            LifecycleConfiguration=lifecycle,
        )
    else:
        s3.delete_bucket_lifecycle(Bucket=name)
    print('    - synced')

    arn = f'arn:aws:s3:::{name}'
    managed_arns.add(arn)
    return arn


def ensure_launch_template(
    name: str,
    *,
    region: str,
    image_id: str,
    instance_type: InstanceTypeType,
    security_group_ids: Sequence[str],
    user_data: str,
    iam_instance_profile: str,
    instance_name: str,
) -> str:
    ec2 = boto3.client('ec2', region_name=region)

    instance_tags = {**TAGS, 'Name': instance_name}
    template_data: RequestLaunchTemplateDataTypeDef = {
        'ImageId': image_id,
        'InstanceType': instance_type,
        'SecurityGroupIds': list(security_group_ids),
        'UserData': base64.b64encode(user_data.encode()).decode(),
        'IamInstanceProfile': {'Name': iam_instance_profile},
        'TagSpecifications': [
            {
                'ResourceType': 'instance',
                'Tags': [{'Key': k, 'Value': v} for k, v in instance_tags.items()],
            },
            {
                'ResourceType': 'volume',
                'Tags': [{'Key': k, 'Value': v} for k, v in instance_tags.items()],
            },
        ],
    }

    print(f'  - launch template {name}')
    with _suppress('InvalidLaunchTemplateName.AlreadyExistsException'):
        ec2.create_launch_template(
            LaunchTemplateName=name,
            LaunchTemplateData=template_data,
            TagSpecifications=[
                {
                    'ResourceType': 'launch-template',
                    'Tags': [{'Key': k, 'Value': v} for k, v in TAGS.items()],
                }
            ],
        )

    # AWS caps launch template versions; delete non-defaults to make room
    # before adding ours, then clean up the old default afterwards.
    versions = ec2.describe_launch_template_versions(LaunchTemplateName=name)['LaunchTemplateVersions']
    old_default = next(str(v['VersionNumber']) for v in versions if v['DefaultVersion'])
    non_default = [str(v['VersionNumber']) for v in versions if not v['DefaultVersion']]
    if non_default:
        ec2.delete_launch_template_versions(
            LaunchTemplateName=name,
            Versions=non_default,
        )

    version_resp = ec2.create_launch_template_version(
        LaunchTemplateName=name,
        LaunchTemplateData=template_data,
    )
    version = version_resp['LaunchTemplateVersion']['VersionNumber']
    ec2.modify_launch_template(LaunchTemplateName=name, DefaultVersion=str(version))
    ec2.delete_launch_template_versions(
        LaunchTemplateName=name,
        Versions=[old_default],
    )

    lt_id = ec2.describe_launch_templates(
        LaunchTemplateNames=[name],
    )['LaunchTemplates'][0]['LaunchTemplateId']

    print(f'    - version {version}')

    managed_arns.add(f'arn:aws:ec2:{region}:{ACCOUNT_ID}:launch-template/{lt_id}')
    return lt_id


def ensure_auto_scaling_group(
    name: str,
    *,
    region: str,
    launch_template: str,
    min_size: int,
    max_size: int,
    desired_capacity: int,
) -> str:
    autoscaling = boto3.client('autoscaling', region_name=region)
    ec2 = boto3.client('ec2', region_name=region)

    subnets = ec2.describe_subnets(
        Filters=[{'Name': 'default-for-az', 'Values': ['true']}],
    )['Subnets']
    vpc_zone_id = ','.join(s['SubnetId'] for s in subnets)
    launch_template_spec: LaunchTemplateSpecificationTypeDef = {
        'LaunchTemplateId': launch_template,
        'Version': '$Default',
    }

    tags: list[ASGTag] = [
        {
            'ResourceId': name,
            'ResourceType': 'auto-scaling-group',
            'Key': k,
            'Value': v,
            'PropagateAtLaunch': False,
        }
        for k, v in TAGS.items()
    ]

    print(f'  - auto scaling group {name}')
    with _suppress('AlreadyExists'):
        autoscaling.create_auto_scaling_group(
            AutoScalingGroupName=name,
            LaunchTemplate=launch_template_spec,
            MinSize=min_size,
            MaxSize=max_size,
            DesiredCapacity=desired_capacity,
            VPCZoneIdentifier=vpc_zone_id,
            Tags=tags,
        )

    autoscaling.update_auto_scaling_group(
        AutoScalingGroupName=name,
        LaunchTemplate=launch_template_spec,
        MinSize=min_size,
        MaxSize=max_size,
        DesiredCapacity=desired_capacity,
        VPCZoneIdentifier=vpc_zone_id,
    )
    autoscaling.create_or_update_tags(Tags=tags)
    print('    - synced')

    resp = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[name])
    asg = resp['AutoScalingGroups'][0]
    managed_arns.add(asg['AutoScalingGroupARN'])
    instance_ids = [i['InstanceId'] for i in asg['Instances']]
    running = _collect_instance_arns(instance_ids)
    if running:
        print('    - running resources:')
        for arn, instance_name in sorted(running.items()):
            print(f'        - {arn}: {instance_name}')
            managed_arns.add(arn)

    return name


def ensure_parameter(name: str, value: str, param_type: ParameterTypeType = 'String') -> None:
    ssm = boto3.client('ssm', region_name=CI_RUNNER_REGION)

    print(f'  - {name} ({param_type}, {len(value)} bytes)')
    ssm.put_parameter(Name=name, Value=value, Type=param_type, Overwrite=True)
    managed_arns.add(f'arn:aws:ssm:{CI_RUNNER_REGION}:{ACCOUNT_ID}:parameter{name}')


def _collect_instance_arns(instance_ids: Sequence[str]) -> dict[str, str]:
    """Describe instances and collect their associated ARNs.

    Returns a dict mapping instance/volume/ENI ARNs to the instance's Name tag.
    """
    if not instance_ids:
        return {}

    ec2 = boto3.client('ec2', region_name=CI_RUNNER_REGION)
    result: dict[str, str] = {}
    arn_prefix = f'arn:aws:ec2:{CI_RUNNER_REGION}:{ACCOUNT_ID}'

    resp = ec2.describe_instances(InstanceIds=list(instance_ids))
    for reservation in resp['Reservations']:
        for instance in reservation['Instances']:
            tags = {t['Key']: t['Value'] for t in instance.get('Tags', ())}
            name = tags.get('Name', instance['InstanceId'])

            result[f'{arn_prefix}:instance/{instance["InstanceId"]}'] = name
            for ni in instance.get('NetworkInterfaces', ()):
                result[f'{arn_prefix}:network-interface/{ni["NetworkInterfaceId"]}'] = name
            for bdm in instance.get('BlockDeviceMappings', ()):
                if vol_id := bdm.get('Ebs', {}).get('VolumeId'):
                    result[f'{arn_prefix}:volume/{vol_id}'] = name

    return result


def check_unmanaged() -> set[str]:
    print('\n## Resource audit')

    explorer = boto3.client('resource-explorer-2')
    resources = {
        r['Arn']
        for page in explorer.get_paginator('search').paginate(QueryString=RESOURCES_QUERY)
        for r in page['Resources']
    }

    if managed := resources & managed_arns:
        print(f'  - {len(managed)} managed resources')
        resources -= managed

    if known_unmanaged := resources & set(UNMANAGED_RESOURCES):
        print('\n### Known unmanaged')
        for arn in sorted(known_unmanaged):
            print(f'  - {arn}: {UNMANAGED_RESOURCES[arn]}')
        resources -= known_unmanaged

    runners = {
        arn: name
        for arn, name in _collect_instance_arns([
            arn.rsplit('/', 1)[-1] for arn in resources if fnmatch.fnmatch(arn, 'arn:aws:ec2:*:instance/*')
        ]).items()
        if name.startswith(RUNNER_NAME_PREFIX)
    }
    if runners:
        print('\n### Running CI jobs')
        for arn in sorted(runners):
            print(f'  - {arn}: {runners[arn]}')
        resources -= set(runners)

    if resources:
        print('\n### Unexpected resources')
        for arn in sorted(resources):
            print(f'  - {RED}{arn}{RESET}')

    return resources
