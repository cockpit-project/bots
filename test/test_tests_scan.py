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
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

from lib.constants import BOTS_DIR
from task import github
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
    "/users/user/repos": [{"full_name": "project/repo"}],
}


class Handler(MockHandler):
    def do_GET(self):
        if self.path in self.server.data:
            self.replyJson(self.server.data[self.path])
        elif self.path.startswith('/repos/project/repo/pulls?'):
            self.replyJson([self.server.data['/repos/project/repo/pulls/1']])
        elif self.path.endswith("/issues"):
            issues = self.server.data.get('issues', [])
            self.replyJson(issues)
        elif self.path == "/project/repo/abcdef/.cockpit-ci/container":
            self.replyData("supertasks")
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
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp, "cache")
        os.environ["XDG_CACHE_HOME"] = self.cache_dir
        self.server = MockServer(ADDRESS, Handler, GITHUB_DATA)
        self.server.start()
        self.repo = "project/repo"
        self.pull_number = "1"
        self.context = "fedora/nightly"
        self.revision = "abcdef"
        os.environ["GITHUB_API"] = f"http://{ADDRESS[0]}:{ADDRESS[1]}"

    def tearDown(self):
        self.server.kill()
        shutil.rmtree(self.temp)

    def run_tests_scan(self, args):
        script = os.path.join(BOTS_DIR, "tests-scan")
        proc = subprocess.Popen([script, *args], stdout=subprocess.PIPE, universal_newlines=True)
        output, stderr = proc.communicate()
        return proc, output, stderr

    def expected_command(self):
        return (f"./s3-streamer --repo {self.repo} --test-name pull-{self.pull_number}-\\d+-\\d+"
                f" --github-context {self.context} --revision {self.revision} -- /bin/sh -c"
                f" \"PRIORITY=0005 ./make-checkout --verbose --repo={self.repo} --rebase=stable-1.0 {self.revision}"
                f" && cd make-checkout-workdir && TEST_OS=fedora BASE_BRANCH=stable-1.0"
                " COCKPIT_BOTS_REF=main TEST_SCENARIO=nightly ../tests-invoke --pull-number"
                f" {self.pull_number} --revision {self.revision} --repo {self.repo}\"")

    def expected_human_output(self, pull_number=None):
        if pull_number is None:
            pull_number = self.pull_number
        return (f"pull-{pull_number}      {self.context}            {self.revision}"
                f"     5.99999  ({self.repo}) [bots@main]   {{stable-1.0}}")

    def test_pull_number(self):
        args = ["--dry", "--repo", self.repo, "--pull-number", self.pull_number,
                "--context", self.context]
        proc, output, stderr = self.run_tests_scan(args)

        self.assertEqual(proc.returncode, 0)
        expected_output = self.expected_command()
        self.assertRegex(output, expected_output)
        self.assertIsNone(stderr)

    def test_unkown_pull_number(self):
        args = ["--dry", "--repo", self.repo, "--pull-number", "2", "--context", "fedora/nightly"]
        proc, _, stderr = self.run_tests_scan(args)

        self.assertEqual(proc.returncode, 1)
        self.assertIsNone(stderr)

    def test_pull_data(self):
        args = ["--dry", "--repo", self.repo, "--pull-data",
                json.dumps({'pull_request': GITHUB_DATA['/repos/project/repo/pulls/1']}),
                "--context", self.context]
        proc, output, stderr = self.run_tests_scan(args)

        self.assertEqual(proc.returncode, 0)
        expected_output = self.expected_command()
        self.assertRegex(output, expected_output)
        self.assertIsNone(stderr)

    def test_no_arguments(self):
        args = ["--dry", "--repo", self.repo, "--context", self.context]
        proc, output, stderr = self.run_tests_scan(args)

        self.assertEqual(proc.returncode, 0)
        expected_output = self.expected_command()
        self.assertRegex(output.strip(), expected_output)
        self.assertIsNone(stderr)

    def test_pull_number_human_readable(self):
        args = ["--dry", "--repo", self.repo, "--pull-number", self.pull_number,
                "--context", self.context, "-v"]
        proc, output, stderr = self.run_tests_scan(args)

        self.assertEqual(proc.returncode, 0)
        expected_output = self.expected_human_output()
        self.assertEqual(output.strip(), expected_output)
        self.assertIsNone(stderr)

    def test_pull_data_human_readable(self):
        args = ["--dry", "--repo", self.repo, "--pull-data",
                json.dumps({'pull_request': GITHUB_DATA['/repos/project/repo/pulls/1']}),
                "--context", self.context, "-v"]
        proc, output, stderr = self.run_tests_scan(args)

        self.assertEqual(proc.returncode, 0)
        expected_output = self.expected_human_output()
        self.assertEqual(output.strip(), expected_output)
        self.assertIsNone(stderr)

    def test_no_arguments_human_readable(self):
        args = ["--dry", "--repo", self.repo, "--context", self.context, "-v"]
        proc, output, stderr = self.run_tests_scan(args)

        self.assertEqual(proc.returncode, 0)
        expected_output = self.expected_human_output()
        self.assertEqual(output.strip(), expected_output)
        self.assertIsNone(stderr)

    def test_no_pull_request(self):
        repo = "cockpit-project/cockpit"
        args = ["--dry", "--sha", self.revision, "--repo", repo,
                "--context", self.context]
        proc, output, stderr = self.run_tests_scan(args)
        expected_output = (f"./s3-streamer --repo {repo} --test-name pull-\\d+-\\d+-\\d+"
                           f" --github-context {self.context} --revision {self.revision} -- /bin/sh -c"
                           f" \"PRIORITY=0006 ./make-checkout --verbose --repo={repo} {self.revision}"
                           f" && cd make-checkout-workdir && TEST_OS=fedora"
                           " COCKPIT_BOTS_REF=main TEST_SCENARIO=nightly ../tests-invoke"
                           f" --revision {self.revision} --repo {repo}\"")

        self.assertEqual(proc.returncode, 0)
        self.assertRegex(output.strip(), expected_output)
        self.assertIsNone(stderr)

    def test_no_pull_request_human(self):
        repo = "cockpit-project/cockpit"
        args = ["--dry", "--sha", self.revision, "--repo", repo,
                "--context", self.context, "-v"]
        proc, output, stderr = self.run_tests_scan(args)
        expected_output = (f"pull-0      {self.context}            {self.revision}"
                           f"     6.0  ({repo}) [bots@main]")

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(output.strip(), expected_output)
        self.assertIsNone(stderr)

    @staticmethod
    def get_tests_scan_module():
        """in-process version of tests-scan

        This is useful for mocking.
        """
        loader = importlib.machinery.SourceFileLoader("tests_scan", os.path.join(BOTS_DIR, "tests-scan"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    # mock time for predictable test name
    @unittest.mock.patch("time.strftime", return_value="20240102-030405")
    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_amqp_pr(self, mock_queue, _mock_strftime):
        args = ["tests-scan", "--dry", "--repo", self.repo, "--context", self.context,
                "--amqp", "amqp.example.com:1234"]

        with unittest.mock.patch("sys.argv", args):
            # needs to be in-process for mocking
            self.get_tests_scan_module().main()

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        expected_command = (
            f"./s3-streamer --repo {self.repo} --test-name pull-{self.pull_number}-20240102-030405"
            f" --github-context {self.context} --revision {self.revision} -- /bin/sh -c"
            f" \"PRIORITY=0005 ./make-checkout --verbose --repo={self.repo} --rebase=stable-1.0 {self.revision}"
            f" && cd make-checkout-workdir && TEST_OS=fedora BASE_BRANCH=stable-1.0"
            " COCKPIT_BOTS_REF=main TEST_SCENARIO=nightly ../tests-invoke --pull-number"
            f" {self.pull_number} --revision {self.revision} --repo {self.repo}\"")

        assert request == {
            "command": expected_command,
            "type": "test",
            "sha": "abcdef",
            "ref": "abcdef",
            "name": f"pull-{self.pull_number}",
            "job": {
                "context": "fedora/nightly",
                "repo": "project/repo",
                "pull": int(self.pull_number),
                "report": None,
                "sha": "abcdef",
                "slug": f"pull-{self.pull_number}-abcdef-20240102-030405-fedora-nightly",
                "target": "stable-1.0",
                "container": "supertasks",
                "secrets": ["github-token", "image-download"],
                "env": {
                    "BASE_BRANCH": "stable-1.0",
                    "COCKPIT_BOTS_REF": "main",
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            }
        }

    # mock time for predictable test name
    @unittest.mock.patch("time.strftime", return_value="20240102-030405")
    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_amqp_sha_nightly(self, mock_queue, _mock_strftime):
        """Nightly test on main branch, without PR"""
        # SHA without PR
        args = ["tests-scan", "--dry", "--repo", self.repo, "--context", self.context,
                "--sha", "9988aa", "--amqp", "amqp.example.com:1234"]

        with unittest.mock.patch("sys.argv", args):
            # needs to be in-process for mocking
            self.get_tests_scan_module().main()

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        expected_command = (
            './s3-streamer --repo project/repo --test-name pull-0-20240102-030405 '
            '--github-context fedora/nightly --revision 9988aa -- /bin/sh -c "PRIORITY=0005 '
            './make-checkout --verbose --repo=project/repo 9988aa && '
            'cd make-checkout-workdir && TEST_OS=fedora COCKPIT_BOTS_REF=main '
            'TEST_SCENARIO=nightly ../tests-invoke --revision 9988aa --repo project/repo"')
        self.maxDiff = None
        assert request == {
            "command": expected_command,
            "type": "test",
            "sha": "9988aa",
            "ref": "9988aa",
            "name": "pull-0",
            "job": {
                "context": "fedora/nightly",
                "repo": "project/repo",
                "sha": "9988aa",
                "slug": "pull-0-9988aa-20240102-030405-fedora-nightly",
                "target": None,
                "pull": None,
                "report": {
                    "title": "Tests failed on 9988aa",
                    "labels": ["nightly"],
                },
                # project/repo doesn't have a custom container name file
                "container": None,
                "secrets": ["github-token", "image-download"],
                "env": {
                    "COCKPIT_BOTS_REF": "main",
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            }
        }

    # mock time for predictable test name
    @unittest.mock.patch("time.strftime", return_value="20240102-030405")
    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def test_amqp_sha_pr(self, mock_queue, _mock_strftime):
        """Status event on PR, via human tests-trigger"""

        # SHA is attached to PR #1
        args = ["tests-scan", "--dry", "--repo", self.repo, "--context", self.context,
                "--sha", "abcdef", "--amqp", "amqp.example.com:1234"]

        with unittest.mock.patch("sys.argv", args):
            # needs to be in-process for mocking
            self.get_tests_scan_module().main()

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        expected_command = (
            './s3-streamer --repo project/repo --test-name pull-1-20240102-030405 '
            '--github-context fedora/nightly --revision abcdef -- /bin/sh -c "PRIORITY=0005 '
            './make-checkout --verbose --repo=project/repo --rebase=stable-1.0 abcdef && '
            'cd make-checkout-workdir && TEST_OS=fedora BASE_BRANCH=stable-1.0 COCKPIT_BOTS_REF=main '
            'TEST_SCENARIO=nightly ../tests-invoke --pull-number 1 --revision abcdef --repo project/repo"')
        assert request == {
            "command": expected_command,
            "type": "test",
            "sha": "abcdef",
            "ref": "abcdef",
            "name": f"pull-{self.pull_number}",
            "job": {
                "context": "fedora/nightly",
                "repo": "project/repo",
                "pull": int(self.pull_number),
                "report": None,
                "sha": "abcdef",
                "slug": f"pull-{self.pull_number}-abcdef-20240102-030405-fedora-nightly",
                "target": "stable-1.0",
                "container": "supertasks",
                "secrets": ["github-token", "image-download"],
                "env": {
                    "BASE_BRANCH": "stable-1.0",
                    "COCKPIT_BOTS_REF": "main",
                    "TEST_OS": "fedora",
                    "TEST_SCENARIO": "nightly",
                }
            }
        }

    # mock time for predictable test name
    @unittest.mock.patch("time.strftime", return_value="20240102-030405")
    @unittest.mock.patch("task.distributed_queue.DistributedQueue")
    def do_test_amqp_pr_cross_project(self, status_branch, mock_queue, _mock_strftime):
        repo_branch = f"cockpit-project/cockpituous{f'/{status_branch}' if status_branch else ''}"
        # SHA is attached to PR #1
        args = ["tests-scan", "--dry", "--repo", self.repo,
                # need to pick a project with a REPO_BRANCH_CONTEXT entry for default branch
                "--context", f"{self.context}@{repo_branch}",
                "--sha", "abcdef", "--amqp", "amqp.example.com:1234"]

        with unittest.mock.patch("sys.argv", args):
            # needs to be in-process for mocking
            self.get_tests_scan_module().main()

        mock_queue.assert_called_once_with("amqp.example.com:1234", ["rhel", "public"])
        channel = mock_queue.return_value.__enter__.return_value.channel

        channel.basic_publish.assert_called_once()
        self.assertEqual(channel.basic_publish.call_args[0][0], "")
        self.assertEqual(channel.basic_publish.call_args[0][1], "public")
        request = json.loads(channel.basic_publish.call_args[0][2])

        branch = status_branch or "main"

        # make-checkout tests cockpituous, but tests-invoke *reports* for project/repo
        expected_command = (
            './s3-streamer --repo project/repo --test-name pull-1-20240102-030405 '
            f'--github-context fedora/nightly@{repo_branch} --revision abcdef -- '
            '/bin/sh -c "PRIORITY=0005 '
            f'./make-checkout --verbose --repo=cockpit-project/cockpituous --rebase={branch} {branch} && '
            f'cd make-checkout-workdir && TEST_OS=fedora BASE_BRANCH={branch} COCKPIT_BOTS_REF=main '
            'TEST_SCENARIO=nightly ../tests-invoke --pull-number 1 --revision abcdef --repo project/repo"')

        assert request == {
            "command": expected_command,
            "type": "test",
            "sha": "abcdef",
            "ref": branch,
            "name": f"pull-{self.pull_number}",
            # job-runner currently disabled for cross-project tests (commit c377eb892)
            "job": None,
        }

    def test_amqp_sha_pr_cross_project_default_branch(self):
        """Default branch cross-project status event on PR"""

        self.do_test_amqp_pr_cross_project(None)

    def test_amqp_sha_pr_cross_project_explicit_branch(self):
        """Explicit branch cross-project status event on PR"""

        self.do_test_amqp_pr_cross_project("otherbranch")

    def do_test_tests_invoke(self, attachments_url, expected_logs_url):
        repo = "cockpit-project/cockpit"
        args = ["--revision", self.revision, "--repo", repo]
        script = os.path.join(BOTS_DIR, "tests-invoke")
        with tempfile.TemporaryDirectory() as tempdir:
            testdir = f"{tempdir}/.cockpit-ci"
            os.makedirs(testdir)
            with open(f"{testdir}/run", "w") as fp:
                fp.write("#!/bin/bash\nexit 1")
            os.system(f"chmod +x {testdir}/run")
            proc = subprocess.Popen([script, *args], stdout=subprocess.PIPE, universal_newlines=True,
                                    env={**os.environ,
                                         "TEST_INVOKE_SLEEP": "1", "TEST_OS": "fedora-38",
                                         "TEST_ATTACHMENTS_URL": attachments_url},
                                    cwd=tempdir)
            output, stderr = proc.communicate()
            api = github.GitHub(f"http://{ADDRESS[0]}:{ADDRESS[1]}/")
            issues = api.get("issues")

            self.assertEqual(output, "")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]['title'], "Nightly tests did not succeed on fedora-38")
            self.assertEqual(issues[0]['body'],
                             f"Tests failed on {self.revision}, [logs]({expected_logs_url})")
            self.assertEqual(issues[0]['labels'], ["nightly"])
            self.assertIsNone(stderr)

    def test_tests_invoke_noslash(self):
        self.do_test_tests_invoke("https://example.org/dir", "https://example.org/dir/log.html")

    def test_tests_invoke_slash(self):
        self.do_test_tests_invoke("https://example.org/dir/", "https://example.org/dir/log.html")

    def test_tests_invoke_no_issue_for_pr(self):
        args = ["--pull-number", "1", "--revision", self.revision, "--repo", self.repo]
        script = os.path.join(BOTS_DIR, "tests-invoke")
        with tempfile.TemporaryDirectory() as tempdir:
            testdir = f"{tempdir}/.cockpit-ci"
            os.makedirs(testdir)
            with open(f"{testdir}/run", "w") as fp:
                fp.write("#!/bin/bash\nexit 1")
            os.system(f"chmod +x {testdir}/run")
            proc = subprocess.Popen([script, *args], stdout=subprocess.PIPE, universal_newlines=True,
                                    env={**os.environ, "TEST_INVOKE_SLEEP": "1"},
                                    cwd=tempdir)
            output, stderr = proc.communicate()
            api = github.GitHub(f"http://{ADDRESS[0]}:{ADDRESS[1]}/")
            issues = api.get("issues")
            self.assertEqual(output, "")
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(len(issues), 0)
            self.assertIsNone(stderr)


if __name__ == '__main__':
    unittest.main()
