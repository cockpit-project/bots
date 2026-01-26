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

import time
from pathlib import Path

from lib import cache


def test_read_write(tmp_path: Path) -> None:
    value = {"blah": 1}

    c = cache.Cache[object](f'{tmp_path}')
    result = c.read(r"pa+t\%h")
    assert result is None

    c.write(r"pa+t\%h", value)
    result = c.read(r"pa+t\%h")
    assert result == value

    other = "other"
    c.write(r"pa+t\%h", other)
    result = c.read(r"pa+t\%h")
    assert result == other

    c.write("second", value)
    result = c.read(r"pa+t\%h")
    assert result == other


def test_current(tmp_path: Path) -> None:
    c = cache.Cache[object](f'{tmp_path}', lag=3)

    c.write("resource2", {"value": 2})
    assert c.current('resource2') is True

    time.sleep(2)
    assert c.current('resource2') is True

    time.sleep(2)
    assert c.current('resource2') is False


def test_current_mark(tmp_path: Path) -> None:
    c = cache.Cache[object](f'{tmp_path}', lag=3)

    assert c.current('resource') is False

    c.write("resource", {"value": 1})
    assert c.current('resource') is True

    time.sleep(2)
    assert c.current('resource') is True

    c.mark()
    assert c.current('resource') is False


def test_current_zero(tmp_path: Path) -> None:
    c = cache.Cache[object](f'{tmp_path}', lag=0)
    c.write("resource", {"value": 1})
    assert c.current('resource') is False
