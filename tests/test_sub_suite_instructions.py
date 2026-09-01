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
"""Tests for reading instructions from the sub suite."""

import os
from contextlib import contextmanager
from unittest import TestCase

from etos_test_runner.etr import ETR


class TestApplySubSuiteEnvironment(TestCase):
    """Test that instructions are read from the sub suite executor instructions."""

    @contextmanager
    def environ(self, keys):
        """Temporarily remove the given environment variables and restore them after."""
        previous = {key: os.environ.pop(key, None) for key in keys}
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_environment_applied_from_sub_suite(self):
        """Environment variables from the sub suite are applied to the process environment.

        Approval criteria:
            - Values defined in the sub suite executor instructions shall be applied
              when they are not already set in the environment.

        Test steps::
            1. Apply a sub suite with executor instruction environment variables.
            2. Verify that the variables were applied to the environment.
        """
        keys = ["RABBITMQ_HOST", "ETOS_API"]
        config = {
            "executor": {
                "instructions": {
                    "environment": {
                        "RABBITMQ_HOST": "rabbitmq.example.com",
                        "ETOS_API": "http://etos-api.example.com",
                    }
                }
            }
        }
        with self.environ(keys):
            ETR.apply_sub_suite_environment(config)
            self.assertEqual(os.environ["RABBITMQ_HOST"], "rabbitmq.example.com")
            self.assertEqual(os.environ["ETOS_API"], "http://etos-api.example.com")

    def test_environment_variables_take_precedence(self):
        """Existing environment variables take precedence over the sub suite instructions.

        Approval criteria:
            - Values already set in the environment shall not be overwritten by the
              sub suite instructions.

        Test steps::
            1. Set an environment variable and apply a sub suite defining the same variable.
            2. Verify that the environment value was kept.
        """
        keys = ["RABBITMQ_HOST"]
        config = {
            "executor": {"instructions": {"environment": {"RABBITMQ_HOST": "from-sub-suite"}}}
        }
        with self.environ(keys):
            os.environ["RABBITMQ_HOST"] = "from-environment"
            ETR.apply_sub_suite_environment(config)
            self.assertEqual(os.environ["RABBITMQ_HOST"], "from-environment")

    def test_missing_executor_instructions_is_noop(self):
        """A sub suite without executor instructions does not raise.

        Approval criteria:
            - Applying a sub suite that does not contain executor instructions shall
              not raise an exception.

        Test steps::
            1. Apply a sub suite without executor instructions.
            2. Verify that no exception is raised.
        """
        ETR.apply_sub_suite_environment({})
        ETR.apply_sub_suite_environment({"executor": {}})

    def test_none_values_are_skipped(self):
        """Environment variables with a value of None are not applied.

        Approval criteria:
            - Sub suite instructions with a None value shall be skipped.

        Test steps::
            1. Apply a sub suite defining a variable with a None value.
            2. Verify that the variable was not set in the environment.
        """
        keys = ["SOURCE_HOST"]
        config = {"executor": {"instructions": {"environment": {"SOURCE_HOST": None}}}}
        with self.environ(keys):
            ETR.apply_sub_suite_environment(config)
            self.assertNotIn("SOURCE_HOST", os.environ)
