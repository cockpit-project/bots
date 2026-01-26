#!/usr/bin/env python3

# This file is part of Cockpit.
#
# Copyright (C) 2024 Red Hat, Inc.
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
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock
from collections.abc import Sequence
from types import ModuleType

from lib.aio.jsonutil import JsonDict, JsonObject
from lib.constants import BOTS_DIR
from lib.test_mock_server import MockHandler, MockServer

ADDRESS = ("127.0.0.7", 9898)


GITHUB_DATA: dict[str, JsonDict] = {
    "/repos/cockpit-project/bots/issues/1": {
        "number": 1,
        "title": "Some random bug",
        "body": "it doesn't work",
        # in our allowlist
        "user": {"login": "cockpit-project"},
        "labels": [{"name": "bug"}],
    },
    "/repos/cockpit-project/bots/issues/2": {
        "number": 2,
        "title": "Refresh foonux image",
        "body": "blabla\n - [ ] image-refresh foonux\n",
        # is in our allowlist
        "user": {"login": "cockpit-project"},
        "labels": [{"name": "bot"}],
    },
    "/repos/cockpit-project/bots/issues/99": {
        "number": 99,
        "title": "Some random bug",
        "body": "it doesn't work",
        # not in our allowlist
        "user": {"login": "randomuser"},
        "labels": [],
    },
    "/repos/cockpit-project/bots/pull/3": {
        "number": 3,
        "title": "Fix barnux image",
        "body": "Fix the breakage\n - [ ] image-refresh barnux\n",
        # is in our allowlist
        "user": {"login": "cockpit-project"},
        "labels": [{"name": "bot"}],
    },
    "/repos/cockpit-project/bots/git/ref/heads/main": {
        "object": {"sha": "123abc"},
    },
}

EXPECTED_JOB_ISSUE_2: JsonObject = {
    "job": {
        "repo": "cockpit-project/bots",
        "sha": "123abc",
        "pull": None,
        "slug": "image-refresh-foonux-123abc-20240102-030405",
        "context": "image-refresh/foonux",
        "command": ["./image-refresh", "--verbose", "--issue=2", "foonux"],
        "secrets": ["github-token", "image-upload"],
    },
    "human": "issue-2 image-refresh foonux main",
}

EXPECTED_JOB_PULL_3: JsonObject = {
    "job": {
        "repo": "cockpit-project/bots",
        "sha": "123abc",
        "pull": None,
        "slug": "image-refresh-barnux-123abc-20240102-030405",
        "context": "image-refresh/barnux",
        "command": ["./image-refresh", "--verbose", "--issue=3", "barnux"],
        "secrets": ["github-token", "image-upload"],
    },
    "human": "issue-3 image-refresh barnux main",
}


class Handler(MockHandler[dict[str, JsonDict]]):
    def do_GET(self) -> None:
        if self.path in self.server.data:
            self.replyJson(self.server.data[self.path])
        elif self.path.startswith('/repos/cockpit-project/bots/issues?'):
            self.replyJson([
                self.server.data['/repos/cockpit-project/bots/issues/1'],
                self.server.data['/repos/cockpit-project/bots/issues/2'],
                self.server.data['/repos/cockpit-project/bots/issues/99'],
                self.server.data['/repos/cockpit-project/bots/pull/3'],
            ])
        else:
            self.send_error(404, 'Mock Not Found: ' + self.path)

    def do_POST(self) -> None:
        self.send_error(405, 'Mock method not allowed: ' + self.path)


class TestIssueScan(unittest.TestCase):
    issue_scan_module: ModuleType

    @classmethod
    def setUpClass(cls) -> None:
        loader = importlib.machinery.SourceFileLoader("issue_scan", os.path.join(BOTS_DIR, "issue-scan"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        cls.issue_scan_module = module

    def setUp(self) -> None:
        self.temp = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp, "cache")
        os.environ["XDG_CACHE_HOME"] = self.cache_dir
        self.server = MockServer(ADDRESS, Handler, GITHUB_DATA)
        self.server.start()
        os.environ["GITHUB_API"] = f"http://{ADDRESS[0]}:{ADDRESS[1]}"

    def tearDown(self) -> None:
        self.server.kill()
        shutil.rmtree(self.temp)

    @unittest.mock.patch("sys.stderr", new_callable=io.StringIO)
    @unittest.mock.patch("sys.stdout", new_callable=io.StringIO)
    # fake the time so that we get predictable test names
    @unittest.mock.patch("time.strftime", return_value="20240102-030405")
    def run_issue_scan(
        self, args: Sequence[str], mock_strftime: object, mock_stdout: io.StringIO, mock_stderr: io.StringIO
    ) -> tuple[str | int | None, str, str]:
        with unittest.mock.patch("sys.argv", ["issue-scan", "--repo", "cockpit-project/bots", *args]):
            code: str | int | None
            try:
                self.issue_scan_module.main()
                code = 0
            except SystemExit as e:
                code = e.code

        return code, mock_stdout.getvalue(), mock_stderr.getvalue()

    def run_success(self, args: Sequence[str], expected_output: str) -> None:
        code, output, stderr = self.run_issue_scan(args)

        assert code == 0
        assert stderr == ""
        assert output == expected_output

    def run_success_json(self, args: Sequence[str], expected_jobs: Sequence[JsonObject]) -> None:
        code, output, stderr = self.run_issue_scan(args)

        assert code == 0
        assert stderr == ""
        assert list(map(json.loads, output.splitlines())) == expected_jobs

    def test_scan_ghapi_default(self) -> None:
        self.run_success_json([], [EXPECTED_JOB_ISSUE_2, EXPECTED_JOB_PULL_3])

    def test_scan_ghapi_human(self) -> None:
        self.run_success(
            ["--human-readable"], "issue-2 image-refresh foonux main\nissue-3 image-refresh barnux main\n"
        )

    @unittest.mock.patch("lib.distributed_queue.DistributedQueue")
    def test_scan_ghapi_amqp(self, mock_queue: unittest.mock.MagicMock) -> None:
        self.run_success(["--amqp", "amqp.example.com:1234"], "")

        mock_queue.assert_called_with("amqp.example.com:1234", queues=["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        self.assertEqual(channel.basic_publish.call_count, 2)

        # first call for issues/2
        self.assertEqual(channel.basic_publish.call_args_list[0][0][0], "")
        self.assertEqual(channel.basic_publish.call_args_list[0][0][1], "public")
        request = json.loads(channel.basic_publish.call_args_list[0][0][2])
        assert request == EXPECTED_JOB_ISSUE_2

        # second call for pull/3
        self.assertEqual(channel.basic_publish.call_args_list[1][0][0], "")
        self.assertEqual(channel.basic_publish.call_args_list[1][0][1], "public")
        request = json.loads(channel.basic_publish.call_args_list[1][0][2])
        assert request == EXPECTED_JOB_PULL_3

    def test_scan_clidata_default(self) -> None:
        self.run_success_json(
            [
                "--issues-data",
                json.dumps({
                    "issue": GITHUB_DATA['/repos/cockpit-project/bots/issues/2'],
                    "repository": {"full_name": "cockpit-project/bots"},
                }),
            ],
            [EXPECTED_JOB_ISSUE_2],
        )

    def test_scan_clidata_no_bots_label(self) -> None:
        issue = GITHUB_DATA['/repos/cockpit-project/bots/issues/2'].copy()
        issue["labels"] = []

        self.run_success(
            [
                "--issues-data",
                json.dumps({
                    "issue": issue,
                    "repository": {"full_name": "cockpit-project/bots"},
                }),
            ],
            "",
        )

    # this represents what actually happens in production
    @unittest.mock.patch("lib.distributed_queue.DistributedQueue")
    def test_scan_clidata_amqp(self, mock_queue: unittest.mock.MagicMock) -> None:
        self.run_success(
            [
                "--amqp",
                "amqp.example.com:1234",
                "--issues-data",
                json.dumps({
                    "issue": GITHUB_DATA['/repos/cockpit-project/bots/issues/2'],
                    "repository": {"full_name": "cockpit-project/bots"},
                }),
            ],
            "",
        )

        mock_queue.assert_called_once_with("amqp.example.com:1234", queues=["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])
        assert request == EXPECTED_JOB_ISSUE_2


if __name__ == '__main__':
    unittest.main()
