#!/bin/bash
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

# Set up the test framework environment.
#
# This script is sourced before checking out tests and before executing them, so
# that both steps run with the same environment.
#
# A test runner image can configure the environment with:
#
#   TEST_FRAMEWORK_VENV  Path to a virtualenv directory. Its 'bin/activate' is
#                        sourced.
#   TEST_FRAMEWORK_INIT  Path to a shell script that is sourced. Use this for test
#                        frameworks that need more than a virtualenv activation,
#                        for example frameworks shipping their own initialization
#                        script that exports additional variables.
#
# Both may be set, in which case the virtualenv is activated first and the
# initialization script is sourced after it, allowing the script to extend or
# override the virtualenv environment.
#
# If neither is set, pyenv is initialized when available, for backward
# compatibility with pre-uv test runner images.
#
# When a variable is set but the environment cannot be set up, this script exits
# non-zero instead of continuing with an incomplete environment.

if [ -n "$TEST_FRAMEWORK_VENV" ]; then
    if [ ! -f "$TEST_FRAMEWORK_VENV/bin/activate" ]; then
        echo "TEST_FRAMEWORK_VENV is set to '$TEST_FRAMEWORK_VENV', but" \
             "'$TEST_FRAMEWORK_VENV/bin/activate' does not exist." >&2
        exit 1
    fi
    echo "Activating test framework virtualenv: $TEST_FRAMEWORK_VENV"
    if ! source "$TEST_FRAMEWORK_VENV/bin/activate"; then
        echo "Failed to activate test framework virtualenv '$TEST_FRAMEWORK_VENV'." >&2
        exit 1
    fi
fi

if [ -n "$TEST_FRAMEWORK_INIT" ]; then
    if [ ! -f "$TEST_FRAMEWORK_INIT" ]; then
        echo "TEST_FRAMEWORK_INIT is set to '$TEST_FRAMEWORK_INIT', but that file" \
             "does not exist." >&2
        exit 1
    fi
    echo "Sourcing test framework initialization script: $TEST_FRAMEWORK_INIT"
    if ! source "$TEST_FRAMEWORK_INIT"; then
        echo "Test framework initialization script '$TEST_FRAMEWORK_INIT' failed." >&2
        exit 1
    fi
fi

# Backward compatibility with pre-uv test runner images that rely on pyenv.
if [ -z "$TEST_FRAMEWORK_VENV" ] && [ -z "$TEST_FRAMEWORK_INIT" ] &&
       command -v pyenv &>/dev/null; then
    eval "$(pyenv init -)"
    pyenv shell --unset
fi
