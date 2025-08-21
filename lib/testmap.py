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
from collections.abc import Iterable, Mapping, Sequence

from lib.constants import TEST_OS_DEFAULT

COCKPIT_SCENARIOS = {'networking', 'storage', 'expensive', 'other'}
ANACONDA_SCENARIOS = {'efi', 'cockpit', 'storage', 'expensive', 'other'}


def contexts(image: str, *scenarios: Iterable[str], repo: str | None = None) -> Sequence[str]:
    return [image + '/' + '-'.join(i) + (('@' + repo) if repo else '')
            for i in itertools.product(*scenarios)]


REPO_BRANCH_CONTEXT: Mapping[str, Mapping[str, Sequence[str]]] = {
    'cockpit-project/bots': {
        # currently no tests outside of GitHub actions, but declares primary branch
        'main': [],
    },
    'cockpit-project/cockpituous': {
        # no real tests on our infra, but used in cockpituous' own integration tests
        'main': [],
    },
    'cockpit-project/cockpit': {
        'main': [
            *contexts('arch', COCKPIT_SCENARIOS),
            *contexts('centos-9-bootc', COCKPIT_SCENARIOS),
            *contexts('debian-stable', COCKPIT_SCENARIOS),
            *contexts('debian-testing', COCKPIT_SCENARIOS),
            *contexts('debian-trixie', COCKPIT_SCENARIOS),
            *contexts('ubuntu-2204', COCKPIT_SCENARIOS),
            *contexts('ubuntu-2404', COCKPIT_SCENARIOS),
            *contexts('ubuntu-stable', COCKPIT_SCENARIOS),
            *contexts('fedora-41', COCKPIT_SCENARIOS),
            *contexts('fedora-42', COCKPIT_SCENARIOS),
            # this runs coverage, reports need the whole test suite
            *contexts(TEST_OS_DEFAULT, ['devel']),
            *contexts(TEST_OS_DEFAULT, ['firefox'], COCKPIT_SCENARIOS),
            # no udisks on CoreOS → skip storage
            *contexts('fedora-coreos', COCKPIT_SCENARIOS - {'storage'}),
            *contexts('rhel-8-10', ['ws-container'], COCKPIT_SCENARIOS),
            *contexts('rhel-9-7', COCKPIT_SCENARIOS),
            *contexts('rhel-10-1', COCKPIT_SCENARIOS),
            *contexts('centos-10', COCKPIT_SCENARIOS),
        ],
        'rhel-8': [
            *contexts('rhel-8-10', COCKPIT_SCENARIOS),
            # all skipped
            *contexts('rhel-8-10-distropkg', COCKPIT_SCENARIOS - {'networking'}),
        ],
        'rhel-9.6': [
            # that branch does not yet have storage tests enabled for bootc
            *contexts('centos-9-bootc', COCKPIT_SCENARIOS - {'storage'}),
            *contexts('rhel-9-6', COCKPIT_SCENARIOS),
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-rawhide',
            'opensuse-tumbleweed',
        ],
    },
    'cockpit-project/starter-kit': {
        'main': [
            TEST_OS_DEFAULT,
            'arch',
            'fedora-41',
            'fedora-42',
            'centos-9-stream',
            'centos-10',
            'fedora-rawhide',
            'opensuse-tumbleweed',
            'rhel-10-1',
        ],
        '_manual': [
            'centos-9-bootc',
            'rhel-8-10/ws-container',
            'rhel-9-6',
            'rhel-9-7',
        ]
    },
    'cockpit-project/cockpit-ostree': {
        'main': [
            'centos-9-bootc',
            'fedora-coreos',
            'fedora-coreos/devel',
        ],
        '_manual': [
        ]
    },
    'cockpit-project/cockpit-podman': {
        'main': [
            f'{TEST_OS_DEFAULT}/devel',
            f'{TEST_OS_DEFAULT}/firefox',
            'arch',
            'centos-9-bootc',
            'debian-stable',
            'debian-testing',
            'debian-trixie',
            'fedora-41',
            'fedora-42',
            'fedora-coreos',
            'opensuse-tumbleweed',
            'rhel-8-10/ws-container',
            'rhel-9-7',
            'rhel-10-1',
            'ubuntu-2204',
            'ubuntu-2404',
            'ubuntu-stable',
        ],
        '_manual': [
            'centos-10',
            'fedora-rawhide',
        ],
    },
    'cockpit-project/cockpit-machines': {
        'main': [
            'arch',
            'debian-stable',
            'debian-testing',
            'debian-trixie',
            'ubuntu-2204',
            'ubuntu-2404',
            'ubuntu-stable',
            'fedora-41',
            'fedora-42',
            f'{TEST_OS_DEFAULT}/devel',
            f'{TEST_OS_DEFAULT}/firefox',
            'opensuse-tumbleweed',
            'rhel-8-10/ws-container',
            'rhel-9-7',
            'rhel-10-1',
        ],
        'rhel-8': [
            'rhel-8-10',
        ],
        '_manual': [
            'centos-10',
            'fedora-rawhide',
        ],
    },
    'cockpit-project/cockpit-files': {
        'main': [
            'arch',
            'debian-testing',
            'debian-trixie',
            'fedora-41',
            'fedora-42',
            f'{TEST_OS_DEFAULT}/devel',
            f'{TEST_OS_DEFAULT}/firefox',
            'fedora-rawhide',
            'centos-10',
            'rhel-8-10/ws-container',
            'rhel-9-7',
            'rhel-10-1',
        ],
        '_manual': [
        ],
    },
    'osbuild/cockpit-composer': {
        'main': [
            'centos-9-stream',
            'rhel-9-6',
        ],
        '_manual': [
        ],
    },
    'candlepin/subscription-manager': {
        'main': [
            'centos-10',
            'rhel-9-7',
            'rhel-10-1',
            'fedora-41',
            'fedora-42',
        ],
        'subscription-manager-1.28': [
            'rhel-8-8',
            'rhel-8-10',
        ],
        'subscription-manager-1.28.36': [
            'rhel-8-8',
        ],
        'subscription-manager-1.29': [
            'centos-9-stream',
            'rhel-9-2',
            'rhel-9-4',
            'rhel-9-6',
        ],
        'subscription-manager-1.29.33': [
            'rhel-9-2',
        ],
        'subscription-manager-1.29.40': [
            'rhel-9-4',
        ],
        'subscription-manager-1.29.45': [
            'rhel-9-6',
        ],
        'subscription-manager-1.30.6': [
            'rhel-10-0',
        ],
        '_manual': [
        ],
    },
    'candlepin/subscription-manager-cockpit': {
        'main': [
            'centos-9-stream/subscription-manager-1.29',
            'centos-10',
            'rhel-9-7/subscription-manager-1.29',
            'rhel-10-1',
            'fedora-41',
            'fedora-42',
        ],
        '_manual': [
        ],
    },
    'rhinstaller/anaconda-webui': {
        'main': [
            *contexts('fedora-rawhide-boot', ANACONDA_SCENARIOS),
            *contexts('fedora-43-boot', ANACONDA_SCENARIOS),
        ],
        '_manual': [
            'fedora-eln-boot',
        ]
    },
}

# The OSTree variants can't build their own packages, so we build in
# their non-Atomic siblings.
OSTREE_BUILD_IMAGE = {
    "centos-9-bootc": "centos-9-stream",
    "fedora-coreos": "fedora-41",
}

# only put auxiliary images here; triggers for primary OS images are computed from testmap
IMAGE_REFRESH_TRIGGERS = {
    "services": [
        *contexts(TEST_OS_DEFAULT, COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts(TEST_OS_DEFAULT, ['firefox'], COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts('ubuntu-stable', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts('debian-stable', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts('debian-trixie', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *contexts('rhel-9-7', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        "rhel-8-10@cockpit-project/cockpit/rhel-8",
        "rhel-8-10@candlepin/subscription-manager/subscription-manager-1.28",
        "rhel-9-7@candlepin/subscription-manager-cockpit",
    ],
    # Anaconda builds in fedora-rawhide and runs tests in fedora-rawhide-boot
    "fedora-rawhide": [
        *contexts("fedora-rawhide-boot", ANACONDA_SCENARIOS, repo='rhinstaller/anaconda-webui'),
    ],
    # Anaconda payload updates can affect tests
    "fedora-rawhide-anaconda-payload": [
        *contexts("fedora-rawhide-boot", ANACONDA_SCENARIOS, repo='rhinstaller/anaconda-webui'),
    ],
    "fedora-43": [
        *contexts("fedora-43-boot", ANACONDA_SCENARIOS, repo='rhinstaller/anaconda-webui'),
    ],
    "fedora-43-anaconda-payload": [
        *contexts("fedora-eln-boot", ANACONDA_SCENARIOS, repo='rhinstaller/anaconda-webui'),
    ],
}


# The OSTree variants can't build their own packages, so we build in
# their classic siblings.  For example, fedora-coreos is built
# in fedora-X
def get_build_image(image: str) -> str:
    return OSTREE_BUILD_IMAGE.get(image, image)


# some tests have suffixes that run the same image in different modes; map a
# test context image to an actual physical image name
def get_test_image(image: str) -> str:
    return image.replace("-distropkg", "")


def split_context(context: str) -> 'tuple[str, int | None, str, str]':
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

    repo_branch_parts = repo_branch.split('/', 2)
    return (image_scenario, bots_pr, '/'.join(repo_branch_parts[:2]), ''.join(repo_branch_parts[2:]))


def is_valid_context(context: str, repo: str) -> bool:
    image_scenario, _bots_pr, context_repo, branch = split_context(context)
    image = image_scenario.split('/')[0]
    # if the context specifies a repo, use that one instead
    branch_contexts = tests_for_project(context_repo or repo)
    if context_repo:
        # if the context specifies a repo, only look at that particular branch
        try:
            repo_images = {c.split('/')[0] for c in branch_contexts[branch or get_default_branch(context_repo)]}
        except KeyError:
            # unknown project
            return False
        # also allow _manual tests
        repo_images.update(c.split('/')[0] for c in branch_contexts.get('_manual', []))
    else:
        # FIXME: if context is just a simple OS/scenario, we don't know which branch
        # is meant by the caller; accept known contexts from all branches for now
        repo_images = {c.split('/')[0] for c in itertools.chain(*branch_contexts.values())}

    # Valid contexts are the ones that exist in the given/current repo
    return image in repo_images


def projects() -> Iterable[str]:
    """Return all projects for which we run tests."""
    return REPO_BRANCH_CONTEXT.keys()


def get_default_branch(repo: str) -> str:
    branches = REPO_BRANCH_CONTEXT[repo]
    if 'main' in branches:
        return 'main'
    if 'master' in branches:
        return 'master'
    raise ValueError(f"repo {repo} does not contain main or master branch")


def tests_for_project(project: str) -> Mapping[str, Sequence[str]]:
    """Return branch -> contexts map."""
    res = dict(REPO_BRANCH_CONTEXT.get(project, {}))
    # allow bots/cockpituous integration tests to inject a new context
    inject = os.getenv("COCKPIT_TESTMAP_INJECT")
    if inject:
        branch, context = inject.split('/', 1)
        res[branch] = [*res.get(branch, ()), context]
    return res


def tests_for_image(image: str) -> Sequence[str]:
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


def tests_for_po_refresh(project: str) -> Sequence[str]:
    # by default, run all tests
    contexts = REPO_BRANCH_CONTEXT.get(project, {}).get(get_default_branch(project), [])
    # cockpit's are expensive, so only run a few
    if project == "cockpit-project/cockpit":
        # check-pages "all languages" test only runs on RHEL
        contexts = sorted([c for c in contexts if c.startswith("rhel-")])
        # plus required f-coreos
        contexts.append("fedora-coreos/other")
    return contexts
