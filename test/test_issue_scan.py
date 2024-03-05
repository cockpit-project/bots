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

import importlib
import io
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock

from lib.constants import BOTS_DIR
from task.test_mock_server import MockHandler, MockServer

ADDRESS = ("127.0.0.7", 9898)


GITHUB_DATA = {
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
    }
}

EXPECTED_COMMAND_ISSUE_2 = (
    "./s3-streamer --repo cockpit-project/bots --test-name image-refresh-foonux-20240102-030405 "
    "--github-context image-refresh/foonux --revision 123abc -- sh -exc '"
    "./make-checkout --verbose --repo cockpit-project/bots main; cd make-checkout-workdir; "
    "./image-refresh --verbose --issue=2 foonux'"
)

EXPECTED_COMMAND_PULL_3 = (
    "./s3-streamer --repo cockpit-project/bots --test-name image-refresh-barnux-20240102-030405 "
    "--github-context image-refresh/barnux --revision 123abc -- sh -exc '"
    "./make-checkout --verbose --repo cockpit-project/bots main; cd make-checkout-workdir; "
    "./image-refresh --verbose --issue=3 barnux'"
)


class Handler(MockHandler):
    def do_GET(self):
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

    def do_POST(self):
        self.send_error(405, 'Mock method not allowed: ' + self.path)


class TestIssueScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("issue_scan", os.path.join(BOTS_DIR, "issue-scan"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        cls.issue_scan_module = module

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp, "cache")
        os.environ["XDG_CACHE_HOME"] = self.cache_dir
        self.server = MockServer(ADDRESS, Handler, GITHUB_DATA)
        self.server.start()
        os.environ["GITHUB_API"] = f"http://{ADDRESS[0]}:{ADDRESS[1]}"

    def tearDown(self):
        self.server.kill()
        shutil.rmtree(self.temp)

    @unittest.mock.patch("sys.stderr", new_callable=io.StringIO)
    @unittest.mock.patch("sys.stdout", new_callable=io.StringIO)
    # fake the time so that we get predictable test names
    @unittest.mock.patch("time.strftime", return_value="20240102-030405")
    def run_issue_scan(self, args, _mock_strftime, mock_stdout, mock_stderr):
        with unittest.mock.patch("sys.argv", ["issue-scan", "--repo", "cockpit-project/bots", *args]):
            try:
                self.issue_scan_module.main()
                code = 0
            except SystemExit as e:
                code = e.code

        return code, mock_stdout.getvalue(), mock_stderr.getvalue()

    def test_scan_ghapi_default(self):
        code, output, error = self.run_issue_scan([])

        self.assertEqual(code, 0)
        self.assertEqual(error, '')
        self.maxDiff = None
        self.assertEqual(output, f'{EXPECTED_COMMAND_ISSUE_2}\n{EXPECTED_COMMAND_PULL_3}\n')

    def test_scan_ghapi_human(self):
        code, output, error = self.run_issue_scan(["--human-readable"])

        self.assertEqual(code, 0)
        self.assertEqual(error, '')
        self.assertEqual(output, ("issue-2 image-refresh foonux main\n"
                                  "issue-3 image-refresh barnux main\n"))

    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_scan_ghapi_amqp(self, mock_queue):
        code, output, error = self.run_issue_scan(["--amqp", "amqp.example.com:1234"])

        self.assertEqual(code, 0)
        self.assertEqual(error, '')
        self.assertEqual(output, '')

        mock_queue.assert_called_with("amqp.example.com:1234", queues=["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        self.assertEqual(channel.basic_publish.call_count, 2)

        # first call for issues/2
        self.assertEqual(channel.basic_publish.call_args_list[0][0][0], "")
        self.assertEqual(channel.basic_publish.call_args_list[0][0][1], "public")
        request = json.loads(channel.basic_publish.call_args_list[0][0][2])

        assert request == {
            'command': EXPECTED_COMMAND_ISSUE_2,
            'type': 'issue',
            'human': 'issue-2 image-refresh foonux main',
            'job': {
                'command': ['./image-refresh', '--verbose', '--issue=2', 'foonux'],
                'context': 'image-refresh/foonux',
                'pull': None,
                'repo': 'cockpit-project/bots',
                'secrets': ['github-token', 'image-upload'],
                'sha': '123abc',
                'slug': 'image-refresh-foonux-123abc-20240102-030405'
            }
        }

        # second call for pull/3
        self.assertEqual(channel.basic_publish.call_args_list[1][0][0], "")
        self.assertEqual(channel.basic_publish.call_args_list[1][0][1], "public")
        request = json.loads(channel.basic_publish.call_args_list[1][0][2])

        assert request == {
            'command': EXPECTED_COMMAND_PULL_3,
            'type': 'issue',
            'human': 'issue-3 image-refresh barnux main',
            'job': {
                'command': ['./image-refresh', '--verbose', '--issue=3', 'barnux'],
                'context': 'image-refresh/barnux',
                'pull': None,
                'repo': 'cockpit-project/bots',
                'secrets': ['github-token', 'image-upload'],
                'sha': '123abc',
                'slug': 'image-refresh-barnux-123abc-20240102-030405'
            }
        }

    def test_scan_clidata_default(self):
        code, output, error = self.run_issue_scan([
            "--issues-data",
            json.dumps({
                "issue": GITHUB_DATA['/repos/cockpit-project/bots/issues/2'],
                "repository": {"full_name": "cockpit-project/bots"},
            })
        ])

        self.assertEqual(error, '')
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), EXPECTED_COMMAND_ISSUE_2)

    def test_scan_clidata_no_bots_label(self):
        issue = GITHUB_DATA['/repos/cockpit-project/bots/issues/2'].copy()
        issue["labels"] = []

        code, output, error = self.run_issue_scan([
            "--issues-data",
            json.dumps({
                "issue": issue,
                "repository": {"full_name": "cockpit-project/bots"},
            })
        ])

        self.assertEqual(error, '')
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), '')

    # this represents what actually happens in production
    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_scan_clidata_amqp(self, mock_queue):
        code, output, error = self.run_issue_scan([
            "--amqp", "amqp.example.com:1234",
            "--issues-data",
            json.dumps({
                "issue": GITHUB_DATA['/repos/cockpit-project/bots/issues/2'],
                "repository": {"full_name": "cockpit-project/bots"},
            })
        ])

        self.assertEqual(code, 0)
        self.assertEqual(error, '')
        self.assertEqual(output, '')

        mock_queue.assert_called_once_with("amqp.example.com:1234", queues=["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        assert request == {
            'command': EXPECTED_COMMAND_ISSUE_2,
            'type': 'issue',
            'human': 'issue-2 image-refresh foonux main',
            'job': {
                'command': ['./image-refresh', '--verbose', '--issue=2', 'foonux'],
                'context': 'image-refresh/foonux',
                'pull': None,
                'repo': 'cockpit-project/bots',
                'secrets': ['github-token', 'image-upload'],
                'sha': '123abc',
                'slug': 'image-refresh-foonux-123abc-20240102-030405'
            }
        }


if __name__ == '__main__':
    unittest.main()
