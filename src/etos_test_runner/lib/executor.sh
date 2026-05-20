#!/bin/bash
# Copyright 2020 Axis Communications AB.
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

# Activate test virtual environment if configured.
# Containers that use a separate virtualenv for test dependencies (e.g. pytest
# plugins) can set TEST_FRAMEWORK_VENV to that venv path.
if [ -n "$TEST_FRAMEWORK_VENV" ] && [ -f "$TEST_FRAMEWORK_VENV/bin/activate" ]; then
    source "$TEST_FRAMEWORK_VENV/bin/activate"
fi

DIR="$(dirname "$0")"
echo "Executing pre-execution script"
cat "$DIR/environ.sh"
if ! source "$DIR/environ.sh" ; then
    echo Could not execute pre-execution script.
    exit 1
fi

COMMAND=$1
shift
ARGS=("$@")

echo "Environment used for tests"
env | sort

echo "Executing:"
echo "$COMMAND" "${ARGS[@]}"
"$COMMAND" "${ARGS[@]}"
