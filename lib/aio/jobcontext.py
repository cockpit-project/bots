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
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import AsyncContextManager, Self

from ..constants import BOTS_DIR
from ..directories import xdg_config_home
from .base import Forge, LogDriver
from .github import GitHub
from .jsonutil import (
    JsonError,
    JsonObject,
    get_nested,
    get_str,
    get_strv,
    json_merge_patch,
    load_external_files,
    typechecked,
)
from .local import LocalLogDriver
from .s3 import S3LogDriver

logger = logging.getLogger(__name__)

# __init__ is weird on types, so typecheck this as a callable to enforce correctness
FORGES: Mapping[str, Callable[[JsonObject], AsyncContextManager[Forge]]] = {
    'github': GitHub,
}

LOG_DRIVERS: Mapping[str, Callable[[JsonObject], AsyncContextManager[LogDriver]]] = {
    's3': S3LogDriver,
    'local': LocalLogDriver,
}


class JobContext(contextlib.AsyncExitStack):
    config: JsonObject = {}  # noqa:RUF012  # JsonObject is immutable
    logs: LogDriver
    forge: Forge

    def load_config(self, path: Path, name: str, *, missing_ok: bool = False) -> None:
        logger.debug('Loading %s configuration from %s', name, str(path))
        try:
            with path.open('rb') as file:
                content = tomllib.load(file)
        except tomllib.TOMLDecodeError as exc:
            sys.exit(f'{path}: {exc}')
        except FileNotFoundError as exc:
            if missing_ok:
                logger.debug('No %s configuration found at %s', name, str(path))
                return
            else:
                sys.exit(f'{path}: {exc}')
        except OSError as exc:
            sys.exit(f'{path}: {exc}')

        # load_external_files() can throw so make sure it's outside of the above block
        self.config = json_merge_patch(self.config, load_external_files(content, path.parent))

    def __init__(self, config_file: Path | str | None, *, debug: bool = False) -> None:
        super().__init__()

        self.debug = debug

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
            with get_nested(self.config, 'container') as container:
                self.container_cmd = get_strv(container, 'command')
                self.container_run_args = get_strv(container, 'run-args')
                with get_nested(container, 'secrets') as secrets:
                    self.secrets_args = {
                        name: [
                            typechecked(arg, str) for arg in typechecked(args, list)
                        ] for name, args in secrets.items()
                    }
                self.default_image = get_str(container, 'default-image')

            with get_nested(self.config, 'logs') as logs:
                driver = get_str(logs, 'driver')
                if driver not in LOG_DRIVERS:
                    sys.exit(f'Unknown log driver {driver}')
                with get_nested(logs, driver) as driver_config:
                    self.logs = await self.enter_async_context(LOG_DRIVERS[driver](driver_config))

            with get_nested(self.config, 'forge') as forge:
                driver = get_str(forge, 'driver')
                if driver not in FORGES:
                    sys.exit(f'Unknown forge driver {driver}')
                with get_nested(forge, driver) as driver_config:
                    self.forge = await self.enter_async_context(FORGES[driver](driver_config))
        except JsonError as exc:
            await self.__aexit__(exc.__class__, exc, None)
            sys.exit(f'Configuration error: {exc}')
        except BaseException as exc:
            await self.__aexit__(exc.__class__, exc, None)
            raise

        return self
