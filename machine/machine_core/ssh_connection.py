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

import errno
import os
import select
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from typing import IO

from . import exceptions
from . import timeout as timeoutlib

# HACK: some projects directly import ssh_connection before adjusting sys.path; add bots root dir
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from lib.constants import TEST_DIR


class SSHConnection:
    ssh_default_opts = (
        "-F", "none",
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "PKCS11Provider=none",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
    )
    ssh_control_path: str | None
    ssh_process: subprocess.Popen[bytes] | None
    boot_id: str | None

    def __init__(
        self,
        user: str,
        address: str,
        ssh_port: int | str,
        identity_file: str,
        verbose: bool = False,
        label: str | None = None
    ):
        self.verbose = verbose

        # Currently all images are x86_64. When that changes we will have
        # an override file for those images that are not
        self.ssh_user = user
        self.identity_file = identity_file
        self.ssh_address = address
        self.ssh_port = ssh_port
        self.ssh_control_path = None
        self.ssh_process = None
        self.ssh_reachable = False
        self.label = label if label else f"{self.ssh_user}@{self.ssh_address}:{self.ssh_port}"

    def disconnect(self) -> None:
        self.ssh_reachable = False
        self._kill_ssh_master()

    def message(self, *args: str) -> None:
        """Prints args if in verbose mode"""
        if self.verbose:
            sys.stderr.write(" ".join(args) + '\n')

    # wait until we can execute something on the machine. ie: wait for ssh
    def wait_execute(self, timeout_sec: int = 120) -> bool:
        """Try to connect to self.address on ssh port"""

        # If connected to machine, kill master connection
        self._kill_ssh_master()

        start_time = time.time()
        while (time.time() - start_time) < timeout_sec:
            addrinfo = socket.getaddrinfo(self.ssh_address, self.ssh_port, 0, socket.SOCK_STREAM)
            family, socktype, proto, _canonname, sockaddr = addrinfo[0]
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(5)
                try:
                    sock.connect(sockaddr)
                    data = sock.recv(10)
                    if len(data):
                        self.ssh_reachable = True
                        return True
                except OSError:
                    time.sleep(0.5)
        return False

    def wait_user_login(self) -> str | None:
        """Wait until logging in as non-root works.

           Most tests run as the "admin" user, so we make sure that
           user sessions are allowed (and cockit-ws will let "admin"
           in) before declaring a test machine as "booted".

           Returns the boot id of the system, or None if ssh timed out.
        """
        tries_left = 60
        while (tries_left > 0):
            try:
                with timeoutlib.Timeout(seconds=30):
                    allow_nologin = os.getenv("TEST_ALLOW_NOLOGIN", False)
                    if allow_nologin:
                        return self.execute("cat /proc/sys/kernel/random/boot_id", direct=True)
                    return self.execute("! test -f /run/nologin && cat /proc/sys/kernel/random/boot_id", direct=True)

            except subprocess.CalledProcessError:
                pass
            except RuntimeError:
                # timeout; assume that ssh just went down during reboot, go back to wait_boot()
                return None
            tries_left = tries_left - 1
            time.sleep(1)
        raise exceptions.Failure("Timed out waiting for /run/nologin to disappear")

    def print_console_log(self) -> None:
        pass

    def wait_boot(self, timeout_sec: int = 120) -> None:
        """Wait for a machine to boot"""
        start_time = time.time()
        boot_id = None
        while (time.time() - start_time) < timeout_sec:
            if self.wait_execute(timeout_sec=15):
                boot_id = self.wait_user_login()
                if boot_id:
                    break
        if not boot_id:
            self.print_console_log()
            raise exceptions.Failure(
                f"Unable to reach machine {self.label} via ssh: {self.ssh_address}:{self.ssh_port}")
        self.boot_id = boot_id

    def wait_reboot(self, timeout_sec: int = 180) -> None:
        self.disconnect()
        assert self.boot_id, "Before using wait_reboot() use wait_boot() successfully"
        boot_id = self.boot_id
        start_time = time.time()
        while (time.time() - start_time) < timeout_sec:
            try:
                self.wait_boot(timeout_sec=timeout_sec)
                if self.boot_id != boot_id:
                    break
            except exceptions.Failure:
                pass  # try again
        else:
            raise exceptions.Failure("Timeout waiting for system to reboot properly")

    def reboot(self, timeout_sec: int = 180) -> None:
        self.spawn("reboot", "reboot", check=False)
        if timeout_sec:
            self.wait_reboot(timeout_sec)

    def _start_ssh_master(self) -> None:
        self._kill_ssh_master()

        control = os.path.join(tempfile.gettempdir(), ".cockpit-test-resources", "ssh-%C-" + str(os.getpid()))
        os.makedirs(os.path.dirname(control), exist_ok=True)

        cmd = (
            "ssh",
            "-p", str(self.ssh_port),
            "-i", self.identity_file,
            *self.ssh_default_opts,
            "-M",  # ControlMaster, no stdin
            "-o", "ControlPath=" + control,
            "-o", "LogLevel=ERROR",
            "-l", self.ssh_user,
            self.ssh_address,
            "/bin/sh -c 'echo READY; read a'"
        )

        # Connection might be refused, so try this 10 times
        tries_left = 10
        while tries_left > 0:
            tries_left = tries_left - 1
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            assert proc.stdout is not None
            stdout_fd = proc.stdout.fileno()
            output = ""
            while stdout_fd > -1 and "READY" not in output:
                ret = select.select([stdout_fd], [], [], 10)
                for fd in ret[0]:
                    if fd == stdout_fd:
                        data = os.read(fd, 1024)
                        if not data:
                            stdout_fd = -1
                            proc.stdout.close()
                        output += data.decode('utf-8', 'replace')

            if stdout_fd > -1:
                break

            # try again if the connection was refused, unless we've used up our tries
            proc.wait()
            if proc.returncode == 255 and tries_left > 0:
                self.message("ssh: connection refused, trying again")
                time.sleep(1)
                continue
            else:
                raise exceptions.Failure(f"SSH master process exited with code: {proc.returncode}")

        self.ssh_control_path = control
        self.ssh_process = proc

        if not self._check_ssh_master():
            raise exceptions.Failure("Couldn't launch an SSH master process")

    def _kill_ssh_master(self) -> None:
        if self.ssh_control_path:
            try:
                os.unlink(self.ssh_control_path)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            self.ssh_control_path = None
        if self.ssh_process:
            self.message("killing ssh master process", str(self.ssh_process.pid))
            assert self.ssh_process.stdin is not None
            assert self.ssh_process.stdout is not None
            self.ssh_process.stdin.close()
            self.ssh_process.terminate()
            self.ssh_process.stdout.close()
            with timeoutlib.Timeout(seconds=90, error_message="Timeout while waiting for ssh master to shut down"):
                self.ssh_process.wait()
            self.ssh_process = None

    def _check_ssh_master(self) -> bool:
        if not self.ssh_control_path:
            return False
        cmd = (
            "ssh",
            "-q",
            "-p", str(self.ssh_port),
            *self.ssh_default_opts,
            "-S", self.ssh_control_path,
            "-O", "check",
            "-l", self.ssh_user,
            self.ssh_address
        )
        with open(os.devnull, 'w') as devnull:
            code = subprocess.call(cmd, stdin=devnull, stdout=devnull, stderr=devnull)
            if code == 0:
                self.ssh_reachable = True
                return True
        return False

    def _get_ssh_options(self, direct: bool = False) -> Sequence[str]:
        """Get the ssh options for connecting to the test machine.

        These options are good for use with either ssh or scp and cover
        everything required to connect to the guest.  The hostname used with
        the ssh or scp command is irrelevant because the options override it.
        """
        assert self.ssh_address

        direct = bool(os.getenv("TEST_SSH_DIRECT", direct))

        # We can't use `-p` or `-l` because of scp. Use `-o` for everything.
        options = {
            "Hostname": self.ssh_address,
            "LogLevel": "ERROR",
            "Port": self.ssh_port,
            "User": self.ssh_user,
        }

        if direct:
            options["IdentityFile"] = self.identity_file
        else:
            if not self._check_ssh_master():
                self._start_ssh_master()
            assert self.ssh_control_path is not None
            options["ControlPath"] = self.ssh_control_path

        return (
            *self.ssh_default_opts,
            *(f"-o{k}={v}" for k, v in options.items()),
        )

    def execute(
        self,
        command: str | Sequence[str],
        input: str | None = None,  # noqa:A002  # shadows `input()` but so does subprocess module
        environment: Mapping[str, str] = {},
        stdout: int | IO[str] | IO[bytes] | None = subprocess.PIPE,
        quiet: bool = False,
        direct: bool = False,
        timeout: int = 120,
        ssh_env: Sequence[str] = ("env", "-u", "LANGUAGE", "LC_ALL=C"),
        check: bool = True
    ) -> str:
        """Execute a shell command in the test machine and return its output.

            command: The string or argument list to execute by /bin/sh (still with shell interpretation)
            input: Input to send to the command
            environment: Additional environment variables
            timeout: Applies if not already wrapped in a #Timeout context
        Returns:
            The command output as a string.
        """
        assert command

        if not isinstance(command, str):
            command = shlex.join(command)

        if not quiet:
            self.message("+", command)

        command_line = (
            *ssh_env,
            'ssh',
            *self._get_ssh_options(direct=direct),
            'vm',
            'set -e;',
            *(f'export {name}={shlex.quote(value)}; ' for name, value in environment.items()),
            command
        )

        with timeoutlib.Timeout(seconds=timeout, error_message="Timed out on '%s'" % command, machine=self):
            res = subprocess.run(command_line,
                                 input=input.encode("UTF-8") if input else b'',
                                 stdout=stdout, check=check)

        return '' if res.stdout is None else res.stdout.decode("UTF-8", "replace")

    def _scp(self, *args: str) -> None:
        """Perform an scp command with the test machine.

        The args should be the arguments you'd normally pass to scp.  The
        remote hostname is ignored, so you should specify something like "vm:"
        as a prefix for remote paths.
        """

        cmd = (
            "scp",
            *self._get_ssh_options(),
            *(("-q",) if not self.verbose else ()),
            *args
        )
        self.message(shlex.join(cmd))
        subprocess.check_call(cmd)

    def upload(self, sources: Sequence[str], dest: str, relative_dir: str = TEST_DIR) -> None:
        """Upload a file into the test machine

        Arguments:
            sources: the array of paths of the file to upload
            dest: the file path in the machine to upload to
        """
        assert sources and dest

        if dest.endswith('/'):
            self.execute(["mkdir", "-p", dest])

        self.message("Uploading", ", ".join(sources))
        self._scp(
            "-r", "-p",
            *(os.path.join(relative_dir, path) for path in sources),
            f"vm:{dest}"
        )

    def download(self, source: str, dest: str, relative_dir: str = TEST_DIR) -> None:
        """Download a file from the test machine.
        """
        assert source and dest

        self.message("Downloading", source)
        self._scp(f"vm:{source}", os.path.join(relative_dir, dest))

    def download_dir(self, source: str, dest: str, relative_dir: str = TEST_DIR) -> None:
        """Download a directory from the test machine, recursively.
        """
        assert source and dest

        self.message("Downloading", source)
        try:
            self._scp("-r", f"vm:{source}", os.path.join(relative_dir, dest))
        except subprocess.CalledProcessError:
            self.message(f"Error while downloading directory '{source}'")

    def write(
        self, dest: str, content: str, append: bool = False, owner: str | None = None, perm: str | None = None
    ) -> None:
        """Write a file into the test machine

        Arguments:
            content: Raw data to write to file
            dest: The file name in the machine to write to
            append: If True, append to existing file instead of replacing it
            owner: If set, call chown on the file with the given owner string
            perm: Optional file permission as chmod shell string (e.g. "0600")

        The directory of dest is created automatically.
        """
        assert dest

        self.execute(["mkdir", "-p", os.path.dirname(dest)])
        self.execute(f"cat {'>>' if append else '>'} {shlex.quote(dest)}", input=content)
        if owner:
            self.execute(["chown", owner, dest])
        if perm:
            self.execute(["chmod", perm, dest])

    def spawn(self, shell_cmd: str, log_id: str, check: bool = True) -> int:
        """Spawn a process in the test machine.

        Arguments:
           shell_cmd: The string to execute by /bin/sh.
           log_id: The name of the file, relative to /var/log on the test
              machine, that will receive stdout and stderr of the command.
        Returns:
            The pid of the /bin/sh process that executes the command.
        """
        res = self.execute(f"{{ ({shell_cmd}) >/var/log/{log_id} 2>&1 & }}; echo $!", check=check)
        return int(res)
