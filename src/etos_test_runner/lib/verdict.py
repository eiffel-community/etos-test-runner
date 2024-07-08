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
"""Verdict module."""
from typing import Union


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

    Condition keywords:
    - test_framework_exit_code: allows set custom verdict if the given exit code is
        found in the list exit codes produced by the test framework.
    """

    REQUIRED_RULE_KEYWORDS = {
        "description",
        "condition",
        "conclusion",
        "verdict",
    }
    SUPPORTED_CONDITION_KEYWORDS = {
        "test_framework_exit_code",
    }

    def __init__(self, rules: list) -> None:
        """Create new instance."""
        self.rules = rules
        for rule in self.rules:
            if set(rule.keys()) != self.REQUIRED_RULE_KEYWORDS:
                raise ValueError(
                    f"Unsupported rule definition: {rule}. "
                    f"Required keywords: {self.REQUIRED_RULE_KEYWORDS}"
                )
            for key in rule["condition"].keys():
                if key not in self.SUPPORTED_CONDITION_KEYWORDS:
                    raise ValueError(
                        f"Unsupported condition keyword for test outcome rules: {key}! "
                        f"Supported keywords: {self.SUPPORTED_CONDITION_KEYWORDS}."
                    )

    def _evaluate_rule(self, rule: dict, test_framework_output: dict) -> bool:
        """Evaluate conditions within the given rule."""
        for kw, expected_value in rule["condition"].items():
            # If the condition has multiple expressions, they are implicitly
            # joined using logical AND: i. e. all shall evaluate to True
            # in order for the condition to be True.
            # False is returned as soon as a false statement is encountered.
            if kw == "test_framework_exit_code":
                # If the exit code given by the condition is found in
                # the list of produced exit codes, the rule will evaluate as True.
                if expected_value not in test_framework_output.get("test_framework_exit_codes"):
                    return False
        return True

    def evaluate(self, test_framework_output: dict) -> Union[dict, None]:
        """Evaluate the list of given rules and return the first match."""
        for rule in self.rules:
            if self._evaluate_rule(rule, test_framework_output):
                return rule
        return None
