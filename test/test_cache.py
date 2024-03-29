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

import os
import tempfile
import time
import unittest

from task import cache


class TestCache(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        for name in os.listdir(self.directory):
            os.unlink(os.path.join(self.directory, name))
        os.rmdir(self.directory)

    def testReadWrite(self):
        value = {"blah": 1}

        c = cache.Cache(self.directory)
        result = c.read(r"pa+t\%h")
        self.assertIsNone(result)

        c.write(r"pa+t\%h", value)
        result = c.read(r"pa+t\%h")
        self.assertEqual(result, value)

        other = "other"
        c.write(r"pa+t\%h", other)
        result = c.read(r"pa+t\%h")
        self.assertEqual(result, other)

        c.write("second", value)
        result = c.read(r"pa+t\%h")
        self.assertEqual(result, other)

    def testCurrent(self):
        c = cache.Cache(self.directory, lag=3)

        c.write("resource2", {"value": 2})
        self.assertTrue(c.current("resource2"))

        time.sleep(2)
        self.assertTrue(c.current("resource2"))

        time.sleep(2)
        self.assertFalse(c.current("resource2"))

    def testCurrentMark(self):
        c = cache.Cache(self.directory, lag=3)

        self.assertFalse(c.current("resource"))

        c.write("resource", {"value": 1})
        self.assertTrue(c.current("resource"))

        time.sleep(2)
        self.assertTrue(c.current("resource"))

        c.mark()
        self.assertFalse(c.current("resource"))

    def testCurrentZero(self):
        c = cache.Cache(self.directory, lag=0)
        c.write("resource", {"value": 1})
        self.assertFalse(c.current("resource"))


if __name__ == '__main__':
    unittest.main()
