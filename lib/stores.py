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
import urllib

from lib.constants import IMAGES_DIR

# Cockpit image/log server CA
CA_PEM = os.getenv("COCKPIT_CA_PEM", os.path.join(IMAGES_DIR, "files", "ca.pem"))

# Servers which have public images
PUBLIC_STORES = [
    "https://images-frontdoor.apps.ocp.ci.centos.org/",
    "https://images-cockpit.apps.ci.centos.org/",
]

# Servers which have the private RHEL/Windows images
REDHAT_STORES = [
    "https://cockpit-11.e2e.bos.redhat.com:8493",
    # fallback RedHat-internal image server in AWS (internal VPN only)
    "https://internal-images.cockpit-project.org:8493/",
]


def redhat_network():
    '''Check if we can access the Red Hat network

    This checks if the image server can be accessed. The result gets cached,
    so this can be called several times.
    '''
    if redhat_network.result is None:
        redhat_network.result = False
        for url in REDHAT_STORES:
            store = urllib.parse.urlparse(url)
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10)
                s.connect((store.hostname, store.port))
                redhat_network.result = True
                break
            except OSError:
                pass

    return redhat_network.result


redhat_network.result = None
