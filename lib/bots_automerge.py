# This file is part of Cockpit.
#
# Copyright (C) 2025 Red Hat, Inc.
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

import logging

from lib.aio.jsonutil import get_int, get_str
from task import github

logger = logging.getLogger(__name__)

# TODO: verify if this is always the same
GITHUB_CI = {
    'login': 'github-actions[bot]',
    'id': 41898282,
}

COCKPITUOUS = {
    'login': 'cockpituous',
    'id': 14330603,
}


def is_ci_bot(api: github.GitHub, pr: int) -> bool:
    author = api.get_author(pr)
    login = get_str(author, 'login')
    login_id = get_int(author, 'id')

    return ((login == GITHUB_CI['login'] and login_id == GITHUB_CI['id']) or
        (login == COCKPITUOUS['login'] and login_id == COCKPITUOUS['id']))


def all_checks_pass(api: github.GitHub, commit_hash: str) -> bool:
    statuses = api.statuses(commit_hash)

    logger.info("Checking statuses:")
    if len(statuses) == 0:
        logger.info("No statuses found for commit %s", commit_hash)
        return False

    for context in statuses:
        status = statuses[context]
        status_state = get_str(status, 'state')
        logger.info("Status for context '%s': %s", context, status_state)
        if status_state != 'success':
            return False

    return True


def auto_merge_bots_pr(repo: str, pr: int, sha: str) -> None:
    api = github.GitHub(repo=repo)

    print(f"is_cu_bot: {is_ci_bot(api, pr)}")
    # Make sure that the PR was made by cockpituous or github actions
    # if not is_ci_bot(api, pr):
    #     logger.info("PR not made by CI bot, skipping automerge")
    #     return

    # check that all checks are green
    print(f"all_checks_pass: {all_checks_pass(api, sha)}")
    if not all_checks_pass(api, sha):
        logger.info("Not every check has passed, skipping automerge")
        return

    logger.info("All checks green, can automerge")
    print("All checks green, can automerge")
    # merge the PR
    api.approve_pr(pr, sha)
