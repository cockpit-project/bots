#!/usr/bin/env python3

# This file is part of Cockpit.
#
# Copyright (C) 2017 Red Hat, Inc.
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

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from lib import task
from lib.aio.jsonutil import JsonObject
from lib.test_mock_server import MockHandler, MockServer

ADDRESS = ("127.0.0.9", 9898)


GITHUB_DATA: JsonObject = {
    "/repos/project/repo": {
        "default_branch": "main"
    },
    "/repos/project/repo/issues/3333": {
        "title": "The issue title",
        "body": "Some bug\n - [ ] image-refresh foonux\n",
    },
    "/repos/project/repo/pulls/1234": {
        "title": "Task title",
        "number": 1234,
        "body": "This is the body",
        "head": {"sha": "abcdef"},
    },
    "/users/user/repos": [{"full_name": "project/repo"}]
}


class Handler(MockHandler[JsonObject]):
    def do_GET(self) -> None:
        if self.path in self.server.data:
            self.replyJson(self.server.data[self.path])
        else:
            self.send_error(404, 'Mock Not Found: ' + self.path)

    def do_POST(self) -> None:
        if self.path == "/repos/project/repo/pulls":
            content_len = int(self.headers['content-length'])
            data = json.loads(self.rfile.read(content_len).decode('utf-8'))
            assert data['title'] == "[no-test] Task title"
            data["number"] = 1234
            self.replyJson(data)
        elif self.path == "/repos/project/repo/pulls/1234":
            content_len = int(self.headers['content-length'])
            data = json.loads(self.rfile.read(content_len).decode('utf-8'))
            data["number"] = 1234
            data["body"] = "This is the body"
            data["head"] = {"sha": "abcde"}
            self.replyJson(data)
        elif self.path == "/repos/project/repo/issues/1234/comments":
            content_len = int(self.headers['content-length'])
            data = json.loads(self.rfile.read(content_len).decode('utf-8'))
            self.replyJson(data)
        elif self.path == "/repos/project/repo/issues/1234/labels":
            content_len = int(self.headers['content-length'])
            data = json.loads(self.rfile.read(content_len).decode('utf-8'))
            self.replyJson(data)
        elif self.path.startswith("/repos/project/repo/issues/3333"):
            self.replyJson({})
        else:
            self.send_error(405, 'Method not allowed: ' + self.path)


def mock_execute(*args: str) -> str:
    assert args[0] == 'git'
    if args[1] == "show":
        return "Task title\n"
    elif args[1] == "commit" and args[2] == "--amend":
        if args[4] != "Task title\nCloses #1234":
            raise Exception("Incorrect commit message")
        return ""
    elif args[1] == "push":
        assert args[2] == "-f"
        return ""
    else:
        raise Exception("Mocking unsupported git command")


class TestTask(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MockServer(ADDRESS, Handler, GITHUB_DATA)
        self.server.start()
        self.temp = tempfile.mkdtemp()
        os.environ["GITHUB_API"] = "http://127.0.0.9:9898"
        os.environ["GITHUB_BASE"] = "project/repo"

    def tearDown(self) -> None:
        self.server.kill()
        shutil.rmtree(self.temp)
        os.unsetenv("GITHUB_API")
        os.unsetenv("GITHUB_BASE")

    def test_run_arguments(self) -> None:
        status = {"ran": False}

        def function(context: str, **kwargs: str) -> None:
            self.assertEqual(context, "my-context")
            self.assertEqual(kwargs["title"], "The issue title")
            status["ran"] = True

        ret = task.run("my-context", function, name="blah", title="Task title", issue=3333)  # type: ignore[no-untyped-call]
        self.assertEqual(ret, 0)
        self.assertTrue(status["ran"])

    def test_comment(self) -> None:
        comment = task.comment(1234, "This is the comment")  # type: ignore[no-untyped-call]
        assert isinstance(comment, dict)
        self.assertEqual(comment["body"], "This is the comment")

    def test_label(self) -> None:
        label = task.label(1234, ['xxx'])  # type: ignore[no-untyped-call]
        self.assertEqual(label, ['xxx'])

    @patch('lib.task.execute', mock_execute)
    def test_pull_body(self) -> None:
        pull = task.pull("branch", body="This is the body", title="Task title")  # type: ignore[no-untyped-call]
        assert isinstance(pull, dict)
        self.assertEqual(pull["title"], "Task title")
        self.assertEqual(pull["body"], "This is the body")


if __name__ == '__main__':
    unittest.main()
