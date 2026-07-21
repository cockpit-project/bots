# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from types_boto3_s3.literals import BucketLocationConstraintType

# This file defines constants for things like policy, role, bucket, etc. names
# along with some related constants like our AWS account number and SSO URLs.
# When adding new resources, ensure that 'cockpit-ci' appears in the name
# (ideally at the start) to make it easier to find resources that we've
# deployed.

# It should be possible to find the resources with a command like:
#
#     aws resource-explorer-2 search --query-string "cockpit"

# ACCOUNT
# Things in this section are things that are to some extent outside of
# our control and may need to change.  The account number is obvious but
# we may also need to change S3 bucket names since they are globally
# unique and first-come, first-serve.
ACCOUNT_ID = '727920394381'

# S3 BUCKETS
# Bucket names are globally unique and first-come, first-serve.
LOGS_BUCKET = 'cockpit-ci-logs'
CI_IMAGES_BUCKETS: Mapping[str, BucketLocationConstraintType | Literal['us-east-1']] = {
    'cockpit-ci-images': 'us-east-1',
    'cockpit-ci-images-fra': 'eu-central-1',
}

# TAGS
# Read corporate policy before changing anything here!
# https://source.redhat.com/departments/products_and_global_engineering/red_hat_public_cloud_services/public_cloud_services_wiki/resource_tagging_policy
# https://source.redhat.com/departments/products_and_global_engineering/red_hat_public_cloud_services/public_cloud_services_wiki/resource_tagging_names
MANDATORY_TAGS: Mapping[str, str] = {
    'app-code': 'ARR-001',
    'cost-center': '700',
    'service-phase': 'dev',
}
TAGS: Mapping[str, str] = {
    **MANDATORY_TAGS,
    'service-owner': 'cockpit',  # we've always done this... perhaps an older policy?
}

# REGIONS
LOGS_REGION = 'us-east-1'
# Also used for the dispatcher, SSM, STS, etc.
CI_RUNNER_REGION = 'us-east-1'

# ROLES
# These are IAM roles that we've created.  The names need only be unique
# inside of our AWS account, but we put them here as constants to avoid
# duplication.
DISPATCHER_ROLE = 'cockpit-ci-dispatcher'
IMAGE_DOWNLOAD_ROLE = 'cockpit-ci-images-download'
IMAGE_UPLOAD_ROLE = 'cockpit-ci-images-upload'
LOGS_WRITE_ROLE = 'cockpit-ci-logs-write'

# The SAML download role is a separate role used by humans via Red Hat
# SSO (Rover).  Rover requires the role name to start with our account
# ID.  It shares the images-download managed policy with the CI role
# above but has a different trust policy (SAML vs same-account).
# Rover group: https://rover.redhat.com/groups/group/it-cloud-aws-727920394381-cockpit-ci-images-download
REDHAT_SSO_IDP_URL = 'https://auth.redhat.com/auth/realms/EmployeeIDP/protocol/saml/clients/itaws'
REDHAT_SSO_SAML_PROVIDER_ARN = f'arn:aws:iam::{ACCOUNT_ID}:saml-provider/RedHatInternal'
REDHAT_SSO_IMAGE_DOWNLOAD_ROLE = f'{ACCOUNT_ID}-cockpit-ci-images-download'
REDHAT_SSO_IMAGE_DOWNLOAD_MAX_SESSION = timedelta(hours=12)

# DISPATCHER INSTANCE
DISPATCHER_ASG = 'cockpit-ci-dispatcher'
# Name used for the instance Name tag.
DISPATCHER_NAME = 'cockpit-ci/dispatcher'
# This is where we store config/secret parameters (in SSM)
DISPATCHER_PARAMS = '/cockpit-ci/dispatcher'

# RUNNER INSTANCES
RUNNER_NAME_PREFIX = 'cockpit-ci/runner/'
RUNNER_INSTANCE_SLUG_TAG = 'cockpit-ci-slug'

# SECURITY GROUPS
SSH_SECURITY_GROUP = 'cockpit-ci-ssh'

# RESOURCE EXPLORER
# Query used to find all our resources, and ARNs that are expected but
# not managed by the bootstrap script.
RESOURCES_QUERY = 'cockpit'
UNMANAGED_RESOURCES: Mapping[str, str] = {
    'arn:aws:ec2:us-east-1:727920394381:elastic-ip/eipalloc-0234f925c7f590290':
        'cockpit-public-webhook elastic IP',
    'arn:aws:ec2:us-east-1:727920394381:network-interface/eni-004f5b4f714f3fda9':
        'cockpit-public-webhook ENI',
}

# Useful derived constants
LOGS_URL = f'https://{LOGS_BUCKET}.s3.{LOGS_REGION}.amazonaws.com/'
