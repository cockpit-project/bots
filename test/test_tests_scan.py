#!/usr/bin/env python3

# This file is part of Cockpit.
#
# Copyright (C) 2023 Red Hat, Inc.
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
    "/repos/project/repo": {
        "default_branch": "main"
    },
    "/repos/project/repo/issues/3333": {
        "title": "The issue title",
        "body": "Some bug\n - [ ] image-refresh foonux\n",
    },
    "/repos/project/repo/pulls/1": {
        "title": "PR title",
        "number": 1,
        "state": "open",
        "body": "This is the body",
        "base": {"ref": "stable-1.0"},
        "head": {"sha": "abcdef", "user": {"login": "cockpit-project"}},
        "labels": [],
        "updated_at": 0,
    },
    # no-test PR
    "/repos/project/repo/pulls/3": {
        "title": "WIP stuff",
        "number": 1,
        "state": "open",
        "body": "Don't run me yet",
        "base": {"ref": "stable-1.0"},
        "head": {"sha": "abcdef", "user": {"login": "cockpit-project"}},
        "labels": [{"name": "no-test"}],
        "updated_at": 0,
    },
    "/repos/project/repo/commits/abcdef/status?page=1&per_page=100": {
        "state": "pending",
        "statuses": [],
        "sha": "abcdef",
    },
    "/repos/cockpit-project/cockpit/commits/abcdef/pulls": [{"state": "closed"}],
    # HACK: we can't change the test map dynamically when invoked via test-scan
    "/repos/cockpit-project/cockpit/commits/abcdef/status?page=1&per_page=100": {
        "state": "pending",
        "statuses": [],
        "sha": "abcdef",
    },
    # SHA without a PR
    "/repos/project/repo/commits/9988aa/status?page=1&per_page=100": {
        "state": "pending",
        "statuses": [],
        "sha": "9988aa",
    },
    # anaconda SHA without a PR
    "/repos/rhinstaller/anaconda-webui/commits/112233/status?page=1&per_page=100": {
        "state": "pending",
        "statuses": [],
        "sha": "112233",
    },
    "/users/user/repos": [{"full_name": "project/repo"}],
}


class Handler(MockHandler):
    def do_GET(self):
        if self.path in self.server.data:
            self.replyJson(self.server.data[self.path])
        elif self.path.startswith('/repos/project/repo/pulls?'):
            self.replyJson([self.server.data['/repos/project/repo/pulls/1'],
                            self.server.data['/repos/project/repo/pulls/3']])
        elif self.path.endswith("/issues"):
            issues = self.server.data.get('issues', [])
            self.replyJson(issues)
        else:
            self.send_error(404, 'Mock Not Found: ' + self.path)

    def do_POST(self):
        if self.path.startswith("/repos/cockpit-project/cockpit/issues"):
            content_len = int(self.headers.get('content-length'))
            data = json.loads(self.rfile.read(content_len).decode('utf-8'))
            self.server.data['issues'] = [data]
            self.replyJson(data)
        else:
            self.send_error(405, 'Method not allowed: ' + self.path)


class TestTestsScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("tests_scan", os.path.join(BOTS_DIR, "tests-scan"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        cls.tests_scan_module = module

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp, "cache")
        os.environ["XDG_CACHE_HOME"] = self.cache_dir
        self.server = MockServer(ADDRESS, Handler, GITHUB_DATA)
        self.server.start()
        self.repo = "project/repo"
        self.pull_number = 1
        self.context = "fedora/nightly"
        self.revision = "abcdef"
        os.environ["GITHUB_API"] = f"http://{ADDRESS[0]}:{ADDRESS[1]}"

        # expected human output for our standard mock PR #1 above
        self.expected_human_output = (
            f"pull-{self.pull_number}      {self.context}            {self.revision}"
            f"       ({self.repo}) [bots@main]   {{stable-1.0}}\n")

    def tearDown(self):
        self.server.kill()
        shutil.rmtree(self.temp)

    @unittest.mock.patch("sys.stderr", new_callable=io.StringIO)
    @unittest.mock.patch("sys.stdout", new_callable=io.StringIO)
    # fake the time so that we get predictable test names
    @unittest.mock.patch("time.strftime", return_value="20240102-030405")
    def run_tests_scan(
        self,
        args: list[str],
        _mock_strftime: unittest.mock.MagicMock,
        mock_stdout: unittest.mock.MagicMock,
        mock_stderr: unittest.mock.MagicMock,
        repo: str | None = None
    ) -> tuple[str | int, str, str]:
        with unittest.mock.patch("sys.argv", ["tests-scan", "--repo", repo or self.repo, *args]):
            try:
                self.tests_scan_module.main()  # type: ignore[attr-defined]
                code: str | int = 0
            except SystemExit as e:
                assert e.code
                code = e.code

        return code, mock_stdout.getvalue(), mock_stderr.getvalue()

    def run_success(self, args: list[str], expected_output: str, repo: str | None = None) -> None:
        code, output, stderr = self.run_tests_scan(args, repo=repo)

        assert code == 0
        assert stderr == ""
        assert output == expected_output

    # expected job JSON output for our standard mock PR #1 above
    def run_success_mock_pr(self, args):
        code, output, stderr = self.run_tests_scan(args)

        assert code == 0
        assert stderr == ""
        assert json.loads(output) == {
            'pull': self.pull_number,
            'context': self.context,
            'env': {
                'BASE_BRANCH': 'stable-1.0',
                'COCKPIT_BOTS_REF': 'main',
                'TEST_PULL': str(self.pull_number),
                'TEST_REVISION': self.revision,
                'TEST_OS': 'fedora',
                'TEST_SCENARIO': 'nightly'},
            'repo': self.repo,
            'command_subject': None,
            'report': None,
            'secrets': ['github-token', 'image-download'],
            'sha': self.revision,
            'slug': f'pull-{self.pull_number}-{self.revision}-20240102-030405-fedora-nightly',
        }

    def test_pull_number(self):
        args = ["--dry", "--pull-number", str(self.pull_number), "--context", self.context]
        self.run_success_mock_pr(args)

    def test_notest_pull_number(self):
        args = ["--dry", "--pull-number=3", "--context", self.context]
        self.run_success(args, "")

    def test_unkown_pull_number(self):
        args = ["--dry", "--pull-number", "2", "--context", "fedora/nightly"]
        code, output, stderr = self.run_tests_scan(args)

        # sys.exit(str) will do that to you..
        assert code == "Can't find pull request 2"
        assert stderr == ""
        assert output == ""

    def test_pull_data(self):
        args = ["--dry", "--context", self.context,
                "--pull-data", json.dumps({'pull_request': GITHUB_DATA['/repos/project/repo/pulls/1']})]
        self.run_success_mock_pr(args)

    def test_no_arguments(self):
        self.run_success_mock_pr(["--dry", "--context", self.context])

    def test_pull_number_human_readable(self):
        self.run_success(["--dry", "-v", "--context", self.context, "--pull-number", str(self.pull_number)],
                         self.expected_human_output)

    def test_notest_human_readable(self):
        self.run_success(["--dry", "-v", "--context", self.context, "--pull-number=3"], "")

    def test_pull_data_human_readable(self):
        args = ["--dry", "-v", "--context", self.context,
                "--pull-data", json.dumps({'pull_request': GITHUB_DATA['/repos/project/repo/pulls/1']})]
        self.run_success(args, self.expected_human_output)

    def test_no_arguments_human_readable(self):
        self.run_success(["--dry", "-v", "--context", self.context], self.expected_human_output)

    def test_no_pull_request_human(self):
        repo = "cockpit-project/cockpit"
        expected_output = (f"pull-0      {self.context}            {self.revision}"
                           f"       ({repo}) [bots@main]\n")

        self.run_success(["--dry", "-v", "--sha", self.revision, "--context", self.context],
                         expected_output, repo=repo)

    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_amqp_pr(self, mock_queue):
        args = ["--dry", "--context", self.context, "--amqp", "amqp.example.com:1234"]
        self.run_success(args, "")

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        assert request == {
            "human": self.expected_human_output.rstrip(),
            "job": {
                "context": "fedora/nightly",
                "repo": "project/repo",
                "pull": self.pull_number,
                "report": None,
                "sha": "abcdef",
                "slug": f"pull-{self.pull_number}-abcdef-20240102-030405-fedora-nightly",
                "command_subject": None,
                "secrets": ["github-token", "image-download"],
                "env": {
                    "BASE_BRANCH": "stable-1.0",
                    "COCKPIT_BOTS_REF": "main",
                    'TEST_PULL': str(self.pull_number),
                    'TEST_REVISION': self.revision,
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            }
        }

    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_amqp_sha_nightly(self, mock_queue):
        """Nightly test on main branch, without PR"""
        # SHA without PR
        args = ["--dry", "--context", self.context, "--sha", "9988aa", "--amqp", "amqp.example.com:1234"]
        self.run_success(args, "")

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        assert request == {
            "human": "pull-0      fedora/nightly            9988aa       (project/repo) [bots@main]",
            "job": {
                "context": "fedora/nightly",
                "repo": "project/repo",
                "sha": "9988aa",
                "slug": "pull-0-9988aa-20240102-030405-fedora-nightly",
                "pull": None,
                "report": {
                    "title": "Tests failed on 9988aa",
                    "labels": ["nightly"],
                },
                "command_subject": None,
                "secrets": ["github-token", "image-download"],
                "env": {
                    "COCKPIT_BOTS_REF": "main",
                    'TEST_REVISION': "9988aa",
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            }
        }

    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_anaconda_secrets(self, mock_queue):
        """anaconda-webui gets extra secrets"""
        # SHA without PR
        args = ["--dry", "--repo", "rhinstaller/anaconda-webui", "--context", self.context,
                "--sha", "112233", "--amqp", "amqp.example.com:1234"]
        self.run_success(args, "")

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        assert request == {
            "human": "pull-0      fedora/nightly            112233       (rhinstaller/anaconda-webui) [bots@main]",
            "job": {
                "context": "fedora/nightly",
                "repo": "rhinstaller/anaconda-webui",
                "sha": "112233",
                "slug": "pull-0-112233-20240102-030405-fedora-nightly",
                "pull": None,
                "report": {
                    "title": "Tests failed on 112233",
                    "labels": ["nightly"],
                },
                "command_subject": None,
                "secrets": ["github-token", "image-download", "fedora-wiki", "fedora-wiki-staging"],
                "env": {
                    "COCKPIT_BOTS_REF": "main",
                    'TEST_REVISION': "112233",
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            }
        }

    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_amqp_sha_pr(self, mock_queue):
        """Status event on PR, via human tests-trigger"""

        # SHA is attached to PR #1
        args = ["--dry", "--context", self.context, "--sha", "abcdef", "--amqp", "amqp.example.com:1234"]
        self.run_success(args, "")

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        assert request == {
            "human": self.expected_human_output.rstrip(),
            "job": {
                "context": "fedora/nightly",
                "repo": "project/repo",
                "pull": self.pull_number,
                "report": None,
                "sha": "abcdef",
                "slug": f"pull-{self.pull_number}-abcdef-20240102-030405-fedora-nightly",
                "command_subject": None,
                "secrets": ["github-token", "image-download"],
                "env": {
                    "BASE_BRANCH": "stable-1.0",
                    "COCKPIT_BOTS_REF": "main",
                    'TEST_PULL': str(self.pull_number),
                    'TEST_REVISION': self.revision,
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            }
        }

    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def do_test_amqp_pr_cross_project(self, status_branch, mock_queue):
        repo_branch = f"cockpit-project/cockpituous{f'/{status_branch}' if status_branch else ''}"
        # SHA is attached to PR #1
        args = ["--dry", "--sha", "abcdef", "--amqp", "amqp.example.com:1234",
                # need to pick a project with a REPO_BRANCH_CONTEXT entry for default branch
                "--context", f"{self.context}@{repo_branch}"]
        self.run_success(args, "")

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        branch = status_branch or "main"

        slug_repo_branch = repo_branch.replace('@', '-').replace('/', '-')

        assert request == {
            "human": ("pull-1      fedora/nightly            abcdef       "
                      f"(cockpit-project/cockpituous) [bots@main]   {{{branch}}}"),
            "job": {
                # reports for project/reop
                "context": f"fedora/nightly@{repo_branch}",
                # but tests cockpituous
                "command_subject": {"repo": "cockpit-project/cockpituous", "branch": branch},
                "repo": "project/repo",
                "pull": self.pull_number,
                "report": None,
                "sha": "abcdef",
                "slug": f"pull-{self.pull_number}-abcdef-20240102-030405-fedora-nightly-{slug_repo_branch}",
                "secrets": ["github-token", "image-download"],
                "env": {
                    "BASE_BRANCH": branch,
                    "COCKPIT_BOTS_REF": "main",
                    'TEST_PULL': str(self.pull_number),
                    'TEST_REVISION': self.revision,
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            },
        }

    def test_amqp_sha_pr_cross_project_default_branch(self):
        """Default branch cross-project status event on PR"""

        self.do_test_amqp_pr_cross_project(None)

    def test_amqp_sha_pr_cross_project_explicit_branch(self):
        """Explicit branch cross-project status event on PR"""

        self.do_test_amqp_pr_cross_project("otherbranch")


if __name__ == '__main__':
    unittest.main()
