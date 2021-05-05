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

# Images which are OSTree based
OSTREE_IMAGES = ["fedora-coreos"]

LIB_DIR = os.path.dirname(__file__)
BOTS_DIR = os.path.dirname(LIB_DIR)
MACHINE_DIR = os.path.join(BOTS_DIR, 'machine')

# bots always act on the project that is the current directory
# FIXME: Get rid of these aliases and drop their usage everywhere, once that approach works
BASE_DIR = os.getcwd()
TEST_DIR = os.path.join(BASE_DIR, "test")
GIT_DIR = os.path.join(BASE_DIR, ".git")

IMAGES_DIR = os.path.join(BOTS_DIR, "images")
SCRIPTS_DIR = os.path.join(IMAGES_DIR, "scripts")

DEFAULT_IDENTITY_FILE = os.path.join(MACHINE_DIR, "identity")

TEST_OS_DEFAULT = "fedora-34"
DEFAULT_IMAGE = os.environ.get("TEST_OS", TEST_OS_DEFAULT)
