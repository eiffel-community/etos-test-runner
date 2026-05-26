#!/usr/bin/env python
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
# -*- coding: utf-8 -*-
"""ETOS test runner module."""

import importlib
import logging
import os
import pkgutil
import signal
import sys
from collections import OrderedDict
from importlib.metadata import version
from pprint import pprint
from typing import Optional, Union

from etos_lib import ETOS
from etos_lib.lib.http import Http
from etos_lib.logging.logger import FORMAT_CONFIG
from etos_lib.messaging.events import Status
from etos_lib.messaging.types import ServiceHealth, ServiceStatus
from jsontas.jsontas import JsonTas
from urllib3.util import Retry

from etos_test_runner.lib.custom_dataset import CustomDataset
from etos_test_runner.lib.decrypt import Decrypt, decrypt
from etos_test_runner.lib.events import EventPublisher
from etos_test_runner.lib.iut import Iut
from etos_test_runner.lib.testrunner import TestRunner

VERSION = version("etos_test_runner")

# Remove spam from pika.
logging.getLogger("pika").setLevel(logging.WARNING)

_LOGGER = logging.getLogger(__name__)


class ETR:
    """ETOS Test Runner."""

    context = None

    def __init__(self) -> None:
        """Initialize ETOS library and start eiffel publisher."""
        self.etos = ETOS("ETOS Test Runner", os.getenv("HOSTNAME"), "ETOS Test Runner")
        if os.getenv("ETOS_ENCRYPTION_KEY"):
            os.environ["RABBITMQ_PASSWORD"] = decrypt(
                os.environ["RABBITMQ_PASSWORD"], os.getenv("ETOS_ENCRYPTION_KEY")
            )

        self.etos.config.rabbitmq_publisher_from_environment()
        self.etos.config.set("etos_rabbitmq_password", os.environ.get("ETOS_RABBITMQ_PASSWORD"))
        self.etos.config.set("suite_id", os.getenv("SUITE_ID"))
        # ETR will print the entire environment just before executing.
        # Hide the password.
        os.environ["RABBITMQ_PASSWORD"] = "*********"
        os.environ["ETOS_RABBITMQ_PASSWORD"] = "*********"

        self.etos.start_publisher()
        self.environment_id = os.getenv("ENVIRONMENT_ID")
        self.environment_url = os.getenv("ENVIRONMENT_URL")

        signal.signal(signal.SIGTERM, self.graceful_shutdown)

    @staticmethod
    def graceful_shutdown(*_) -> None:
        """Catch sigterm."""
        raise Exception("ETR has been terminated.")  # pylint:disable=broad-exception-raised

    def download_and_load(self, sub_suite_url: str) -> None:
        """Download and load test json.

        :param sub_suite_url: URL to where the sub suite information exists.
        """
        codes = [*Retry.RETRY_AFTER_STATUS_CODES, 404, 500]
        retry = Retry(
            total=None,
            read=10,
            connect=10,  # With 1 as backoff_factor, will retry for 1023s
            status=10,  # With 1 as backoff_factor, will retry for 1023s
            backoff_factor=1,
            other=0,
            status_forcelist=codes,  # 413, 429, 503, 404, 500
        )
        http_client = Http(retry=retry)

        response = http_client.get(sub_suite_url)
        json_config = response.json(object_pairs_hook=OrderedDict)
        dataset = CustomDataset()
        dataset.add("decrypt", Decrypt)
        config = JsonTas(dataset).run(json_config)

        # ETR will print the entire environment just before executing.
        # Hide the encryption key.
        if os.getenv("ETOS_ENCRYPTION_KEY"):
            os.environ["ETOS_ENCRYPTION_KEY"] = "*********"

        self.etos.config.set("test_config", config)
        self.etos.config.set("context", config.get("context"))
        self.etos.config.set("artifact", config.get("artifact"))
        self.etos.config.set("main_suite_id", config.get("test_suite_started_id"))
        self.etos.config.set("suite_id", config.get("suite_id"))

    def load_plugins(self) -> None:
        """Load plugins from environment using the name etr_."""
        disable_plugins = os.getenv("DISABLE_PLUGINS")
        disabled_plugins = []
        if disable_plugins:
            disabled_plugins = disable_plugins.split(",")

        discovered_plugins = {
            name: importlib.import_module(name)
            for _, name, _ in pkgutil.iter_modules()
            if name.startswith("etr_") and name not in disabled_plugins
        }
        plugins = []
        for name, module in discovered_plugins.items():
            _LOGGER.info("Loading plugin: %r", name)
            if not hasattr(module, "ETRPlugin"):
                raise AttributeError(f"{name} does not have an ETRPlugin class!")
            plugins.append(module.ETRPlugin(self.etos))
        self.etos.config.set("plugins", plugins)

    def get_sub_suite_url(self, environment_id: str) -> Optional[str]:
        """Get sub suite from ETOS environment defined event.

        :param environment_id: ID of th environment defined event.
        :return: URL for sub suite.
        """
        query = """
        {
          environmentDefined(search: "{'meta.id': '%s'}") {
            edges {
              node {
                data {
                  uri
                }
              }
            }
          }
        }
        """ % environment_id
        # Timeout can be configured using ETOS_DEFAULT_WAIT_TIMEOUT environment variable
        # Default timeout is 60s.
        wait_generator = self.etos.utils.wait(self.etos.graphql.execute, query=query)
        for response in wait_generator:
            if response:
                try:
                    _, environment_defined = next(
                        self.etos.graphql.search_for_nodes(response, "environmentDefined")
                    )
                except StopIteration:
                    continue
                return environment_defined["data"]["uri"]
        return None

    def run_etr(self) -> Union[int, dict]:
        """Send activity events and run ETR.

        :return: Result of testrunner execution.
        """
        event_publisher = EventPublisher(self.etos)
        _LOGGER.info("Publishing status event: ETOS Test Runner is starting.")
        event_publisher.publish_v2(
            Status(
                data=ServiceStatus(
                    name="test-runner",
                    instance=self.environment_id,
                    version=VERSION,
                    status=ServiceHealth.OK,
                    message="ETOS Test Runner is starting.",
                )
            ),
        )
        try:
            _LOGGER.info("Starting ETR.")
            sub_suite_url = self.environment_url
            if sub_suite_url is None:
                sub_suite_url = self.get_sub_suite_url(self.environment_id)
                if sub_suite_url is None:
                    raise TimeoutError(
                        f"Could not get sub suite environment event with id {self.environment_id!r}"
                    )
            self.download_and_load(sub_suite_url)
            FORMAT_CONFIG.identifier = self.etos.config.get("suite_id")
            self.load_plugins()
            iut = Iut(self.etos.config.get("test_config").get("iut"))
            test_runner = TestRunner(iut, self.etos)
        except Exception as exception:  # pylint:disable=broad-except
            _LOGGER.exception("ETR failed to start.")
            _LOGGER.info("Publishing status event: ETOS Test Runner failed to start.")
            event_publisher.publish_v2(
                Status(
                    data=ServiceStatus(
                        name="test-runner",
                        instance=self.environment_id,
                        version=VERSION,
                        status=ServiceHealth.ERROR,
                        message=f"ETOS Test Runner failed to download sub suite: {exception}",
                    )
                ),
            )
            raise
        # test_runner.execute() will publish TestSuiteStarted and TestSuiteFinished events to manage
        # if there are any failures, no need for status events after this point.
        result = test_runner.execute()
        _LOGGER.info("ETR finished.")
        return result


def main() -> None:
    """Start ETR."""
    etr = ETR()
    result = etr.run_etr()
    if isinstance(result, dict):
        pprint(result)
    _LOGGER.info("Done. Exiting")
    _LOGGER.info(result)
    sys.exit(result)


def run():
    """Entry point to ETR."""
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()


if __name__ == "__main__":
    run()
