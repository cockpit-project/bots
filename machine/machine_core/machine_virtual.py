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

import contextlib
import fcntl
import os
import shlex
import socket
import string
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from typing import IO, Any, TextIO

import libvirt
import libvirt_qemu

from lib.constants import (
    BOTS_DIR,
    DEFAULT_BOOT_TIMEOUT,
    DEFAULT_MACHINE_MEMORY_MB,
    DEFAULT_SHUTDOWN_TIMEOUT,
    TEST_DIR,
)

from .exceptions import Failure
from .machine import Machine

sys.path.insert(1, BOTS_DIR)


# based on http://stackoverflow.com/a/17753573
# we use this to quieten down calls
@contextlib.contextmanager
def stdchannel_redirected(stdchannel: TextIO, dest_filename: str) -> Iterator[None]:
    """
    A context manager to temporarily redirect stdout or stderr
    e.g.:
    with stdchannel_redirected(sys.stderr, os.devnull):
        noisy_function()
    """
    try:
        stdchannel.flush()
        oldstdchannel = os.dup(stdchannel.fileno())
        dest_file = open(dest_filename, 'w')
        os.dup2(dest_file.fileno(), stdchannel.fileno())
        yield
    finally:
        if oldstdchannel is not None:
            os.dup2(oldstdchannel, stdchannel.fileno())
        if dest_file is not None:
            dest_file.close()


TEST_DOMAIN_XML = """
<domain type='{type}' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>
  <name>{label}</name>
  {cpu}
  <os>
    <type arch='{arch}'>hvm</type>
  </os>
  <memory unit='MiB'>{memory_in_mib}</memory>
  <currentMemory unit='MiB'>{memory_in_mib}</currentMemory>
  <features>
    <acpi/>
  </features>
  <devices>
    <disk type='file'>
      <driver name='qemu' type='qcow2' cache='unsafe'/>
      <source file='{drive}'/>
      <target dev='{disk_dev}' bus='{disk_bus}'/>
      <serial>ROOT</serial>
      <boot order='2'/>
    </disk>
    <controller type='scsi' model='virtio-scsi' index='0' id='hot'/>
    <graphics type='vnc' autoport='yes' listen='127.0.0.1'>
      <listen type='address' address='127.0.0.1'/>
    </graphics>
    <console type='{console_type}'>
      <target type='serial' port='0'/>
      {console_source}
    </console>
    <disk type='file' device='cdrom'>
      <source file='{iso}'/>
      <target dev='hdb' bus='ide'/>
      <readonly/>
    </disk>
    <rng model='virtio'>
      <backend model='random'>/dev/urandom</backend>
    </rng>
    <tpm model='tpm-crb'>
      <backend type='emulator' version='2.0'>
        <profile name='default-v1'/>
      </backend>
      <alias name='tpm0'/>
    </tpm>
  </devices>
  <qemu:commandline>
    {ethernet}
    {firmware}
    <qemu:arg value='-netdev'/>
    <qemu:arg
      value='user,id=base0,restrict={restrict},net=172.27.0.0/24,dnssearch=loopback,hostname={hostname},{forwards}'/>
    <qemu:arg value='-device'/>
    <qemu:arg value='virtio-net-pci,netdev=base0,bus=pci.0,addr=0x0e'/>
  </qemu:commandline>
</domain>
"""

TEST_DISK_XML = """
<disk type='file'>
  <driver name='qemu' type='%(type)s' cache='unsafe' />
  <source file='%(file)s'/>
  <serial>%(serial)s</serial>
  <address type='drive' controller='0' bus='0' target='2' unit='%(unit)d'/>
  <target dev='%(dev)s' bus='scsi'/>
  %(extra)s
</disk>
"""

TEST_KVM_XML = """
  <cpu mode='host-passthrough'/>
  <vcpu>{cpus}</vcpu>
"""

# The main network interface which we use to communicate between VMs
TEST_MCAST_XML = """
    <qemu:arg value='-netdev'/>
    <qemu:arg value='socket,mcast=230.0.0.1:{mcast},id=mcast0,localaddr=127.0.0.1'/>
    <qemu:arg value='-device'/>
    <qemu:arg value='virtio-net-pci,netdev=mcast0,mac={mac},bus=pci.0,addr=0x0f'/>
"""

TEST_USERNET_XML = """
    <qemu:arg value='-netdev'/>
    <qemu:arg value='user,id=user0'/>
    <qemu:arg value='-device'/>
    <qemu:arg value='virtio-net-pci,netdev=user0,mac={mac},bus=pci.0,addr=0x0f'/>
"""


class VirtNetwork:
    def __init__(self, network: int | None = None, image: str = "generic"):
        self.locked: list[int] = []  # fds
        self.image = image

        if network is None:
            offset = 0
            force = False
        else:
            offset = network * 100
            force = True

        # This is a shared port used as the identifier for the socket mcast network
        self.network = self._lock(5500 + offset, step=100, force=force)

        # An offset for other ports allocated later
        self.offset = (self.network - 5500)

        # The last machine we allocated
        self.last = 0

        # Unique hostnet identifiers
        self.hostnet = 8

    def _lock(self, start: int, step: int = 1, force: bool = False) -> int:
        resources = os.path.join(tempfile.gettempdir(), ".cockpit-test-resources")
        os.makedirs(resources, 0o755, exist_ok=True)
        for port in range(start, start + (100 * step), step):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                lockpath = os.path.join(resources, f"network-{port}")
                try:
                    lockf = os.open(lockpath, os.O_WRONLY | os.O_CREAT)
                    fcntl.flock(lockf, fcntl.LOCK_NB | fcntl.LOCK_EX)
                    sock.bind(("127.0.0.1", port))
                    self.locked.append(lockf)
                except OSError:
                    if not force:
                        os.close(lockf)
                        continue

                return port
        raise Failure("Couldn't find unique network port number")

    # Create resources for an interface, returns address and XML
    def interface(self, number: int | None = None) -> dict[str, Any]:
        if number is None:
            number = self.last + 1
        if number > self.last:
            self.last = number
        mac = self._lock(10000 + self.offset + number) - (10000 + self.offset)
        hostnet = self.hostnet
        self.hostnet += 1
        result = {
            "number": self.offset + number,
            "mac": f'52:54:01:{(mac >> 16) & 0xff:02x}:{(mac >> 8) & 0xff:02x}:{mac & 0xff:02x}',
            "name": f"m{mac}.cockpit.lan",
            "mcast": self.network,
            "hostnet": f"hostnet{hostnet}"
        }
        return result

    def host(
        self,
        number: int | None = None,
        restrict: bool = False,
        isolate: str | bool = False,
        forward: Mapping[str, int] = {}
    ) -> dict[str, Any]:
        """Create resources for a host, returns address and XML

        isolate: True for no network at all, "user" for QEMU user network instead of bridging
        """
        localaddr = '' if os.getenv('TEST_BIND_GLOBAL') else '127.0.0.2'
        result = self.interface(number)
        result["mcast"] = self.network
        result["restrict"] = "on" if restrict else "off"
        result["forward"] = {"22": 2200, "9090": 9090}
        result["forward"].update(forward)
        forwards = []
        for remote, local in result["forward"].items():
            local = self._lock(int(local) + result["number"])
            result["forward"][remote] = f"{localaddr or '127.0.0.1'}:{local}"
            forwards.append(f"hostfwd=tcp:{localaddr}:{local}-:{remote}")
            if remote == "22":
                result["control"] = result["forward"][remote]
            elif remote == "9090":
                result["browser"] = result["forward"][remote]

        if isolate == 'user':
            result["ethernet"] = TEST_USERNET_XML.format(**result)
        elif isolate:
            result["ethernet"] = ""
        else:
            result["ethernet"] = TEST_MCAST_XML.format(**result)
        result["forwards"] = ",".join(forwards)
        return result

    def kill(self) -> None:
        locked = self.locked
        self.locked = []
        for x in locked:
            os.close(x)


class VirtMachine(Machine):
    networking: dict[str, Any]
    virt_connection: libvirt.virConnect | None
    _transient_image: IO[bytes] | None
    _domain: libvirt.virDomain | None

    network: int | None = None
    memory_mb: int | None = None
    cpus: int | None = None
    is_efi: bool = False
    image_file: str
    run_dir: str
    disk_bus: str = 'virtio'
    disk_dev: str = 'vda'

    # Cache for nested virtualization detection
    _is_nested_virt: bool | None = None

    def __init__(
        self,
        image: str,
        networking: dict[str, Any] | None = None,
        maintain: bool = False,
        memory_mb: int | None = None,
        cpus: int | None = None,
        capture_console: bool = True,
        **kwargs: Any
    ):
        self.maintain = maintain

        self.memory_mb = memory_mb or VirtMachine.memory_mb or DEFAULT_MACHINE_MEMORY_MB
        self.cpus = cpus or VirtMachine.cpus or 1
        if capture_console:
            console_file = tempfile.NamedTemporaryFile(suffix='.log', prefix='console-')
        else:
            console_file = None
        self.console_file = console_file
        self.is_efi = "-efi" in image

        # Set up some temporary networking info if necessary
        if networking is None:
            networking = VirtNetwork(image=image).host()

        if "disk_bus" in kwargs:
            self.disk_bus = str(kwargs.pop("disk_bus"))
        if "disk_dev" in kwargs:
            self.disk_dev = str(kwargs.pop("disk_dev"))

        # Allocate network information about this machine
        self.networking = networking
        kwargs["address"] = networking["control"]
        kwargs["browser"] = networking["browser"]
        self.forward = networking["forward"]

        # The path to the image file to load, and parse an image name
        if "/" in image:
            self.image_file = image = os.path.abspath(image)
        else:
            self.image_file = os.path.join(TEST_DIR, "images", image)
            if not os.path.lexists(self.image_file):
                self.image_file = os.path.join(BOTS_DIR, "images", image)
        image, _extension = os.path.splitext(os.path.basename(image))

        Machine.__init__(self, image=image, **kwargs)

        overlay_dir = os.getenv("TEST_OVERLAY_DIR")
        if not overlay_dir:
            # toolbox compatibility: /tmp is shared with the host, but may be too small for big overlays (tmpfs!)
            # $HOME is shared, but we don't want to put our junk there (NFS, backups)
            # /var/tmp is not shared with the host but the right place; just in case session libvirtd is already
            # running, use the shared path so that the daemon can actually see our overlay.
            # But this only makes sense if the host also has /run/host set up (toolbox ships a tmpfiles.d)
            if os.path.exists("/run/host/var/tmp") and os.path.exists("/run/host/run/host"):
                overlay_dir = "/run/host/var/tmp"
            else:
                overlay_dir = "/var/tmp"
        self.run_dir = os.path.join(overlay_dir, "bots-run")
        os.makedirs(self.run_dir, 0o700, exist_ok=True)

        self.virt_connection = self._libvirt_connection(hypervisor="qemu:///session")

        self._disks: list[dict[str, Any]] = []
        self._domain = None
        self._transient_image = None

        # init variables needed for running a vm
        self._cleanup()

    def _libvirt_connection(self, hypervisor: str, read_only: bool = False) -> libvirt.virConnect:
        tries_left = 5
        connection = None
        if read_only:
            open_function = libvirt.openReadOnly
        else:
            open_function = libvirt.open
        while not connection and (tries_left > 0):
            try:
                connection = open_function(hypervisor)
            except libvirt.libvirtError:
                # wait a bit
                time.sleep(1)
            tries_left -= 1
        if not connection:
            # try again, but if an error occurs, don't catch it
            connection = open_function(hypervisor)
        return connection

    def _start_qemu(self) -> None:
        self._cleanup()

        if not self.maintain:
            self._transient_image = tempfile.NamedTemporaryFile(suffix='.qcow2', prefix='cockpit-', dir=self.run_dir)
            cmd = ['qemu-img', 'create', '-q', '-f', 'qcow2', '-b', self.image_file]
            # specify the backing format (libvirt complains otherwise)
            with open(self.image_file, "rb") as f:
                if f.read(3) == b"QFI":
                    cmd.extend(['-F', 'qcow2'])
                else:
                    cmd.extend(['-F', 'raw'])
            image_to_use = self._transient_image.name
            cmd.append(image_to_use)
            self.message(shlex.join(cmd))
            subprocess.check_call(cmd)
        else:
            image_to_use = self.image_file

        keys: dict[str, Any] = {
            "label": self.label,
            "image": self.image,
            "type": "qemu",
            "arch": self.arch,
            "cpu": "",
            "cpus": self.cpus,
            "memory_in_mib": self.memory_mb,
            "drive": image_to_use,
            "iso": os.path.join(BOTS_DIR, "machine", "cloud-init.iso"),
            "console_type": "file" if self.console_file else "pty",
            "console_source": f"<source path='{self.console_file.name}'/>" if self.console_file else "",
            "disk_bus": self.disk_bus,
            "disk_dev": self.disk_dev,
        }

        if self.is_efi:
            candidates = [
                # path for Fedora/RHEL (our tasks container)
                '/usr/share/OVMF/OVMF_CODE.fd',
                # path for Ubuntu (GitHub Actions runners)
                '/usr/share/ovmf/OVMF.fd',
                # path for Arch
                '/usr/share/edk2/x64/OVMF.4m.fd',
            ]

            for path in candidates:
                if os.path.exists(path):
                    keys["firmware"] = f"<qemu:arg value='-bios' /><qemu:arg value={path!r} />"
                    break
            else:
                raise FileNotFoundError('Unable to find OVMF UEFI BIOS')
        else:
            keys["firmware"] = ""

        if os.path.exists("/dev/kvm"):
            keys["type"] = "kvm"
            keys["cpu"] = TEST_KVM_XML.format(**keys)
        else:
            sys.stderr.write("WARNING: Starting virtual machine with emulation due to missing KVM\n")
            sys.stderr.write("WARNING: Machine will run about 10-20 times slower\n")

        keys.update(self.networking)
        keys["hostname"] = keys["image"] + '-' + keys["control"].replace(':', '-').replace('.', '-')
        test_domain_desc = TEST_DOMAIN_XML.format(**keys)

        # add the virtual machine
        # print >> sys.stderr, test_domain_desc
        assert self.virt_connection is not None
        self._domain = self.virt_connection.createXML(test_domain_desc, libvirt.VIR_DOMAIN_START_AUTODESTROY)

    # start virsh console
    def qemu_console(self, extra_message: str = "") -> None:
        self.message(f"Started machine {self.label}")
        if self.maintain:
            message = "\nWARNING: Uncontrolled shutdown can lead to a corrupted image\n"
        else:
            message = "\nWARNING: All changes are discarded, the image file won't be changed\n"
        message += self.diagnose() + extra_message + "\nlogin: "
        message = message.replace("\n", "\r\n")

        try:
            assert self._domain is not None
            proc = subprocess.Popen("virsh -c qemu:///session console %s" % str(self._domain.ID()), shell=True)

            # Fill in information into /etc/issue about login access
            pid = 0
            while pid == 0:
                if message:
                    try:
                        with stdchannel_redirected(sys.stderr, os.devnull):
                            Machine.wait_boot(self)
                        sys.stderr.write(message)
                    except (Failure, subprocess.CalledProcessError):
                        # machine not booted yet, try again in next iteration
                        pass
                    message = ''
                pid, _ret = os.waitpid(proc.pid, os.WNOHANG if message else 0)

            try:
                if self.maintain:
                    self.shutdown()
                else:
                    self.kill()
            except libvirt.libvirtError as le:
                # the domain may have already been freed (shutdown) while the console was running
                self.message("libvirt error during shutdown: %s" % (le.get_error_message()))

        except OSError as exc:
            raise Failure(f"Failed to launch virsh command: {exc.strerror}") from exc
        finally:
            self._cleanup()

    def graphics_console(self) -> None:
        self.message(f"Started machine {self.label}")
        if self.maintain:
            message = "\nWARNING: Uncontrolled shutdown can lead to a corrupted image\n"
        else:
            message = "\nWARNING: All changes are discarded, the image file won't be changed\n"
        message = message.replace("\n", "\r\n")

        try:
            assert self._domain is not None
            proc = subprocess.Popen(["virt-viewer", str(self._domain.ID())])
            sys.stderr.write(message)
            proc.wait()
        except OSError as exc:
            raise Failure(f"Failed to launch virt-viewer command: {exc.strerror}") from exc
        finally:
            self._cleanup()

    def wait_for_exit(self) -> None:
        assert self._domain is not None
        cmdline = ['virsh', 'event', '--event', 'lifecycle', '--domain', str(self._domain.ID())]
        try:
            while subprocess.call(cmdline, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL) == 0:
                pass
        except KeyboardInterrupt:
            # user-requested Control-C, stop
            pass

    def start(self) -> None:
        try:
            self._start_qemu()
            assert self._domain is not None
            if not self._domain.isActive():
                self._domain.start()
        except Failure:
            self.kill()
            raise

    @classmethod
    def is_nested_virt(cls) -> bool:
        """Detect if running in a nested virtualization environment"""
        if cls._is_nested_virt is None:
            result = subprocess.run(['systemd-detect-virt', '--vm', '--quiet'])
            cls._is_nested_virt = (result.returncode == 0)
        return cls._is_nested_virt

    def boot(self, timeout_sec: int = DEFAULT_BOOT_TIMEOUT, *, nested_kvm_retry: bool = True) -> None:
        """Start the machine and wait for boot to complete

        In nested virtualization environments this retries up to 3 times on boot failure.

        Args:
            timeout_sec: Boot timeout in seconds
        """
        max_attempts = 3 if (self.is_nested_virt() and nested_kvm_retry) else 1

        for attempt in range(1, max_attempts + 1):
            self.start()
            try:
                self.wait_boot(timeout_sec)
                return
            except Failure as e:
                if attempt < max_attempts:
                    print(f"WARNING: Boot attempt #{attempt} failed in nested KVM: {e}", file=sys.stderr)
                    self.kill()
                else:
                    raise

    def stop(self, timeout_sec: int = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        if self.maintain:
            self.shutdown(timeout_sec=timeout_sec)
        else:
            self.kill()

    def _cleanup(self, quick: bool = False) -> None:
        self.disconnect()
        try:
            for disk in self._disks:
                self.rem_disk(disk, quick)

            if self._transient_image is not None:
                self._transient_image.close()
                self._transient_image = None

            self._domain = None
        except Exception as e:
            sys.stderr.write(f"WARNING: Cleanup failed: {e}\n")

    def kill(self) -> None:
        # stop system immediately, with potential data loss
        # to shutdown gracefully, use shutdown()
        self.disconnect()
        if self._domain:
            try:
                # not graceful
                with stdchannel_redirected(sys.stderr, os.devnull):
                    self._domain.destroyFlags(libvirt.VIR_DOMAIN_DESTROY_DEFAULT)
            except libvirt.libvirtError as e:
                sys.stderr.write(f"WARNING: Destroying machine failed: {e}\n")
        self._cleanup(quick=True)

    def wait_poweroff(self, timeout_sec: int = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        # shutdown must have already been triggered
        if self._domain:
            start_time = time.time()
            while (time.time() - start_time) < timeout_sec:
                try:
                    with stdchannel_redirected(sys.stderr, os.devnull):
                        if not self._domain.isActive():
                            break
                except libvirt.libvirtError as le:
                    if 'no domain' in str(le) or 'not found' in str(le):
                        break
                    raise
                time.sleep(1)
            else:
                self.print_console_log()
                raise Failure("Waiting for machine poweroff timed out")
            try:
                with stdchannel_redirected(sys.stderr, os.devnull):
                    self._domain.destroyFlags(libvirt.VIR_DOMAIN_DESTROY_DEFAULT)
            except libvirt.libvirtError as le:
                if 'not found' not in str(le) and 'not running' not in str(le):
                    raise
        self._cleanup(quick=True)

    def shutdown(self, timeout_sec: int = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        # shutdown the system gracefully
        # to stop it immediately, use kill()
        self.disconnect()
        try:
            if self._domain:
                self._domain.shutdown()
            self.wait_poweroff(timeout_sec=timeout_sec)
        finally:
            self._cleanup()

    def add_disk(
        self,
        size: str | None = None,
        serial: str | None = None,
        path: str | None = None,
        image_type: str = 'raw',
        boot_disk: bool = False
    ) -> dict[str, Any]:
        assert self._domain is not None

        index = len(self._disks)

        if path:
            fd, image = tempfile.mkstemp(suffix='.qcow2', prefix=os.path.basename(path), dir=self.run_dir)
            os.close(fd)
            subprocess.check_call(["qemu-img", "create", "-q", "-f", "qcow2",
                                   "-o", f"backing_file={os.path.realpath(path)},backing_fmt=qcow2", image])

        else:
            assert self._domain is not None
            assert size is not None
            name = f"disk-{self._domain.name()}"
            fd, image = tempfile.mkstemp(suffix='qcow2', prefix=name, dir=self.run_dir)
            os.close(fd)
            subprocess.check_call(["qemu-img", "create", "-q", "-f", "raw", image, size])

        if not serial:
            serial = f"DISK{index}"
        dev = 'sd' + string.ascii_lowercase[index]
        extra = "<boot order='1'/>" if boot_disk else ""
        disk_desc = TEST_DISK_XML % {
            'file': image,
            'serial': serial,
            'unit': index,
            'dev': dev,
            'type': image_type,
            'extra': extra,
        }

        if self._domain.attachDeviceFlags(disk_desc, libvirt.VIR_DOMAIN_AFFECT_LIVE) != 0:
            raise Failure("Unable to add disk to vm")

        disk = {
            "path": image,
            "serial": serial,
            "filename": image,
            "dev": dev,
            "index": index,
            "type": image_type,
            "extra": extra,
        }

        self._disks.append(disk)
        return disk

    def rem_disk(self, disk: dict[str, Any], quick: bool = False) -> None:
        if not quick:
            disk_desc = TEST_DISK_XML % {
                'file': disk["filename"],
                'serial': disk["serial"],
                'unit': disk["index"],
                'dev': disk["dev"],
                'type': disk["type"],
                'extra': disk["extra"],
            }

            if self._domain:
                if self._domain.detachDeviceFlags(disk_desc, libvirt.VIR_DOMAIN_AFFECT_LIVE) != 0:
                    raise Failure("Unable to remove disk from vm")
        os.unlink(disk['filename'])

    def _qemu_monitor(self, command: str) -> str:
        self.message("& " + command)
        # you can run commands manually using virsh:
        # virsh -c qemu:///session qemu-monitor-command [domain name/id] --hmp [command]
        output = libvirt_qemu.qemuMonitorCommand(self._domain, command,
                                                 libvirt_qemu.VIR_DOMAIN_QEMU_MONITOR_COMMAND_HMP)
        self.message(output.strip())
        assert isinstance(output, str)
        return output

    def add_netiface(self, networking: dict[str, Any] | None = None) -> str:
        if not networking:
            networking = VirtNetwork(image=self.image).interface()
        self._qemu_monitor("netdev_add socket,mcast=230.0.0.1:{mcast},id={id}".format(
            mcast=networking["mcast"], id=networking["hostnet"]))
        self._qemu_monitor(f"device_add virtio-net-pci,mac={networking['mac']},netdev={networking['hostnet']}")
        assert isinstance(networking["mac"], str)
        return networking["mac"]

    def needs_writable_usr(self) -> None:
        # On atomic systems, we need a hack to change files in /usr/lib/systemd
        if self.ostree_image:
            self.execute("mount -o remount,rw /usr")

    def print_console_log(self) -> None:
        """Prints VM's console to stderr"""
        if not self.console_file:
            return

        file_name = self.console_file.name

        try:
            with open(file_name) as f:
                log = f.read().strip()
        except OSError as ex:
            sys.stderr.write(f"Failed to open '{file_name}': {ex}\n")
            return

        if not log:
            sys.stderr.write(f"VM's console log file '{file_name}' is empty\n")
            return

        sys.stderr.write(f"---- Console log starts here ----\n{log}\n---- Console log ends here ----\n")
