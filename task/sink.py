# This file is part of Cockpit.
#
# Copyright (C) 2015 Red Hat, Inc.
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

import json
import os
import subprocess
import sys

__all__ = (
    'Sink',
)


class Sink(object):
    def __init__(self, host, identifier, status=None):
        self.status = status

        # Start a gzip and cat processes
        self.ssh = subprocess.Popen(["ssh", "-o", "ServerAliveInterval=30", host, "--", "./sink", identifier],
                                    stdin=subprocess.PIPE)

        # Send the status line
        self.ssh.stdin.write(json.dumps(status).encode('utf-8') + b"\n")
        self.ssh.stdin.flush()

        # Now dup our own output and errors into the pipeline
        sys.stdout.flush()
        self.fout = os.dup(1)
        os.dup2(self.ssh.stdin.fileno(), 1)
        sys.stderr.flush()
        self.ferr = os.dup(2)
        os.dup2(self.ssh.stdin.fileno(), 2)

    def flush(self, status=None):
        assert self.ssh is not None

        # Reset stdout back
        sys.stdout.flush()
        os.dup2(self.fout, 1)
        os.close(self.fout)
        self.fout = -1

        # Reset stderr back
        sys.stderr.flush()
        os.dup2(self.ferr, 2)
        os.close(self.ferr)
        self.ferr = -1

        # Splice in the github status
        if status is None:
            status = self.status
        if status is not None:
            self.ssh.stdin.write(b"\n" + json.dumps(status).encode('utf-8'))

        # All done sending output
        try:
            self.ssh.stdin.close()
        except BrokenPipeError:
            # SSH already terminated
            pass

        # SSH should terminate by itself; It legitimately exits with 77 on collisions
        ret = self.ssh.wait()
        if ret not in [0, 77]:
            raise subprocess.CalledProcessError(ret, "ssh")
        self.ssh = None
