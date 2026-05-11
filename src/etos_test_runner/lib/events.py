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
"""ETOS internal message bus module."""

import os

from etos_lib import ETOS
from etos_lib.lib.exceptions import PublisherConfigurationMissing
from etos_lib.logging.log_publisher import RabbitMQLogPublisher
from etos_lib.messaging.events import Artifact, Report
from etos_lib.messaging.types import File


class EventPublisher:
    """EventPublisher helps in sending events to the internal ETOS message bus."""

    disabled = False

    def __init__(self, etos: ETOS):
        """Set up, but do not start, the RabbitMQ publisher."""
        if os.getenv("DISABLE_EVENT_PUBLISHING", "false").lower() == "true":
            self.disabled = True
        v1_publisher = etos.config.get("event_publisher")
        if self.disabled is False and v1_publisher is None:
            config = etos.config.etos_rabbitmq_publisher_data()
            # This password should already be decrypted when setting up the logging.
            config["password"] = etos.config.get("etos_rabbitmq_password")
            v1_publisher = RabbitMQLogPublisher(**config, routing_key=None)
            etos.config.set("event_publisher", v1_publisher)
        self.v1_publisher = v1_publisher

        v2_publisher = None
        if self.disabled is False:
            try:
                v2_publisher = etos.messagebus_publisher()
            except PublisherConfigurationMissing:
                v2_publisher = None
        self.v2_publisher = v2_publisher

        self.identifier = etos.config.get("suite_id")

    def __del__(self):
        """Close the RabbitMQ publisher."""
        self.close()

    def close(self):
        """Close the RabbitMQ publisher if it is started."""
        if self.v1_publisher is not None and self.v1_publisher.is_alive():
            self.v1_publisher.wait_for_unpublished_events()
            self.v1_publisher.close()
            self.v1_publisher.wait_close()

    def publish(self, event: dict):
        """Publish an event to the ETOS internal message bus."""
        if self.disabled:
            return

        # SSEv1
        if self.v1_publisher is None:
            return
        if not self.v1_publisher.running:
            self.v1_publisher.start()
        routing_key = f"{self.identifier}.event.{event.get('event')}"
        self.v1_publisher.send_event(event, routing_key=routing_key)

        # SSEv2
        if event.get("event") == "artifact":
            self.__publish_artifact(event.get("data", {}))
        elif event.get("event") == "report":
            self.__publish_report(event.get("data", {}))

    def __publish_artifact(self, artifact: dict):
        """Publish an artifact to the ETOS SSEv2 internal message bus."""
        if not artifact:
            return
        if self.v2_publisher is None:
            return
        self.v2_publisher.publish(
            self.identifier,
            Artifact(
                data=File(
                    url=artifact.get("url"),
                    name=artifact.get("name"),
                    directory=artifact.get("directory"),
                    checksums=artifact.get("checksums", []),
                )
            ),
        )

    def __publish_report(self, report: dict):
        """Publish a report to the ETOS SSEv2 internal message bus."""
        if not report:
            return
        if self.v2_publisher is None:
            return
        self.v2_publisher.publish(
            self.identifier,
            Report(
                data=File(
                    url=report.get("url"),
                    name=report.get("name"),
                    directory=report.get("directory"),
                    checksums=report.get("checksums", []),
                )
            ),
        )
