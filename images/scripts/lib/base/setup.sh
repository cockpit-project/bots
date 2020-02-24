#! /bin/sh
set -eu

dnf -v -y update
dnf install -y sed findutils glib-networking json-glib libssh openssl python3
dnf clean all
