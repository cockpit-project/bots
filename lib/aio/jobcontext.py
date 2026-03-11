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

import contextlib
import logging
import os
import string
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import AsyncContextManager, Self

from ..constants import BOTS_DIR
from ..directories import xdg_config_home
from .base import Forge, LogDriver, Subject, SubjectSpecification
from .github import GitHub
from .jsonutil import (
    JsonError,
    JsonObject,
    JsonValue,
    get_nested,
    get_str,
    get_str_map,
    get_strv,
    json_merge_patch,
    load_external_files,
    typechecked,
)
from .local import LocalLogDriver
from .s3 import S3LogDriver

logger = logging.getLogger(__name__)


class PathTemplate(string.Template):
    delimiter = '%'

# __init__ is weird on types, so typecheck this as a callable to enforce correctness
FORGE_DRIVERS: Mapping[str, Callable[[str, JsonObject], AsyncContextManager[Forge]]] = {
    'github': GitHub,
}

LOG_DRIVERS: Mapping[str, Callable[[JsonObject], AsyncContextManager[LogDriver]]] = {
    's3': S3LogDriver,
    'local': LocalLogDriver,
}


def serialize_path(value: JsonValue) -> JsonObject:
    """Serialize a path value to inline content format.

    Handles:
      - String: reads file/directory at that path
      - {"content": "..."}: returns unchanged
      - {"entries": {...}}: recurses into entries
    """
    if isinstance(value, str):
        path = Path(value).expanduser()
        if path.is_file():
            return {'content': path.read_text()}
        elif path.is_dir():
            return {'entries': {child.name: serialize_path(str(child)) for child in path.iterdir()}}
        else:
            raise ValueError(f"Path is neither file nor directory: {path}")
    elif isinstance(value, Mapping):
        if 'content' in value:
            return value
        elif 'entries' in value:
            entries = typechecked(value['entries'], dict)
            return {'entries': {name: serialize_path(v) for name, v in entries.items()}}
    raise ValueError("Path value must be string, or have 'content' or 'entries'")


def unpack_serialized_path(contents: JsonObject, target: Path) -> None:
    """Write path contents to filesystem.

    Contents format:
      - File: {"content": "file text"}
      - Directory: {"entries": {"name": {...}, ...}}
    """
    if 'content' in contents:
        target.write_text(typechecked(contents['content'], str))
    elif 'entries' in contents:
        target.mkdir(parents=True, exist_ok=True)
        for name, value in typechecked(contents['entries'], dict).items():
            if name in ('', '.', '..') or '/' in name or '\0' in name:
                raise ValueError(f"Invalid filename: {name!r}")
            unpack_serialized_path(typechecked(value, dict), target / name)
    else:
        raise ValueError("Path contents must have 'content' or 'entries'")


class JobContext(contextlib.AsyncExitStack):
    config: JsonObject = {}  # noqa:RUF012  # JsonObject is immutable
    logs: LogDriver
    _forges: dict[str, Forge]
    _default_forge: str

    def load_config(self, path: Path, name: str, *, missing_ok: bool = False) -> None:
        logger.debug('Loading %s configuration from %s', name, path)
        try:
            with path.open('rb') as file:
                content = tomllib.load(file)
        except tomllib.TOMLDecodeError as exc:
            sys.exit(f'{path}: {exc}')
        except FileNotFoundError as exc:
            if missing_ok:
                logger.debug('No %s configuration found at %s', name, path)
                return
            else:
                sys.exit(f'{path}: {exc}')
        except OSError as exc:
            sys.exit(f'{path}: {exc}')

        # load_external_files() can throw so make sure it's outside of the above block
        self.config = json_merge_patch(self.config, load_external_files(content, path.parent))

    def __init__(
        self, config_file: Path | str | None = None, *, config: JsonObject | None = None, debug: bool = False
    ) -> None:
        super().__init__()
        self.debug = debug

        # Pre-serialized config for remote execution
        if config is not None:
            self.config = config
            return

        # The config is made out of the built-in config...
        self.load_config(Path(BOTS_DIR) / 'job-runner.toml', 'built-in')

        # ... plus exactly one of the following:
        if config_file:
            self.load_config(Path(config_file), 'command-line')
        elif config_file := os.environ.get('JOB_RUNNER_CONFIG'):
            self.load_config(Path(config_file), '$JOB_RUNNER_CONFIG-specified')
        else:
            self.load_config(Path(xdg_config_home('cockpit-dev/job-runner.toml')), 'user', missing_ok=True)

    async def __aenter__(self) -> Self:
        try:
            # Build paths mapping for %{name} substitution
            paths: dict[str, str] = {}
            tmpdir: Path | None = None
            with get_nested(self.config, 'paths') as paths_config:
                for name in paths_config:
                    if name in ('', '.', '..') or '/' in name or '\0' in name:
                        raise JsonError(paths_config, f"Invalid path name: {name!r}")
                    value = paths_config[name]
                    if isinstance(value, str):
                        paths[name] = os.path.expanduser(value)
                    elif isinstance(value, Mapping):
                        if tmpdir is None:
                            tmpdir = Path(self.enter_context(tempfile.TemporaryDirectory()))
                        target = tmpdir / name
                        unpack_serialized_path(serialize_path(value), target)
                        paths[name] = str(target)
                    else:
                        raise JsonError(value, f"path '{name}' must be string or object")

            def expand_args(args: Sequence[str]) -> tuple[str, ...]:
                return tuple(PathTemplate(arg).substitute(paths) for arg in args)

            with get_nested(self.config, 'container') as container:
                self.container_cmd = get_strv(container, 'command')
                self.container_run_args = expand_args(get_strv(container, 'run-args'))
                with get_nested(container, 'secrets') as secrets:
                    self.secrets_args = {
                        name: expand_args(get_strv(secrets, name))
                        for name in secrets
                    }
                self.default_image = get_str(container, 'default-image')

            with get_nested(self.config, 'logs') as logs:
                driver = get_str(logs, 'driver')
                if driver not in LOG_DRIVERS:
                    sys.exit(f'Unknown log driver {driver}')
                with get_nested(logs, driver) as driver_config:
                    self.logs = await self.enter_async_context(LOG_DRIVERS[driver](driver_config))

            # NB: The Forge class contains a per-instance cache which prevents
            # us from being banned for exceeding rate limits.  It's critical
            # that we have only one instance of the forge driver per forge.
            self._forges = {}
            with get_nested(self.config, 'forge') as forges:
                self._default_forge = get_str(forges, 'default')

                for name in forges:
                    # ignore "default" which is expected and "driver" from legacy configs
                    if name in ['default', 'driver']:
                        continue

                    with get_nested(forges, name) as forge:
                        driver = get_str(forge, 'driver')

                        if driver not in FORGE_DRIVERS:
                            sys.exit(f'Unknown forge driver {driver}')

                        self._forges[name] = await self.enter_async_context(FORGE_DRIVERS[driver](name, forge))

        except JsonError as exc:
            await self.__aexit__(exc.__class__, exc, None)
            sys.exit(f'Configuration error: {exc}')
        except BaseException as exc:
            await self.__aexit__(exc.__class__, exc, None)
            raise

        return self

    async def resolve_subject(self, spec: SubjectSpecification) -> Subject:
        forge = spec.forge or self._default_forge
        return await self._forges[forge].resolve_subject(spec)

    def serialize(self) -> JsonObject:
        """Serialize config for remote execution.

        Converts string paths to inline content format so the config
        is self-contained and can be sent over the wire.
        """
        with get_nested(self.config, 'paths') as paths_config:
            paths = {name: serialize_path(paths_config[name]) for name in paths_config}
        return {**self.config, 'paths': paths}
