# Cockpit CI AWS infrastructure guide

## Files in this directory

### Common

 - [`account.py`](account.py): contains constants like account numbers or S3
   bucket names that are used to configure and access various AWS services.
   Things belong in this file if they're used to setup the infrastructure
   (`infractl sync`) and also to *use* the infrastructure, for example the
   names of S3 buckets where images are downloaded.  In general, the constants
   in this file are really useful with `git grep` to connect infrastructure
   definitions to actual runtime uses.

### Infrastructure deployment

 - [`authorized_keys`](authorized_keys): an `authorized_keys` file for who is
   allowed to ssh to the dispatcher
 - [`infra_definitions.py`](infra_definitions.py): the definition of our AWS
   deployment.  This uses many constants from [`account.py`](account.py) and
   generally defines the shape of our infra in terms of IAM Policies, Roles,
   Users, S3 Buckets, and EC2 launch templates and auto-scaling groups.  It
   also defines several SSM parameters which customize the dispatcher and
   runners and contain secrets.
 - [`ensure_resource.py`](ensure_resource.py): a set of helpers which allow
   [`infra_definitions.py`](infra_definitions.py) to be written in a
   declarative/idempotent style.  Each function in here is more or less
   responsible for making sure a particular resource exists, and has a
   particular state.
 - [`infractl.py`](infractl.py): a tool for performing various infrastructure
   tasks.  Invoke this as `python -m lib.aws.infractl` from the root of the
   bots checkout.

### Runtime/dispatcher

 - [`dashboard.html`](dashboard.html): an HTML published on the logs bucket
   when the dispatcher is running.  It fetches a file called `summary.json`
   which contains the current set of active jobs and runners.
 - [`dispatcher.py`](dispatcher.py): the core dispatcher logic.  This is the part that consumes
   jobs from the AMQP queue and launches EC2 instances.
 - [`ec2.py`](ec2.py): helpers for launching and querying EC2 instances.  This
   is mostly used for runners, since the dispatcher itself is run from an
   auto-scaling group.  Launching needs a job-runner config and a job.
 - [`jobconfig.py`](jobconfig.py): a generator for a JSON form of a
   `job-runner.toml` containing ephemeral S3 credentials issued via the STS
   service.  This is used by the dispatcher to create ephemeral configurations
   for runners but it could also be adapted for use with non-EC2 runners, or
   even for local `job-runner`.
 - [`launch_runner.py`](launch_runner.py): a utility script which can be used
   for launching one-off runners for testing

## Overview

The CI deployment is "infrastructure as code".  We went with Python instead of
other solutions for three main reasons:

 - Python is the most widely-understood language in the Cockpit team

 - the AWS Python bindings (`boto3`) are high quality, officially supported,
   very actively maintained by Amazon, and with very good type annotations
   available

 - we don't need any external "state" storage as is often required by other
   solutions (OpenTofu, CloudFormation, etc).  The deployed state of the
   infrastructure itself is the only state.

The infrastructure is completely defined inside of `lib/aws/account.py` (for
"constants' which are also shared by runtime code) and
`lib/aws/infra_definitions.py` (for the straight-up infra deployment).
Although those definitions are written as a series of Python functions, they
are written in a declarative/idempotent way, directly stating the desired state
of the deployment.

There's a middle layer that takes the declarative form and converts it to
reality via AWS calls.  That's the "helpers" in `lib/aws/ensure_resource.py`.
These are unloved, but relatively small and self-contained.  It should
generally not be necessary to modify these unless adding new resource types.


## AWS on-boarding

Everything that infractl does happens via boto3 which means that it understands
native AWS configuration (ie: configured via `~/.aws/`).  In particular, you
may want to familiarize yourself with the [AWS
Documentation](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html),
particular around the use of the `AWS_PROFILE` environment variable.

Make sure you have the `python3-boto3` package installed.  The `awscli2`
package can also be very helpful.

If you don't already have a `~/.aws/config`, here's a reasonable starting point:

```
[default]
region = us-east-1
```

The credentials can be found in the `cockpit-infra-accounts` Bitwarden group.
Access to that group is available only on Red Hat Bitwarden accounts (search
the source for how to get an invite email) and is regulated via [a Rover
group](https://rover.redhat.com/groups/edit/basic/cockpit-infra-accounts).
Contact one of the owners of that group if you want to be added.

You can add those credentials to `~/.aws/credentials` in a format similar to this:

```
[cockpit-ci-infractl]
aws_access_key_id = AKIA...
aws_secret_access_key = secret...
```

Some high-privilege operations below require access to the `admin` role on the
AWS account.  These credentials are very powerful, and (accordingly) are not
associated with any static key, and are not stored in Bitwarden.  They are only
available as an IAM role on time-limited sessions via SAML login and are
regulated by [a separate Rover
group](https://rover.redhat.com/groups/group/it-cloud-aws-727920394381-admin).
Contact the admins of that group if you need access.

The easiest way to get this working is by configuring an `admin` profile in
`~/.aws/credentials`, something like so:

```
[admin]
credential_process = /home/lis/src/bots/main/saml-login --output=awscreds 727920394381-admin
```

with the `/home/lis/src/bots/main` path adjusted to point to your bots
checkout.

You can test that your admin (or any other profile) access is working by using
a command like this:

```
AWS_PROFILE=admin aws sts get-caller-identity
```

Finally, if you want to login to the AWS web console, you need to use this URL:
https://auth.redhat.com/auth/realms/EmployeeIDP/protocol/saml/clients/itaws

In general, the web console is good for poking around or doing experiments, but 


## ci-secrets repository

The [ci-secrets
repository](https://gitlab.cee.redhat.com/front-door-ci-wranglers/ci-secrets/)
contains the static secrets used by the CI infrastructure.  Normally you'll
want to check that out in `$XDG_RUNTIME_DIR/ci-secrets`.

Access to this repository is regulated by [a rover
group](https://rover.redhat.com/groups/group/front-door-ci) and is only
available from the Red Hat internal network (or via VPN).

You can configure your SSH key on the `gitlab.cee.redhat.com` instance via
https://gitlab.cee.redhat.com/-/user_settings/ssh_keys.  You'll want to use
"Red Hat SAML Login" if prompted.

Once everything is setup you should be able to clone the secrets like so:

```
git clone git@gitlab.cee.redhat.com:front-door-ci-wranglers/ci-secrets $XDG_RUNTIME_DIR/ci-secrets
```

## Task-oriented cheat sheet

This is a "if you want to do X, type Y" list of instructions.

All commands are run from a `cockpit-project/bots` checkout and assume the AWS
on-boarding (above) has been completed.

### Deploy the entire CI infrastructure from scratch

Deploying the infrastructure from scratch involves creation/modification of IAM
roles and policies which is a very highly-privileged operation.  You'll need to
use the "admin" profile for this.

You'll also want a checkout of the `ci-secrets` repository, mentioned above.

```
AWS_PROFILE=admin python3 -m lib.aws.infractl sync \
    --secrets-dir $XDG_RUNTIME_DIR/ci-secrets/aws-secrets/dispatcher/
    --bots-ref main
```

The entire process should take well under a minute to complete.  When it's done
deploying, the `sync` command will scan existing resources on the cluster with
`cockpit` in the name that were unaffected by the current deployment.  The goal
of this is to find any cruft lying around.  You may want to remove things or
add them to the "known" `UNMANAGED_RESOURCES` list in `account.py` with an
explanation for why they're there.


### Updating secrets

There's currently no way to update only the secrets.  In order to do this, just
redeploy the entire infrastructure from scratch (which is harmless and fast).


### Make changes to the CI infrastructure

You can make the required changes by modifying `lib/aws/infra_definitions.py` and running

```
AWS_PROFILE=admin python3 -m lib.aws.infractl sync --bots-ref main
```

if you omit the `--secrets-dir` argument then the secrets will be left unmodified.


### Changing the deployed version of the dispatcher or runners

The version of the `bots` repo that gets checked out on the dispatcher and
runners is controlled by the `--bots-ref` argument to `infractl sync`.  It's
important to note that this reference is resolved at deployment time and
remains hardcoded as a sha in the deployed configuration.  If you make changes
to the dispatcher or `job-runner` and want them to be used, you need to
explicitly update them.  This also gives a mechanism to roll back to known-good
versions.

It's possible to do this without requiring a full infrastructure deploy.  This
is also a lower-privilege operation and can be performed using the
`cockpit-ci-infractl` IAM user from Bitwarden).

```
AWS_PROFILE=cockpit-ci-infractl python3 -m lib.aws.infractl dispatcher update --bots-ref=main
```

The reference can be a branch name or a raw sha.

You can also pass `--only-dispatcher` or `--only-runner` to only update the
version used on the dispatcher or the runners (which might be particular useful
during rollbacks).

In any case, you'll need to restart the dispatcher after it's done in order to
pick up the new dispatcher version.  You'll also need to restart the dispatcher
in order to pick up the new runner version because the parameter is read at
dispatcher startup time and sent to the runners from the dispatcher.

### Restart the dispatcher

The dispatcher is brought online by bringing up an instance to run it.  The
launch template for the dispatcher will pick the latest version of its
configured OS and pull the version of the bots repository as configured above.

Once the dispatcher is running, it is never updated in place.  The only thing
that can be done is to power it off, at which point the auto-scaling group will
bring up a new instance.  This can be done via:

```
AWS_PROFILE=cockpit-ci-infractl python3 -m lib.aws.infractl dispatcher restart
```

### Start or stop the dispatcher

```
AWS_PROFILE=cockpit-ci-infractl python3 -m lib.aws.infractl dispatcher up
AWS_PROFILE=cockpit-ci-infractl python3 -m lib.aws.infractl dispatcher down
```

This will configure the auto-scaling group to have a desired capacity of 0 or
1, effectively controlling if the dispatcher is running or not.

### Check dispatcher status

```
AWS_PROFILE=cockpit-ci-infractl python3 -m lib.aws.infractl dispatcher status
```

This will show the status of the auto-scaling group and any dispatcher
instances that were found (running, terminated, etc.).

### SSH to the dispatcher

You can ssh to (`admin@`) the dispatcher public IP directly (as discovered by
the `status` command) but there's also a convenience wrapper:

```
AWS_PROFILE=cockpit-ci-infractl python3 -m lib.aws.infractl dispatcher ssh
```

In order to do that, you'll need to have your ssh key in the
`lib/aws/authorized_keys` file.  Note: this file is baked into the launch
template of the dispatcher as part of `infractl sync` and `infractl dispatcher
update` will not update it.

### List, inspect, or terminate runner instances

```
export AWS_PROFILE=cockpit-ci-infractl
python3 -m lib.aws.infractl runner list
python3 -m lib.aws.infractl runner list -a          # include terminated
python3 -m lib.aws.infractl runner ssh SLUG
python3 -m lib.aws.infractl runner console SLUG     # EC2 serial console (delayed ~10 min)
python3 -m lib.aws.infractl runner terminate SLUG
```

You can also check the [dashboard
page](https://cockpit-ci-logs.s3.us-east-1.amazonaws.com/dashboard.html) that
the dispatcher regularly updates when it's running:

### Launch a one-off runner instance for debugging

You can manually launch a runner instance for a given job JSON blob like so:

```
AWS_PROFILE-cockpit-ci python3 -m lib.aws.launch_runner '{"slug": "abc123", ...}'
```

If you omit the job then a synthetic job (which just sleeps) will be made up.

In any case, you'll be connected to the machine via ssh as soon as it's
available.  This is good for inspecting job runs and debugging issues.

Since this involves launching EC2 instances (and requires access to the secrets
required to launch the instances) this requires the `cockpit-ci` profile from
Bitwarden.

Closing the ssh connection will cause the instance to be terminated.
