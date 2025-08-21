#!/usr/bin/python3 -u

# This file is part of Cockpit.
#
# Copyright (C) 2013 Red Hat, Inc.
#
# Cockpit is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# Cockpit is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Cockpit; If not, see <http://www.gnu.org/licenses/>.

import os
import sys

if os.path.realpath(f'{__file__}/../..') not in sys.path:
    # ensure that the top-level is present in the path so the following imports work
    sys.path.insert(1, os.path.realpath(f'{__file__}/../..'))

from lib.constants import BOTS_DIR, DEFAULT_IMAGE, IMAGES_DIR, SCRIPTS_DIR, TEST_DIR, TEST_OS_DEFAULT
from lib.directories import get_images_data_dir
from lib.testmap import get_build_image, get_test_image
from machine.machine_core.cli import cmd_cli
from machine.machine_core.exceptions import Failure
from machine.machine_core.machine import Machine
from machine.machine_core.machine_virtual import VirtMachine, VirtNetwork
from machine.machine_core.timeout import Timeout

__all__ = (
    "BOTS_DIR",
    "DEFAULT_IMAGE",
    "IMAGES_DIR",
    "SCRIPTS_DIR",
    "TEST_DIR",
    "TEST_OS_DEFAULT",
    "Failure",
    "Machine",
    "Timeout",
    "VirtMachine",
    "VirtNetwork",
    "get_build_image",
    "get_images_data_dir",
    "get_test_image"
)

# This can be used as helper program for tests not written in Python: Run given
# image name until SIGTERM or SIGINT; the image must exist in test/images/;
# use image-prepare or image-customize to create that. For example:
# $ bots/image-customize -v -i cockpit arch
# $ bots/machine/testvm.py arch
if __name__ == "__main__":
    cmd_cli()
