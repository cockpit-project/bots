#!/bin/bash

set -eu

# most images use cockpit.spec from  master branch
case "$1" in
    rhel*7*|centos*7*) branch=rhel-7.8 ;;
    *) branch=master ;;
esac

# Download cockpit.spec, replace `npm-version` macro and then query all build requires
curl -s https://raw.githubusercontent.com/cockpit-project/cockpit/$branch/tools/cockpit.spec |
    sed 's/%{npm-version:.*}/0/' |
    sed '/Recommends:/d' |
    rpmspec -D "$1" --buildrequires --query /dev/stdin |
    sed 's/.*/"&"/' |
    tr '\n' ' '
