# This file is part of Cockpit.
#
# Copyright (C) 2017 Red Hat, Inc.
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

# Shared GitHub code. When run as a script, we print out info about
# our GitHub interacition.

import os

from lib.constants import LIB_DIR

ALL_STORES = [line.split() for line in open(os.path.join(LIB_DIR, 'stores'))]

# hosted on public internet
PUBLIC_STORES = [url for scope, url in ALL_STORES if scope == 'public']

# hosted behind the Red Hat VPN
REDHAT_STORES = [url for scope, url in ALL_STORES if scope == 'redhat']
