#!/bin/bash

set -eu
# Guard against GitHub outages, redirects etc., and let this script fail on rpmspec failures
set -o pipefail

# most images use cockpit.spec from  master branch
branch="master"

case "$1" in
    rhel*7|centos*7) branch=rhel-7.9 ;;
esac

# Download cockpit.spec, replace `npm-version` macro and then query all build requires
# also re-enable building of optional packages by default, so that we get libssh-devel
curl -s https://raw.githubusercontent.com/cockpit-project/cockpit/$branch/tools/cockpit.spec |
    sed 's/%{npm-version:.*}/0/; /Recommends:/d; s/build_optional 0/build_optional 1/' |
    rpmspec -D "$1" --buildrequires --query /dev/stdin |
    sed 's/.*/"&"/' |
    tr '\n' ' '

# HACK: Install selinux-policy manually as it will be pulled in through dependencies only once https://github.com/cockpit-project/cockpit/pull/15707 lands
if [ "${1#fedora*}" != "$1" ] || [ "${1#rhel*9}" != "$1" ]; then
    echo '"selinux-policy" "selinux-policy-devel"'
fi
