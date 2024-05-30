# Copyright 2020-2021 Axis Communications AB.
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
"""ETR test runner module."""
import json
import time
import os
import logging
from pprint import pprint
from typing import Union

from etos_test_runner.lib.iut_monitoring import IutMonitoring
from etos_test_runner.lib.executor import Executor
from etos_test_runner.lib.workspace import Workspace
from etos_test_runner.lib.log_area import LogArea
from etos_test_runner.lib.verdict import VerdictMatcher


class TestRunner:
    """Test runner for ETOS."""

    logger = logging.getLogger("ETR")

    def __init__(self, iut, etos):
        """Initialize.

        :param iut: IUT to execute tests on.
        :type iut: :obj:`etr.lib.iut.Iut`
        :param etos: ETOS library
        :type etos: :obj:`etos_lib.etos.ETOS`
        """
        self.etos = etos
        self.iut = iut
        self.config = self.etos.config.get("test_config")

        self.log_area = LogArea(self.etos)
        self.iut_monitoring = IutMonitoring(self.iut, self.etos)
        self.issuer = {"name": "ETOS Test Runner"}
        self.etos.config.set("iut", self.iut)
        self.plugins = self.etos.config.get("plugins")
        rules = []
        if os.getenv("VERDICT_RULE_FILE"):
            with open(os.getenv("VERDICT_RULE_FILE"), "r", encoding="utf-8") as inp:
                rules = json.load(inp)
            self.verdict_matcher = VerdictMatcher(rules=rules)
        else:
            self.verdict_matcher = VerdictMatcher()

    def test_suite_started(self):
        """Publish a test suite started event.

        :return: Reference to test suite started.
        :rtype: :obj:`eiffel.events.base_event.BaseEvent`
        """
        suite_name = self.config.get("name")
        categories = ["Regression test_suite", "Sub suite"]
        categories.append(self.iut.identity.name)
        livelogs = self.config.get("log_area", {}).get("livelogs")

        # TODO: Remove CONTEXT link here.
        return self.etos.events.send_test_suite_started(
            suite_name,
            links={
                "CONTEXT": self.etos.config.get("context"),
                "CAUSE": self.etos.config.get("main_suite_id"),
            },
            categories=categories,
            types=["FUNCTIONAL"],
            liveLogs=[{"name": "console", "uri": livelogs}],
        )

    def environment(self, context):
        """Send out which environment we're executing within.

        :param context: Context where this environment is used.
        :type context: str
        """
        # TODO: Get this from prepare
        if os.getenv("HOSTNAME") is not None:
            self.etos.events.send_environment_defined(
                "ETR Hostname",
                links={"CONTEXT": context},
                host={"name": os.getenv("HOSTNAME"), "user": "etos"},
            )
        if os.getenv("EXECUTION_SPACE_URL") is not None:
            self.etos.events.send_environment_defined(
                "Execution Space URL",
                links={"CONTEXT": context},
                host={"name": os.getenv("EXECUTION_SPACE_URL"), "user": "etos"},
            )

    def run_tests(self, workspace: Workspace) -> list[Union[int, None]]:
        """Execute test recipes within a test executor.

        :param workspace: Which workspace to execute test suite within.
        :type workspace: :obj:`etr.lib.workspace.Workspace`
        :return: List of test framework exit codes for each recipe.
        :rtype: list of int or None instances
        """
        recipes = self.config.get("recipes")
        test_framework_exit_codes = []
        for num, test in enumerate(recipes):
            self.logger.info("Executing test %s/%s", num + 1, len(recipes))
            with Executor(test, self.iut, self.etos) as executor:
                self.logger.info("Starting test '%s'", executor.test_name)
                executor.execute(workspace)
                if executor.returncode is not None:
                    self.logger.info(
                        "Test finished. Test framework exit code: %d",
                        executor.returncode,
                    )
                else:
                    self.logger.info("Test finished. Test framework exit code is None.")
                test_framework_exit_codes.append(executor.returncode)
        return executor.returncode

    def outcome(
        self, detailed_description: str, test_framework_exit_codes: list[Union[int, None]]
    ) -> dict:
        """Get outcome from test execution.

        :param detailed_description: Optional detailed description.
        :type detailed_description: str
        :test_framework_exit_codes: list of exit codes for each recipe
        :
        :return: Outcome of test execution.
        :rtype: dict
        """
        test_framework_output = {
            "test_framework_exit_codes": test_framework_exit_codes
        }
        verdict = self.verdict_matcher.evaluate(test_framework_output)
        verdict["detailed_description"] = detailed_description
        return verdict

    def _test_suite_triggered(self, name):
        """Call on_test_suite_triggered for all ETR plugins.

        :param name: Name of test suite that triggered.
        :type name: str
        """
        for plugin in self.plugins:
            plugin.on_test_suite_triggered(name)

    def _test_suite_started(self, test_suite_started):
        """Call on_test_suite_started for all ETR plugins.

        :param test_suite_started: The test suite started event
        :type test_suite_started: :obj:`eiffellib.events.EiffelTestSuiteStartedEvent`
        """
        for plugin in self.plugins:
            plugin.on_test_suite_started(test_suite_started)

    def _test_suite_finished(self, name, outcome):
        """Call on_test_suite_finished for all ETR plugins.

        :param name: Name of test suite that finished.
        :type name: str
        :param outcome: Outcome of test suite execution.
        :type outcome: dict
        """
        for plugin in self.plugins:
            plugin.on_test_suite_finished(name, outcome)

    def execute(self):  # pylint:disable=too-many-branches,disable=too-many-statements
        """Execute all tests in test suite.

        :return: Result of execution. Linux exit code.
        :rtype: int
        """
        self._test_suite_triggered(self.config.get("name"))
        self.logger.info("Send test suite started event.")
        test_suite_started = self.test_suite_started()
        self._test_suite_started(test_suite_started)
        sub_suite_id = test_suite_started.meta.event_id

        self.logger.info("Send test environment events.")
        self.environment(sub_suite_id)
        self.etos.config.set("sub_suite_id", sub_suite_id)

        description = None
        test_framework_exit_code = None
        try:
            with Workspace(self.log_area) as workspace:
                self.logger.info("Start IUT monitoring.")
                self.iut_monitoring.start_monitoring()
                self.logger.info("Starting test executor.")
                test_framework_exit_code = self.run_tests(workspace)
                self.logger.info("Stop IUT monitoring.")
                self.iut_monitoring.stop_monitoring()
        except Exception as exception:  # pylint:disable=broad-except
            description = str(exception)
            raise
        finally:
            if self.iut_monitoring.monitoring:
                self.logger.info("Stop IUT monitoring.")
                self.iut_monitoring.stop_monitoring()
            self.logger.info("Figure out test outcome.")
            outcome = self.outcome(description, test_framework_exit_code)
            pprint(outcome)

            self.logger.info("Send test suite finished event.")
            self._test_suite_finished(self.config.get("name"), outcome)
            test_suite_finished = self.etos.events.send_test_suite_finished(
                test_suite_started,
                links={"CONTEXT": self.etos.config.get("context")},
                outcome=outcome,
                persistentLogs=self.log_area.persistent_logs,
            )
            self.logger.info(test_suite_finished.pretty)

        timeout = time.time() + 600  # 10 minutes
        self.logger.info("Waiting for eiffel publisher to deliver events (600s).")

        previous = 0
        # pylint:disable=protected-access
        current = len(self.etos.publisher._deliveries)
        while current:
            current = len(self.etos.publisher._deliveries)
            self.logger.info("Remaining events to send        : %d", current)
            self.logger.info("Events sent since last iteration: %d", previous - current)
            if time.time() > timeout:
                if current < previous:
                    self.logger.info(
                        "Timeout reached, but events are still being sent. Increase timeout by 10s."
                    )
                    timeout = time.time() + 10
                else:
                    raise TimeoutError("Eiffel publisher did not deliver all eiffel events.")
            previous = current
            time.sleep(1)
        self.logger.info("Tests finished executing.")
        return 0 if result else outcome
