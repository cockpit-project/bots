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


class TestPolicy(unittest.TestCase):
    def testKnownIssue(self):
        script = os.path.join(BOTS_DIR, "test-failure-policy")
        cmd = [script, "--offline", "example"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        output = proc.communicate(PCP_CRASH)[0]
        self.assertEqual(output, "Known issue #9876\n")
        self.assertEqual(proc.returncode, 77)

    def testAlreadyKnownIssue(self):
        script = os.path.join(BOTS_DIR, "test-failure-policy")
        cmd = [script, "--offline", "--all", "bogus"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        output = proc.communicate(PCP_CRASH)[0]
        self.assertEqual(output, "Known issue #9876 in example\n")
        self.assertEqual(proc.returncode, 78)

    def testRetry(self):
        script = os.path.join(BOTS_DIR, "test-failure-policy")
        cmd = [script, "--offline", "example"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        output = proc.communicate("""
# testBasic (__main__.TestEmbed)
Traceback (most recent call last):
  File "/work/bots/make-checkout-workdir/test/common/testlib.py", line 878, in setUp
    machine.wait_boot()
  File "/work/bots/make-checkout-workdir/bots/machine/machine_core/ssh_connection.py", line 118, in wait_boot
    raise exceptions.Failure("Unable to reach machine {0} via ssh: {1}:{2}".format(
machine_core.exceptions.Failure: Unable to reach machine fedora-33-127.0.0.2-2401 via ssh: 127.0.0.2:2401

# Result testBasic (__main__.TestEmbed) failed
# 1 TEST FAILED [120s on centosci-tasks-zwzrj]
""")[0]
        self.assertEqual(output, "due to failure of test harness or framework\n")
        self.assertEqual(proc.returncode, 1)

    def testNoOp(self):
        script = os.path.join(BOTS_DIR, "test-failure-policy")
        cmd = [script, "--offline", "example"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        output = proc.communicate("""
# testBasic (__main__.TestMachinesLifecycle)
Traceback (most recent call last):
  File "/work/bots/make-checkout-workdir/test/verify/check-machines-lifecycle", line 33, in testBasic
    self._testBasic()
  File "/work/bots/make-checkout-workdir/test/verify/check-machines-lifecycle", line 99, in _testBasic
    wait(lambda: "login as 'cirros' user." in self.machine.execute("cat {0}".format(args["logfile"])), delay=3)
  File "/work/bots/make-checkout-workdir/test/common/testlib.py", line 1725, in wait
    raise Error(msg or "Condition did not become true.")
testlib.Error: Condition did not become true.

# Result testBasic (__main__.TestMachinesLifecycle) failed
# 1 TEST FAILED [195s on 2-ci-srv-01]
""")[0]
        self.assertEqual(output, "")
        self.assertEqual(proc.returncode, 0)

    def testLineGlob(self):
        script = os.path.join(BOTS_DIR, "test-failure-policy")
        cmd = [script, "--offline", "example"]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        output = proc.communicate("""
> log: phase coils are misaligned by 0.34 micron
> warning: this will explode in your face
Some other mubo-jumbo
Traceback (most recent call last):
  File "test/verify/check-warp-drive", line 34, in testCoils
     self.assertTrue(all_in_order)
not ok 1 test/verify/check-warp-drive TestDrive.testCoils
""")[0]
        self.assertEqual(output, "Known issue #123\n")

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        output = proc.communicate("""
> log: phase coils are misaligned by 0.34 micron
Traceback (most recent call last):
  File "test/verify/check-warp-drive", line 34, in testCoils
     self.assertTrue(all_in_order)
not ok 1 test/verify/check-warp-drive TestDrive.testCoils
""")[0]
        self.assertEqual(output, "Known issue #123\n")


if __name__ == '__main__':
    unittest.main()
