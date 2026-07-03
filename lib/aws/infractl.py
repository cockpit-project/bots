# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cockpit CI AWS infrastructure management."""

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
)
from .infra_definitions import sync_infra, update_bots_urls

if TYPE_CHECKING:
    from types_boto3_ec2.type_defs import InstanceTypeDef

logger = logging.getLogger(__name__)


def resolve_bots_ref(ref: str) -> str:
    github = GitHub()
    if github.repo != "cockpit-project/bots":
        raise ValueError("run from a cockpit-project/bots checkout")

    result = github.get_obj(f"commits/{ref}", None)
    if result is None:
        raise ValueError(f"{ref!r} not found on github.com/{github.repo}")

    sha = get_str(result, "sha")
    logger.debug("resolved %r to %r", ref, sha)
    return sha


def ssh_to_instance(instance: "InstanceTypeDef", user: str) -> None:
    ip = get_instance_ip(instance)
    if not ip:
        sys.exit(f"instance {instance['InstanceId']} has no public IP")
    logger.debug("exec ssh %s@%s", user, ip)
    cmd = ["ssh", "-Fnone", "-oKnownHostsCommand=/bin/echo %H %t %K", f"{user}@{ip}"]
    os.execvp(cmd[0], cmd)


# --- dispatcher ---


def get_dispatcher_instances() -> Iterator["InstanceTypeDef"]:
    logger.debug("looking up instance %r", DISPATCHER_NAME)
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    resp = ec2.describe_instances(
        Filters=[{"Name": "tag:Name", "Values": [DISPATCHER_NAME]}],
    )
    for reservation in resp["Reservations"]:
        for instance in reservation["Instances"]:
            logger.debug("found instance %r", instance["InstanceId"])
            yield instance


def get_dispatcher_instance() -> InstanceTypeDef | None:
    for instance in get_dispatcher_instances():
        if get_instance_state(instance) == "running":
            return instance
    return None


def dispatcher_up() -> None:
    autoscaling = boto3.client("autoscaling", region_name=CI_RUNNER_REGION)
    logger.debug("setting desired capacity to 1 for %r", DISPATCHER_NAME)
    autoscaling.set_desired_capacity(
        AutoScalingGroupName=DISPATCHER_ASG,
        DesiredCapacity=1,
    )
    print("desired capacity set to 1")


def dispatcher_down() -> None:
    autoscaling = boto3.client("autoscaling", region_name=CI_RUNNER_REGION)
    logger.debug("setting desired capacity to 0 for %r", DISPATCHER_NAME)
    autoscaling.set_desired_capacity(
        AutoScalingGroupName=DISPATCHER_ASG,
        DesiredCapacity=0,
    )
    print("desired capacity set to 0")


def dispatcher_restart() -> None:
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


def dispatcher_ssh() -> None:
    instance = get_dispatcher_instance()
    if instance is None:
        sys.exit("no running dispatcher instance found")
    ssh_to_instance(instance, "admin")


def dispatcher_update(args: argparse.Namespace) -> None:
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


def dispatcher_status() -> None:
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


# --- runner ---


def runner_list(*, show_all: bool = False) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    for instance in describe_runner_instances(ec2):
        state = get_instance_state(instance)
        if not show_all and state == "terminated":
            continue
        print(f"  {get_instance_slug(instance)}  {instance['InstanceId']}  {state}")


def runner_terminate(slug: str) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    instances = describe_runner_instances(ec2, slug=slug)
    if not instances:
        sys.exit(f"no runner instances found for slug {slug!r}")
    instance_ids = [inst["InstanceId"] for inst in instances]
    logger.debug("terminating %r", instance_ids)
    ec2.terminate_instances(InstanceIds=instance_ids)
    print(f"terminated {instance_ids}")


def runner_ssh(slug: str) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    running = [
        inst
        for inst in describe_runner_instances(ec2, slug=slug)
        if get_instance_state(inst) == "running"
    ]
    if not running:
        sys.exit(f"no running runner instance found for slug {slug!r}")
    ssh_to_instance(running[0], "core")


def runner_console(slug: str) -> None:
    ec2 = boto3.client("ec2", region_name=CI_RUNNER_REGION)
    instances = describe_runner_instances(ec2, slug=slug)
    if not instances:
        sys.exit(f"no runner instance found for slug {slug!r}")
    instance_id = instances[0]["InstanceId"]
    logger.debug("getting console output for %r", instance_id)
    resp = ec2.get_console_output(InstanceId=instance_id)
    output = resp.get("Output", "")
    if output:
        print(output, end="")
    else:
        print("(no console output available yet)")
    print("\nNote: console log output is delayed by ~10 minutes", file=sys.stderr)


# --- main ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--debug", "-d", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser(
        "sync", help="Sync AWS infrastructure to desired state"
    )
    sync_parser.add_argument(
        "--bots-ref", required=True, help="bots ref to deploy"
    )
    sync_parser.add_argument(
        "--secrets-dir",
        type=Path,
        default=None,
        help="directory containing secret files to upload to SSM",
    )

    disp = sub.add_parser("dispatcher", help="Manage the dispatcher instance")
    disp_sub = disp.add_subparsers(dest="dispatcher_command", required=True)
    disp_sub.add_parser("up", help="Start the dispatcher instance")
    disp_sub.add_parser("down", help="Stop the dispatcher instance")
    disp_sub.add_parser(
        "restart", help="Terminate and let the ASG replace the instance"
    )
    disp_sub.add_parser("ssh", help="SSH to the dispatcher instance")
    disp_sub.add_parser("status", help="Show dispatcher instance status")
    update_parser = disp_sub.add_parser(
        "update", help="Update bots SHA in SSM parameters"
    )
    update_parser.add_argument(
        "--bots-ref", required=True, help="bots ref to deploy"
    )
    update_group = update_parser.add_mutually_exclusive_group()
    update_group.add_argument(
        "--only-dispatcher", action="store_true", help="only update the dispatcher URL"
    )
    update_group.add_argument(
        "--only-runner", action="store_true", help="only update the runner URL"
    )

    runner = sub.add_parser("runner", help="Manage CI runner instances")
    runner_sub = runner.add_subparsers(dest="runner_command", required=True)

    runner_list_parser = runner_sub.add_parser("list", help="List CI runner instances")
    runner_list_parser.add_argument(
        "-a", "--show-all", action="store_true", help="Include terminated instances"
    )

    runner_terminate_parser = runner_sub.add_parser(
        "terminate", help="Terminate CI runner instances by slug"
    )
    runner_terminate_parser.add_argument("slug")

    runner_ssh_parser = runner_sub.add_parser(
        "ssh", help="SSH to a CI runner instance by slug"
    )
    runner_ssh_parser.add_argument("slug")

    runner_console_parser = runner_sub.add_parser(
        "console", help="Show EC2 console output for a runner"
    )
    runner_console_parser.add_argument("slug")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(name)s: %(message)s",
    )

    match args.command:
        case "sync":
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
                print(
                    "Use --secrets-dir to provide secret files if they need updating."
                )
            print(f"\nRun `{parser.prog} dispatcher restart` to pick up changes.")
        case "dispatcher":
            match args.dispatcher_command:
                case "up":
                    dispatcher_up()
                case "down":
                    dispatcher_down()
                case "restart":
                    dispatcher_restart()
                case "ssh":
                    dispatcher_ssh()
                case "status":
                    dispatcher_status()
                case "update":
                    dispatcher_update(args)
        case "runner":
            match args.runner_command:
                case "list":
                    runner_list(show_all=args.show_all)
                case "terminate":
                    runner_terminate(args.slug)
                case "ssh":
                    runner_ssh(args.slug)
                case "console":
                    runner_console(args.slug)


if __name__ == "__main__":
    main()
