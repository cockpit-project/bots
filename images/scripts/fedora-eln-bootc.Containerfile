FROM quay.io/centos-bootc/fedora-bootc:eln

# pre-install the distro version, which is useful for testing extensions and manual experiments
RUN \
    dnf install -y --setopt install_weak_deps=False cockpit-system cockpit-networkmanager && \
    dnf clean all

ADD lib/mcast1.nmconnection /usr/lib/NetworkManager/system-connections/

# NM insists on tight permissions
RUN chmod 600 /usr/lib/NetworkManager/system-connections/mcast1.nmconnection

# HACK: workaround for https://github.com/osbuild/bootc-image-builder/issues/143
# so that we can configure root password/ssh key
RUN mkdir /var/roothome

# HACK: workaround for https://github.com/osbuild/bootc-image-builder/issues/326
RUN rm -rf /usr/local; ln -s ../var/usrlocal /usr/local
