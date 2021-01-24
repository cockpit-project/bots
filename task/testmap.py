# This file is part of Cockpit.
#
# Copyright (C) 2019 Red Hat, Inc.
#
# Cockpit is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# Cockpit is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Cockpit; If not, see <http://www.gnu.org/licenses/>.

import os.path

from machine.machine_core.constants import TEST_OS_DEFAULT

REPO_BRANCH_CONTEXT = {
    'cockpit-project/cockpit': {
        'master': [
            'fedora-32/container-bastion',
            'fedora-32/selenium-firefox',
            'fedora-32/selenium-chrome',
            'fedora-32/selenium-edge',
            'debian-stable',
            'debian-testing',
            'ubuntu-2004',
            'ubuntu-stable',
            'fedora-32',
            'fedora-33',
            'fedora-coreos',
            'fedora-32/firefox',
            'rhel-8-4',
            'rhel-8-4-distropkg',
            'centos-8-stream',
        ],
        'rhel-7.9': [
            'rhel-7-9',
            'rhel-atomic',
            'fedora-32/container-bastion',
            'fedora-32/selenium-firefox',
            'fedora-32/selenium-chrome',
            'centos-7',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-testing',
            'fedora-testing/dnf-copr',
            'rhel-8-4-distropkg',
        ],
    },
    'cockpit-project/starter-kit': {
        'master': [
            'fedora-32',
            'centos-8-stream',
        ],
        '_manual': [
            'fedora-32/firefox',
        ],
    },
    'cockpit-project/cockpit-ostree': {
        'master': [
            'rhel-atomic',
            'fedora-coreos',
        ],
        '_manual': [
        ],
    },
    'cockpit-project/cockpit-podman': {
        'master': [
            'rhel-8-3',
            'rhel-8-4',
            'fedora-32',
            'fedora-33',
            'fedora-33/rawhide',
            'debian-testing',
            'ubuntu-stable',
        ],
        '_manual': [
            'centos-8-stream',
        ],
    },
    'weldr/lorax': {
        'master': [
            'fedora-32/osbuild-composer',
        ],
        'rhel8-branch': [
            'rhel-8-3',
            'rhel-8-3/live-iso',
            'rhel-8-3/qcow2',
            'rhel-8-3/aws',
            'rhel-8-3/azure',
            'rhel-8-3/openstack',
            'rhel-8-3/vmware',
            'rhel-8-3/tar',
            'rhel-8-3/ci',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'rhel-7-9',
            'rhel-7-9/azure',
            'rhel-7-9/live-iso',
            'rhel-7-9/qcow2',
            'rhel-7-9/aws',
            'rhel-7-9/openstack',
            'rhel-7-9/vmware',
            'rhel-7-9/tar',
            'rhel-8-3/osbuild-composer',
            'centos-8-stream',
        ],
    },
    'osbuild/cockpit-composer': {
        'master': [
            'fedora-32',
            'fedora-32/firefox',
            'fedora-33',
            'rhel-8-4',
        ],
        'rhel-8': [
            'rhel-8-3',
            'rhel-8-3/firefox',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
        ],
    },
    'candlepin/subscription-manager': {
        'master': [
            'rhel-8-3',
        ],
        '_manual': [
            'rhel-8-4',
        ],
    },
    'skobyda/cockpit-certificates': {
        'master': [
            'fedora-32',
            'fedora-33',
        ],
        '_manual': [
            'rhel-8-4',
            'centos-8-stream',
        ]
    },
}

# The OSTree variants can't build their own packages, so we build in
# their non-Atomic siblings.
OSTREE_BUILD_IMAGE = {
    "fedora-coreos": "fedora-33",
    "rhel-atomic": "rhel-7-9",
}

# only put auxiliary images here; triggers for primary OS images are computed from testmap
IMAGE_REFRESH_TRIGGERS = {
    "fedora-testing": [
        "fedora-testing@cockpit-project/cockpit",
        "fedora-testing/dnf-copr@cockpit-project/cockpit",
    ],
    # some tests run against centos-7's cockpit-ws for backwards compat testing
    "centos-7": [
        TEST_OS_DEFAULT + "@cockpit-project/cockpit",
    ],
    "openshift": [
        "rhel-7-9@cockpit-project/cockpit/rhel-7.9",
    ],
    "services": [
        "fedora-32@cockpit-project/cockpit",
        "fedora-32/selenium-firefox@cockpit-project/cockpit",
        "fedora-32/selenium-chrome@cockpit-project/cockpit",
        "ubuntu-2004@cockpit-project/cockpit",
        "debian-stable@cockpit-project/cockpit",
        "rhel-8-4@cockpit-project/cockpit",
        "rhel-7-9@cockpit-project/cockpit/rhel-7.9",
        "fedora-32/firefox@osbuild/cockpit-composer",
    ]
}


# The OSTree variants can't build their own packages, so we build in
# their classic siblings.  For example, rhel-atomic is built
# in rhel-7-X
def get_build_image(image):
    (test_os, unused) = os.path.splitext(os.path.basename(image))
    return OSTREE_BUILD_IMAGE.get(image, image)


# some tests have suffixes that run the same image in different modes; map a
# test context image to an actual physical image name
def get_test_image(image):
    return image.replace("-distropkg", "")


def projects():
    """Return all projects for which we run tests."""
    return REPO_BRANCH_CONTEXT.keys()


def tests_for_project(project):
    """Return branch -> contexts map."""
    return REPO_BRANCH_CONTEXT.get(project, {})


def tests_for_image(image):
    """Return context list of all tests required for testing an image"""

    tests = set(IMAGE_REFRESH_TRIGGERS.get(image, []))
    for repo, branch_contexts in REPO_BRANCH_CONTEXT.items():
        for branch, contexts in branch_contexts.items():
            if branch.startswith('_'):
                continue
            for context in contexts:
                if context.split('/')[0].replace('-distropkg', '') == image:
                    c = context + '@' + repo
                    if branch != "master":
                        c += "/" + branch
                    tests.add(c)

    # is this a build image for Atomic? then add the Atomic tests
    for a, i in OSTREE_BUILD_IMAGE.items():
        if image == i:
            tests.update(tests_for_image(a))
            break

    return list(tests)


def tests_for_po_refresh(project):
    if project == "cockpit-project/cockpit":
        return [TEST_OS_DEFAULT]
    return REPO_BRANCH_CONTEXT.get(project, {}).get("master", [])
