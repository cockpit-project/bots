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

import fnmatch
import itertools
import os
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import NamedTuple

from lib.constants import TEST_OS_DEFAULT

COCKPIT_SCENARIOS = {'networking', 'storage', 'expensive', 'other'}
ANACONDA_SCENARIOS = {'bios', 'cockpit', 'dnf', 'storage', 'expensive', 'other', 'bootopts-net1'}


def product(image: str, *scenarios: Iterable[str], repo: str | None = None) -> Sequence[str]:
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
            *product('arch', COCKPIT_SCENARIOS),
            *product('centos-9-bootc', COCKPIT_SCENARIOS),
            *product('debian-testing', COCKPIT_SCENARIOS),
            *product('debian-trixie', COCKPIT_SCENARIOS),
            *product('ubuntu-2604', COCKPIT_SCENARIOS),
            *product('ubuntu-stable', COCKPIT_SCENARIOS),
            *product('fedora-43', COCKPIT_SCENARIOS),
            *product('fedora-44', COCKPIT_SCENARIOS),
            # this runs coverage, reports need the whole test suite
            *product(TEST_OS_DEFAULT, ['devel']),
            *product(TEST_OS_DEFAULT, ['firefox'], COCKPIT_SCENARIOS),
            # no udisks on CoreOS → skip storage
            *product('fedora-coreos', COCKPIT_SCENARIOS - {'storage'}),
            # TODO: gradually fix the remaining scenarios
            *product('opensuse-tumbleweed', COCKPIT_SCENARIOS - {'networking', 'storage', 'expensive'}),
            *product('rhel-8-10', ['ws-container'], COCKPIT_SCENARIOS),
            *product('rhel-9-9', COCKPIT_SCENARIOS),
            *product('rhel-10-3', COCKPIT_SCENARIOS),
            *product('centos-10', COCKPIT_SCENARIOS),
        ],
        'rhel-8': [
            *product('rhel-8-10', COCKPIT_SCENARIOS),
            # all skipped
            *product('rhel-8-10-distropkg', COCKPIT_SCENARIOS - {'networking'}),
        ],
        'rhel-9.8': [
            *product('rhel-9-8', COCKPIT_SCENARIOS),
            *product('rhel-10-2', COCKPIT_SCENARIOS),
        ],
        # These can be triggered manually with bots/tests-trigger
        '_manual': [
            'fedora-rawhide',
            'opensuse-tumbleweed',
            *product('fedora-45', COCKPIT_SCENARIOS),
            *product('rhel-10-3', COCKPIT_SCENARIOS),
            *product('ubuntu-2604', COCKPIT_SCENARIOS),
        ],
    },
    'cockpit-project/starter-kit': {
        'main': [
            TEST_OS_DEFAULT,
            'arch',
            'fedora-43',
            'fedora-44',
            'centos-9-stream',
            'centos-10',
            'fedora-rawhide',
            'opensuse-tumbleweed',
        ],
        '_manual': [
            'centos-9-bootc',
            'rhel-8-10/ws-container',
            'fedora-45',
            'rhel-10-3',
            'rhel-9-9',
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
            'debian-testing',
            'debian-trixie',
            'fedora-43',
            'fedora-44',
            'fedora-coreos',
            'opensuse-tumbleweed',
            'rhel-8-10/ws-container',
            'rhel-10-3',
            'rhel-9-9',
            'ubuntu-2604',
            'ubuntu-stable',
        ],
        '_manual': [
            'centos-10',
            'fedora-rawhide',
            'fedora-45',
        ],
    },
    'cockpit-project/cockpit-machines': {
        'main': [
            'arch',
            'debian-testing',
            'debian-trixie',
            'ubuntu-2604',
            'ubuntu-stable',
            'fedora-43',
            'fedora-44',
            f'{TEST_OS_DEFAULT}/devel',
            f'{TEST_OS_DEFAULT}/firefox',
            'opensuse-tumbleweed',
            'rhel-8-10/ws-container',
            'rhel-10-3',
            'rhel-9-9',
        ],
        'rhel-8': [
            'rhel-8-10',
        ],
        '_manual': [
            'centos-10',
            'fedora-rawhide',
            'fedora-45',
        ],
    },
    'cockpit-project/cockpit-files': {
        'main': [
            'arch',
            'debian-testing',
            'debian-trixie',
            'fedora-43',
            'fedora-44',
            f'{TEST_OS_DEFAULT}/devel',
            f'{TEST_OS_DEFAULT}/firefox',
            'fedora-rawhide',
            'centos-10',
            'rhel-8-10/ws-container',
            'rhel-10-3',
            'rhel-9-9',
        ],
        '_manual': [
            'ubuntu-2604',
            'fedora-45',
        ],
    },
    'codeberg:lis/test.thing': {
        'main': [
        ],
        'cockpit-ci': [
        ],
        '_manual': [
            'arch'
        ],
    },
    'candlepin/subscription-manager': {
        'main': [
            'centos-10',
            'rhel-10-3',
            'fedora-43',
            'fedora-44',
        ],
        'subscription-manager-1.28': [
            'rhel-8-10',
        ],
        'subscription-manager-1.29': [
            'centos-9-stream',
            'rhel-9-8',
            'rhel-9-9',
        ],
        '_manual': [
            'fedora-45',
        ],
    },
    'cockpit-project/subscription-manager-cockpit': {
        'main': [
            'centos-9-stream',
            'centos-10',
            'rhel-9-9',
            'rhel-10-3',
            'rhel-10-3/devel',
            'fedora-43',
            'fedora-44',
        ],
        '_manual': [
            'fedora-45',
        ],
    },
    'rhinstaller/anaconda-webui': {
        'main': [
            *product('fedora-rawhide-boot', ANACONDA_SCENARIOS),
        ],
        '_manual': [
            'fedora-eln-boot',
            *product('fedora-45-boot', ANACONDA_SCENARIOS),
        ]
    },
}

# The OSTree variants can't build their own packages, so we build in
# their non-Atomic siblings.
OSTREE_BUILD_IMAGE = {
    "centos-9-bootc": "centos-9-stream",
    "fedora-coreos": "fedora-44",
}

# ws-container scenarios build RPMs for the cockpit/ws container on a different
# image than the one being tested.  This must match the base OS version used in
# the cockpit/ws container present in the given image.
WSCONTAINER_BUILD_IMAGE = {
    "rhel-8-10": "fedora-43",
}

# only put auxiliary images here; triggers for primary OS images are computed from testmap
# every entry here must also appear in REPO_BRANCH_CONTEXT — otherwise it will never be triggered
IMAGE_REFRESH_TRIGGERS = {
    "services": {
        *product(TEST_OS_DEFAULT, COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *product(TEST_OS_DEFAULT, ['firefox'], COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *product('ubuntu-stable', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *product('debian-trixie', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit'),
        *product('rhel-9-8', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit/rhel-9.8'),
        *product('rhel-8-10', COCKPIT_SCENARIOS, repo='cockpit-project/cockpit/rhel-8'),
        "rhel-8-10@candlepin/subscription-manager/subscription-manager-1.28",
        "rhel-9-8@candlepin/subscription-manager/subscription-manager-1.29",
    },
    # Anaconda builds in fedora-rawhide and runs tests in fedora-rawhide-boot
    "fedora-rawhide": {
        *product("fedora-rawhide-boot", ANACONDA_SCENARIOS, repo='rhinstaller/anaconda-webui'),
    },
    # Anaconda payload updates can affect tests
    "fedora-rawhide-anaconda-payload": {
        *product("fedora-rawhide-boot", ANACONDA_SCENARIOS, repo='rhinstaller/anaconda-webui'),
    },
}


# The OSTree variants can't build their own packages, so we build in
# their classic siblings.  For example, fedora-coreos is built
# in fedora-X
def get_build_image(image: str) -> str:
    return OSTREE_BUILD_IMAGE.get(image, image)


def get_build_image_for_ws_container_inside_of(image: str) -> str | None:
    return WSCONTAINER_BUILD_IMAGE.get(image)


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
    return (repo for repo in REPO_BRANCH_CONTEXT if ':' not in repo)


def get_default_branch(repo: str) -> str:
    return 'main'


def tests_for_project(project: str) -> Mapping[str, Sequence[str]]:
    """Return branch -> contexts map."""
    res = dict(REPO_BRANCH_CONTEXT.get(project, {}))
    # allow bots/cockpituous integration tests to inject a new context
    inject = os.getenv("COCKPIT_TESTMAP_INJECT")
    if inject:
        branch, context = inject.split('/', 1)
        res[branch] = [*res.get(branch, ()), context]
    return res


class Test(NamedTuple):
    os: str
    scenario: str
    repo: str
    branch: str

    @property
    def image(self) -> str:
        return get_test_image(self.os)

    @property
    def context(self) -> str:
        return f'{self.os}/{self.scenario}' if self.scenario else self.os

    @classmethod
    def from_context(cls, s: str, repo: str, branch: str = 'main') -> 'Test':
        os_name, _, scenario = s.partition('/')
        return cls(os=os_name, scenario=scenario, repo=repo, branch=branch)

    @classmethod
    def from_bots_context(cls, s: str) -> 'Test':
        context_str, _, repo_branch = s.partition('@')
        match repo_branch.split('/', 2):
            case [org, project]:
                return cls.from_context(context_str, repo=f'{org}/{project}')
            case [org, project, branch]:
                return cls.from_context(context_str, repo=f'{org}/{project}', branch=branch)
        raise ValueError(s)

    def bots_context(self) -> str:
        s = f'{self.context}@{self.repo}'
        if self.branch != 'main':
            s += f'/{self.branch}'
        return s


_REFRESH_TRIGGER_TESTS = {
    (image, Test.from_bots_context(s))
    for image, triggers in IMAGE_REFRESH_TRIGGERS.items()
    for s in triggers
}


def _test_depends_on_image(t: Test, image: str) -> bool:
    # tests always depend on their own image
    if t.image == image:
        return True

    # ostree images require non-ostree builders
    if OSTREE_BUILD_IMAGE.get(t.image) == image:
        return True

    # the ws-container scenarios build the container on a different image
    if WSCONTAINER_BUILD_IMAGE.get(t.image) == image:
        return t.scenario.startswith('ws-container')

    # finally, some scenarios are known to depend on other images (like services)
    return (image, t) in _REFRESH_TRIGGER_TESTS


def _all_tests() -> Iterator[Test]:
    for repo, branches in REPO_BRANCH_CONTEXT.items():
        for branch, context_list in branches.items():
            if branch.startswith('_'):
                continue
            for context in context_list:
                yield Test.from_context(context, repo=repo, branch=branch)


def tests_for_image(image: str) -> Sequence[str]:
    """Return context list of all tests required for testing an image"""
    return [t.bots_context() for t in _all_tests() if _test_depends_on_image(t, image)]


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
