#!/bin/bash

# Download cockpit.spec, replace `npm-version` macro and then query all build requires
# also re-enable building of optional packages by default, so that we get libssh-devel

set -eu
# Guard against GitHub outages, redirects etc., and let this script fail on rpmspec failures
set -o pipefail

GET="curl --silent --show-error --fail"
COCKPIT_GIT="https://raw.githubusercontent.com/cockpit-project/cockpit"
OS_VER="$1"

# most images use cockpit.spec from main branch, but there's a RHEL 7 stable branch with a completely different layout
case "$OS_VER" in
    rhel*7|centos*7)
        spec=$($GET "$COCKPIT_GIT/rhel-7.9/tools/cockpit.spec" |
            sed 's/%{npm-version:.*}/0/; /Recommends:/d; s/build_optional 0/build_optional 1/')
        ;;

    *)
        spec=$($GET "$COCKPIT_GIT/main/tools/cockpit.spec.in" | sed 's/@BUILD_ALL@/1/; s/@[A-Z_]*/0/g')
        ;;
esac

echo "$spec" | rpmspec -D "$OS_VER" --buildrequires --query /dev/stdin | sed 's/.*/"&"/' | tr '\n' ' '

# some extra build dependencies:
# - libappstream-glib for validating appstream metadata in starter-kit and derivatives
# - rpmlint for validating built RPMs
EXTRA_DEPS="libappstream-glib rpmlint"

# nodejs for starter-kit and other projects which rebuild webpack during RPM build; but it can't be installed on RHEL 8
# mocks due to missing modularity package indexes
case "$OS_VER" in
    rhel*8) ;;
    *) EXTRA_DEPS="$EXTRA_DEPS nodejs" ;;
esac

echo "$EXTRA_DEPS"
