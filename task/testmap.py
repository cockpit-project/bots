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


REPO_BRANCH_CONTEXT = {
    'cockpit-project/bots': {
        'master': [
            'host'  # bots doesn't need a vm
        ],
    },
    'cockpit-project/cockpit': {
        'master': [
            'fedora-30/container-bastion',
            'fedora-30/selenium-firefox',
            'fedora-30/selenium-chrome',
            'fedora-30/selenium-edge',
            'debian-stable',
            'debian-testing',
            'ubuntu-1804',
            'ubuntu-stable',
            'fedora-30',
            'fedora-31',
            'fedora-coreos',
            'fedora-30/firefox',
            'rhel-8-1-distropkg',
            'rhel-8-2',
            'centos-8-stream',
        ],
        'rhel-7.8': [
            'rhel-7-8',
            'rhel-atomic',
            'continuous-atomic',
            'fedora-30/container-bastion',
            'fedora-30/selenium-firefox',
            'fedora-30/selenium-chrome',
            'centos-7',
            ],
        'rhel-8-appstream': [
            'fedora-30/container-bastion',
            'fedora-30/selenium-firefox',
            'fedora-30/selenium-chrome',
            'rhel-8-1-distropkg',
            'rhel-8-1',
            ],
        'rhel-8.1': [
            'fedora-30/container-bastion',
            'fedora-30/selenium-firefox',
            'fedora-30/selenium-chrome',
            'rhel-8-1',
            ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-testing',
        ],
    },
    'cockpit-project/starter-kit': {
        'master': [
            'centos-7',
            'fedora-30',
            'centos-8-stream',
        ],
        '_manual': [
        ],
    },
    'cockpit-project/cockpit-ostree': {
        'master': [
            'continuous-atomic',
            'rhel-atomic',
        ],
        '_manual': [
            'fedora-coreos',
        ],
    },
    'cockpit-project/cockpit-podman': {
        'master': [
            'fedora-30',
            'fedora-31',
            'rhel-8-1',
            'rhel-8-2',
        ],
        '_manual': [
            'centos-8-stream',
        ],
    },
    'weldr/lorax': {
        'master': [
            'fedora-31',
            'fedora-31/tar',
            'fedora-31/live-iso',
            'fedora-31/qcow2',
            'fedora-31/aws',
            'fedora-31/azure',
            'fedora-31/openstack',
            'fedora-31/vmware',
        ],
        'rhel8-branch': [
            'rhel-8-1',
            'rhel-8-1/live-iso',
            'rhel-8-1/qcow2',
            'rhel-8-1/aws',
            'rhel-8-1/azure',
            'rhel-8-1/openstack',
            'rhel-8-1/vmware',
            'rhel-8-1/tar',
        ],
        'rhel7-extras': [
            'rhel-7-8',
            'rhel-7-8/live-iso',
            'rhel-7-8/qcow2',
            'rhel-7-8/aws',
            'rhel-7-8/azure',
            'rhel-7-8/openstack',
            'rhel-7-8/vmware',
            'rhel-7-8/tar',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'centos-8-stream',
            'rhel-8-2',
            'rhel-8-2/live-iso',
            'rhel-8-2/qcow2',
            'rhel-8-2/aws',
            'rhel-8-2/azure',
            'rhel-8-2/openstack',
            'rhel-8-2/vmware',
            'rhel-8-2/tar',
        ],
    },
    'weldr/cockpit-composer': {
        'master': [
            'fedora-30/chrome',
            'rhel-8-2/firefox',
            'fedora-31/edge',
            'fedora-31/firefox',
            'rhel-7-8/firefox',
            'rhel-8-1/chrome',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'centos-8-stream',
        ],
    },
    'candlepin/subscription-manager': {
        'master': [
            'rhel-8-1',
        ],
    }
}

# The OSTree variants can't build their own packages, so we build in
# their non-Atomic siblings.
OSTREE_BUILD_IMAGE = {
    "fedora-coreos": "fedora-30",
    "rhel-atomic": "rhel-7-7",
    "continuous-atomic": "centos-7",
}

# only put auxiliary images here; triggers for primary OS images are computed from testmap
IMAGE_REFRESH_TRIGGERS = {
    "fedora-testing": [
        "fedora-testing@cockpit-project/cockpit"
    ],
    "openshift": [
        "rhel-7-8@cockpit-project/cockpit/rhel-7.8",
    ],
    "services": [
        "fedora-31@cockpit-project/cockpit",
        "fedora-30/selenium-firefox@cockpit-project/cockpit",
        "fedora-30/selenium-chrome@cockpit-project/cockpit",
        "ubuntu-1804@cockpit-project/cockpit",
        "debian-stable@cockpit-project/cockpit",
        "rhel-8-2@cockpit-project/cockpit",
        "rhel-7-8@cockpit-project/cockpit/rhel-7.8",
        "fedora-31/firefox@weldr/cockpit-composer",
        "rhel-8-1/chrome@weldr/cockpit-composer",
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

    # bots' own unit test ("host") is required for all bots PRs
    tests.add("host")

    return list(tests)
