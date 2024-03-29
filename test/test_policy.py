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
import subprocess
import unittest

from lib.constants import BOTS_DIR

PCP_CRASH = """
# ----------------------------------------------------------------------
# testFrameNavigation (check_multi_machine.TestMultiMachine)
#
Unexpected journal message '/usr/libexec/cockpit-pcp: bridge was killed: 11'
not ok 110 testFrameNavigation (check_multi_machine.TestMultiMachine)
Traceback (most recent call last):
  File "test/verify/check-multi-machine", line 202, in tearDown
    MachineCase.tearDown(self)
  File "/home/martin/upstream/cockpit/test/common/testlib.py", line 533, in tearDown
    self.check_journal_messages()
  File "/home/martin/upstream/cockpit/test/common/testlib.py", line 689, in check_journal_messages
    raise Error(first)
Error: /usr/libexec/cockpit-pcp: bridge was killed: 11
Wrote TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.png
Wrote TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.html
Wrote TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.js.log
Journal extracted to TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.log
Journal extracted to TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2503-FAIL.log
Journal extracted to TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2502-FAIL.log
"""

PCP_KNOWN = """
# ----------------------------------------------------------------------
# testFrameNavigation (check_multi_machine.TestMultiMachine)
#
Unexpected journal message '/usr/libexec/cockpit-pcp: bridge was killed: 11'
ok 110 testFrameNavigation (check_multi_machine.TestMultiMachine) # SKIP Known issue #9876
Traceback (most recent call last):
  File "test/verify/check-multi-machine", line 202, in tearDown
    MachineCase.tearDown(self)
  File "/home/martin/upstream/cockpit/test/common/testlib.py", line 533, in tearDown
    self.check_journal_messages()
  File "/home/martin/upstream/cockpit/test/common/testlib.py", line 689, in check_journal_messages
    raise Error(first)
Error: /usr/libexec/cockpit-pcp: bridge was killed: 11
Wrote TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.png
Wrote TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.html
Wrote TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.js.log
Journal extracted to TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2501-FAIL.log
Journal extracted to TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2503-FAIL.log
Journal extracted to TestMultiMachine-testFrameNavigation-fedora-i386-127.0.0.2-2502-FAIL.log
"""


class TestPolicy(unittest.TestCase):
    def testSimpleNumber(self):
        script = os.path.join(BOTS_DIR, "tests-policy")
        cmd = [script, "--simple", "--offline", "verify/example"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        (output, unused) = proc.communicate(PCP_CRASH)
        self.assertEqual(output, "9876\n")

    def testScenario(self):
        script = os.path.join(BOTS_DIR, "tests-policy")
        cmd = [script, "--simple", "--offline", "verify/example/scen-one"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        (output, unused) = proc.communicate(PCP_CRASH)
        self.assertEqual(output, "9876\n")

    def testKnownIssue(self):
        script = os.path.join(BOTS_DIR, "tests-policy")
        cmd = [script, "--offline", "verify/example"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        (output, unused) = proc.communicate(PCP_CRASH)
        self.assertEqual(output, PCP_KNOWN)

    def testLineGlob(self):
        script = os.path.join(BOTS_DIR, "tests-policy")
        cmd = [script, "--offline", "verify/example"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        (output, unused) = proc.communicate("""
> log: phase coils are misaligned by 0.34 micron
> warning: this will explode in your face
Some other mubo-jumbo
Traceback (most recent call last):
  File "test/verify/check-warp-drive", line 34, in testCoils
     self.assertTrue(all_in_order)
not ok 1 test/verify/check-warp-drive TestDrive.testCoils
""")
        self.assertIn("\nok 1 test/verify/check-warp-drive TestDrive.testCoils # SKIP Known issue #123", output)

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        (output, unused) = proc.communicate("""
> log: phase coils are misaligned by 0.34 micron
Traceback (most recent call last):
  File "test/verify/check-warp-drive", line 34, in testCoils
     self.assertTrue(all_in_order)
not ok 1 test/verify/check-warp-drive TestDrive.testCoils
""")
        self.assertIn("\nok 1 test/verify/check-warp-drive TestDrive.testCoils # SKIP Known issue #123", output)


if __name__ == '__main__':
    unittest.main()
