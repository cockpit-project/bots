#!/usr/bin/env python3

# This file is part of Cockpit.
#
# Copyright (C) 2021 Red Hat, Inc.
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

import testmap


class TestTestMap(unittest.TestCase):
    def test_split_context(self):
        self.assertEqual(testmap.split_context("myos"), ("myos", None, ""))
        self.assertEqual(testmap.split_context("myos/scen"), ("myos/scen", None, ""))
        self.assertEqual(testmap.split_context("myos@owner/repo"), ("myos", None, "owner/repo"))
        self.assertEqual(testmap.split_context("myos/scen@owner/repo"), ("myos/scen", None, "owner/repo"))
        self.assertEqual(testmap.split_context("myos@owner/repo/branch"), ("myos", None, "owner/repo/branch"))
        self.assertEqual(testmap.split_context("myos@bots#1234"), ("myos", 1234, ""))
        self.assertEqual(testmap.split_context("myos/scen@bots#1234"), ("myos/scen", 1234, ""))
        self.assertEqual(testmap.split_context("myos/scen@bots#1234@owner/repo"),
                         ("myos/scen", 1234, "owner/repo"))
        self.assertEqual(testmap.split_context("myos/scen@bots#1234@owner/repo/branch"),
                         ("myos/scen", 1234, "owner/repo/branch"))

    def test_is_valid_context(self):
        # this makes some assumptions about the concrete test map, only use scenarios which don't change often

        def good(context, repo):
            self.assertTrue(testmap.is_valid_context(context, repo))

        def bad(context, repo):
            self.assertFalse(testmap.is_valid_context(context, repo))

        good("debian-testing", "cockpit-project/cockpit")
        # context from _manual pseudo-branch
        good("fedora-testing", "cockpit-project/cockpit")
        # not known in this branch
        bad("debian-testing", "cockpit-project/cockpit/rhel-8.5")

        # unknown scenarios/projects/branches
        bad("wrongos", "cockpit-project/cockpit")
        bad("debian-testing/wrongscen", "cockpit-project/cockpit")
        bad("debian-testing", "cockpit-project/wrongproject")
        bad("debian-testing", "cockpit-project/cockpit/wrongbranch")

        # bots has no integration tests for itself
        bad("debian-testing", "cockpit-project/bots")
        # but can refer to foreign projects
        good("debian-testing@cockpit-project/cockpit", "cockpit-project/bots")
        good("debian-testing@cockpit-project/cockpit/main", "cockpit-project/bots")
        # can refer to _manual contexts of foreign projects
        good("fedora-testing@cockpit-project/cockpit", "cockpit-project/bots")
        good("fedora-testing@cockpit-project/cockpit/main", "cockpit-project/bots")

        # unknown scenarios/project/branches with foreign project
        bad("wrongos@cockpit-project/cockpit", "cockpit-project/bots")
        bad("debian-testing@cockpit-project/wrongproject", "cockpit-project/bots")
        # FIXME: this is currently valid
        # bad("debian-testing@cockpit-project/cockpit/wrongbranch", "cockpit-project/bots")


if __name__ == '__main__':
    unittest.main()
