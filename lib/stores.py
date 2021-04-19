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
import socket

from lib.constants import IMAGES_DIR, LIB_DIR

# Cockpit image/log server CA
CA_PEM = os.getenv("COCKPIT_CA_PEM", os.path.join(IMAGES_DIR, "files", "ca.pem"))

ALL_STORES = [line.split() for line in open(os.path.join(LIB_DIR, 'stores'))]

# Servers which have public images
PUBLIC_STORES = [url for scope, url in ALL_STORES if scope == 'public']

# Servers which have the private RHEL images
REDHAT_STORES = [url for scope, url in ALL_STORES if scope == 'redhat']

# Servers which can host either public or private images (via ACL specification)
HYBRID_STORES = [url for scope, url in ALL_STORES if scope == 'hybrid']


def redhat_network():
    '''Check if we can access the Red Hat network

    The result gets cached, so this can be called several times.
    '''
    if redhat_network.result is None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect(("download.devel.redhat.com", 443))
            redhat_network.result = True
        except OSError:
            redhat_network.result = False

    return redhat_network.result


redhat_network.result = None
