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

from lib.aio.jsonutil import JsonObject
from lib.github import GitHub
from lib.test_mock_server import MockHandler, MockServer

GITHUB_DATA: JsonObject = {
    "/repos/project/repo": {
        "default_branch": "main"
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
        content_len = int(self.headers['content-length'])
        data = json.loads(self.rfile.read(content_len).decode('utf-8'))
        if self.path == "/repos/project/repo/pulls":
            data["number"] = 1234
            self.replyJson(data)
        elif self.path == "/repos/project/repo/issues/1234/comments":
            self.replyJson(data)
        elif self.path == "/repos/project/repo/issues/1234/labels":
            self.replyJson(data)
        else:
            self.send_error(405, 'Method not allowed: ' + self.path)


class TestGitHubHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MockServer(("127.0.0.1", 0), Handler, GITHUB_DATA)
        self.server.start()
        self.temp = tempfile.mkdtemp()
        os.environ["GITHUB_API"] = f"http://{self.server.address[0]}:{self.server.address[1]}"
        os.environ["GITHUB_BASE"] = "project/repo"
        self.github = GitHub()

    def tearDown(self) -> None:
        self.server.kill()
        shutil.rmtree(self.temp)
        os.unsetenv("GITHUB_API")
        os.unsetenv("GITHUB_BASE")

    def test_comment(self) -> None:
        comment = self.github.comment(1234, "This is the comment")
        self.assertEqual(comment["body"], "This is the comment")

    def test_set_labels(self) -> None:
        self.github.set_labels(1234, ['xxx'])

    def test_create_pull_request(self) -> None:
        number = self.github.create_pull_request("branch", "Task title", body="This is the body")
        self.assertIsInstance(number, int)


if __name__ == '__main__':
    unittest.main()
