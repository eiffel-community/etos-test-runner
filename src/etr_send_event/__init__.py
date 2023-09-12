# Copyright 2022 Axis Communications AB.
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
"""Pre-installed ETR event send plugin."""
import os
from etos_test_runner.plugins.plugin import ETRPlugin as Base


class ETRPlugin(Base):
    """Plugin for sending test case events."""

    def __init__(self, *args, **kwargs):
        """Get context from ETOS config and initialize a test dictionary."""
        super().__init__(*args, **kwargs)
        self.tests = {}
        self.current_test = None

    def on_test_case_started(self, test_name):
        """Send a testcase started event.

        :param test_name: Name of test that has started.
        :type test_name: str
        """
        context = self.etos.config.get("sub_suite_id")
        triggered = self.tests[test_name].get("triggered")
        if triggered is None:
            return None
        event = self.etos.events.send_test_case_started(triggered, links={"CONTEXT": context})
        self.tests[test_name]["started"] = event

    def on_test_case_triggered(self, test_name):
        """Send a testcase triggered event.

        :param test_name: Name of test that has triggered.
        :type test_name: str
        """
        context = self.etos.config.get("sub_suite_id")
        self.tests.setdefault(test_name, {})
        event = self.etos.events.send_test_case_triggered(
            {"id": test_name},
            self.etos.config.get("artifact"),
            links={"CONTEXT": context},
        )
        self.tests[test_name]["triggered"] = event

    def on_test_case_error(self, test_name):
        """Send a testcase finished event with error outcome.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """
        context = self.etos.config.get("sub_suite_id")
        triggered = self.tests[test_name].get("triggered")
        if triggered is None:
            return None
        outcome = {"verdict": "FAILED", "conclusion": "INCONCLUSIVE"}
        event = self.etos.events.send_test_case_finished(
            triggered, outcome, links={"CONTEXT": context}
        )
        self.tests[test_name]["finished"] = event
        self.current_test = None

    def on_test_case_failure(self, test_name):
        """Send a testcase finished event with failed outcome.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """
        context = self.etos.config.get("sub_suite_id")
        triggered = self.tests[test_name].get("triggered")
        if triggered is None:
            return None
        self.current_test = None
        outcome = {"verdict": "FAILED", "conclusion": "FAILED"}
        event = self.etos.events.send_test_case_finished(
            triggered, outcome, links={"CONTEXT": context}
        )
        self.tests[test_name]["finished"] = event
        self.current_test = None

    def on_test_case_skipped(self, test_name):
        """Send a testcase finished event with skipped outcome.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """
        context = self.etos.config.get("sub_suite_id")
        triggered = self.tests[test_name].get("triggered")
        if triggered is None:
            return None
        self.current_test = None
        outcome = {
            "verdict": "PASSED",
            "conclusion": "SUCCESSFUL",
            "description": "SKIPPED",
        }
        environment_id = os.getenv("ENVIRONMENT_ID")
        event = self.etos.events.send_test_case_finished(
            triggered, outcome, links={"CONTEXT": context, "ENVIRONMENT": environment_id}
        )
        self.tests[test_name]["finished"] = event
        self.current_test = None

    def on_test_case_success(self, test_name):
        """Send a testcase finished event with successful outcome.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """
        context = self.etos.config.get("sub_suite_id")
        triggered = self.tests[test_name].get("triggered")
        if triggered is None:
            return None
        self.current_test = None
        outcome = {"verdict": "PASSED", "conclusion": "SUCCESSFUL"}
        event = self.etos.events.send_test_case_finished(
            triggered, outcome, links={"CONTEXT": context}
        )
        self.tests[test_name]["finished"] = event
        self.current_test = None
