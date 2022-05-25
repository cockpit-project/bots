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

# Shared GitHub code. When run as a script, we print out info about
# our GitHub interacition.

import os
import ssl
import socket

from lib.constants import IMAGES_DIR

# Cockpit image/log server CA
CA_PEM = os.getenv("COCKPIT_CA_PEM", os.path.join(IMAGES_DIR, "files", "ca.pem"))


CA_PEM_DOMAINS = [
    "e2e.bos.redhat.com",
    # points to our AWS sink; obsolete after 2022-07 when we settled down on "S3 logs only"
    "logs.cockpit-project.org",
    # development/cockpituous project tests
    "localdomain",
]


def get_host_ca(hostname):
    '''Return custom CA that applies to the given host name.

    Self-hosted infrastructure uses CA_PEM, while publicly hosted infrastructure ought to have
    an officially trusted TLS certificate. Return None for these.
    '''
    # strip off port
    hostname = hostname.split(':')[0]

    if any((hostname == domain or hostname.endswith("." + domain)) for domain in CA_PEM_DOMAINS):
        return CA_PEM
    return None


def get_curl_ca_arg(hostname):
    '''Return curl CLI arguments for talking to hostname.

    This uses get_host_ca() to determine an appropriate CA for talking to hostname.
    Returns ["--cacert", "CAFilePath"] or [] as approprioate.
    '''
    ca = get_host_ca(hostname)
    return ['--cacert', ca] if ca else []


def host_ssl_context(hostname):
    '''Return SSLContext suitable for given hostname.

    This uses get_host_ca() to determine an appropriate CA.
    '''
    cafile = get_host_ca(hostname)
    return ssl.create_default_context(cafile=cafile) if cafile else None


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
