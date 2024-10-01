#! /bin/sh
set -eu

dnf -y update
dnf install -y sed findutils glib-networking json-glib openssl python3 systemd
dnf clean all
