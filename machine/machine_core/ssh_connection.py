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


import os
import time
import socket
import subprocess
import select
import errno
import shlex
import sys
import tempfile

from . import exceptions
from . import timeout as timeoutlib

# HACK: some projects directly import ssh_connection before adjusting sys.path; add bots root dir
sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from lib.constants import TEST_DIR


def write_all(fd, data):
    while len(data) > 0:
        select.select([], [fd], [])
        written = os.write(fd, data)
        data = data[written:]


class SSHConnection(object):
    ssh_default_opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "PKCS11Provider=none"]

    def __init__(self, user, address, ssh_port, identity_file, verbose=False, label=None):
        self.verbose = verbose

        # Currently all images are x86_64. When that changes we will have
        # an override file for those images that are not
        self.ssh_user = user
        self.identity_file = identity_file
        self.ssh_address = address
        self.ssh_port = ssh_port
        self.ssh_master = None
        self.ssh_process = None
        self.ssh_reachable = False
        self.label = label if label else "{}@{}:{}".format(self.ssh_user, self.ssh_address, self.ssh_port)

    def disconnect(self):
        self.ssh_reachable = False
        self._kill_ssh_master()

    def message(self, *args):
        """Prints args if in verbose mode"""
        if self.verbose:
            sys.stderr.write(" ".join(args) + '\n')

    # wait until we can execute something on the machine. ie: wait for ssh
    def wait_execute(self, timeout_sec=120):
        """Try to connect to self.address on ssh port"""

        # If connected to machine, kill master connection
        self._kill_ssh_master()

        start_time = time.time()
        while (time.time() - start_time) < timeout_sec:
            addrinfo = socket.getaddrinfo(self.ssh_address, self.ssh_port, 0, socket.SOCK_STREAM)
            (family, socktype, proto, canonname, sockaddr) = addrinfo[0]
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(5)
                try:
                    sock.connect(sockaddr)
                    data = sock.recv(10)
                    if len(data):
                        self.ssh_reachable = True
                        return True
                except IOError:
                    time.sleep(0.5)
        return False

    def wait_user_login(self):
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

    def wait_boot(self, timeout_sec=120):
        """Wait for a machine to boot"""
        start_time = time.time()
        boot_id = None
        while (time.time() - start_time) < timeout_sec:
            if self.wait_execute(timeout_sec=15):
                boot_id = self.wait_user_login()
                if boot_id:
                    break
        if not boot_id:
            raise exceptions.Failure("Unable to reach machine {0} via ssh: {1}:{2}".format(
                self.label, self.ssh_address, self.ssh_port))
        self.boot_id = boot_id

    def wait_reboot(self, timeout_sec=180):
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

    def reboot(self, timeout_sec=180):
        self.spawn("reboot", "reboot", check=False)
        if timeout_sec:
            self.wait_reboot(timeout_sec)

    def _start_ssh_master(self):
        self._kill_ssh_master()

        control = os.path.join(tempfile.gettempdir(), ".cockpit-test-resources", "ssh-%h-%p-%r-" + str(os.getpid()))
        os.makedirs(os.path.dirname(control), exist_ok=True)

        cmd = [
            "ssh",
            "-p", str(self.ssh_port),
            "-i", self.identity_file,
            *self.ssh_default_opts,
            "-M",  # ControlMaster, no stdin
            "-o", "ControlPath=" + control,
            "-o", "LogLevel=ERROR",
            "-l", self.ssh_user,
            self.ssh_address,
            "/bin/bash -c 'echo READY; read a'"
        ]

        # Connection might be refused, so try this 10 times
        tries_left = 10
        while tries_left > 0:
            tries_left = tries_left - 1
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
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
                raise exceptions.Failure("SSH master process exited with code: {0}".format(proc.returncode))

        self.ssh_master = control
        self.ssh_process = proc

        if not self._check_ssh_master():
            raise exceptions.Failure("Couldn't launch an SSH master process")

    def _kill_ssh_master(self):
        if self.ssh_master:
            try:
                os.unlink(self.ssh_master)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            self.ssh_master = None
        if self.ssh_process:
            self.message("killing ssh master process", str(self.ssh_process.pid))
            self.ssh_process.stdin.close()
            self.ssh_process.terminate()
            self.ssh_process.stdout.close()
            with timeoutlib.Timeout(seconds=90, error_message="Timeout while waiting for ssh master to shut down"):
                self.ssh_process.wait()
            self.ssh_process = None

    def _check_ssh_master(self):
        if not self.ssh_master:
            return False
        cmd = [
            "ssh",
            "-q",
            "-p", str(self.ssh_port),
            *self.ssh_default_opts,
            "-S", self.ssh_master,
            "-O", "check",
            "-l", self.ssh_user,
            self.ssh_address
        ]
        with open(os.devnull, 'w') as devnull:
            code = subprocess.call(cmd, stdin=devnull, stdout=devnull, stderr=devnull)
            if code == 0:
                self.ssh_reachable = True
                return True
        return False

    def _ensure_ssh_master(self):
        if not self._check_ssh_master():
            self._start_ssh_master()

    def __ssh_direct_opt_var(self, direct=False):
        return os.getenv("TEST_SSH_DIRECT", direct)

    def __execution_opts(self, direct=False):
        direct = self.__ssh_direct_opt_var(direct=direct)
        if direct:
            return ["-i", self.identity_file]
        else:
            return ["-o", "ControlPath=" + self.ssh_master]

    def execute(self, command, input=None, environment={},
                stdout=subprocess.PIPE, quiet=False, direct=False, timeout=120,
                ssh_env=["env", "-u", "LANGUAGE", "LC_ALL=C"], check=True):
        """Execute a shell command in the test machine and return its output.

            command: The string or argument list to execute by /bin/sh (still with shell interpretation)
            input: Input to send to the command
            environment: Additional environment variables
            timeout: Applies if not already wrapped in a #Timeout context
        Returns:
            The command output as a string.
        """
        assert command
        assert self.ssh_address

        if not self.__ssh_direct_opt_var(direct=direct):
            self._ensure_ssh_master()

        default_ssh_params = [
            "ssh",
            "-p", str(self.ssh_port),
            *self.ssh_default_opts,
            "-o", "LogLevel=ERROR",
            "-l", self.ssh_user,
            self.ssh_address
        ]
        additional_ssh_params = []

        cmd = ['set -e;']
        cmd += [f'export {name}={shlex.quote(value)}; ' for name, value in environment.items()]

        additional_ssh_params += self.__execution_opts(direct=direct)

        if getattr(command, "strip", None):  # Is this a string?
            cmd += [command]
            if not quiet:
                self.message("+", command)
        else:
            # use shlex.join() once Python 3.8 is available everywhere
            cmd.append(' '.join(shlex.quote(arg) for arg in command))
            if not quiet:
                self.message("+", *command)
        command_line = ssh_env + default_ssh_params + additional_ssh_params + cmd

        with timeoutlib.Timeout(seconds=timeout, error_message="Timed out on '%s'" % command, machine=self):
            res = subprocess.run(command_line,
                                 input=input.encode("UTF-8") if input else b'',
                                 stdout=stdout, check=check)

        return None if res.stdout is None else res.stdout.decode("UTF-8", "replace")

    def upload(self, sources, dest, relative_dir=TEST_DIR, use_scp=False):
        """Upload a file into the test machine

        Arguments:
            sources: the array of paths of the file to upload
            dest: the file path in the machine to upload to
        """
        assert sources and dest
        assert self.ssh_address

        if not self.__ssh_direct_opt_var():
            self._ensure_ssh_master()

        if use_scp:
            cmd = [
                "scp",
                "-r", "-p",
                "-P", str(self.ssh_port),
                *self.__execution_opts(),
            ]
            if not self.verbose:
                cmd += ["-q"]
        else:
            cmd = [
                "rsync",
                "--recursive", "--perms", "--copy-links",
                "-e",
                f"ssh -p {self.ssh_port} " + " ".join([shlex.quote(o) for o in self.__execution_opts()]),
            ]
            if self.verbose:
                cmd += ["--verbose"]

        def relative_to_test_dir(path):
            return os.path.join(relative_dir, path)
        cmd += map(relative_to_test_dir, sources)

        cmd += [f"{self.ssh_user}@[{self.ssh_address}]:{dest}"]

        self.message("Uploading", ", ".join(sources))
        self.message(" ".join([shlex.quote(a) for a in cmd]))
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            if not use_scp and e.returncode == 127:
                self.message("rsync not available, falling back to scp")
                self.upload(sources, dest, relative_dir, use_scp=True)
            else:
                raise

    def download(self, source, dest, relative_dir=TEST_DIR):
        """Download a file from the test machine.
        """
        assert source and dest
        assert self.ssh_address

        if not self.__ssh_direct_opt_var():
            self._ensure_ssh_master()
        dest = os.path.join(relative_dir, dest)

        cmd = [
            "rsync",
            "-e", f"ssh -p {self.ssh_port} " + " ".join([shlex.quote(o) for o in self.__execution_opts()]),
        ]
        if self.verbose:
            cmd += ["--verbose"]
        cmd += [f"{self.ssh_user}@[{self.ssh_address}]:{source}", dest]

        self.message("Downloading", source)
        self.message(" ".join(cmd))
        subprocess.check_call(cmd)

    def download_dir(self, source, dest, relative_dir=TEST_DIR):
        """Download a directory from the test machine, recursively.
        """
        assert source and dest
        assert self.ssh_address

        if not self.__ssh_direct_opt_var():
            self._ensure_ssh_master()
        dest = os.path.join(relative_dir, dest)

        cmd = [
            "rsync",
            "--recursive", "--copy-links",
            "-e", f"ssh -p {self.ssh_port} " + " ".join([shlex.quote(o) for o in self.__execution_opts()]),
        ]
        if self.verbose:
            cmd += ["--verbose"]
        cmd += [f"{self.ssh_user}@[{self.ssh_address}]:{source}", dest]

        self.message("Downloading", source)
        self.message(" ".join(cmd))
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            self.message("Error while downloading directory '{0}'".format(source))

    def write(self, dest, content, append=False, owner=None, perm=None):
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
        assert self.ssh_address

        self.execute(["mkdir", "-p", os.path.dirname(dest)])
        self.execute(f"cat {append and '>>' or '>'} {shlex.quote(dest)}", input=content)
        if owner:
            self.execute(["chown", owner, dest])
        if perm:
            self.execute(["chmod", perm, dest])

    def spawn(self, shell_cmd, log_id, check=True):
        """Spawn a process in the test machine.

        Arguments:
           shell_cmd: The string to execute by /bin/sh.
           log_id: The name of the file, realtive to /var/log on the test
              machine, that will receive stdout and stderr of the command.
        Returns:
            The pid of the /bin/sh process that executes the command.
        """
        res = self.execute(f"{{ ({shell_cmd}) >/var/log/{log_id} 2>&1 & }}; echo $!",
                           check=check)
        if not check:
            return None
        return int(res)
