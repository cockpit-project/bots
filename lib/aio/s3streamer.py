# SPDX-FileCopyrightText: 2022-2024 Red Hat, Inc.
# SPDX-License-Identifier: AGPL-3.0-or-later

# S3 Log Streaming Protocol
# =========================
#
# This module implements a protocol for streaming log output through S3 (or
# any object store with similar semantics).  The core problem is that S3
# objects are immutable once written, so we can't append to a file.  Instead,
# we write a series of chunk objects and a manifest that tells clients how to
# reassemble them.  The base filename ("log" in this case) is not special —
# any name works as long as the writer and clients agree on it.
#
# The entire protocol is bytes-oriented: chunk sizes in the manifest are
# byte counts, Range request offsets are byte offsets, and chunk filenames
# encode byte ranges.  Although character offsets are never used for
# anything, the content is assumed to be UTF-8 text.  The server
# is responsible for ensuring that a single codepoint is never split across
# two chunk files, so clients can safely decode each chunk independently.
#
# The object store should support Range requests and respond with 206
# Partial Content.  If the server does not support Range requests (e.g.
# python -m http.server for local development), it will return 200 with
# the complete object body.  Clients must handle both cases: on 206 the
# body is exactly the requested range; on 200 the client must slice the
# body at the requested byte offset and discard the prefix.
#
# File layout during streaming:
#
#   log.chunks          JSON array of chunk sizes in bytes, e.g. [81920, 40960]
#   log.0-81920         First chunk (size 81920, bytes [0, 81920))
#   log.81920-122880    Second chunk (size 40960, bytes [81920, 122880))
#
# File layout after streaming:
#
#   log                 Complete log contents (single object)
#
# The chunk files and log.chunks are deleted when streaming ends.
#
#
# Writer protocol (this module)
# -----------------------------
#
# LogStreamer buffers incoming data and flushes it as chunk objects.  A flush
# happens when the buffer exceeds SIZE_LIMIT (1MB) or TIME_LIMIT (30s) elapses
# with data pending.
#
# Each flush appends a new entry to the internal chunks list, then runs a
# merge pass modelled after the game 2048: if the last two entries have the
# same number of constituent blocks, they are merged into one.  This keeps
# the total number of chunk objects logarithmic in the amount of data written,
# while only ever rewriting the last chunk (so the write amplification is
# also logarithmically bounded).
#
# The manifest (log.chunks) is a JSON array of chunk sizes in bytes.  Clients
# use it to derive the chunk filenames: each chunk is named
# "log.{start}-{end}" where start is the cumulative size of all preceding
# chunks and end = start + size.  The range is end-exclusive: a chunk named
# "log.0-81920" has length 81920, containing bytes [0, 81920).
#
# Order of operations matters for consistency.  On each flush, the writer
# must write the chunk object first, then update the manifest — otherwise a
# client could read a manifest that references a chunk that doesn't exist
# yet.  On close(), the writer writes the final "log" object first, then
# deletes the manifest and chunk files.  This way, a client that gets a 404
# on the manifest can be confident that the final log object is already
# available.
#
#
# Client protocol (log.html, s3stream CLI)
# -----------------------------------------
#
# Clients always read the manifest first.  On each poll they compare it
# against how many bytes they have already received, then fetch only the
# new/updated chunk objects, using Range requests to avoid re-downloading
# data within a chunk that grew due to a merge.  If the server responds
# with 200 instead of 206, the client reads the full body as bytes and
# slices at the requested offset before decoding to text.
#
# S3 can return 500 Internal Server Error at any time, even under normal
# operation.  Both clients and the server should retry transient failures (5xx,
# network errors) with exponential backoff:
# https://docs.aws.amazon.com/AmazonS3/latest/developerguide/ErrorBestPractices.html
#
# When fetching the manifest or a chunk returns 404 (or 403 — S3 returns 403
# instead of 404 when the bucket policy does not grant s3:ListBucket),
# streaming is over (or never started). The client fetches "log" with a Range
# header for any bytes beyond what it already has, giving a seamless transition
# from streamed to final content.

import asyncio
import json
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
