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
import re
import subprocess
from collections.abc import Collection, Mapping, Sequence

from lib.constants import BOTS_DIR, DEFAULT_IDENTITY_FILE, OSTREE_IMAGES

from . import ssh_connection, timeout

LOCAL_MESSAGE = """
TTY LOGIN
  User: {ssh_user}/admin  Password: foobar
  To quit use Ctrl+], Ctrl+5 (depending on locale)

"""
REMOTE_MESSAGE = """
SSH ACCESS
  $ ssh -p {ssh_port} -i bots/machine/identity {ssh_user}@{ssh_address}

COCKPIT
  http://{web_address}:{web_port}
"""

RESOLV_SCRIPT = """
set -e
# HACK: Racing with operating systems reading/updating resolv.conf and
# the fact that resolv.conf can be a symbolic link. Avoid failures like:
# chattr: Operation not supported while reading flags on /etc/resolv.conf
mkdir -p /etc/NetworkManager/conf.d
printf '[main]\ndns=none\n' > /etc/NetworkManager/conf.d/dns.conf
systemctl reload-or-restart NetworkManager
printf 'domain {domain}\nsearch {domain}\nnameserver {nameserver}\n' >/etc/resolv2.conf
chcon -v unconfined_u:object_r:net_conf_t:s0 /etc/resolv2.conf 2> /dev/null || true
mv /etc/resolv2.conf /etc/resolv.conf
"""


class Machine(ssh_connection.SSHConnection):
    web_port: int | str

    def __init__(
        self,
        address: str = "127.0.0.1",
        image: str = "unknown",
        verbose: bool = False,
        label: str | None = None,
        browser: str | None = None,
        user: str = "root",
        identity_file: str | None = None,
        arch: str = "x86_64",
        ssh_port: int | str = 22,
        web_port: int | str = 9090
    ):
        identity_file_old = identity_file
        identity_file = identity_file or DEFAULT_IDENTITY_FILE

        if identity_file_old is None:
            os.chmod(identity_file, 0o600)
        if ":" in address:
            ssh_address, _, ssh_port = address.rpartition(":")
        else:
            ssh_address = address
        if not browser:
            browser = address

        if not label and image != "unknown":
            label = f"{image}-{ssh_address}-{ssh_port}"

        super().__init__(user, ssh_address, ssh_port, identity_file, verbose=verbose, label=label)

        self.arch = arch
        self.image = image
        self.ostree_image = self.image in OSTREE_IMAGES
        # start via cockpit/ws container on OSTree or when explicitly requested
        self.ws_container = self.ostree_image or "ws-container" in os.getenv("TEST_SCENARIO", "")

        if ":" in browser:
            self.web_address, _, self.web_port = browser.rpartition(":")
        else:
            self.web_address = browser
            self.web_port = web_port

        # The Linux kernel boot_id
        self.boot_id = None

    def diagnose(self, tty: bool = True) -> str:
        keys = {
            "ssh_user": self.ssh_user,
            "ssh_address": self.ssh_address,
            "ssh_port": self.ssh_port,
            "web_address": self.web_address,
            "web_port": self.web_port,
        }
        message = (LOCAL_MESSAGE if tty else '') + REMOTE_MESSAGE
        return message.format(**keys)

    def start(self) -> None:
        """Overridden by machine classes to start the machine"""
        self.message("Assuming machine is already running")

    def stop(self) -> None:
        """Overridden by machine classes to stop the machine"""
        self.message("Not shutting down already running machine")

    def wait_poweroff(self, timeout_sec: int = 120) -> None:
        """Overridden by machine classes to wait for a machine to stop"""
        raise NotImplementedError

    def kill(self) -> None:
        """Overridden by machine classes to unconditionally kill the running machine"""
        raise NotImplementedError

    def shutdown(self, timeout_sec: int = 120) -> None:
        """Overridden by machine classes to gracefully shutdown the running machine"""
        raise NotImplementedError

    def pull(self, image: str) -> str:
        """Download image.
        """
        if "/" in image:
            image_file = os.path.abspath(image)
        else:
            image_file = os.path.join(BOTS_DIR, "images", image)
        if not os.path.exists(image_file):
            try:
                subprocess.check_call([os.path.join(BOTS_DIR, "image-download"), image_file])
            except OSError as ex:
                if ex.errno != errno.ENOENT:
                    raise
        return image_file

    def journal_cursor(self) -> str:
        """Return current journal cursor

        This can be passed to journal_messages() or audit_messages().
        """
        return self.execute("journalctl --show-cursor -n0 -o cat | sed 's/^.*cursor: *//'")

    def journal_messages(self, matches: Collection[str], log_level: int, cursor: str | None = None) -> list[str]:
        """Return interesting journal messages"""

        # give the OS some time to write pending log messages, to make
        # unexpected message detection more reliable
        self.execute("sleep 1; journalctl --sync")

        # Prepend "SYSLOG_IDENTIFIER=" as a default field, for backwards compatibility
        filters = (m if re.match("[a-zA-Z0-9_]+=", m) else "SYSLOG_IDENTIFIER=" + m for m in matches)

        # Some versions of journalctl terminate unsuccessfully when
        # the output is empty.  We work around this by ignoring the
        # exit status and including error messages from journalctl
        # itself in the returned messages.

        if cursor:
            cursor_arg = "--cursor '%s'" % cursor
        else:
            cursor_arg = ""

        cmd = "journalctl 2>&1 %s -o cat -p %d %s || true" % (cursor_arg, log_level, " + ".join(filters))
        messages = self.execute(cmd).splitlines()
        if len(messages) == 1 and \
           ("Cannot assign requested address" in messages[0] or "-- No entries --" in messages[0]):
            # No messages
            return []
        else:
            return messages

    def audit_messages(self, type_pref: str, cursor: str | None = None) -> Sequence[str]:
        if cursor:
            cursor_arg = "--cursor '%s'" % cursor
        else:
            cursor_arg = ""

        cmd = f"journalctl {cursor_arg} -o cat SYSLOG_IDENTIFIER=kernel 2>&1 | grep 'type={type_pref}.*audit' || true"
        messages = self.execute(cmd).splitlines()
        if len(messages) == 1 and "Cannot assign requested address" in messages[0]:
            messages = []

        # SELinux full auditing; https://fedoraproject.org/wiki/SELinux/Debugging#Enable_full_auditing
        if any("avc:  denied" in m for m in messages):
            try:
                audit = self.execute("ausearch -i -m avc,user_avc,selinux_err,user_selinux_err "
                                     "--checkpoint /run/cockpit.ausearch.checkpoint --start checkpoint "
                                     "--input-logs")
                messages.extend(audit.strip().splitlines())
            except subprocess.CalledProcessError:
                pass  # opportunistic, and error message is in the log

        return messages

    def allowed_messages(self) -> Collection[str]:
        allowed = []
        if self.image.startswith('debian') or self.ostree_image:
            # These images don't have any non-C locales (mostly deliberate, to test this scenario somewhere)
            allowed.append("invalid or unusable locale: .*")

        if self.image == "arch":
            # Default PAM configuration logs motd for cockpit-session
            allowed.append(".*cockpit-session: pam: Web console: .*")

        if self.image == "centos-10":
            # https://issues.redhat.com/browse/RHEL-37631
            allowed.append('.*avc:  denied  { map_read map_write } for .* tclass=bpf.*')
            allowed.append('.*avc:  denied .* comm=daemon-init name=libvirt.*')
            # also need to ignore the corresponding ausearch
            allowed.append('----')
            allowed.append('type=(PROCTITLE|SYSCALL|EXECVE|PATH|CWD).*')

        if self.image in ["debian-testing", "ubuntu-2404", "ubuntu-stable"]:
            # https://bugs.launchpad.net/ubuntu/+source/libvirt/+bug/1989073
            allowed.append('audit.* apparmor="DENIED" operation="open" class="file" '
                           'profile=".*" name="/sys/devices/system/cpu/possible" .* '
                           'comm="qemu-system-x86" requested_mask="r" denied_mask="r".*')

        if self.image in ["debian-testing", "ubuntu-2404", "ubuntu-stable"]:
            # https://bugs.debian.org/1053706
            allowed.append(r"Process.*\(w\) .*dumped core.")
            # yes, this ignores all crash info; we can't help it
            allowed.append("^(Module|ELF|Stack trace|#[0-9]).*")

        return allowed

    def get_admin_group(self) -> str:
        if "debian" in self.image or "ubuntu" in self.image:
            return "sudo"
        else:
            return "wheel"

    def get_cockpit_container(self) -> str:
        return self.execute("podman ps --quiet --all --filter name=ws").strip()

    def start_cockpit(self, *, tls: bool = False) -> None:
        """Start Cockpit.

        Cockpit is not running when the test virtual machine starts up, to
        allow you to make modifications before it starts.
        """
        if self.ws_container:
            self.stop_cockpit()
            cmd = "podman container runlabel RUN cockpit/ws"
            if not tls:
                cmd += " -- --no-tls"
            self.execute(cmd)
            self.wait_for_cockpit_running()
        elif tls:
            self.execute("""
            systemctl stop --quiet cockpit.service
            rm -f /etc/systemd/system/cockpit.service.d/notls.conf
            systemctl reset-failed 'cockpit*'
            # unpredictable, see https://bugzilla.redhat.com/show_bug.cgi?id=2303828
            systemctl reset-failed cockpit.socket 2>/dev/null || true
            systemctl daemon-reload
            systemctl start cockpit.socket
            """)
        else:
            self.execute("""
            systemctl stop --quiet cockpit.service
            mkdir -p /etc/systemd/system/cockpit.service.d/
            rm -f /etc/systemd/system/cockpit.service.d/notls.conf
            printf "[Service]
            ExecStartPre=-/bin/sh -c 'echo 0 > /proc/sys/kernel/yama/ptrace_scope'
            ExecStart=
            %s --no-tls" `grep ExecStart= /lib/systemd/system/cockpit.service` \
                    > /etc/systemd/system/cockpit.service.d/notls.conf
            systemctl reset-failed 'cockpit*'
            systemctl reset-failed cockpit.socket 2>/dev/null || true
            systemctl daemon-reload
            systemctl start cockpit.socket
            """)

    def restart_cockpit(self) -> None:
        """Restart Cockpit.
        """
        if self.ws_container:
            self.execute(f"podman restart {self.get_cockpit_container()}")
            self.wait_for_cockpit_running()
        else:
            self.execute("systemctl reset-failed 'cockpit*'; systemctl restart cockpit")

    def stop_cockpit(self) -> None:
        """Stop Cockpit.
        """
        if self.ws_container:
            self.execute(f"echo {self.get_cockpit_container()} | xargs --no-run-if-empty podman rm -f")
        else:
            self.execute("systemctl stop cockpit.socket cockpit.service")

    def set_address(self, address: str, mac: str = '52:54:01') -> None:
        """Set IP address for the network interface with given mac prefix"""
        # HACK: ':' causes some trouble, escape it: https://bugzilla.redhat.com/show_bug.cgi?id=2151504
        name = f"static-{mac.replace(':', '-')}"
        self.execute(f"""set -eu
             iface=$(grep -l '{mac}' /sys/class/net/*/address | cut -d / -f 5)
             nmcli con add type ethernet autoconnect yes con-name {name} ifname $iface ip4 {address}
             nmcli con delete $iface || true # may not have an active connection
             nmcli con up {name}""")

    def set_dns(self, nameserver: str | None = None, domain: str | None = None) -> None:
        self.execute(RESOLV_SCRIPT.format(nameserver=nameserver or "127.0.0.1", domain=domain or "cockpit.lan"))

    def dhcp_server(
        self, mac: str = '52:54:01', dhcp_range: tuple[str, str] = ('10.111.112.2', '10.111.127.254')
    ) -> None:
        """Sets up a DHCP server on the interface"""
        self.execute(fr"""
             dnsmasq \
                --domain=cockpit.lan \
                --interface="$(grep -l '{mac}' /sys/class/net/*/address | cut -d / -f 5)" \
                --bind-interfaces \
                --dhcp-range={','.join(dhcp_range)},4h

            systemctl start firewalld
            firewall-cmd --add-service=dhcp
        """)

    def dns_server(self, mac: str = '52:54:01') -> None:
        """Sets up a DNS server on the interface"""
        self.execute(fr"""
            dnsmasq \
                --domain=cockpit.lan \
                --interface="$(grep -l '{mac}' /sys/class/net/*/address | cut -d / -f 5)" \
                --bind-dynamic
        """)

    def wait_for_cockpit_running(
        self, address: str = "localhost", port: int = 9090, seconds: int = 30, tls: bool = False
    ) -> None:
        proto = 'https' if tls else 'http'
        WAIT_COCKPIT_RUNNING = fr"""
        until curl --insecure --silent --connect-timeout 2 --max-time 3 {proto}://{address}:{port} >/dev/null; do
            sleep 0.5;
        done;
        """
        with timeout.Timeout(seconds=seconds, error_message="Timeout while waiting for cockpit to start"):
            self.execute(WAIT_COCKPIT_RUNNING)

    def curl(self, *args: str, headers: Mapping[str, str] = {}) -> str:
        cmd = ['curl', '--silent', '--show-error']
        for key, value in headers.items():
            cmd.extend(['--header', f'{key}: {value}'])
        return self.execute(cmd + list(args))
