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
"""ETOS plugin support.

In order to create a plugin, create a class with the name ETRPlugin inheriting the
base ETRPlugin class from this module.
Whenever that plugin is installed within the test runner that is executing tests ETOS
will automatically load and call your plugin.

Note that a TEST_REGEX file must be set for these plugins to work with test cases.
"""
