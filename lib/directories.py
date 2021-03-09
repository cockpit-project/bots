# This file is part of Cockpit.
#
# Copyright (C) 2019 Red Hat, Inc.
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
import subprocess

from .constants import GIT_DIR

_images_data_dir = None
_temp_dir = None


def get_git_config(*args):
    if not os.path.exists(GIT_DIR):
        return None

    try:
        myenv = os.environ.copy()
        myenv["GIT_DIR"] = GIT_DIR
        return subprocess.check_output(("git", "config") + args, universal_newlines=True, env=myenv).strip()

    except (OSError, subprocess.CalledProcessError):  # 'git' not in PATH, or cmd fails
        return None


def get_images_data_dir():
    global _images_data_dir

    if _images_data_dir is None:
        _images_data_dir = get_git_config('--type=path', 'cockpit.bots.images-data-dir')

        if _images_data_dir is None:
            _images_data_dir = os.path.join(os.getenv('XDG_CACHE_HOME', os.path.expanduser("~/.cache")),
                                            "cockpit-images")

    return _images_data_dir
