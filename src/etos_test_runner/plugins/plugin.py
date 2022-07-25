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
"""Base ETOS plugin."""


class ETRPlugin:
    """Base plugin class and should be inherited by all ETR plugins.

    All methods can be overriden in order to get the desired results.
    """

    def __init__(self, etos):
        """Initialize ETOS library."""
        self.etos = etos

    def on_triggered(self, test_name):
        """Call when a test case has been triggered.

        :param test_name: Name of test that has triggered.
        :type test_name: str
        """

    def on_started(self, test_name):
        """Call when a test case has been started.

        :param test_name: Name of test that has started.
        :type test_name: str
        """

    def on_finished(self, test_name, result):
        """Call when a test case has been finished.

        Will, in turn, call :meth:`on_started`, :meth:`on_failure`,
        :meth:`on_skipped` or :meth:`on_success` depending on the result.

        :param test_name: Name of test that has finished.
        :type test_name: str
        :param result: Result of test execution. ERROR, FAILED, SKIPPED or PASSED.
        :type result: str
        """
        if result.lower() == "error":
            self.on_error(test_name)
        elif result.lower() == "failed":
            self.on_failure(test_name)
        elif result.lower() == "skipped":
            self.on_skipped(test_name)
        else:
            self.on_success(test_name)

    def on_failure(self, test_name):
        """Call when a test case has finished with a failure.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """

    def on_error(self, test_name):
        """Call when a test case has finished with an error.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """

    def on_skipped(self, test_name):
        """Call when a test case has been skipped.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """

    def on_success(self, test_name):
        """Call when a test case has finished successfully.

        :param test_name: Name of test that has finished.
        :type test_name: str
        """
