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
    'cockpit-project/bots': {
        # currently no tests outside of GitHub actions, but declares primary branch
        'main': [],
    },
    'cockpit-project/cockpit': {
        'main': [
            'arch',
            'debian-stable',
            'debian-testing',
            'ubuntu-2204',
            'ubuntu-stable',
            'fedora-36',
            'fedora-37',
            f'{TEST_OS_DEFAULT}/devel',
            f'{TEST_OS_DEFAULT}/firefox',
            'fedora-coreos',
            'rhel-8-7',
            'rhel-8-7-distropkg',
            'rhel-8-8',
            'centos-8-stream',
            'rhel-9-1',
            'rhel-9-2',
        ],
        'rhel-7.9': [
            'rhel-7-9',
            'centos-7',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            f'{TEST_OS_DEFAULT}/pybridge',
            'fedora-testing',
            'fedora-testing/dnf-copr',
            'fedora-rawhide',
        ],
    },
    'cockpit-project/starter-kit': {
        'main': [
            TEST_OS_DEFAULT,
            'centos-8-stream',
            'fedora-36',
            'fedora-37',
            'fedora-rawhide',
        ],
        '_manual': [
            f'{TEST_OS_DEFAULT}/firefox',
        ],
    },
    'cockpit-project/cockpit-ostree': {
        'main': [
            'fedora-coreos',
        ],
        '_manual': [
        ],
    },
    'cockpit-project/cockpit-podman': {
        'main': [
            'arch',
            'rhel-8-7',
            'rhel-9-1',
            'fedora-36',
            'fedora-37',
            f'{TEST_OS_DEFAULT}/devel',
            'fedora-coreos',
            'debian-testing',
            'ubuntu-2204',
            'ubuntu-stable',
        ],
        '_manual': [
            'centos-8-stream',
            'fedora-rawhide',
        ],
    },
    'cockpit-project/cockpit-machines': {
        'main': [
            'arch',
            'debian-stable',
            'debian-testing',
            'ubuntu-2204',
            'ubuntu-stable',
            'fedora-36',
            'fedora-37',
            f'{TEST_OS_DEFAULT}/firefox',
            'rhel-8-7',
            'rhel-9-1',
            'centos-8-stream',
        ],
        '_manual': [
            'fedora-rawhide',
            'fedora-testing',
            f'{TEST_OS_DEFAULT}/devel',
        ],
    },
    'weldr/lorax': {
        'master': [
        ],
        'rhel8-branch': [
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'rhel-8-6/osbuild-composer',
        ],
    },
    'osbuild/cockpit-composer': {
        'main': [
            'fedora-36',
            'fedora-36/firefox',
            'rhel-8-7',
            'rhel-9-1',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-37',
            'fedora-37/firefox',
            'fedora-rawhide',
            'rhel-8-8',
            'centos-8-stream',
            'rhel-9-2',
            'centos-9-stream',
        ],
    },
    'candlepin/subscription-manager': {
        'main': [
            'rhel-8-8',
            'rhel-9-0',
            'rhel-9-1',
            'rhel-9-2',
            'fedora-36',
            'fedora-37',
        ],
        'subscription-manager-1.28': [
            'rhel-8-4',
            'rhel-8-6',
            'rhel-8-7',
            'rhel-8-8',
        ],
        'subscription-manager-1.28.29': [
            'rhel-8-6',
        ],
        'subscription-manager-1.28.32': [
            'rhel-8-7',
        ],
        'subscription-manager-1.29.26': [
            'rhel-9-0',
        ],
        'subscription-manager-1.29.30': [
            'rhel-9-1',
        ],
        '_manual': [
        ],
    },
    'candlepin/subscription-manager-cockpit': {
        'main': [
            'rhel-9-1',
            'centos-9-stream',
            'fedora-36',
            'fedora-37',
        ],
        '_manual': [
            'centos-8-stream/subscription-manager-1.28',
            'rhel-8-7',
            'rhel-8-7/subscription-manager-1.28',
        ],
    },
    'cockpit-project/cockpit-certificates': {
        'master': [
            'fedora-37',
        ],
        '_manual': [
            'rhel-8-7',
            'rhel-9-1',
            'centos-8-stream',
            'fedora-36',
        ]
    },
    'rhinstaller/anaconda': {
        'master': [
            'fedora-rawhide-boot',
        ],
        '_manual': [
            'fedora-rawhide-boot/devel',
        ]
    },
}

# The OSTree variants can't build their own packages, so we build in
# their non-Atomic siblings.
OSTREE_BUILD_IMAGE = {
    "fedora-coreos": "fedora-36",
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
        f"{TEST_OS_DEFAULT}@cockpit-project/cockpit",
        "ubuntu-stable@cockpit-project/cockpit",
        "debian-stable@cockpit-project/cockpit",
        "rhel-9-1@cockpit-project/cockpit",
        "rhel-7-9@cockpit-project/cockpit/rhel-7.9",
        "rhel-8-8@candlepin/subscription-manager",
        "rhel-9-1@candlepin/subscription-manager-cockpit",
    ],
    # Anaconda builds in fedora-37 and runs tests in fedora-rawhide-boot
    "fedora-37": [
        "fedora-rawhide-boot@rhinstaller/anaconda"
    ],
}


# The OSTree variants can't build their own packages, so we build in
# their classic siblings.  For example, fedora-coreos is built
# in fedora-X
def get_build_image(image):
    (test_os, unused) = os.path.splitext(os.path.basename(image))
    return OSTREE_BUILD_IMAGE.get(image, image)


# some tests have suffixes that run the same image in different modes; map a
# test context image to an actual physical image name
def get_test_image(image):
    return image.replace("-distropkg", "")


def split_context(context):
    bots_pr = None
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

    repo_branch = repo_branch.split('/', 2)
    return (os_scenario, bots_pr, '/'.join(repo_branch[:2]), ''.join(repo_branch[2:]))


def is_valid_context(context, repo):
    os_scenario, _bots_pr, context_repo, branch = split_context(context)
    # if the context specifies a repo, use that one instead
    branch_contexts = tests_for_project(context_repo or repo)
    if context_repo:
        # if the context specifies a repo, only look at that particular branch
        try:
            repo_contexts = branch_contexts[branch or get_default_branch(context_repo)].copy()
        except KeyError:
            # unknown project
            return False
        # also allow _manual tests
        repo_contexts.extend(branch_contexts.get('_manual', []))
    else:
        # FIXME: if context is just a simple OS/scenario, we don't know which branch
        # is meant by the caller; accept known contexts from all branches for now
        repo_contexts = set(itertools.chain(*branch_contexts.values()))

    # Valid contexts are the ones that exist in the given/current repo
    return os_scenario in repo_contexts


def projects():
    """Return all projects for which we run tests."""
    return REPO_BRANCH_CONTEXT.keys()


def get_default_branch(repo):
    branches = REPO_BRANCH_CONTEXT[repo]
    if 'main' in branches:
        return 'main'
    if 'master' in branches:
        return 'master'
    raise ValueError(f"repo {repo} does not contain main or master branch")


def tests_for_project(project):
    """Return branch -> contexts map."""
    res = REPO_BRANCH_CONTEXT.get(project, {}).copy()
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
                    if branch != get_default_branch(repo):
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
        # check-pages "all languages" test only runs on RHEL; plus required status
        return ["rhel-9-1", "fedora-coreos"]
    return REPO_BRANCH_CONTEXT.get(project, {}).get(get_default_branch(project), [])
