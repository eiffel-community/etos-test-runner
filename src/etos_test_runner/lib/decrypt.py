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
"""JSONTas decrypt string data structure module."""
import os
from cryptography.fernet import Fernet
from jsontas.data_structures.datastructure import DataStructure

# pylint:disable=too-few-public-methods


def decrypt(value, key):
    """Decrypt a string.

    :param value: Data to decrypt.
    :type value: str
    :param key: Encryption key to decrypt data with.
    :type key: str
    :return: Decrypted data.
    :rtype: str
    """
    return Fernet(key).decrypt(value).decode()


class Decrypt(DataStructure):
    """Decrypt an encrypted string."""

    def execute(self):
        """Execute datastructure.

        :return: Name of key. None, to tel JSONTas to not override key name, and decrypted value.
        """
        key = os.getenv("ETOS_ENCRYPTION_KEY")
        assert key is not None, "ETOS_ENCRYPTION_KEY environment variable must be set"
        return None, decrypt(self.data.get("value"), key)
