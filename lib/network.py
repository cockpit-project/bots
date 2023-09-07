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

import functools
import os
import socket
import ssl
from typing import List, Optional

from lib.constants import IMAGES_DIR

# Cockpit image/log server CA
CA_PEM = os.getenv("COCKPIT_CA_PEM", os.path.join(IMAGES_DIR, "files", "ca.pem"))


CA_PEM_DOMAINS = [
    "e2e.bos.redhat.com",
    # development/cockpituous project tests
    "localdomain",
]


def get_host_ca(hostname: str) -> Optional[str]:
    """Return custom CA that applies to the given host name.

    Self-hosted infrastructure uses CA_PEM, while publicly hosted infrastructure ought to have
    an officially trusted TLS certificate. Return None for these.
    """
    # strip off port
    hostname = hostname.split(':')[0]

    if any((hostname == domain or hostname.endswith("." + domain)) for domain in CA_PEM_DOMAINS):
        return CA_PEM
    return None


def get_curl_ca_arg(hostname: str) -> List[str]:
    """Return curl CLI arguments for talking to hostname.

    This uses get_host_ca() to determine an appropriate CA for talking to hostname.
    Returns ["--cacert", "CAFilePath"] or [] as approprioate.
    """
    ca = get_host_ca(hostname)
    return ['--cacert', ca] if ca else []


def host_ssl_context(hostname: str) -> Optional[ssl.SSLContext]:
    """Return SSLContext suitable for given hostname.

    This uses get_host_ca() to determine an appropriate CA.
    """
    cafile = get_host_ca(hostname)
    return ssl.create_default_context(cafile=cafile) if cafile else None


@functools.lru_cache()
def redhat_network() -> bool:
    """Check if we can access the Red Hat network

    The result gets cached, so this can be called several times.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(("download.devel.redhat.com", 443))
        return True
    except OSError:
        return False
