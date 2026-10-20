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
"""Offline checks for the prebuilt local runner image."""

import json
import os
import subprocess
import unittest


@unittest.skipUnless(os.environ.get("ETR_IMAGE"), "Set ETR_IMAGE to test a built image")
class TestContainer(unittest.TestCase):
    """Validate image provenance, inherited runtime and installer-free startup."""

    def run_docker(self, *args):
        """Run Docker with bounded execution and return its standard output."""
        return subprocess.check_output(["docker", *args], text=True, timeout=120).strip()

    def test_metadata_and_runtime(self):
        """The image preserves the base contract and includes an importable runner."""
        image = os.environ["ETR_IMAGE"]
        config = json.loads(self.run_docker("image", "inspect", image))[0]["Config"]
        self.assertEqual(
            config["Entrypoint"],
            ["/home/etos/.venv/bin/python", "-m", "etos_test_runner.etr"],
        )
        revision = config["Labels"]["org.opencontainers.image.revision"]
        self.assertRegex(revision, r"^[0-9a-f]{40}$")
        result = self.run_docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--env",
            "ETOS_ENABLE_SENDING_LOGS=false",
            "--env",
            "DISABLE_EVENT_PUBLISHING=true",
            "--entrypoint",
            "/home/etos/.venv/bin/python",
            image,
            "-c",
            "import json, os, sys; from importlib.metadata import version; "
            "import etos_test_runner.etr; "
            "from importlib.resources import files; "
            "assert files('etos_test_runner').joinpath('lib/executor.sh').is_file(); "
            "print(json.dumps([os.getuid(), os.getgid(), sys.version_info[:2], "
            "sys.prefix, version('etos_test_runner'), "
            "{k: os.environ[k] for k in "
            "['TEST_FRAMEWORK_VENV', 'TEST_ARTIFACT_PATH', "
            "'GLOBAL_ARTIFACT_PATH', 'TEST_LOCAL_PATH']}]))",
        )
        uid, gid, python, prefix, version, paths = json.loads(result)
        self.assertEqual((uid, gid, python, prefix), (3705, 3705, [3, 13], "/home/etos/.venv"))
        self.assertTrue(version)
        self.assertEqual(
            paths,
            {
                "TEST_FRAMEWORK_VENV": "/home/etos/.test-framework",
                "TEST_ARTIFACT_PATH": "/home/etos/artifacts",
                "GLOBAL_ARTIFACT_PATH": "/home/etos/global",
                "TEST_LOCAL_PATH": "/home/etos/local",
            },
        )

    def test_startup_forwards_arguments_without_installing(self):
        """DEV and ETR_VERSION cannot trigger an installer before the Python module."""
        # Substitute only the module, leaving the image entrypoint unchanged.
        setup = (
            "mkdir -p /home/etos/startup-probe/etos_test_runner && "
            "printf '' > /home/etos/startup-probe/etos_test_runner/__init__.py && "
            "printf 'import json, sys; print(json.dumps(sys.argv[1:]))\\n' "
            "> /home/etos/startup-probe/etos_test_runner/etr.py && "
            'export PYTHONPATH=/home/etos/startup-probe && exec "$@"'
        )
        output = self.run_docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--env",
            "DEV=true",
            "--env",
            "ETR_VERSION=nonexistent",
            "--env",
            "ETR_REPOSITORY=https://invalid.example/runner.git",
            "--entrypoint",
            "/bin/sh",
            os.environ["ETR_IMAGE"],
            "-c",
            setup,
            "probe",
            "/home/etos/.venv/bin/python",
            "-m",
            "etos_test_runner.etr",
            "argument=with spaces",
            "second=value",
        )
        self.assertEqual(json.loads(output), ["argument=with spaces", "second=value"])
