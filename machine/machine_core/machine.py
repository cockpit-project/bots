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
    def __init__(self, address="127.0.0.1", image="unknown", verbose=False, label=None, browser=None,
                 user="root", identity_file=None, arch="x86_64", ssh_port=22, web_port=9090):

        identity_file_old = identity_file
        identity_file = identity_file or DEFAULT_IDENTITY_FILE

        if identity_file_old is None:
            os.chmod(identity_file, 0o600)
        if ":" in address:
            (ssh_address, unused, ssh_port) = address.rpartition(":")
        else:
            ssh_address = address
        if not browser:
            browser = address

        if not label and image != "unknown":
            label = "{}-{}-{}".format(image, ssh_address, ssh_port)

        super(Machine, self).__init__(user, ssh_address, ssh_port, identity_file, verbose=verbose, label=label)

        self.arch = arch
        self.image = image
        self.ostree_image = self.image in OSTREE_IMAGES
        if ":" in browser:
            (self.web_address, unused, self.web_port) = browser.rpartition(":")
        else:
            self.web_address = browser
            self.web_port = web_port

        # The Linux kernel boot_id
        self.boot_id = None

    def diagnose(self, tty=True):
        keys = {
            "ssh_user": self.ssh_user,
            "ssh_address": self.ssh_address,
            "ssh_port": self.ssh_port,
            "web_address": self.web_address,
            "web_port": self.web_port,
        }
        message = (tty and LOCAL_MESSAGE or '') + REMOTE_MESSAGE
        return message.format(**keys)

    def start(self):
        """Overridden by machine classes to start the machine"""
        self.message("Assuming machine is already running")

    def stop(self):
        """Overridden by machine classes to stop the machine"""
        self.message("Not shutting down already running machine")

    def wait_poweroff(self, timeout_sec=120):
        """Overridden by machine classes to wait for a machine to stop"""
        assert False, "Cannot wait for a machine we didn't start"

    def kill(self):
        """Overridden by machine classes to unconditionally kill the running machine"""
        assert False, "Cannot kill a machine we didn't start"

    def shutdown(self, timeout_sec=120):
        """Overridden by machine classes to gracefully shutdown the running machine"""
        assert False, "Cannot shutdown a machine we didn't start"

    def pull(self, image):
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

    def journal_cursor(self):
        """Return current journal cursor

        This can be passed to journal_messages() or audit_messages().
        """
        return self.execute("journalctl --show-cursor -n0 -o cat | sed 's/^.*cursor: *//'")

    def journal_messages(self, matches, log_level, cursor=None):
        """Return interesting journal messages"""

        # give the OS some time to write pending log messages, to make
        # unexpected message detection more reliable; RHEL/CentOS 7 does not
        # yet know about --sync, so ignore failures
        self.execute("journalctl --sync 2>/dev/null || true; sleep 1; journalctl --sync 2>/dev/null || true")

        # Prepend "SYSLOG_IDENTIFIER=" as a default field, for backwards compatibility
        matches = map(lambda m: m if re.match("[a-zA-Z0-9_]+=", m) else "SYSLOG_IDENTIFIER=" + m, matches)

        # Some versions of journalctl terminate unsuccessfully when
        # the output is empty.  We work around this by ignoring the
        # exit status and including error messages from journalctl
        # itself in the returned messages.

        if cursor:
            cursor_arg = "--cursor '%s'" % cursor
        else:
            cursor_arg = ""

        cmd = "journalctl 2>&1 %s -o cat -p %d %s || true" % (cursor_arg, log_level, " + ".join(matches))
        messages = self.execute(cmd).splitlines()
        if len(messages) == 1 and \
           ("Cannot assign requested address" in messages[0] or "-- No entries --" in messages[0]):
            # No messages
            return []
        else:
            return messages

    def audit_messages(self, type_pref, cursor=None):
        if cursor:
            cursor_arg = "--cursor '%s'" % cursor
        else:
            cursor_arg = ""

        cmd = "journalctl %s -o cat SYSLOG_IDENTIFIER=kernel 2>&1 | grep 'type=%s.*audit' || true" % (
            cursor_arg, type_pref,)
        messages = self.execute(cmd).splitlines()
        if len(messages) == 1 and "Cannot assign requested address" in messages[0]:
            messages = []
        return messages

    def allowed_messages(self):
        allowed = []
        if self.image.startswith('debian') or self.ostree_image:
            # These images don't have any non-C locales (mostly deliberate, to test this scenario somewhere)
            allowed.append("invalid or unusable locale: .*")

        if self.image == "arch":
            # Default PAM configuration logs motd for cockpit-session
            allowed.append(".*cockpit-session: pam: Web console: .*")

        if self.image in ["fedora-37", "fedora-testing"]:
            # https://bugzilla.redhat.com/show_bug.cgi?id=2083900
            allowed.append('audit.*denied  { sys_admin } .* comm="systemd-gpt-aut".*')

        if self.image in ["fedora-37", "fedora-testing", "fedora-coreos"]:
            # https://bugzilla.redhat.com/show_bug.cgi?id=2122888
            allowed.append('audit.*denied  { sys_admin } .* comm="mv" .*NetworkManager_dispatcher_console_t.*')

        if self.image in ["debian-testing", "ubuntu-stable"]:
            # https://bugs.launchpad.net/ubuntu/+source/libvirt/+bug/1989073
            allowed.append('audit.* apparmor="DENIED" operation="open" class="file" ' +
                           'profile=".*" name="/sys/devices/system/cpu/possible" .* ' +
                           'comm="qemu-system-x86" requested_mask="r" denied_mask="r".*')

        if self.image in ["rhel-8-6", "rhel-9-0"]:
            # https://bugzilla.redhat.com/show_bug.cgi?id=2124550 / https://bugzilla.redhat.com/show_bug.cgi?id=2124549
            allowed.append(
                'audit.*denied  { read .* for.*comm="gpg" .* tcontext=unconfined_u:object_r:admin_home_t.*'
            )
            allowed.append("Error importing insights.client.*newest.egg: No module named 'insights'")

        return allowed

    def get_admin_group(self):
        if "debian" in self.image or "ubuntu" in self.image:
            return "sudo"
        else:
            return "wheel"

    def get_cockpit_container(self):
        return self.execute("podman ps --quiet --all --filter name=ws").strip()

    def start_cockpit(self, atomic_wait_for_host=None, tls=False):
        """Start Cockpit.

        Cockpit is not running when the test virtual machine starts up, to
        allow you to make modifications before it starts.
        """

        if self.ostree_image:
            self.stop_cockpit()
            cmd = "podman container runlabel RUN cockpit/ws"
            if not tls:
                cmd += " -- --no-tls"
            self.execute(cmd)
            self.wait_for_cockpit_running(atomic_wait_for_host or "localhost")
        elif tls:
            self.execute("""
            rm -f /etc/systemd/system/cockpit.service.d/notls.conf &&
            systemctl reset-failed 'cockpit*' &&
            systemctl daemon-reload &&
            systemctl stop --quiet cockpit.service &&
            systemctl start cockpit.socket
            """)
        else:
            self.execute("""
            mkdir -p /etc/systemd/system/cockpit.service.d/ &&
            rm -f /etc/systemd/system/cockpit.service.d/notls.conf &&
            printf "[Service]
            ExecStartPre=-/bin/sh -c 'echo 0 > /proc/sys/kernel/yama/ptrace_scope'
            ExecStart=
            %s --no-tls" `grep ExecStart= /lib/systemd/system/cockpit.service` \
                    > /etc/systemd/system/cockpit.service.d/notls.conf &&
            systemctl reset-failed 'cockpit*' &&
            systemctl daemon-reload &&
            systemctl stop --quiet cockpit.service &&
            systemctl start cockpit.socket
            """)

    def restart_cockpit(self):
        """Restart Cockpit.
        """
        if self.ostree_image:
            # HACK: podman restart is broken (https://bugzilla.redhat.com/show_bug.cgi?id=1780161)
            # self.execute("podman restart `podman ps --quiet --filter ancestor=cockpit/ws`")
            inspect_res = self.execute("podman inspect {0}".format(self.get_cockpit_container()))
            tls = "--no-tls" not in inspect_res
            self.stop_cockpit()
            self.start_cockpit(tls=tls)
            self.wait_for_cockpit_running()
        else:
            self.execute("systemctl reset-failed 'cockpit*'; systemctl restart cockpit")

    def stop_cockpit(self):
        """Stop Cockpit.
        """
        if self.ostree_image:
            self.execute("echo {0} | xargs --no-run-if-empty podman rm -f".format(self.get_cockpit_container()))
        else:
            self.execute("systemctl stop cockpit.socket cockpit.service")

    def set_address(self, address, mac='52:54:01'):
        """Set IP address for the network interface with given mac prefix"""
        # HACK: ':' causes some trouble, escape it: https://bugzilla.redhat.com/show_bug.cgi?id=2151504
        name = f"static-{mac.replace(':', '-')}"
        self.execute(f"""set -eu
             iface=$(grep -l '{mac}' /sys/class/net/*/address | cut -d / -f 5)
             nmcli con add type ethernet autoconnect yes con-name {name} ifname $iface ip4 {address}
             nmcli con delete $iface || true # may not have an active connection
             nmcli con up {name}""")

    def set_dns(self, nameserver=None, domain=None):
        self.execute(RESOLV_SCRIPT.format(nameserver=nameserver or "127.0.0.1", domain=domain or "cockpit.lan"))

    def dhcp_server(self, mac='52:54:01', range=['10.111.112.2', '10.111.127.254']):
        """Sets up a DHCP server on the interface"""
        cmd = "dnsmasq --domain=cockpit.lan " \
              "--interface=\"$(grep -l '{mac}' /sys/class/net/*/address | cut -d / -f 5)\"" \
              " --bind-interfaces --dhcp-range=" + ','.join(range) + ",4h" + \
              " && firewall-cmd --add-service=dhcp"
        self.execute(cmd.format(mac=mac))

    def dns_server(self, mac='52:54:01'):
        """Sets up a DNS server on the interface"""
        cmd = "dnsmasq --domain=cockpit.lan " \
              "--interface=\"$(grep -l '{mac}' /sys/class/net/*/address | cut -d / -f 5)\"" \
              " --bind-dynamic"
        self.execute(cmd.format(mac=mac))

    def wait_for_cockpit_running(self, address="localhost", port=9090, seconds=30, tls=False):
        WAIT_COCKPIT_RUNNING = """
        until curl --insecure --silent --connect-timeout 2 --max-time 3 %s://%s:%s >/dev/null; do
            sleep 0.5;
        done;
        """ % (tls and "https" or "http", address, port)
        with timeout.Timeout(seconds=seconds, error_message="Timeout while waiting for cockpit to start"):
            self.execute(WAIT_COCKPIT_RUNNING)

    def curl(self, *args, headers=None):
        cmd = ['curl', '--silent', '--show-error']
        if headers is not None:
            for key, value in headers.items():
                cmd.extend(['--header', f'{key}: {value}'])
        return self.execute(cmd + list(args))
