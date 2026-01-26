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

"""Task automation module for GitHub-based workflows.

This module provides utilities for automating GitHub-based workflows including
issue management, pull request creation, and task execution.
"""

from lib.task import (
    api,
    attach,
    branch,
    comment,
    comment_done,
    default_branch,
    execute,
    issue,
    label,
    labels_of_pull,
    main,
    pull,
    push_branch,
    run,
    verbose,
    would,
)

from . import github

__all__ = (
    "api",
    "attach",
    "branch",
    "comment",
    "comment_done",
    "default_branch",
    "execute",
    "github",
    "issue",
    "label",
    "labels_of_pull",
    "main",
    "pull",
    "push_branch",
    "run",
    "verbose",
    "would",
)
