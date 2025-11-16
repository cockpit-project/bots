#!/bin/bash

# Download cockpit.spec, replace `npm-version` macro and then query all build requires

set -eu
# Guard against GitHub outages, redirects etc., and let this script fail on rpmspec failures
set -o pipefail

GET="curl --silent --show-error --fail"
COCKPIT_GIT="https://raw.githubusercontent.com/cockpit-project/cockpit"
OS_VER="$1"
# Remove variant information from OS_VER (e.g. fedora 40 eln -> fedora 40)
OS_VER_NO_VARIANT="$(echo $OS_VER | cut -d' ' -f 1,2)"

# most images use cockpit.spec from main branch, but stable RHEL branches diverge
case "$OS_VER" in
    rhel*8|centos*8)
        spec=$($GET "$COCKPIT_GIT/rhel-8/tools/cockpit.spec")
        ;;
    *suse*)
        # macro for determining suse version is %suse_version
        spec=$($GET "$COCKPIT_GIT/main/tools/cockpit.spec")
        OS_VER_NO_VARIANT="suse_version $(rpm --eval '%suse_version')"
        ;;
    *)
        spec=$($GET "$COCKPIT_GIT/main/tools/cockpit.spec")
        ;;
esac

echo "$spec" | rpmspec -D "$OS_VER_NO_VARIANT" -D 'version 0' -D 'enable_old_bridge 0' --buildrequires --query /dev/stdin | sed 's/.*/"&"/' | tr '\n' ' '

# some extra build dependencies:
# - libappstream-glib for validating appstream metadata in starter-kit and derivatives
# - rpmlint for validating built RPMs
# - gettext to build/merge GNU gettext translations
# - desktop-file-utils for validating desktop files
# - nodejs for starter-kit and other projects which rebuild webpack during RPM build
case "$OS_VER" in
    *suse*)
        EXTRA_DEPS="appstream-glib rpmlint gettext-runtime desktop-file-utils nodejs-default"
        ;;
    rhel*10|centos*10)
        # no rpmlint in RHEL 10: https://pkgs.devel.redhat.com/cgit/rpms/rpmlint/commit/?h=rhel-10-main&id=9a9efcbfd844
        EXTRA_DEPS="libappstream-glib gettext desktop-file-utils nodejs"
        ;;
    *)
        EXTRA_DEPS="libappstream-glib rpmlint gettext desktop-file-utils nodejs"
        ;;
esac

# TEMP: asciidoctor (most distros) or asciidoc (CentOS) needed for PR testing
# https://github.com/cockpit-project/cockpit/pull/21515
case "$OS_VER" in
    rhel*|centos*) EXTRA_DEPS="$EXTRA_DEPS asciidoc" ;;
    *suse*) EXTRA_DEPS="$EXTRA_DEPS ruby3.4-rubygem-asciidoctor" ;;
    *) EXTRA_DEPS="$EXTRA_DEPS asciidoctor";;
esac

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
    fedora*eln) ;;
    fedora*) EXTRA_DEPS="$EXTRA_DEPS nodejs-devel" ;;
    *) ;;
esac

# TEMP: pull nodejs and nodejs-esbuild until they become proper cockpit BuildRequires
case "$OS_VER" in
    fedora*eln) ;;
    fedora*) EXTRA_DEPS="$EXTRA_DEPS nodejs nodejs-esbuild" ;;
    *) ;;
esac

echo "$EXTRA_DEPS"
