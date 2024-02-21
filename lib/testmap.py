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

import itertools
import os.path
from typing import Iterable, Optional

from lib.constants import TEST_OS_DEFAULT

COCKPIT_SCENARIOS = {'networking', 'storage', 'expensive', 'other'}


def contexts(image, *scenarios: Iterable[str], repo: Optional[str] = None):
    return [image + '/' + '-'.join(i) + (('@' + repo) if repo else '')
            for i in itertools.product(*scenarios)]


REPO_BRANCH_CONTEXT = {
    'cockpit-project/bots': {
        # currently no tests outside of GitHub actions, but declares primary branch
        'main': [],
    },
    'cockpit-project/cockpit': {
        'main': [
            *contexts('arch', COCKPIT_SCENARIOS),
            *contexts('debian-stable', COCKPIT_SCENARIOS),
            *contexts('debian-testing', COCKPIT_SCENARIOS),
            *contexts('ubuntu-2204', COCKPIT_SCENARIOS),
            *contexts('ubuntu-stable', COCKPIT_SCENARIOS),
            *contexts('fedora-38', COCKPIT_SCENARIOS),
            *contexts('fedora-39', COCKPIT_SCENARIOS),
            # this runs coverage, reports need the whole test suite
            *contexts(TEST_OS_DEFAULT, ['devel']),
            *contexts(TEST_OS_DEFAULT, ['firefox'], COCKPIT_SCENARIOS),
            # no udisks on CoreOS → skip storage
            *contexts('fedora-coreos', COCKPIT_SCENARIOS - {'storage'}),
            *contexts('rhel-9-4', COCKPIT_SCENARIOS),
            *contexts('rhel4edge', COCKPIT_SCENARIOS),
        ],
        'rhel-8': [
            *contexts('rhel-8-10', COCKPIT_SCENARIOS),
            # all skipped
            *contexts('rhel-8-10-distropkg', COCKPIT_SCENARIOS - {'networking'}),
            *contexts('centos-8-stream', COCKPIT_SCENARIOS),
        ],
        'rhel-7.9': [
            'rhel-7-9',
            'centos-7',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-rawhide',
            'fedora-40',
            'rhel-8-10',
        ],
    },
    'cockpit-project/starter-kit': {
        'main': [
            TEST_OS_DEFAULT,
            'fedora-39',
            'fedora-40',
            'centos-8-stream',
            'fedora-rawhide',
        ],
    },
    'cockpit-project/cockpit-ostree': {
        'main': [
            'fedora-coreos',
            'fedora-coreos/devel',
            'rhel4edge',
        ],
    },
    'cockpit-project/cockpit-podman': {
        'main': [
            'arch',
            'rhel-8-10',
            'rhel-9-4',
            'rhel4edge',
            'fedora-38',
            'fedora-39',
            f'{TEST_OS_DEFAULT}/devel',
            'fedora-coreos',
            'debian-stable',
            'debian-testing',
            'ubuntu-2204',
            'ubuntu-stable',
        ],
        '_manual': [
            'centos-8-stream',
            'fedora-rawhide',
            'fedora-40',
        ],
    },
    'cockpit-project/cockpit-machines': {
        'main': [
            'arch',
            'debian-stable',
            'debian-testing',
            'ubuntu-2204',
            'ubuntu-stable',
            'fedora-38',
            'fedora-39',
            f'{TEST_OS_DEFAULT}/devel',
            f'{TEST_OS_DEFAULT}/firefox',
            'rhel-8-10',
            'rhel-9-4',
            'centos-8-stream',
        ],
        '_manual': [
            'fedora-rawhide',
            'fedora-40',
        ],
    },
    'cockpit-project/cockpit-navigator': {
        'main': [
            'arch',
            'debian-testing',
            'fedora-38',
            'fedora-39',
            f'{TEST_OS_DEFAULT}/devel',
            'fedora-rawhide',
        ],
        '_manual': [
            TEST_OS_DEFAULT,
            'rhel-9-4',
            'fedora-40',
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
            'fedora-38',
            'fedora-39',
            'fedora-39/firefox',
            'centos-8-stream',
            'centos-9-stream',
            'rhel-8-9',
            'rhel-9-3',
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-rawhide',
            'fedora-40',
            'rhel-8-10',
            'rhel-9-4',
        ],
    },
    'candlepin/subscription-manager': {
        'main': [
            'rhel-9-0',
            'rhel-9-2',
            'rhel-9-3',
            'rhel-9-4',
            'fedora-38',
            'fedora-39',
        ],
        'subscription-manager-1.28': [
            'rhel-8-4',
            'rhel-8-6',
            'rhel-8-8',
            'rhel-8-9',
        ],
        'subscription-manager-1.28.29': [
            'rhel-8-6',
        ],
        'subscription-manager-1.28.36': [
            'rhel-8-8',
        ],
        'subscription-manager-1.29.26': [
            'rhel-9-0',
        ],
        'subscription-manager-1.29.33': [
            'rhel-9-2',
        ],
        '_manual': [
            'rhel-8-10',
        ],
    },
    'candlepin/subscription-manager-cockpit': {
        'main': [
            'centos-9-stream',
            'rhel-9-3',
            'rhel-9-4',
            'fedora-38',
            'fedora-39',
        ],
        '_manual': [
        ],
    },
    'cockpit-project/cockpit-certificates': {
        'master': [
            'fedora-38',
            'fedora-39',
        ],
        '_manual': [
            'rhel-9-4',
            'centos-8-stream',
            'fedora-39',
        ]
    },
    'rhinstaller/anaconda-webui': {
        'main': [
            'fedora-rawhide-boot',
        ],
        '_manual': [
            'fedora-eln-boot',
        ]
    },
}

# The OSTree variants can't build their own packages, so we build in
# their non-Atomic siblings.
OSTREE_BUILD_IMAGE = {
    "fedora-coreos": "fedora-39",
    "rhel4edge": "rhel-9-2",
}

# only put auxiliary images here; triggers for primary OS images are computed from testmap
IMAGE_REFRESH_TRIGGERS = {
    # some tests run against centos-7's cockpit-ws for backwards compat testing
    "centos-7": [
        f"{TEST_OS_DEFAULT}/expensive@cockpit-project/cockpit",
    ],
    "services": [
        *contexts(TEST_OS_DEFAULT, COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts(TEST_OS_DEFAULT, ['firefox'], COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts('ubuntu-stable', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts('debian-stable', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts('rhel-9-4', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        "rhel-7-9@cockpit-project/cockpit/rhel-7.9",
        "rhel-8-8@candlepin/subscription-manager/subscription-manager-1.28",
        "rhel-9-4@candlepin/subscription-manager-cockpit",
    ],
    # Anaconda builds in fedora-rawhide and runs tests in fedora-rawhide-boot
    "fedora-rawhide": [
        "fedora-rawhide-boot@rhinstaller/anaconda-webui"
    ],
    "fedora-eln": [
        "fedora-eln-boot@rhinstaller/anaconda-webui"
    ],
    # Anaconda payload updates can affect tests
    "fedora-rawhide-anaconda-payload": [
        "fedora-rawhide-boot@rhinstaller/anaconda-webui"
        "fedora-eln-boot@rhinstaller/anaconda-webui"
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
    image_scenario = context_parts[0]

    # Second part can be be either `bots#<pr_number>` or repo specification
    if len(context_parts) > 1:
        if context_parts[1].startswith("bots#"):
            bots_pr = int(context_parts[1][5:])
        else:
            repo_branch = context_parts[1]

    if len(context_parts) > 2:
        repo_branch = context_parts[2]

    repo_branch = repo_branch.split('/', 2)
    return (image_scenario, bots_pr, '/'.join(repo_branch[:2]), ''.join(repo_branch[2:]))


def is_valid_context(context, repo):
    image_scenario, _bots_pr, context_repo, branch = split_context(context)
    image = image_scenario.split('/')[0]
    # if the context specifies a repo, use that one instead
    branch_contexts = tests_for_project(context_repo or repo)
    if context_repo:
        # if the context specifies a repo, only look at that particular branch
        try:
            repo_images = [c.split('/')[0] for c in branch_contexts[branch or get_default_branch(context_repo)]]
        except KeyError:
            # unknown project
            return False
        # also allow _manual tests
        repo_images.extend([c.split('/')[0] for c in branch_contexts.get('_manual', [])])
    else:
        # FIXME: if context is just a simple OS/scenario, we don't know which branch
        # is meant by the caller; accept known contexts from all branches for now
        repo_images = {c.split('/')[0] for c in itertools.chain(*branch_contexts.values())}

    # Valid contexts are the ones that exist in the given/current repo
    return image in repo_images


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
    # by default, run all tests
    contexts = REPO_BRANCH_CONTEXT.get(project, {}).get(get_default_branch(project), [])
    # cockpit's are expensive, so only run a few
    if project == "cockpit-project/cockpit":
        # check-pages "all languages" test only runs on RHEL
        contexts = sorted([c for c in contexts if c.startswith("rhel-")])
        # plus required f-coreos
        contexts.append("fedora-coreos/other")
    return contexts
