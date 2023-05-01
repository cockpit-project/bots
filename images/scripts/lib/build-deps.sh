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
        spec=$($GET "$COCKPIT_GIT/main/tools/cockpit.spec")
        ;;
esac

echo "$spec" | rpmspec -D "$OS_VER" -D 'version 0' -D 'cockpit_enable_python 1' --buildrequires --query /dev/stdin | sed 's/.*/"&"/' | tr '\n' ' '

# We build anaconda rpms
case "$OS_VER" in
    fedora*) # let's try if Anaconda have branch for the given fedora, if not, use master (rawhide)
        SPEC=$($GET "https://raw.githubusercontent.com/rhinstaller/anaconda/fedora-${OS_VER#fedora }/anaconda.spec.in") || \
            SPEC=$($GET "https://raw.githubusercontent.com/rhinstaller/anaconda/master/anaconda.spec.in")
        echo "$SPEC" | \
            sed 's/@PACKAGE.*@/0/' | rpmspec --buildrequires --query /dev/stdin | \
            sed 's/.*/"&"/' | tr '\n' ' '
    ;;
esac

# some extra build dependencies:
# - libappstream-glib for validating appstream metadata in starter-kit and derivatives
# - rpmlint for validating built RPMs
# - gettext to build/merge GNU gettext translations
# - desktop-file-utils for validating desktop files
# - nodejs for starter-kit and other projects which rebuild webpack during RPM build
EXTRA_DEPS="libappstream-glib rpmlint gettext desktop-file-utils nodejs"

# libappstream-glib-devel is needed for merging translations in AppStream XML files in starter-kit and derivatives
# on RHEL 8 only: gettext in RHEL 8 does not know about .metainfo.xml files, and libappstream-glib-devel
# provides /usr/share/gettext/its/appdata.{its,loc} for them
case "$OS_VER" in
    rhel*8|centos*8) EXTRA_DEPS="$EXTRA_DEPS libappstream-glib-devel" ;;
    *) ;;
esac

# pull nodejs-devel on Fedora for compliance with the guidelines on using nodejs modules:
# https://docs.fedoraproject.org/en-US/packaging-guidelines/Node.js/#_buildrequires
case "$OS_VER" in
    fedora*) EXTRA_DEPS="$EXTRA_DEPS nodejs-devel" ;;
    *) ;;
esac

echo "$EXTRA_DEPS"
