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
"""ETR workspace module."""
from os import chdir
import logging
from contextlib import contextmanager
from tempfile import mkdtemp
from pathlib import Path
from shutil import make_archive


class Workspace:
    """Test runner workspace. This is where all testing is done."""

    logger = logging.getLogger(__name__)
    workspace = None
    compressed_workspace = None

    def __init__(self):
        """Initialize workspace with a dictionary of identifiers."""
        self.top_dir = Path.cwd()
        self.identifiers = {}

    def __enter__(self, path=None):
        """Create and chdir to a workspace."""
        self.workspace = Path(path) if path else self.top_dir.joinpath("workspace")
        self.logger.info(
            "Creating workspace directory %r", self.workspace.relative_to(self.top_dir)
        )
        self.workspace.mkdir(exist_ok=True)
        self.logger.info(
            "Changing directory to workspace %r",
            self.workspace.relative_to(self.top_dir),
        )
        chdir(self.workspace)
        return self

    def __exit__(self, _type, _value, _traceback):
        """Compress and cleanup workspace."""
        self.logger.info("Returning to %r", self.top_dir)
        chdir(self.top_dir)
        self.compress()

    @contextmanager
    def test_directory(
        self, identifier, on_create=None, *on_create_args
    ):  # pylint:disable=keyword-arg-before-vararg
        """Create and chdir to a subfolder within the workspace.

        :param identifier: Identifier for this new test_directory.
                           Does not create a new directory if directory with
                           identifier already exists.
        :type identifier: str
        :param on_create: Call callable on creation of directory.
        :type on_create: callable
        :param on_create_args: Positional arguments for on_create callable.
        :type on_create_args: tuple
        :return: Path to the newly created directory.
        :rtype: :obj:`pathlib.Path`
        """
        if self.workspace is None or not self.workspace.is_dir():
            raise Exception("Workspace not created.")
        try:
            self.logger.info("Getting test directory with identifier %r", identifier)
            if self.identifiers.get(identifier) is None:
                directory = Path(mkdtemp(dir=self.workspace))
                self.logger.info(
                    "Directory not found. Created %r",
                    directory.relative_to(self.top_dir),
                )
                self.identifiers[identifier] = directory
                self.logger.info(
                    "Change directory to %r",
                    self.identifiers.get(identifier).relative_to(self.top_dir),
                )
                chdir(self.identifiers.get(identifier))
                if on_create is not None:
                    on_create(*on_create_args)
            else:
                self.logger.info(
                    "Found %r",
                    self.identifiers.get(identifier).relative_to(self.top_dir),
                )
                self.logger.info(
                    "Change directory to %r",
                    self.identifiers.get(identifier).relative_to(self.top_dir),
                )
                chdir(self.identifiers.get(identifier))
            yield self.identifiers.get(identifier)
        finally:
            self.logger.info(
                "Returning to %r", self.workspace.relative_to(self.top_dir)
            )
            chdir(self.workspace)

    def compress(self):
        """Compress the entire workspace folder."""
        if self.workspace is None or not self.workspace.is_dir():
            raise Exception("Workspace not created.")
        self.logger.info("Compress workspace directory")
        compressed_workspace = self.top_dir.joinpath("workspace").relative_to(
            Path.cwd()
        )
        filename = make_archive(
            compressed_workspace,
            format="gztar",
            root_dir=self.top_dir.relative_to(Path.cwd()),
            base_dir=self.workspace.relative_to(Path.cwd()),
            logger=self.logger,
        )
        self.compressed_workspace = Path(filename)
