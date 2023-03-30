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
"""ETR executor module."""
import os
import shlex
import logging
import signal
import json
import re
import subprocess
from pathlib import Path
from shutil import copy
from pprint import pprint

BASE = Path(__file__).parent.absolute()


class SubprocessReadTimeout(Exception):
    """Timeout on reading from subprocess."""


class TestCheckoutTimeout(TimeoutError):
    """Test checkout timeout exception."""


def _subprocess_signal_handler(signum, frame):  # pylint:disable=unused-argument
    """Raise subprocess read timeout."""
    raise SubprocessReadTimeout("Timeout while reading subprocess stdout.")


def _test_checkout_signal_handler(signum, frame):  # pylint:disable=unused-argument
    """Raise timeout error on test checkout."""
    raise TestCheckoutTimeout("Took too long to checkout test cases.")


class Executor:  # pylint:disable=too-many-instance-attributes
    """Execute a single test-case, -class, -module, -folder etc."""

    report_path = "test_output.log"
    test_name = ""
    current_test = None
    test_regex = {}
    logger = logging.getLogger("Executor")

    def __init__(self, test, iut, etos):
        """Initialize.

        :param test: Test to execute.
        :type test: str
        :param iut: IUT to execute test on.
        :type iut: :obj:`etr.lib.iut.Iut`
        :param etos: ETOS library instance.
        :type etos: :obj:`etos_lib.etos.Etos`
        """
        self.load_regex()
        self.test = test
        self.tests = {}

        self.test_environment_variables = {}
        self.test_command = None
        self.pre_test_execution = []
        self.test_command_input_arguments = {}
        self.checkout_command = []

        self.constraints = test.get("constraints", [])
        for constraint in self.constraints:
            if constraint.get("key") == "ENVIRONMENT":
                self.test_environment_variables = constraint.get("value")
            elif constraint.get("key") == "COMMAND":
                self.test_command = constraint.get("value")
            elif constraint.get("key") == "EXECUTE":
                self.pre_test_execution = constraint.get("value")
            elif constraint.get("key") == "PARAMETERS":
                self.test_command_input_arguments = constraint.get("value")
            elif constraint.get("key") == "CHECKOUT":
                self.checkout_command = constraint.get("value")

        self.test_name = test.get("testCase").get("id")
        self.test_id = test.get("id")
        self.iut = iut
        self.etos = etos
        self.context = self.etos.config.get("context")
        self.plugins = self.etos.config.get("plugins")
        self.result = True

    def load_regex(self):
        """Attempt to load regex file from environment variables.

        The regex file is used to determine when a test case has triggered,
        started, passed, failed, been skipped, raise error and the test name.
        """
        if os.getenv("TEST_REGEX"):
            try:
                path = Path(os.getenv("TEST_REGEX"))
                if path.exists() and path.is_file():
                    with path.open(encoding="utf-8") as regex_file:
                        regex = json.load(regex_file)
                    for key, value in regex.items():
                        self.test_regex[key] = re.compile(value)
                else:
                    self.logger.warning("%r is not a file or does not exist.", path)
            except TypeError as exception:
                self.logger.error("%r", exception)
                self.logger.error("Wrong type when loading %r", path)
            except re.error as exception:
                self.logger.error("%r", exception)
                self.logger.error("Failed to parse regex in file %r (%r)", path, value)
            except json.decoder.JSONDecodeError as exception:
                self.logger.error("%r", exception)
                self.logger.error("Failed to load JSON %r", path)
            except Exception as exception:  # pylint:disable=broad-exception-caught
                self.logger.error("%r", exception)
                self.logger.error("Unknown error when loading regex JSON file.")

    def _checkout_tests(self, test_checkout, workspace):
        """Check out tests for this execution.

        :param test_checkout: Test checkout parameters from test suite.
        :type test_checkout: list
        :param workspace: The workspace directory where the checkout script should be placed.
        :type workspace: :obj:`pathlib.Path`
        """
        test_directory_name = Path().absolute().name
        checkout = workspace.joinpath(f"checkout_{test_directory_name}.sh")
        with checkout.open(mode="w", encoding="utf-8") as checkout_file:
            checkout_file.write('eval "$(pyenv init -)"\n')
            checkout_file.write("pyenv shell --unset\n")
            for command in test_checkout:
                checkout_file.write(f"{command} || exit 1\n")

        self.logger.info("Checkout script:\n %s", checkout.read_text())

        signal.signal(signal.SIGALRM, _test_checkout_signal_handler)
        signal.alarm(60)
        try:
            success, output = self._call(
                ["/bin/bash", str(checkout)], shell=True, wait_output=False
            )
        finally:
            signal.alarm(0)
        if not success:
            pprint(output)
            raise RuntimeError(f"Could not checkout tests using {test_checkout!r}")

    def _build_test_command(self):
        """Build up the actual test command based on data from event."""
        base_executor = Path(BASE).joinpath("executor.sh")
        executor = Path().joinpath("executor.sh")
        copy(base_executor, executor)

        self.logger.info("Executor script:\n %s", executor.read_text(encoding="utf-8"))

        test_command = ""
        parameters = []

        for parameter, value in self.test_command_input_arguments.items():
            if value == "":
                parameters.append(parameter)
            else:
                parameters.append(f"{parameter}={value}")
        parameters = " ".join(parameters)

        test_command = f"./{executor} {self.test_command} {parameters} 2>&1"
        return test_command

    def __enter__(self):
        """Enter context and set current test."""
        self.etos.config.set("test_name", self.test_name)
        return self

    def __exit__(self, _type, value, traceback):
        """Exit context and unset current test."""
        self.etos.config.set("test_name", None)

    def _pre_execution(self, command):
        """Write pre execution command to a shell script.

        :param command: Environment and pre execution shell command to write to shell script.
        :type command: str
        """
        environ = Path().joinpath("environ.sh")
        with environ.open(mode="w", encoding="utf-8") as environ_file:
            for arg in command:
                environ_file.write(f"{arg} || exit 1\n")
        self.logger.info(
            "Pre-execution script (includes ENVIRONMENT):\n %s",
            environ.read_text(encoding="utf-8"),
        )

    def _build_environment_command(self):
        """Build command for setting environment variables prior to execution.

        :return: Command to run pre execution.
        :rtype: str
        """
        environments = [
            f"export {key}={shlex.quote(value)}"
            for key, value in self.test_environment_variables.items()
        ]
        return environments + self.pre_test_execution

    def _triggered(self, test_name):
        """Call on_test_case_triggered for all ETR plugins.

        :param test_name: Name of test that is triggered.
        :type test_name: str
        """
        for plugin in self.plugins:
            plugin.on_test_case_triggered(test_name)

    def _started(self, test_name):
        """Call on_test_case_started for all ETR plugins.

        :param test_name: Name of test that has started.
        :type test_name: str
        """
        for plugin in self.plugins:
            plugin.on_test_case_started(test_name)

    def _finished(self, test_name, result):
        """Call on_test_case_finished for all ETR plugins.

        :param test_name: Name of test that is finished.
        :type test_name: str
        :param result: Result of test case.
        :type result: str
        """
        for plugin in self.plugins:
            plugin.on_test_case_finished(test_name, result)
        self.current_test = None

    def _call(
        self, cmd, shell=False, env=None, executable=None, output=None, wait_output=True
    ):  # pylint:disable=too-many-arguments
        """Call a system command.

        :param cmd: Command to run.
        :type cmd: list
        :param env: Override subprocess environment.
        :type env: dict
        :param executable: Override subprocess executable.
        :type executable: str
        :param output: Path to a file to write stdout to.
        :type output: str
        :param wait_output: Whether or not to wait for output.
                            Some commands can fail in a non-interactive
                            shell due to waiting for 'readline' forever.
                            Set this to False on commands that we're
                            not in control of.
        :type wait_output: boolean
        :return: Result and output from command.
        :rtype: tuple
        """
        out = []
        for _, line in self._iterable_call(cmd, shell, env, executable, output, wait_output):
            if isinstance(line, str):
                out.append(line)
            else:
                success = line
                break
        return success, out

    def _iterable_call(
        self, cmd, shell=False, env=None, executable=None, output=None, wait_output=True
    ):  # pylint:disable=too-many-arguments
        """Call a system command and yield the output.

        :param cmd: Command to run.
        :type cmd: list
        :param env: Override subprocess environment.
        :type env: dict
        :param executable: Override subprocess executable.
        :type executable: str
        :param output: Path to a file to write stdout to.
        :type output: str
        :param wait_output: Whether or not to wait for output.
                            Some commands can fail in a non-interactive
                            shell due to waiting for 'readline' forever.
                            Set this to False on commands that we're
                            not in control of.
        :type wait_output: boolean
        :return: Result and output from command.
        :rtype: tuple
        """
        self.logger.debug("Running command: %s", " ".join(cmd))
        if shell:
            cmd = " ".join(cmd)
        proc = subprocess.Popen(  # pylint:disable=consider-using-with
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=shell,
            env=env,
            executable=executable,
        )

        signal.signal(signal.SIGALRM, _subprocess_signal_handler)
        output_file = None
        try:
            if output:
                # pylint:disable=consider-using-with
                output_file = open(output, "w", encoding="utf-8")
            # Make sure you can read all output with 'docker logs'
            for line in iter(proc.stdout.readline, b""):
                yield proc, line.decode("utf-8")
                self.logger.info(line.decode("utf-8").strip())
                signal.alarm(0)

                if output_file:
                    output_file.write(line.decode("utf-8"))

                if not wait_output:
                    signal.alarm(5)
        except SubprocessReadTimeout:
            pass
        finally:
            if output_file:
                output_file.close()

        _, err = proc.communicate()
        if err is not None:
            self.logger.debug(err.decode("utf-8"))
        self.logger.debug("Return code: %s (0=Good >0=Bad)", proc.returncode)

        # Unix return code 0 = success >0 = failure.
        # Python int 0 = failure >0 = success.
        # Converting unix return code to python bool.
        success = not proc.returncode

        yield proc, success

    def parse(self, line):
        """Parse test output in order to send test case events.

        :param line: Line to parse.
        :type line: str
        """
        if not isinstance(line, str):
            return
        test_name = self.test_regex["test_name"].findall(line)
        if test_name:  # A new test case has been detected.
            self.current_test = test_name[0]
            self.tests.setdefault(self.current_test, {})
        elif self.current_test is None:  # No test case has been detected.
            return
        current_test = self.current_test

        if self.test_regex["triggered"].match(line):
            self._triggered(current_test)
        if self.test_regex["started"].match(line):
            self._started(current_test)
        if self.test_regex["passed"].match(line):
            self._finished(current_test, "PASSED")
        if self.test_regex["failed"].match(line):
            self._finished(current_test, "FAILED")
        if self.test_regex["error"].match(line):
            self._finished(current_test, "ERROR")
        if self.test_regex["skipped"].match(line):
            self._finished(current_test, "SKIPPED")

    def execute(self, workspace):
        """Execute a test case.

        :param workspace: Workspace instance for creating test directories.
        :type workspace: :obj:`etos_test_runner.lib.workspace.Workspace`
        """
        line = False
        with workspace.test_directory(
            " ".join(self.checkout_command),
            self._checkout_tests,
            self.checkout_command,
            workspace.workspace,
        ) as test_directory:
            self.report_path = test_directory.joinpath(f"logs/{self.report_path}")
            self.logger.info("Report path: %r", self.report_path)

            self.logger.info("Build pre-execution script.")
            self._pre_execution(self._build_environment_command())

            self.logger.info("Build test command")
            command = self._build_test_command()

            self.logger.info("Run test command: %r", command)
            iterator = self._iterable_call(
                [command], shell=True, executable="/bin/bash", output=self.report_path
            )

            self.logger.info("Wait for test to finish.")
            # We must consume the iterator here, even if we do not parse the lines.
            for _, line in iterator:
                if self.test_regex:
                    self.parse(line)
            self.result = line
            self.logger.info("Finished with result %r.", self.result)
