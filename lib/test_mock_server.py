# This file is part of Cockpit.
#
# Copyright (C) 2023 Red Hat, Inc.
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

from __future__ import annotations

import http.server
import json
import multiprocessing
from collections.abc import Mapping

from lib.aio.jsonutil import JsonValue

# This is a bit confusing, here's how it goes:
#
# We run a totally normal HTTPServer.  Generally speaking, a HTTPServer has a
# handler type which must subclass BaseHTTPRequestHandler which handles the
# methods.  All of our handlers additionally derive from MockHandler which adds
# a couple of useful methods.
#
# We also have a HTTPServer subclass which is responsible for holding 'data'
# and 'reply_count'.  This is available on the handler as `self.server` when
# methods are being run.
#
# The MockServer class exists entirely to facilitate starting the actual
# server.  Note: this uses multiprocessing, so the data is copied each time,
# which is why we can pass in mutable state but it's never modified.


class HTTPServer[T](http.server.HTTPServer):
    reply_count = 0
    data: T


class MockServer[T]:
    def __init__(
        self, address: tuple[str, int], handler: type[MockHandler[T]], data: T
    ):
        self.address = address
        self.handler = handler
        self.data = data

    def run(self) -> None:
        srv = HTTPServer[T](self.address, self.handler)
        srv.data = self.data
        srv.serve_forever()

    def start(self) -> None:
        self.process = multiprocessing.Process(target=self.run)
        self.process.start()

    def kill(self) -> None:
        self.process.terminate()
        self.process.join()
        assert self.process.exitcode is not None


class MockHandler[T](http.server.BaseHTTPRequestHandler):
    # This is wrong and broken and unsafe, but we kinda need to do it.  We know
    # that we'll only ever use this with the correct server type, but this
    # information doesn't get carried through the library stack (in fact, we
    # can't even be sure that .server here is even an HTTP server: it could be
    # any socket server).  So let's add it back.  It's just tests...
    server: HTTPServer[T]

    def replyData(self, value: str, headers: Mapping[str, str] = {}, status: int = 200) -> None:
        self.send_response(status)
        for name, content in headers.items():
            self.send_header(name, content)
        self.end_headers()
        self.wfile.write(value.encode('utf-8'))
        self.wfile.flush()

    def replyJson(self, value: JsonValue, headers: Mapping[str, str] = {}, status: int = 200) -> None:
        assert isinstance(self.server, HTTPServer)
        self.server.reply_count += 1
        all_headers = {"Content-type": "application/json", **headers}
        self.replyData(json.dumps(value), headers=all_headers, status=status)
