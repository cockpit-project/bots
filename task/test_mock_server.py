#!/usr/bin/env python3

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

import http.server
import json
import multiprocessing


class MockServer(http.server.HTTPServer):
    def __init__(self, address, handler, data=None):
        self.address = address
        self.handler = handler
        self.data = data
        self.reply_count: int = 0
        super(MockServer, self).__init__(address, handler)

    def start(self):
        self.process = multiprocessing.Process(target=self.serve_forever)
        self.process.start()

    def kill(self):
        self.process.terminate()
        self.process.join()


class MockHandler(http.server.BaseHTTPRequestHandler):
    server: MockServer

    def replyData(self, value, headers={}, status=200):
        self.send_response(status)
        for name, content in headers.items():
            self.send_header(name, content)
        self.end_headers()
        self.wfile.write(value.encode('utf-8'))
        self.wfile.flush()

    def replyJson(self, value, headers=None, status=200):
        self.server.reply_count += 1
        all_headers = {"Content-type": "application/json"}
        all_headers.update(headers or {})
        self.replyData(json.dumps(value), headers=all_headers, status=status)
