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

from lib import github


def test_parse() -> None:
    parse_line = github.Checklist.parse_line
    assert parse_line("blah") == (None, None)
    assert parse_line("") == (None, None)
    assert parse_line("") == (None, None)
    assert parse_line("* [ ] test two") == ("test two", False)
    assert parse_line("- [ ] test two") == ("test two", False)
    assert parse_line(" * [ ]  test two ") == ("test two", False)
    assert parse_line(" - [ ]  test two ") == ("test two", False)
    assert parse_line(" - [x] test two ") == ("test two", True)
    assert parse_line(" * [x] test two") == ("test two", True)
    assert parse_line(" * [x] FAIL: test two") == ("test two", "FAIL")
    assert parse_line(" * [x] FAIL: test FAIL: two") == ("test FAIL: two", "FAIL")
    assert parse_line(" * [x]test three") == (None, None)
    assert parse_line(" - [X] test two ") == ("test two", True)
    assert parse_line(" * [X] test four") == ("test four", True)
    assert parse_line(" * [X] FAIL: test four") == ("test four", "FAIL")
    assert parse_line(" * [X] FAIL: test FAIL: four") == ("test FAIL: four", "FAIL")
    assert parse_line(" * [X]test five") == (None, None)


def test_empty_body() -> None:
    assert github.Checklist('').items == {}
    assert github.Checklist(None).items == {}


def test_format() -> None:
    format_line = github.Checklist.format_line
    assert format_line("blah", True) == " * [x] blah"
    assert format_line("blah", False) == " * [ ] blah"
    assert format_line("blah", "FAIL") == " * [ ] FAIL: blah"


def test_process() -> None:
    body = "This is a description\n- [ ] item1\n * [x] Item two\n * [X] Item three\n\nMore lines"
    checklist = github.Checklist(body)
    assert checklist.body == body
    assert checklist.items == {"item1": False, "Item two": True, "Item three": True}


def test_check() -> None:
    body = "This is a description\n- [ ] item1\n * [x] Item two\n * [X] Item three\n\nMore lines"
    checklist = github.Checklist(body)
    checklist.check("item1", True)
    checklist.check("Item three", False)
    assert checklist.body == \
                     "This is a description\n * [x] item1\n * [x] Item two\n * [ ] Item three\n\nMore lines"
    assert checklist.items == {"item1": True, "Item two": True, "Item three": False}


def test_disable() -> None:
    body = "This is a description\n- [ ] item1\n * [x] Item two\n\nMore lines"
    checklist = github.Checklist(body)
    checklist.check("item1", "Status")
    assert checklist.body == \
                     "This is a description\n * [ ] Status: item1\n * [x] Item two\n\nMore lines"
    assert checklist.items == {"item1": "Status", "Item two": True}


def test_add() -> None:
    body = "This is a description\n- [ ] item1\n * [x] Item two\n\nMore lines"
    checklist = github.Checklist(body)
    checklist.add("Item three")
    assert checklist.body == \
                     "This is a description\n- [ ] item1\n * [x] Item two\n\nMore lines\n * [ ] Item three"
    assert checklist.items == {"item1": False, "Item two": True, "Item three": False}


def test_checked() -> None:
    body = "This is a description\n- [ ] item1\n * [x] Item two\n * [X] Item three\n\nMore lines"
    checklist = github.Checklist(body)
    checklist.check("item1", True)
    checklist.check("Item three", False)
    checked = checklist.checked()
    assert checklist.items == {"item1": True, "Item two": True, "Item three": False}
    assert checked == {"item1": True, "Item two": True}
