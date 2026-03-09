#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Invoke bots job-runner with podman.
# Intended to run on a cloud instance with KVM support.
#
# Required environment variables:
#   GITHUB_TOKEN    - GitHub API token for posting statuses/comments
#   S3_KEY_{EU,US}  - S3 image credentials for eu-central-1 and us-east-1 (format: "access secret")
#   S3_KEY_LOGS     - S3 credentials for log storage
#   JOB_JSON        - job-runner specification
#
# You can test this locally by creating a GitHub PAT with repo:status and public_repo scopes in /tmp/token,
# checking out the Cockpit CI credentials into /tmp/ci-secrets, copying the job JSON to /tmp/job.json, and running:
#
# JOB_JSON=$(< /tmp/job.json) GITHUB_TOKEN=$(< /tmp/token) S3_KEY_LOGS=$(< /tmp/ci-secrets/github/env/image-build/S3_KEY_LOGS) S3_KEY_EU=$(< /tmp/ci-secrets/github/env/image-build/S3_KEY_EU) S3_KEY_US=$(< /tmp/ci-secrets/github/env/image-build/S3_KEY_US) plans/job-runner.sh
set -eu

# Set up secrets BEFORE enabling -x
SECRETS_DIR="$PWD/secrets"
mkdir -p "$SECRETS_DIR/s3-keys"
echo "$GITHUB_TOKEN" > "$SECRETS_DIR/github-token"
echo "$S3_KEY_EU" > "$SECRETS_DIR/s3-keys/eu-central-1.linodeobjects.com"
echo "$S3_KEY_US" > "$SECRETS_DIR/s3-keys/us-east-1.linodeobjects.com"
# Parse S3 key (format: "ACCESS SECRET")
read -r S3_ACCESS S3_SECRET <<< "$S3_KEY_LOGS"

set -x

# Check that KVM is available
test -c /dev/kvm
# Log the current commit for debugging
git show -s

# Create job-runner config
cat > job-runner-local.toml << EOF
[logs]
driver = 's3'

[logs.s3]
url = 'https://cockpit-logs.us-east-1.linodeobjects.com/'
key = {access='$S3_ACCESS', secret='$S3_SECRET'}

[forge.github]
post = true
token = [{file="$SECRETS_DIR/github-token"}]

[container]
run-args = [
    '--device=/dev/kvm',
    '--env=GIT_COMMITTER_NAME=Cockpituous',
    '--env=GIT_COMMITTER_EMAIL=cockpituous@cockpit-project.org',
    '--env=GIT_AUTHOR_NAME=Cockpituous',
    '--env=GIT_AUTHOR_EMAIL=cockpituous@cockpit-project.org',
]

[container.secrets]
github-token = [
    '--volume=$SECRETS_DIR/github-token:/run/secrets/github-token:ro,z,U',
    '--env=COCKPIT_GITHUB_TOKEN_FILE=/run/secrets/github-token',
]
image-upload = [
    '--volume=$SECRETS_DIR/s3-keys:/run/secrets/s3-keys:ro,z,U',
    '--env=COCKPIT_S3_KEY_DIR=/run/secrets/s3-keys',
]
EOF

BOTS_DIR=$(git rev-parse --show-toplevel)
"$BOTS_DIR/job-runner" --config-file job-runner-local.toml json "$JOB_JSON"
