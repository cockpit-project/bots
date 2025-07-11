# Copyright (C) 2022-2024 Red Hat, Inc.
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

import asyncio
import codecs
import json
import locale
import logging
import os
import textwrap
from collections.abc import Collection
from typing import ClassVar

from yarl import URL

from ..constants import LIB_DIR
from .base import Destination

logger = logging.getLogger(__name__)


class Index(Destination):
    files: set[str]

    def __init__(self, destination: Destination, filename: str = 'index.html') -> None:
        self.destination = destination
        self.filename = filename
        self.files = set()
        self.dirty = True

    def has(self, filename: str) -> bool:
        return filename in self.files

    def write(self, filename: str, data: bytes) -> None:
        self.destination.write(filename, data)
        self.files.add(filename)
        self.dirty = True

    def delete(self, filenames: Collection[str]) -> None:
        raise NotImplementedError

    def sync(self) -> None:
        if self.dirty:
            self.destination.write(self.filename, textwrap.dedent('''
                <html>
                  <body>
                    <h1>Directory listing for /</h1>
                    <hr>
                    <ul>''' + ''.join(f'''
                      <li><a href={f}>{f}</a></li> ''' for f in sorted(self.files)) + '''
                    </ul>
                  </body>
                </html>
                ''').encode('utf-8'))
            self.dirty = False


class AttachmentsDirectory:
    def __init__(self, destination: Destination, local_directory: str) -> None:
        self.destination = destination
        self.path = local_directory

    def scan(self) -> None:
        for subdir, _dirs, files in os.walk(self.path):
            for filename in files:
                path = os.path.join(subdir, filename)
                name = os.path.relpath(path, start=self.path)

                if not self.destination.has(name):
                    logger.debug('Uploading attachment %s', name)
                    with open(path, 'rb') as file:
                        data = file.read()
                    self.destination.write(name, data)


class LogStreamer:
    SIZE_LIMIT: ClassVar[int] = 1000000  # 1MB
    TIME_LIMIT: ClassVar[int] = 30       # 30s

    chunks: list[list[bytes]]
    suffixes: set[str]
    send_at: float | None

    def __init__(self, index: Index, proxy_url: URL | None = None) -> None:
        assert locale.getpreferredencoding() == 'UTF-8'
        self.input_decoder = codecs.getincrementaldecoder('UTF-8')(errors='replace')
        self.suffixes = {'chunks'}
        self.chunks = []
        self.index = index
        self.destination = index.destination
        self.pending = b''
        self.timer: asyncio.TimerHandle | None = None
        # Use proxy URL for external links (GitHub status), fallback to destination location
        self.url = (proxy_url or self.destination.location) / 'log.html'

    def clear_timer(self) -> None:
        if self.timer:
            self.timer.cancel()
        self.timer = None

    def send_pending(self) -> None:
        # Consume the pending buffer into the chunks list.
        self.chunks.append([self.pending])
        self.pending = b''
        self.clear_timer()

        # 2048 algorithm.
        #
        # This can be changed to merge more or less often, or to never merge at
        # all. The only restriction is that it may only ever update the last
        # item in the list.
        while len(self.chunks) > 1 and len(self.chunks[-1]) == len(self.chunks[-2]):
            last = self.chunks.pop()
            second_last = self.chunks.pop()
            self.chunks.append(second_last + last)

        # Now we figure out how to send that last item.
        # Let's keep the client dumb: it doesn't need to know about blocks: only bytes.
        chunk_sizes = [sum(len(block) for block in chunk) for chunk in self.chunks]

        if chunk_sizes:
            last_chunk_start = sum(chunk_sizes[:-1])
            last_chunk_end = last_chunk_start + chunk_sizes[-1]
            last_chunk_suffix = f'{last_chunk_start}-{last_chunk_end}'
            self.destination.write(f'log.{last_chunk_suffix}', b''.join(self.chunks[-1]))
            self.suffixes.add(last_chunk_suffix)

        self.destination.write('log.chunks', json.dumps(chunk_sizes).encode('ascii'))

    def start(self, data: str) -> None:
        # Send the initial data immediately, to get the chunks file written out.
        self.pending = data.encode()
        self.send_pending()
        AttachmentsDirectory(self.index, f'{LIB_DIR}/s3-html').scan()

    def write(self, data: str) -> None:
        self.pending += data.encode()

        if len(self.pending) > LogStreamer.SIZE_LIMIT:
            self.send_pending()

        elif self.pending and self.timer is None:
            self.timer = asyncio.get_running_loop().call_later(LogStreamer.TIME_LIMIT, self.send_pending)

    def close(self) -> None:
        # We're about to delete all of the chunks, so don't bother with
        # anything still pending...
        self.clear_timer()

        everything = b''.join(b''.join(block for block in chunk) for chunk in self.chunks) + self.pending
        self.index.write('log', everything)

        # If the client ever sees a 404, it knows that the streaming is over.
        self.destination.delete([f'log.{suffix}' for suffix in self.suffixes])
