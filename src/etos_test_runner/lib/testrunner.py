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


class CustomVerdictMatcher:
    # pylint: disable=too-few-public-methods
    """Match testframework output against user-defined verdict rules.

    Example rule definition:

    rules = [
        {
            "description": "Test collection error, no artifacts created",
            "condition": {
                "test_framework_exit_code": 4,
            },
            "conclusion": "FAILED",
            "verdict": "FAILED",
        }
    ]
    """

    SUPPORTED_CONDITION_KEYWORDS = [
        "test_framework_exit_code",
    ]

    def __init__(self, rules: list, test_framework_output: dict) -> None:
        """Create new instance."""
        self.rules = rules
        self.test_framework_output = test_framework_output

        for rule in self.rules:
            for key in rule["condition"].keys():
                if key not in self.SUPPORTED_CONDITION_KEYWORDS:
                    raise ValueError(
                        f"Unsupported condition keyword for test outcome rules: {key}! "
                        f"Supported keywords: {self.SUPPORTED_CONDITION_KEYWORDS}."
                    )

    def _evaluate_rule(self, rule: dict) -> bool:
        """Evaluate conditions within the given rule."""
        for kw, expected_value in rule["condition"].items():
            # logical AND: return False as soon as a false statement is encountered:
            if (
                kw == "test_framework_exit_code"
                and "test_framework_exit_code" in self.test_framework_output.keys()
            ):
                if self.test_framework_output["test_framework_exit_code"] != expected_value:
                    return False
            # implement more keywords if needed
        return True

    def evaluate(self) -> Union[dict, None]:
        """Evaluate the list of given rules and return the first match."""
        for rule in self.rules:
            if self._evaluate_rule(rule):
                return rule
        return None


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

    def run_tests(self, workspace: Workspace) -> tuple[bool, int]:
        """Execute test recipes within a test executor.

        :param workspace: Which workspace to execute test suite within.
        :type workspace: :obj:`etr.lib.workspace.Workspace`
        :return: Result of test execution.
        :rtype: bool
        """
        recipes = self.config.get("recipes")
        result = True
        for num, test in enumerate(recipes):
            self.logger.info("Executing test %s/%s", num + 1, len(recipes))
            with Executor(test, self.iut, self.etos) as executor:
                self.logger.info("Starting test '%s'", executor.test_name)
                executor.execute(workspace)
                if not executor.result:
                    result = executor.result
                self.logger.info(
                    "Test finished. Result: %s. Test framework exit code: %d",
                    executor.result,
                    executor.returncode,
                )
        return result, executor.returncode

    def outcome(
        self, result: bool, executed: bool, description: str, test_framework_exit_code: int
    ) -> dict:
        """Get outcome from test execution.

        :param result: Result of execution.
        :type result: bool
        :param executed: Whether or not tests have successfully executed.
        :type executed: bool
        :param description: Optional description.
        :type description: str
        :return: Outcome of test execution.
        :rtype: dict
        """
        verdict_rule_file = os.getenv("VERDICT_RULE_FILE")
        custom_verdict = None
        if verdict_rule_file is not None:
            test_framework_output = {
                "test_framework_exit_code": test_framework_exit_code,
            }
            with open(os.getenv("VERDICT_RULE_FILE"), "r", encoding="utf-8") as inp:
                rules = json.load(inp)
            cvm = CustomVerdictMatcher(rules, test_framework_output)
            custom_verdict = cvm.evaluate()
        if None not in (verdict_rule_file, custom_verdict):
            conclusion = custom_verdict["conclusion"]
            verdict = custom_verdict["verdict"]
            description = custom_verdict["description"]
            self.logger.info("Verdict matches testrunner verdict rule: %s", custom_verdict)
        elif executed:
            conclusion = "SUCCESSFUL"
            verdict = "PASSED" if result else "FAILED"
            self.logger.info(
                "Tests executed successfully. Verdict set to '%s' due to result being '%s'",
                verdict,
                result,
            )
        else:
            conclusion = "FAILED"
            verdict = "INCONCLUSIVE"
            self.logger.info(
                "Tests did not execute successfully. Setting verdict to '%s'",
                verdict,
            )

        suite_name = self.config.get("name")
        if not description and not result:
            self.logger.info("No description but result is a failure. At least some tests failed.")
            description = f"At least some {suite_name} tests failed."
        elif not description and result:
            self.logger.info(
                "No description and result is a success. All tests executed successfully."
            )
            description = f"All {suite_name} tests completed successfully."
        else:
            self.logger.info("Description was set. Probably due to an exception.")
        return {
            "verdict": verdict,
            "description": description,
            "conclusion": conclusion,
        }

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

        result = True
        description = None
        executed = False
        test_framework_exit_code = None
        try:
            with Workspace(self.log_area) as workspace:
                self.logger.info("Start IUT monitoring.")
                self.iut_monitoring.start_monitoring()
                self.logger.info("Starting test executor.")
                result, test_framework_exit_code = self.run_tests(workspace)
                executed = True
                self.logger.info("Stop IUT monitoring.")
                self.iut_monitoring.stop_monitoring()
        except Exception as exception:  # pylint:disable=broad-except
            result = False
            executed = False
            description = str(exception)
            raise
        finally:
            if self.iut_monitoring.monitoring:
                self.logger.info("Stop IUT monitoring.")
                self.iut_monitoring.stop_monitoring()
            self.logger.info("Figure out test outcome.")
            outcome = self.outcome(result, executed, description, test_framework_exit_code)
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
