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

import signal
from types import FrameType
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from machine_core import ssh_connection


class Timeout:
    """ Add a timeout to an operation
        Specify machine to ensure that a machine's ssh operations are canceled when the timer expires.
    """
    def __init__(self, seconds: int = 1, error_message: str = 'Timeout',
                 machine: Optional['ssh_connection.SSHConnection'] = None) -> None:
        if signal.getsignal(signal.SIGALRM) != signal.SIG_DFL:
            # there is already a different Timeout active
            self.seconds = None
            return

        self.seconds = seconds
        self.error_message = error_message
        self.machine = machine

    def handle_timeout(self, signum: int, frame: Optional[FrameType]) -> None:
        if self.machine:
            if self.machine.ssh_process:
                self.machine.ssh_process.terminate()
            self.machine.disconnect()

        raise RuntimeError(self.error_message)

    def __enter__(self) -> None:
        if self.seconds:
            signal.signal(signal.SIGALRM, self.handle_timeout)
            signal.alarm(self.seconds)

    def __exit__(self, *_args: object) -> None:
        if self.seconds:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
