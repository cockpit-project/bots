# This file is part of Cockpit.
#
# Copyright (C) 2026 Red Hat, Inc.
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

import importlib.machinery
import importlib.util
import io
import os
import sys
import typing
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest

from lib.aio.jsonutil import JsonValue
from lib.constants import BOTS_DIR
from lib.test_mock_server import MockHandler, MockServer

GITHUB_DATA: dict[str, JsonValue] = {
    "/repos/cockpit-project/cockpit/pulls/1": {
        "title": "Some PR",
        "number": 1,
        "state": "open",
        "head": {"sha": "abc123", "user": {"login": "cockpit-project"}},
        "base": {"ref": "main"},
        "labels": [],
    },
    "/repos/cockpit-project/cockpit/commits/abc123/status?page=1&per_page=100": {
        "state": "pending",
        "statuses": [],
        "sha": "abc123",
    },
    "/repos/cockpit-project/bots/pulls/1": {
        "title": "Some bots PR",
        "number": 1,
        "state": "open",
        "head": {"sha": "def456", "user": {"login": "cockpit-project"}},
        "base": {"ref": "main"},
        "labels": [],
    },
    "/repos/cockpit-project/bots/commits/def456/status?page=1&per_page=100": {
        "state": "pending",
        "statuses": [],
        "sha": "def456",
    },
}


class Handler(MockHandler[dict[str, JsonValue]]):
    def do_GET(self) -> None:
        if self.path in self.server.data:
            self.replyJson(self.server.data[self.path])
        else:
            self.send_error(404, 'Mock Not Found: ' + self.path)


@pytest.fixture(scope="module")
def tests_trigger_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("tests_trigger", os.path.join(BOTS_DIR, "tests-trigger"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


type TestsTrigger = Callable[[list[str]], tuple[int, str]]


@pytest.fixture(scope="module")
def tests_trigger(tests_trigger_module: ModuleType) -> TestsTrigger:
    def _run(args: list[str]) -> tuple[int, str]:
        with pytest.MonkeyPatch.context() as mp:
            stderr = io.StringIO()
            mp.setattr(sys, 'argv', ['tests-trigger', *args])
            mp.setattr(sys, 'stderr', stderr)
            try:
                assert typing.get_type_hints(tests_trigger_module.main)['return'] is int
                ret: int = tests_trigger_module.main()
            except SystemExit as e:
                ret = e.code if isinstance(e.code, int) else 0
        sys.stderr.write(stderr.getvalue())
        return ret, stderr.getvalue()

    return _run


@pytest.fixture(autouse=True)
def mock_server() -> Iterator[None]:
    server = MockServer(("127.0.0.1", 0), Handler, GITHUB_DATA)
    server.start()
    os.environ["GITHUB_API"] = f"http://{server.address[0]}:{server.address[1]}"
    yield
    server.kill()


def test_wildcard_project_repo(tests_trigger: TestsTrigger) -> None:
    # wildcard from a project repo should produce bare contexts for that repo/branch only
    ret, stderr = tests_trigger(["--repo", "cockpit-project/cockpit", "-n", "1", "*/networking"])
    assert ret == 0
    assert "arch/networking: triggering on pull request 1\n" in stderr
    assert "debian-testing/networking: triggering on pull request 1\n" in stderr
    # no bots-form contexts for the current repo, no other repos
    assert "@" not in stderr


def test_wildcard_bots_repo(tests_trigger: TestsTrigger) -> None:
    # wildcard from the bots repo should produce full bots contexts across all repos
    ret, stderr = tests_trigger(
        ["--repo", "cockpit-project/bots", "-n", "1", "*/networking@cockpit-project/cockpit"])
    assert ret == 0
    assert "arch/networking@cockpit-project/cockpit: triggering on pull request 1\n" in stderr
    assert "debian-testing/networking@cockpit-project/cockpit: triggering on pull request 1\n" in stderr
    # should not appear as bare contexts
    assert "arch/networking: triggering" not in stderr
