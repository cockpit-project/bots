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

from collections.abc import Sequence

from lib.aws.account import CI_IMAGES_BUCKETS, LOGS_URL
from lib.directories import xdg_config_home

# hosted on the public internet, requires a private token for some/all images
IMAGE_STORES: Sequence[str] = (
    *(f'https://{name}.s3.{region}.amazonaws.com/' for name, region in CI_IMAGES_BUCKETS.items()),
)

# locally configured stores in ~/.config/cockpit-dev/image-stores or $COCKPIT_IMAGE_STORES_FILE
try:
    with open(xdg_config_home('cockpit-dev', 'image-stores', envvar='COCKPIT_IMAGE_STORES_FILE')) as fp:
        data = fp.read().strip()
except FileNotFoundError:
    # that config file is optional
    data = ""

LOCAL_STORES: Sequence[str] = data.splitlines()

LOG_STORE = LOGS_URL
