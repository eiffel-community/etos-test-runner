# Copyright Axis Communications AB.
#
# For a full list of individual contributors, please see the commit history.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""ETOS test runner request handler."""
import os
import json
import logging
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from graphql import parse
from etos_lib.lib.debug import Debug
import requests


class Handler(BaseHTTPRequestHandler):
    """HTTP handler for the fake HTTP server."""

    logger = logging.getLogger(__name__)
    requests = []
    files = []

    def __init__(self, sub_suite, *args, **kwargs):
        """Initialize a BaseHTTPRequestHandler. This must be initialized with functools.partial.

        Example:
            handler = functools.partial(Handler, sub_suite)
            with FakeServer(handler) as server:
                print(server.host)
        """
        self.debug = Debug()
        self.sub_suite = sub_suite
        super().__init__(*args, **kwargs)

    @classmethod
    def reset(cls):
        """Reset the handler. This has to be done after each test."""
        cls.requests.clear()
        cls.files.clear()

    def store_request(self, data):
        """Store a request for testing purposes.

        :param data: Request to store.
        :type data: obj:`http.Request`
        """
        if self.requests is not None:
            self.requests.append(data)

    def store_file(self, data):
        """Store a filename for testing purposes.

        :param data: Filename to store.
        :type data: str
        """
        if self.files is not None:
            self.files.append(data)

    def get_gql_query(self, request_data):
        """Parse request data in order to get a GraphQL query string.

        :param request_data: Data to parse query string from.
        :type request_data: byte
        :return: The GraphQL query name.
        :rtype: str
        """
        data_dict = json.loads(request_data)
        parsed = parse(data_dict["query"]).to_dict()
        for definition in parsed.get("definitions", []):
            for selection in definition.get("selection_set", {}).get("selections", []):
                return selection.get("name", {}).get("value")
        raise TypeError("Not a valid GraphQL query")

    def environment_defined(self):
        """Create environment defined events for all expected sub suites.

        :return: A GraphQL response for several environment defined.
        :rtype: dict
        """
        host = os.getenv("ETOS_GRAPHQL_SERVER")  # This is set by the tests.
        return {
            "data": {
                "environmentDefined": {"edges": [{"node": {"data": {"uri": host, "name": "Test"}}}]}
            }
        }

    def do_graphql(self, query_name):
        """Handle GraphQL queries to a fake ER.

        :param query_name: The name of query (or eiffel event) from a GraphQL query.
        :type query_name: str
        :return: JSON data mimicking an ER.
        :rtype: dict
        """
        if query_name == "environmentDefined":
            return self.environment_defined()
        return None

    # pylint:disable=invalid-name
    def do_POST(self):
        """Handle POST requests."""
        self.store_request(self.request)
        request_data = self.rfile.read(int(self.headers["Content-Length"]))

        query_name = self.get_gql_query(request_data)
        response = self.do_graphql(query_name)

        self.send_response(requests.codes["ok"])
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

        response_content = json.dumps(response)
        self.wfile.write(response_content.encode("utf-8"))

    def do_GET(self):
        """Handle GET requests."""
        self.send_response(requests.codes["ok"])
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        response_content = json.dumps(self.sub_suite)
        self.wfile.write(response_content.encode("utf-8"))

    def do_PUT(self):
        """Handle PUT requests."""
        try:
            path = self.path.split("/")[1]
        except IndexError:
            path = self.path
        try:
            content_length = int(self.headers["Content-Length"])
        except TypeError:  # No file in request
            pass
        else:
            data = self.rfile.read(content_length)
            with Path.cwd().joinpath(path).open("wb") as upload_file:
                upload_file.write(data)
                self.store_file(path)
        self.send_response(requests.codes["no_content"])
        self.end_headers()
