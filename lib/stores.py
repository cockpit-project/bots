# This file is part of Cockpit.
#
# Copyright (C) 2022 Red Hat, Inc.
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

from typing import List

from lib.directories import xdg_config_home

# hosted on public internet
PUBLIC_STORES = [
    "https://cockpit-images.eu-central-1.linodeobjects.com/",
    "https://cockpit-images.us-east-1.linodeobjects.com/",
]

# hosted behind the Red Hat VPN
REDHAT_STORES: List[str] = [
    # e2e down for maintenance
    # "https://cockpit-11.apps.cnfdb2.e2e.bos.redhat.com/images/",
]

# local stores
try:
    with open(xdg_config_home('cockpit-dev', 'image-stores'), 'r') as fp:
        data = fp.read().strip()
        if data:
            PUBLIC_STORES += data.split("\n")
except FileNotFoundError:
    # that config file is optional
    pass


LOG_STORE = "https://cockpit-logs.us-east-1.linodeobjects.com/"
