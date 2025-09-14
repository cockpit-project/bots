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

from collections.abc import Collection
from typing import AsyncContextManager, NamedTuple, Self

from yarl import URL

from .jsonutil import JsonObject, get_int, get_str


class SubjectSpecification:
    def __init__(self, obj: JsonObject) -> None:
        self.forge = get_str(obj, 'forge', None)
        self.repo = get_str(obj, 'repo')
        self.sha = get_str(obj, 'sha', None)
        self.pull = get_int(obj, 'pull', None)
        self.branch = get_str(obj, 'branch', None)
        self.target = get_str(obj, 'target', None)


class Subject(NamedTuple):
    forge: 'Forge'
    repo: str
    sha: str
    rebase: str | None = None

    @property
    def clone_url(self) -> URL:
        return self.forge.clone / self.repo

    async def read_file(self, filename: str) -> str | None:
        return await self.forge.read_file(self, filename)


class Status:
    link: str

    async def post(self, state: str, description: str) -> None:
        raise NotImplementedError


class Forge:
    clone: URL

    async def resolve_subject(self, spec: SubjectSpecification) -> Subject:
        raise NotImplementedError

    async def check_pr_changed(self, repo: str, pull_nr: int, expected_sha: str) -> str | None:
        raise NotImplementedError

    def get_status(self, repo: str, sha: str, context: str | None, location: URL) -> Status:
        raise NotImplementedError

    async def open_issue(self, repo: str, issue: JsonObject) -> None:
        raise NotImplementedError

    async def read_file(self, subject: Subject, filename: str) -> str | None:
        raise NotImplementedError

    @classmethod
    def new(cls, name: str, config: JsonObject) -> Self:
        raise NotImplementedError


class Destination:
    location: URL
    proxy_location: URL | None = None

    def has(self, filename: str) -> bool:
        raise NotImplementedError

    def write(self, filename: str, data: bytes) -> None:
        raise NotImplementedError

    def delete(self, filenames: Collection[str]) -> None:
        raise NotImplementedError


class LogDriver:
    def get_destination(self, slug: str) -> AsyncContextManager[Destination]:
        raise NotImplementedError

    @classmethod
    def new(cls, config: JsonObject) -> Self:
        raise NotImplementedError
