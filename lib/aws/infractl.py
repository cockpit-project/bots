# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cockpit CI AWS infrastructure management."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import boto3

from ..aio.jsonutil import get_str
from ..github import GitHub
from .account import CI_RUNNER_REGION, DISPATCHER_ASG, DISPATCHER_NAME
from .ec2 import (
    describe_runner_instances,
    get_instance_ip,
    get_instance_slug,
    get_instance_state,
    print_console_output,
)
from .infra_definitions import (
    sync_infra,
    update_bots_urls,
    update_max_awaiting_logs,
    update_max_jobs,
    upload_secrets,
)

if TYPE_CHECKING:
    from types_boto3_ec2.type_defs import InstanceTypeDef

logger = logging.getLogger(__name__)


def resolve_bots_ref(ref: str) -> str:
    api = GitHub(repo="cockpit-project/bots")
    result = api.get_obj(f"commits/{ref}", None)
    if result is None:
        raise SystemExit(f"ref {ref!r} not found on github.com/cockpit-project/bots")

    sha = get_str(result, "sha")
    logger.info("bots ref %r → %s", ref, sha)
    return sha


def ssh_to_instance(instance: InstanceTypeDef, user: str) -> None:
    ip = get_instance_ip(instance)
    if not ip:
        sys.exit(f"instance {instance['InstanceId']} has no public IP")
    logger.debug("exec ssh %s@%s", user, ip)
    cmd = ["ssh", "-Fnone", "-oKnownHostsCommand=/bin/echo %H %t %K", f"{user}@{ip}"]
    os.execvp(cmd[0], cmd)


# --- dispatcher ---


def get_dispatcher_instances() -> Iterator[InstanceTypeDef]:
    logger.debug("looking up instance %r", DISPATCHER_NAME)
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    resp = ec2.describe_instances(
        Filters=[{"Name": "tag:Name", "Values": [DISPATCHER_NAME]}],
    )
    for reservation in resp["Reservations"]:
        for instance in reservation["Instances"]:
            logger.debug("found instance %r", instance["InstanceId"])
            yield instance


def remind_restart(prog: str) -> None:
    print(f"\nRun `{prog} dispatcher restart` to pick up changes.")


def cmd_dispatcher_up(_args: argparse.Namespace) -> None:
    autoscaling = boto3.client("autoscaling", region_name=CI_RUNNER_REGION)
    logger.debug("setting desired capacity to 1 for %r", DISPATCHER_NAME)
    autoscaling.set_desired_capacity(
        AutoScalingGroupName=DISPATCHER_ASG,
        DesiredCapacity=1,
    )
    print("desired capacity set to 1")


def cmd_dispatcher_down(_args: argparse.Namespace) -> None:
    autoscaling = boto3.client("autoscaling", region_name=CI_RUNNER_REGION)
    logger.debug("setting desired capacity to 0 for %r", DISPATCHER_NAME)
    autoscaling.set_desired_capacity(
        AutoScalingGroupName=DISPATCHER_ASG,
        DesiredCapacity=0,
    )
    print("desired capacity set to 0")


def cmd_dispatcher_restart(_args: argparse.Namespace) -> None:
    autoscaling = boto3.client("autoscaling", region_name=CI_RUNNER_REGION)
    resp = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[DISPATCHER_ASG]
    )
    instance_ids = [
        inst["InstanceId"]
        for asg in resp["AutoScalingGroups"]
        for inst in asg["Instances"]
    ]
    if not instance_ids:
        sys.exit("no instances in ASG")
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    logger.debug("terminating %r", instance_ids)
    ec2.terminate_instances(InstanceIds=instance_ids)
    print(f"detached and terminated {instance_ids}, ASG will launch a replacement")


def cmd_dispatcher_ssh(_args: argparse.Namespace) -> None:
    for instance in get_dispatcher_instances():
        if get_instance_state(instance) == "running":
            ssh_to_instance(instance, "admin")
            return
    sys.exit("no running dispatcher instance found")


def cmd_dispatcher_set_max_jobs(args: argparse.Namespace) -> None:
    logger.debug("setting max-active to %r", args.count)
    update_max_jobs(args.count)
    remind_restart(args.prog)


def cmd_dispatcher_set_max_awaiting_logs(args: argparse.Namespace) -> None:
    logger.debug("setting max-awaiting-logs to %r", args.count)
    update_max_awaiting_logs(args.count)
    remind_restart(args.prog)


def cmd_dispatcher_set_secrets(args: argparse.Namespace) -> None:
    secrets = {p.name: p.read_text() for p in args.secrets_dir.iterdir()}
    logger.debug("uploading secrets %r", list(secrets))
    upload_secrets(secrets)
    remind_restart(args.prog)


def cmd_dispatcher_update(args: argparse.Namespace) -> None:
    sha = resolve_bots_ref(args.bots_ref)
    bots_url = f"https://github.com/cockpit-project/bots/archive/{sha}.tar.gz"
    logger.debug("updating SSM with bots URL %r", bots_url)
    print(f"bots ref: {args.bots_ref}")
    print(f"bots sha: {sha}")
    update_bots_urls(
        bots_url,
        dispatcher=not args.only_runner,
        runner=not args.only_dispatcher,
    )
    remind_restart(args.prog)


def cmd_dispatcher_status(_args: argparse.Namespace) -> None:
    autoscaling = boto3.client("autoscaling", region_name=CI_RUNNER_REGION)
    resp = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[DISPATCHER_ASG],
    )
    for asg in resp["AutoScalingGroups"]:
        print(
            f"{asg['AutoScalingGroupName']} desired: {asg['DesiredCapacity']}  "
            f"min: {asg['MinSize']}  "
            f"max: {asg['MaxSize']}"
        )
        for inst in asg["Instances"]:
            print(f"  {inst['InstanceId']}  {inst['LifecycleState']}")

    for instance in get_dispatcher_instances():
        print(
            instance["InstanceId"],
            f"state: {get_instance_state(instance)}",
            f"ip: {get_instance_ip(instance)}",
        )


def cmd_dispatcher_console(_args: argparse.Namespace) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    instances = list(get_dispatcher_instances())
    if not instances:
        sys.exit("no dispatcher instance found")
    print_console_output(ec2, instances[0])


# --- runner ---


def cmd_runner_list(args: argparse.Namespace) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    for instance in describe_runner_instances(ec2):
        state = get_instance_state(instance)
        if not args.show_all and state == "terminated":
            continue
        print(f"  {get_instance_slug(instance)}  {instance['InstanceId']}  {state}")


def cmd_runner_terminate(args: argparse.Namespace) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    instances = describe_runner_instances(ec2, slug=args.slug)
    if not instances:
        sys.exit(f"no runner instances found for slug {args.slug!r}")
    instance_ids = [inst["InstanceId"] for inst in instances]
    logger.debug("terminating %r", instance_ids)
    ec2.terminate_instances(InstanceIds=instance_ids)
    print(f"terminated {instance_ids}")


def cmd_runner_ssh(args: argparse.Namespace) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    running = [
        inst
        for inst in describe_runner_instances(ec2, slug=args.slug)
        if get_instance_state(inst) == "running"
    ]
    if not running:
        sys.exit(f"no running runner instance found for slug {args.slug!r}")
    ssh_to_instance(running[0], "core")


def cmd_runner_console(args: argparse.Namespace) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    instances = describe_runner_instances(ec2, slug=args.slug)
    if not instances:
        sys.exit(f"no runner instance found for slug {args.slug!r}")
    print_console_output(ec2, instances[0])


# --- sync ---


def cmd_sync(args: argparse.Namespace) -> None:
    sha = resolve_bots_ref(args.bots_ref)
    bots_url = f"https://github.com/cockpit-project/bots/archive/{sha}.tar.gz"
    secrets = (
        {p.name: p.read_text() for p in args.secrets_dir.iterdir()}
        if args.secrets_dir
        else {}
    )
    print("\n# Deployment")
    print(f"  - bots ref: {args.bots_ref}")
    print(f"  - bots sha: {sha}")
    print(f"  - bots url: {bots_url}")
    print(f"  - secrets: {list(secrets)}")
    unexpected = sync_infra(cockpit_bots_url=bots_url, secrets=secrets)
    if not args.secrets_dir and any(":parameter/" in arn for arn in unexpected):
        print("\nHint: some unexpected SSM parameters were found.")
        print("Use --secrets-dir to provide secret files if they need updating.")
    remind_restart(args.prog)


# --- main ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--debug", "-d", action="store_true")
    parser.set_defaults(prog=parser.prog)
    sub = parser.add_subparsers(required=True)

    # fmt: off

    # --- sync ---

    sync = sub.add_parser("sync", help="Sync AWS infrastructure to desired state")
    sync.add_argument("--bots-ref", required=True, help="bots ref to deploy")
    sync.add_argument(
        "--secrets-dir", type=Path, default=None,
        help="directory containing secret files to upload to SSM",
    )
    sync.set_defaults(func=cmd_sync)

    # --- dispatcher ---

    dispatcher = sub.add_parser("dispatcher", help="Manage the dispatcher instance")
    dispatcher_cmds = dispatcher.add_subparsers(required=True)

    dispatcher_up = dispatcher_cmds.add_parser("up", help="Start the dispatcher")
    dispatcher_up.set_defaults(func=cmd_dispatcher_up)

    dispatcher_down = dispatcher_cmds.add_parser("down", help="Stop the dispatcher")
    dispatcher_down.set_defaults(func=cmd_dispatcher_down)

    dispatcher_restart = dispatcher_cmds.add_parser(
        "restart", help="Terminate and let the ASG replace the dispatcher")
    dispatcher_restart.set_defaults(func=cmd_dispatcher_restart)

    dispatcher_ssh = dispatcher_cmds.add_parser("ssh", help="SSH to the dispatcher")
    dispatcher_ssh.set_defaults(func=cmd_dispatcher_ssh)

    dispatcher_status = dispatcher_cmds.add_parser(
        "status", help="Show dispatcher instance status")
    dispatcher_status.set_defaults(func=cmd_dispatcher_status)

    dispatcher_console = dispatcher_cmds.add_parser("console",
        help="Show EC2 console output for the dispatcher")
    dispatcher_console.set_defaults(func=cmd_dispatcher_console)

    dispatcher_update = dispatcher_cmds.add_parser("update",
        help="Update bots download url in SSM parameters")
    dispatcher_update.add_argument("--bots-ref", required=True,
        help="bots ref to deploy")

    dispatcher_update_group = dispatcher_update.add_mutually_exclusive_group()
    dispatcher_update_group.add_argument("--only-dispatcher", action="store_true",
                                         help="only update the dispatcher URL")
    dispatcher_update_group.add_argument("--only-runner", action="store_true",
                                         help="only update the runner URL")
    dispatcher_update.set_defaults(func=cmd_dispatcher_update)

    dispatcher_set = dispatcher_cmds.add_parser("set", help="Configure dispatcher")
    dispatcher_set_cmds = dispatcher_set.add_subparsers(required=True)

    dispatcher_set_max_jobs = dispatcher_set_cmds.add_parser("max-jobs",
        help="Set the maximum number of concurrently active jobs")
    dispatcher_set_max_jobs.add_argument("count", type=int,
                                         help="set maximum number of active jobs")
    dispatcher_set_max_jobs.set_defaults(func=cmd_dispatcher_set_max_jobs)

    dispatcher_set_max_awaiting_logs = dispatcher_set_cmds.add_parser(
        "max-awaiting-logs",
        help="Set the maximum number of jobs awaiting log upload"
    )
    dispatcher_set_max_awaiting_logs.add_argument("count", type=int,
        help="new value for max-awaiting-logs")
    dispatcher_set_max_awaiting_logs.set_defaults(func=cmd_dispatcher_set_max_awaiting_logs)

    dispatcher_set_secrets = dispatcher_set_cmds.add_parser("secrets",
        help="Upload secrets from a directory to SSM SecureString parameters")
    dispatcher_set_secrets.add_argument(
        "--secrets-dir", type=Path, required=True,
        help="directory of secret files to upload (filename becomes parameter name)",
    )
    dispatcher_set_secrets.set_defaults(func=cmd_dispatcher_set_secrets)

    # --- runner ---

    runner = sub.add_parser("runner", help="Manage CI runner instances")
    runner_cmds = runner.add_subparsers(required=True)

    runner_list = runner_cmds.add_parser("list", help="List CI runner instances")
    runner_list.add_argument("-a", "--show-all", action="store_true",
                             help="Include terminated instances")
    runner_list.set_defaults(func=cmd_runner_list)

    runner_terminate = runner_cmds.add_parser("terminate",
      help="Terminate CI runner instance by slug")
    runner_terminate.add_argument("slug")
    runner_terminate.set_defaults(func=cmd_runner_terminate)

    runner_ssh = runner_cmds.add_parser("ssh", help="SSH to a CI runner by slug")
    runner_ssh.add_argument("slug")
    runner_ssh.set_defaults(func=cmd_runner_ssh)

    runner_console = runner_cmds.add_parser("console",
        help="Show EC2 console output for a runner")
    runner_console.add_argument("slug")
    runner_console.set_defaults(func=cmd_runner_console)

    # fmt: on

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(name)s: %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
