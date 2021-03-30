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
import itertools

from lib.constants import TEST_OS_DEFAULT

REPO_BRANCH_CONTEXT = {
    'cockpit-project/cockpit': {
        'master': [
            'fedora-33/container-bastion',
            'debian-stable',
            'debian-testing',
            'ubuntu-2004',
            'ubuntu-stable',
            'fedora-33',
            'fedora-34',
            'fedora-coreos',
            'fedora-33/firefox',
            'rhel-8-5',
            'rhel-8-5-distropkg',
            'centos-8-stream',
        ],
        'rhel-7.9': [
            'rhel-7-9',
            'rhel-atomic',
            'centos-7',
        ],
        'rhel-8.4': [
            'rhel-8-4',
            'rhel-8-4-distropkg',
            'centos-8-stream',
            'fedora-33/container-bastion',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-testing',
            'fedora-testing/dnf-copr',
            'rhel-9-0',
            'rhel-9-0-distropkg',
        ],
    },
    'cockpit-project/starter-kit': {
        'master': [
            'fedora-33',
            'fedora-34',
            'centos-8-stream',
        ],
        '_manual': [
            'fedora-34/firefox',
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
            'rhel-8-4',
            'fedora-33',
            'fedora-34',
            'fedora-34/rawhide',
            'debian-testing',
            'ubuntu-stable',
        ],
        '_manual': [
            'centos-8-stream',
            'rhel-8-5',
            'rhel-9-0',
        ],
    },
    'cockpit-project/cockpit-machines': {
        'main': [
            'debian-stable',
            'debian-testing',
            'ubuntu-2004',
            'ubuntu-stable',
            'fedora-33',
            'fedora-34',
            'fedora-33/firefox',
            'rhel-8-5',
            'rhel-9-0',
            'centos-8-stream',
        ],
        '_manual': [
            'fedora-testing',
        ],
    },
    'weldr/lorax': {
        'master': [
        ],
        'rhel8-branch': [
            'rhel-8-4/osbuild-composer',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-34/lorax',
            'fedora-34/osbuild-composer',
            'rhel-8-4/lorax',
            'rhel-8-5/osbuild-composer',
            'rhel-9-0/osbuild-composer',
            'rhel-7-9',
            'rhel-7-9/azure',
            'rhel-7-9/live-iso',
            'rhel-7-9/qcow2',
            'rhel-7-9/aws',
            'rhel-7-9/openstack',
            'rhel-7-9/vmware',
            'rhel-7-9/tar',
            'centos-8-stream',
        ],
    },
    'osbuild/cockpit-composer': {
        'master': [
            'fedora-33',
            'fedora-33/firefox',
            'rhel-8-4',
            'rhel-8-4/firefox',
        ],
        'rhel-8': [
            'rhel-8-4',
            'rhel-8-4/firefox',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-34',
            'rhel-8-5',
            'rhel-8-5/firefox',
            'rhel-9-0',
            'rhel-9-0/firefox',
        ],
    },
    'candlepin/subscription-manager': {
        'master': [
            'rhel-8-3',
            'rhel-8-4',
        ],
        '_manual': [
            'rhel-8-5',
            'rhel-9-0',
        ],
    },
    'skobyda/cockpit-certificates': {
        'master': [
            'fedora-33',
        ],
        '_manual': [
            'fedora-34',
            'rhel-8-4',
            'rhel-8-5',
            'rhel-9-0',
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
        "fedora-33@cockpit-project/cockpit",
        "ubuntu-2004@cockpit-project/cockpit",
        "debian-stable@cockpit-project/cockpit",
        "rhel-8-4@cockpit-project/cockpit",
        "rhel-7-9@cockpit-project/cockpit/rhel-7.9",
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


def split_context(context):
    os_scenario = ""
    bots_pr = ""
    repo_branch = ""

    context_parts = context.split("@")
    os_scenario = context_parts[0]

    # Second part can be be either `bots#<pr_number>` or repo specification
    if len(context_parts) > 1:
        if context_parts[1].startswith("bots#"):
            bots_pr = int(context_parts[1][5:])
        else:
            repo_branch = context_parts[1]

    if len(context_parts) > 2:
        repo_branch = context_parts[2]
    return (os_scenario, bots_pr, repo_branch)


def is_valid_context(context, repo, contexts=[]):
    branch_contexts = tests_for_project(repo).values()
    repo_contexts = set(itertools.chain(*branch_contexts))

    os_scenario, bots_pr, repo_branch = split_context(context)

    # If contexts were specified, only those are valid
    if contexts:
        for c in contexts:
            c = c.split("@")[0]
            if c == os_scenario:
                return True
        return False

    # If repo in context, consider only contexts from the given repo
    if repo_branch:
        repo_branch = "/".join(repo_branch.split("/")[:2])
        repo_cs = tests_for_project(repo_branch).values()
        return os_scenario in set(itertools.chain(*repo_cs))

    # Valid contexts are the ones that exist in the current repo
    return os_scenario in repo_contexts


def projects():
    """Return all projects for which we run tests."""
    return REPO_BRANCH_CONTEXT.keys()


def tests_for_project(project):
    """Return branch -> contexts map."""
    res = REPO_BRANCH_CONTEXT.get(project, {})
    # allow bots/cockpituous integration tests to inject a new context
    inject = os.getenv("COCKPIT_TESTMAP_INJECT")
    if inject:
        branch, context = inject.split('/', 1)
        res.setdefault(branch, []).append(context)
    return res


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


def known_context(context):
    context = context.split("@")[0]
    for project in projects():
        for branch_tests in tests_for_project(project).values():
            if context in branch_tests:
                return True
    return False
