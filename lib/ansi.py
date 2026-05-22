# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys

IS_TTY = os.isatty(sys.stderr.fileno())
USE_COLOR = 'FORCE_COLOR' in os.environ or (IS_TTY and 'NO_COLOR' not in os.environ)

RED = '\033[31m' if USE_COLOR else ''
GREEN = '\033[32m' if USE_COLOR else ''
BLUE = '\033[34m' if USE_COLOR else ''
RESET = '\033[0m' if USE_COLOR else ''
CLEAR_LINE = '\033[2K\r' if IS_TTY else ''
