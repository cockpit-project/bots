#!/bin/sh

# test.thing workaround for SELinux issues with vsock on older RHEL versions
# https://issues.redhat.com/browse/RHEL-113647

vsock-fling 2 1111 X_SYSTEMD_UNIT_ACTIVE=patching-selinux

cat > /tmp/sshd_vsock.te <<EOF
    module sshd_vsock 1.0;

    require {
        type init_t;
        type sshd_t;
        type sshd_net_t;
        class vsock_socket {
            create bind listen accept getattr read write getopt setopt ioctl name_bind
        };
    }

    allow init_t sshd_t:vsock_socket { create bind listen accept getattr setopt name_bind };
    allow sshd_t self:vsock_socket { read write getattr getopt setopt ioctl accept };
    allow sshd_net_t sshd_t:vsock_socket { read write getattr };
EOF

checkmodule -M -m -o /tmp/sshd_vsock.mod /tmp/sshd_vsock.te
semodule_package -m /tmp/sshd_vsock.mod -o /tmp/sshd_vsock.pp
semodule -i /tmp/sshd_vsock.pp

vsock-fling 2 1111 X_SYSTEMD_UNIT_ACTIVE=patch-complete
