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
"""Verdict-related classes and functions."""
from typing import Union

DEFAULT_RULES = [
    {
        "description": "Executed, no errors",
        "condition" : {
            "test_framework_exit_codes": {
                "match": "all",
                "op": "eq",
                "value": 0,
            }
        },
        "conclusion": "SUCCESSFUL",
        "verdict": "PASSED",
    },
    {
        "description": "Executed with errors",
        "condition" : {
            "test_framework_exit_codes": {
                "match": "some",
                "op": "gte",
                "value": 1,
            },
        },
        "conclusion": "SUCCESSFUL",
        "verdict": "FAILED",
    },
    {
        "description": "Abnormal termination due to an exception",
        "condition" : {
            "test_framework_exit_codes": {
                "match": "some",
                "op": "eq",
                "value": None,
            },
        },
        "conclusion": "INCONCLUSIVE",
        "verdict": "FAILED",
    },
]

class ConditionEvaluator:
    """Evaluate a list of exit codes against a condition."""
    def __init__(self, exit_codes, condition):
        self.exit_codes = exit_codes
        self.condition = condition

    def evaluate(self) -> bool:
        """Run evaluation."""
        match = self.condition.get("match")
        op = self.condition.get("op")
        value = self.condition.get("value")
        if match == "all":
            if not all(self._evaluate_expression(op, value, exit_code) for exit_code in self.exit_codes):
                return False
        elif match == "some":
            if not any(self._evaluate_expression(op, value, exit_code) for exit_code in self.exit_codes):
                return False
        elif match == "none":
            if any(self._evaluate_expression(op, value, exit_code) for exit_code in self.exit_codes):
                return False
        return True

    def _evaluate_expression(self, op, value, exit_code) -> bool:
        """"Evaluate a single exit code against the condition."""
        if op == "eq":
            return exit_code == value
        elif op == "neq":
            return exit_code != value
        elif op == "gt":
            return exit_code > value
        elif op == "lt":
            return exit_code < value
        elif op == "gte":
            return exit_code >= value
        elif op == "lte":
            return exit_code <= value
        else:
            raise ValueError(f"Unsupported operator: {op}")


class VerdictMatcher:
    """Verdict matcher."""

    REQUIRED_RULE_PARAMETERS = {
        "description",
        "condition",
        "conclusion",
        "verdict",
    }

    SUPPORTED_CONDITION_KEYWORDS = {
        "test_framework_exit_codes",
    }

    SUPPORTED_EXPRESSION_OPERATORS = {
        "eq",
        "neq",
        "gt",
        "lt",
        "gte",
        "lte",
    },
    SUPPORTED_EXPRESSION_MATCH_OPERATORS = {
        "all",
        "some",
        "none",
    }

    def __init__(self, rules: list = []):
        self.rules = rules if rules else DEFAULT_RULES
        for rule in self.rules:
            # Make sure all rules have required parameters:
            if set(rule.keys()) != self.REQUIRED_RULE_PARAMETERS:
                raise ValueError(
                    f"Not all rule keywords are given in the rule: {rule}! "
                    f"Required keywords: {self.REQUIRED_RULE_PARAMETERS}."
                )
            # Make sure the rule's condition is not empty
            if len(rule["condition"].keys()) == 0:
                raise ValueError(f"No keywords are given in the rule condition: {rule}")
            
            # For each expression of the condition:
            for keyword, expression  in rule["condition"].keys():

                # All keywords shall be supported:
                if keyword not in self.SUPPORTED_CONDITION_KEYWORDS:
                    raise ValueError(
                        f"Unsupported condition keyword for test outcome rules: {keyword}! "
                        f"Supported keywords: {self.SUPPORTED_CONDITION_KEYWORDS}."
                    )

    def evaluate(self, test_framework_output: dict) -> Union[dict, None]:
        """Evaluate the list of given rules and return the first match."""
        for rule in self.rules:
            ce = ConditionEvaluator(test_framework_output["test_framework_exit_codes"], rule["condition"])
            if ce.evaluate():
                return rule
        return None

