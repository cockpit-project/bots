#!/usr/bin/python3

# Copyright (C) 2018 Red Hat, Inc.
# SPDX-License-Identifier: LGPL-2.1-or-later


import json
import os
import subprocess
from pathlib import Path

import pytest

from lib.constants import BOTS_DIR, MACHINE_DIR
from machine import testvm


@pytest.fixture
def test_os() -> str:
    try:
        value = os.environ["TEST_OS"]
    except KeyError:
        pytest.skip("TEST_OS not set")

    # TODO: the cockpituous integration tests queue a test run on the bots repo
    # with a context of `unit-tests`, which tests-scan sets as `TEST_OS`, even
    # though it's not one.  One day we might stop setting `TEST_OS` that way,
    # but until such a time, just add a workaround here.
    if value == 'unit-tests':
        pytest.skip("TEST_OS=unit-tests is a pseudo-context, not a real image")

    return value


@pytest.fixture
def tmp_image(tmp_path: Path, test_os: str) -> Path:
    return tmp_path / test_os


def check_boot(image: Path) -> None:
    with testvm.Timeout(seconds=300, error_message="Timed out waiting for image to run"):
        network = testvm.VirtNetwork(None, image=str(image))
        machine = testvm.VirtMachine(image=str(image), networking=network.host())
        machine.boot()
        out = machine.execute('cat /var/custom-test')
        machine.stop()
    assert out == "hello\n"


def test_image_customize_custom_dir(tmp_image: Path) -> None:
    with testvm.Timeout(seconds=300, error_message="Timed out waiting for image-customize"):
        subprocess.check_call([f"{BOTS_DIR}/image-customize", "--verbose", "--run-command",
                               "echo hello > /var/custom-test", tmp_image])

    assert tmp_image.exists()
    check_boot(tmp_image)


def test_image_customize_script_relative_path(tmp_image: Path) -> None:
    script = tmp_image.parent / "setup.sh"
    script.write_text("#!/bin/sh -eu\necho hello > /var/custom-test\n")

    with testvm.Timeout(seconds=300, error_message="Timed out waiting for image-customize"):
        subprocess.check_call([f"{BOTS_DIR}/image-customize", "--verbose", "--script",
                               os.path.relpath(script), tmp_image])

    assert tmp_image.exists()
    check_boot(tmp_image)


def test_image_customize_upload(tmp_image: Path) -> None:
    with testvm.Timeout(seconds=300, error_message="Timed out waiting for image-customize"):
        subprocess.check_call([f"{BOTS_DIR}/image-customize", "--verbose",
                               "--upload", "/etc/passwd:/tmp/passwd",
                               "--run-command", "echo hello > /var/custom-test",
                               "--run-command", "grep ^root: /tmp/passwd", tmp_image])

    check_boot(tmp_image)


def test_image_customize_failure_propagation(tmp_image: Path) -> None:
    with testvm.Timeout(seconds=300, error_message="Timed out waiting for image-customize"):
        subprocess.check_call([f"{BOTS_DIR}/image-customize", "--verbose",
                               "--run-command", "true", tmp_image])

        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_call([f"{BOTS_DIR}/image-customize", "--verbose",
                                   "--run-command", "false", tmp_image])


def test_image_customize_resize(tmp_image: Path) -> None:
    with testvm.Timeout(seconds=300, error_message="Timed out waiting for image-customize"):
        subprocess.check_call([f"{BOTS_DIR}/image-customize", "--verbose",
                               "--resize", "30G", tmp_image])

    output = subprocess.check_output(["qemu-img", "info", "--output=json", tmp_image], encoding="utf-8")
    info = json.loads(output)
    assert int(info['virtual-size']) // 1024 // 1024 // 1024 == 30


def test_testvm_basic(tmp_image: Path) -> None:
    with testvm.Timeout(seconds=300, error_message="Timed out waiting for image-customize"):
        subprocess.check_call([f"{BOTS_DIR}/image-customize", "--verbose", "--run-command",
                               "echo hello > /var/custom-test", tmp_image])

    # boot it and wait for RUNNING marker, parse out ssh and cockpit addresses
    with testvm.Timeout(seconds=300, error_message="Timed out waiting for testvm.py to boot VM"):
        vm = subprocess.Popen([f"{MACHINE_DIR}/testvm.py", tmp_image],
                              stdout=subprocess.PIPE, text=True)
        assert vm.stdout is not None
        # first line should be the SSH command
        ssh_command = vm.stdout.readline().split()
        # second line is the redirected cockpit address
        cockpit_address = vm.stdout.readline()
        # third should be the "I am ready" flag
        running = vm.stdout.readline()

    assert running == "RUNNING\n"
    assert cockpit_address.startswith("http://127.0.0.2:9"), cockpit_address
    # test SSH command and that we have the expected flag file
    assert ssh_command[0] == "ssh"
    with testvm.Timeout(seconds=30, error_message="Timed out waiting for ssh command"):
        out = subprocess.check_output([*ssh_command, "cat", "/var/custom-test"])
    assert out == b"hello\n"

    # should cleanly stop on SIGTERM
    vm.terminate()
    with testvm.Timeout(seconds=60, error_message="Timed out waiting for script to terminate"):
        assert vm.wait() == 0
