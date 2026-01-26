# This file is part of Cockpit.
#
# Copyright (C) 2015 Red Hat, Inc.
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

"""Backwards compatibility shim - import from lib.github instead."""

from lib.github import (
    ISSUE_TITLE_IMAGE_REFRESH,
    NO_TESTING,
    NOT_TESTED,
    NOT_TESTED_DIRECT,
    TESTING,
    Checklist,
    GitHub,
    GitHubError,
)

__all__ = (
    'ISSUE_TITLE_IMAGE_REFRESH',
    'NOT_TESTED',
    'NOT_TESTED_DIRECT',
    'NO_TESTING',
    'TESTING',
    'Checklist',
    'GitHub',
    'GitHubError',
)
