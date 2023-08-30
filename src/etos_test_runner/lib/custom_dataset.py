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
"""Custom dataset module."""
from jsontas.dataset import Dataset


class CustomDataset(Dataset):
    """Custom dataset for ETR to decrypt secrets.

    This custom dataset removes all default JsonTas datastructures
    as we are going to run JsonTas on the sub suite information
    retrieved from the environment provider.
    This sub suite information is quite large and if we keep the
    default datastructures the ETR would be susceptible to remote
    code execution. This custom dataset shall only be used when
    decrypting secrets.
    """

    def __init__(self):
        """Initialize an empty dataset."""
        super().__init__()
        # pylint:disable=unused-private-member
        # It is used by the parent class.
        self.__dataset = {}
