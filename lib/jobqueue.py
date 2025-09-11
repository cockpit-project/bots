# Copyright (C) 2024 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from collections.abc import Mapping, Sequence
from typing import Required, TypedDict

from lib.aio.jsonutil import JsonObject


class SubjectSpecification(TypedDict, total=False):
    forge: str | None
    repo: Required[str]
    sha: str | None
    branch: str | None
    pull: int | None


class JobSpecification(SubjectSpecification, total=False):
    context: Required[str]
    slug: str
    report: JsonObject | None
    command_subject: SubjectSpecification | None
    command: Sequence[str]
    env: Mapping[str, str]
    secrets: Sequence[str]


class QueueEntry(TypedDict):
    job: JobSpecification
    human: str
