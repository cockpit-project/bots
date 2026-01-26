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

import fnmatch
import json
import shutil
import tempfile
import time
import unittest
import urllib.parse

from lib import cache, github
from lib.test_mock_server import MockHandler, MockServer

ADDRESS = ("127.0.0.8", 9898)
GITHUB_ISSUES = [{"number": "5", "state": "open", "created_at": "2011-04-22T13:33:48Z"},
                 {"number": "6", "state": "closed", "closed_at": "2011-04-21T13:33:48Z"},
                 {"number": "7", "state": "open"}]


class Handler(MockHandler[list[dict[str, str]]]):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/count":
            self.replyJson(self.server.reply_count)
        elif parsed.path == "/issues":
            issues_ = self.server.data
            if "state=open" in self.path:
                issues_ = [i for i in issues_ if i["state"] == "open"]
            if "since=" in self.path:
                issues_ = [i for i in issues_ if "created_at" not in i.keys() and "closed_at" not in i.keys()]
            self.replyJson(issues_)
        elif parsed.path == "/test/user":
            if self.headers.get("If-None-Match") == "blah":
                self.replyData("", status=304)
            else:
                self.replyJson({"user": "blah"}, headers={"ETag": "blah"})
        elif parsed.path == "/test/user/modified":
            if self.headers.get("If-Modified-Since") == "Thu, 05 Jul 2012 15:31:30 GMT":
                self.replyData("", status=304)
            else:
                self.replyJson({"user": "blah"}, headers={"Last-Modified": "Thu, 05 Jul 2012 15:31:30 GMT"})
        else:
            self.send_error(404, 'Mock Not Found: ' + parsed.path)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/issues/7':
            del self.server.data[-1]
            self.replyJson({})
        else:
            self.send_error(404, 'Mock Not Found: ' + parsed.path)


class TestGitHub(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MockServer(ADDRESS, Handler, GITHUB_ISSUES)
        self.server.start()
        self.temp = tempfile.mkdtemp()
        self.api = github.GitHub(f"http://{ADDRESS[0]}:{ADDRESS[1]}/", cacher=cache.Cache(self.temp))

    def tearDown(self) -> None:
        self.server.kill()
        shutil.rmtree(self.temp)

    def test_cache(self) -> None:
        values = self.api.get("/test/user")
        cached = self.api.get("/test/user")
        self.assertEqual(json.dumps(values), json.dumps(cached))

        count = self.api.get("/count")
        self.assertEqual(count, 1)

    def test_log(self) -> None:
        self.api.get("/test/user")
        self.api.cache.mark(time.time() + 1)
        self.api.get("/test/user")

        expect = (
            '127.0.0.8:9898 - - * "GET /test/user HTTP/1.1" 200 -\n'
            '127.0.0.8:9898 - - * "GET /test/user HTTP/1.1" 304 -\n'
        )

        with open(self.api.log.path, "r") as f:
            data = f.read()

        match = fnmatch.fnmatch(data, expect)
        if not match:
            self.fail(f"'{data}' did not match '{expect}'")

    def test_issues_since(self) -> None:
        issues = self.api.issues(since=1499838499)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["number"], "7")

    def test_last_issue_delete(self) -> None:
        self.assertEqual(len(self.api.issues()), 2)
        self.api.delete("/issues/7")
        issues = self.api.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["number"], "5")


if __name__ == '__main__':
    unittest.main()
