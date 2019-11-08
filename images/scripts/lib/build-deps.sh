#!/bin/bash

set -eu

# most images use cockpit.spec from  master branch
branch="master"
stable_branch_deps=""

case "$1" in
    rhel*7|centos*7) branch=rhel-7.8 ;;
    # intltool got removed on cockpit master, but not from rhel-[78].* branches
    rhel*8|fedora*30) stable_branch_deps="intltool" ;;
esac

# Download cockpit.spec, replace `npm-version` macro and then query all build requires
curl -s https://raw.githubusercontent.com/cockpit-project/cockpit/$branch/tools/cockpit.spec |
    sed 's/%{npm-version:.*}/0/' |
    sed '/Recommends:/d' |
    rpmspec -D "$1" --buildrequires --query /dev/stdin |
    sed 's/.*/"&"/' |
    tr '\n' ' '

echo "$stable_branch_deps"
