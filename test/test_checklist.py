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

import unittest

from task import github


class TestChecklist(unittest.TestCase):
    def testParse(self):
        parse_line = github.Checklist.parse_line
        self.assertEqual(parse_line("blah"), (None, None))
        self.assertEqual(parse_line(""), (None, None))
        self.assertEqual(parse_line(""), (None, None))
        self.assertEqual(parse_line("* [ ] test two"), ("test two", False))
        self.assertEqual(parse_line("- [ ] test two"), ("test two", False))
        self.assertEqual(parse_line(" * [ ]  test two "), ("test two", False))
        self.assertEqual(parse_line(" - [ ]  test two "), ("test two", False))
        self.assertEqual(parse_line(" - [x] test two "), ("test two", True))
        self.assertEqual(parse_line(" * [x] test two"), ("test two", True))
        self.assertEqual(parse_line(" * [x] FAIL: test two"), ("test two", "FAIL"))
        self.assertEqual(parse_line(" * [x] FAIL: test FAIL: two"), ("test FAIL: two", "FAIL"))
        self.assertEqual(parse_line(" * [x]test three"), (None, None))
        self.assertEqual(parse_line(" - [X] test two "), ("test two", True))
        self.assertEqual(parse_line(" * [X] test four"), ("test four", True))
        self.assertEqual(parse_line(" * [X] FAIL: test four"), ("test four", "FAIL"))
        self.assertEqual(parse_line(" * [X] FAIL: test FAIL: four"), ("test FAIL: four", "FAIL"))
        self.assertEqual(parse_line(" * [X]test five"), (None, None))

    def testFormat(self):
        format_line = github.Checklist.format_line
        self.assertEqual(format_line("blah", True), " * [x] blah")
        self.assertEqual(format_line("blah", False), " * [ ] blah")
        self.assertEqual(format_line("blah", "FAIL"), " * [ ] FAIL: blah")

    def testProcess(self):
        body = "This is a description\n- [ ] item1\n * [x] Item two\n * [X] Item three\n\nMore lines"
        checklist = github.Checklist(body)
        self.assertEqual(checklist.body, body)
        self.assertEqual(checklist.items, {"item1": False, "Item two": True, "Item three": True})

    def testCheck(self):
        body = "This is a description\n- [ ] item1\n * [x] Item two\n * [X] Item three\n\nMore lines"
        checklist = github.Checklist(body)
        checklist.check("item1", True)
        checklist.check("Item three", False)
        self.assertEqual(checklist.body,
                         "This is a description\n * [x] item1\n * [x] Item two\n * [ ] Item three\n\nMore lines")
        self.assertEqual(checklist.items, {"item1": True, "Item two": True, "Item three": False})

    def testDisable(self):
        body = "This is a description\n- [ ] item1\n * [x] Item two\n\nMore lines"
        checklist = github.Checklist(body)
        checklist.check("item1", "Status")
        self.assertEqual(checklist.body,
                         "This is a description\n * [ ] Status: item1\n * [x] Item two\n\nMore lines")
        self.assertEqual(checklist.items, {"item1": "Status", "Item two": True})

    def testAdd(self):
        body = "This is a description\n- [ ] item1\n * [x] Item two\n\nMore lines"
        checklist = github.Checklist(body)
        checklist.add("Item three")
        self.assertEqual(checklist.body,
                         "This is a description\n- [ ] item1\n * [x] Item two\n\nMore lines\n * [ ] Item three")
        self.assertEqual(checklist.items, {"item1": False, "Item two": True, "Item three": False})

    def testChecked(self):
        body = "This is a description\n- [ ] item1\n * [x] Item two\n * [X] Item three\n\nMore lines"
        checklist = github.Checklist(body)
        checklist.check("item1", True)
        checklist.check("Item three", False)
        checked = checklist.checked()
        self.assertEqual(checklist.items, {"item1": True, "Item two": True, "Item three": False})
        self.assertEqual(checked, {"item1": True, "Item two": True})


if __name__ == '__main__':
    unittest.main()
