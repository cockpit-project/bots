ARG base_image
FROM $base_image

# pre-install the distro version, which is useful for testing extensions and manual experiments
RUN \
    dnf update -y --exclude='kernel*' && \
    dnf install -y --setopt install_weak_deps=False cockpit-system cockpit-networkmanager && \
    dnf clean all

ADD lib/mcast1.nmconnection /usr/lib/NetworkManager/system-connections/

# NM insists on tight permissions
RUN chmod 600 /usr/lib/NetworkManager/system-connections/mcast1.nmconnection

# Make /usr/local writable for our testing: https://containers.github.io/bootc/filesystem.html#usrlocal
RUN rm -rf /usr/local; ln -s ../var/usrlocal /usr/local
