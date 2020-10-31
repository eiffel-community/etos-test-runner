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
"""ETR log hander module."""
import os
import shutil
import logging
import traceback
import time
import errno
from json.decoder import JSONDecodeError
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from requests.exceptions import HTTPError
from urllib3.exceptions import MaxRetryError, NewConnectionError


class LogHandler:  # pylint:disable=too-many-arguments,too-many-instance-attributes
    """Handle logfiles for ETOSTestRunner."""

    logger = logging.getLogger("LogHandler")

    def __init__(self, main_suite_id, sub_suite_id, context, iut, etos):
        """Initialize loghandler.

        :param main_suite_id: The id of the main suite.
        :type main_suite_id: str
        :param sub_suite_id:  The id of the sub suite.
        :type sub_suite_id: str
        :param context: Context in which this sub-suite is executing. Base path of logs.
        :type context: str
        :param iut: IUT this sub-suite is executing on.
        :type iut: :obj:`etr.lib.iut.Iut`
        :param etos: ETOS library instance.
        :type etos: :obj:`etos_lib.Etos`
        """
        self.logs = []
        self.iut = iut

        self.etos = etos
        self.context = context
        self.log_area = self.etos.config.get("test_config").get("log_area")

        # Path in log storage for the logs in this handler.
        self.log_storage_path = os.path.join(main_suite_id, sub_suite_id)

        # Storage location of logs and artifacts from test executions.
        self.executor_log_path = os.getenv("TEST_ARTIFACT_PATH")
        # Storage location of logs globally collected for ETR execution.
        self.global_log_path = os.getenv("GLOBAL_ARTIFACT_PATH")
        # Path for logs before uploading them to log storage area.
        self.pre_upload_path = os.getenv("TEST_LOCAL_PATH")

        self.full_execution_log_path = os.path.join(
            self.global_log_path, "full_execution.log"
        )

    @property
    def persistent_logs(self):
        """All persistent log formatted for EiffelTestSuiteFinishedEvent.

        :return: All persistent logs.
        :rtype: list
        """
        return [{"name": log["name"], "uri": log["uri"]} for log in self.logs]

    @property
    def executor_logs(self):
        """All logs found in executor log path."""
        for log in os.listdir(self.executor_log_path):
            yield log, os.path.join(self.executor_log_path, log)

    @property
    def global_logs(self):
        """All logs found in global log path."""
        for log in os.listdir(self.global_log_path):
            yield log, os.path.join(self.global_log_path, log)

    def _log_name_and_path(self, log, path, test_name=None):
        """Fix log names by attaching IUT identity and compress if log path is a folder.

        :param log: Name of log file to fix name on.
        :type log: str
        :param path: Path to logfile to fix name on.
        :type path: PathLike
        :param test_name: Name of test to which these logs belong.
        :type test_name: str
        :return: Name of log and path to log.
        :rtype: tuple
        """
        filename = log
        filepath = path

        if os.path.isdir(path):
            filepath, filename = self._compress_folder(path)

        # Attach test name to log.
        if test_name:
            filename = "{}_{}".format(test_name, filename)
        log_info = self.log_area.get("logs")
        if log_info:
            filename = "{}{}{}".format(
                log_info.get("prepend", ""),
                log_info.get("join_character", "_"),
                filename,
            )

        return filename, filepath

    @staticmethod
    def __auth(username, password, type="basic"):  # pylint:disable=redefined-builtin
        """Create an authentication for HTTP request.

        :param username: Username to authenticate.
        :type username: str
        :param password: Password to authenticate with.
        :type password: str
        :param type: Type of authentication. 'basic' or 'digest'.
        :type type: str
        :return: Authentication method.
        :rtype: :obj:`requests.auth`
        """
        if type.lower() == "basic":
            return HTTPBasicAuth(username, password)
        return HTTPDigestAuth(username, password)

    def retry_upload(
        self, verb, url, log_file, timeout=None, as_json=True, **requests_kwargs
    ):
        """Attempt to connect to url for x time.

        :param verb: Which HTTP verb to use. GET, PUT, POST
                     (DELETE omitted)
        :type verb: str
        :param url: URL to retry upload request
        :type url: str
        :param log_file: Opened log file to upload.
        :type log_file: file
        :param timeout: How long, in seconds, to retry request.
        :type timeout: int or None
        :param as_json: Whether or not to return json instead of response.
        :type as_json: bool
        :param request_kwargs: Keyword arguments for the requests command.
        :type request_kwargs: dict
        :return: HTTP response or json.
        :rtype: Response or dict
        """
        if timeout is None:
            timeout = self.etos.debug.default_http_timeout
        end_time = time.time() + timeout
        self.logger.debug(
            "Retrying URL %s for %d seconds with a %s request.", url, timeout, verb
        )
        iteration = 0
        while time.time() < end_time:
            iteration += 1
            self.logger.debug("Iteration: %d", iteration)
            try:
                # Seek back to the start of the file so that the uploaded file
                # is not 0 bytes in size.
                log_file.seek(0)
                yield self.etos.http.request(
                    verb, url, as_json, data=log_file, **requests_kwargs
                )
                break
            except (
                ConnectionError,
                HTTPError,
                NewConnectionError,
                MaxRetryError,
                TimeoutError,
                JSONDecodeError,
            ):
                self.logger.warning("%r", traceback.format_exc())
                time.sleep(2)
        else:
            raise ConnectionError(
                "Unable to {} {} with params {}".format(verb, url, requests_kwargs)
            )

    def _upload_log(self, context, log, name, folder):
        """Upload log to a storage location.

        :param context: Context for the http request.
        :type context: str
        :param log: Path to the log to upload.
        :type log: str
        :param name: Name of file to upload.
        :type name: str
        :param folder: Folder to upload to.
        :type folder: str
        :return: URI where log was uploaded to.
        :rtype: str
        """
        upload = deepcopy(self.log_area.get("upload"))
        data = {"context": context, "name": name, "folder": folder}

        # ETOS Library, for some reason, uses the key 'verb' instead of 'method'
        # for HTTP method.
        upload["verb"] = upload.pop("method")
        upload["url"] = upload["url"].format(**data)
        upload["timeout"] = upload.get("timeout", 30)
        if upload.get("auth"):
            upload["auth"] = self.__auth(**upload["auth"])

        with open(log, "rb") as log_file:
            for _ in range(3):
                request_generator = self.retry_upload(log_file=log_file, **upload)
                try:
                    for response in request_generator:
                        self.logger.debug("%r", response)
                        if not upload.get("as_json", True):
                            self.logger.debug("%r", response.text)
                        self.logger.info("Uploaded log %r.", log)
                        self.logger.info("Upload URI          %r", upload["url"])
                        self.logger.info("Data:               %r", data)
                        break
                    break
                except:  # noqa pylint:disable=bare-except
                    self.logger.error("%r", traceback.format_exc())
                    self.logger.error("Failed to upload log!")
                    self.logger.error("Attempted upload of %r", log)
        return upload["url"]

    def upload_workspace(self, workspace):
        """Upload compressed workspace to log area.

        :param workspace: Workspace to upload.
        :type workspace: :obj:`etos_test_runner.lib.workspace.Workspace`
        """
        filename, filepath = self._log_name_and_path(
            workspace.compressed_workspace.name, str(workspace.compressed_workspace)
        )
        log = {"file": filepath, "name": filename, "folder": self.log_storage_path}
        log["uri"] = self._upload_log(
            self.context, log["file"], log["name"], log["folder"]
        )
        self.logs.append(log)

    def _rename_log_file_if_already_exists(self, target_path, log):
        """Rename a log file if it already exists.

        :param target_path: Which path to check if it exists.
        :type target_path: str
        :param log: Log to attempt to create.
        :type log: dict
        :return: New target path
        :rtype: str
        """
        index = 0
        while os.path.isfile(target_path):
            index += 1
            log["name"] = "{}_{}".format(index, log["name"])
            target_path = os.path.join(self.pre_upload_path, log["name"])
            self.logger.info(
                "Log with that name already exists. Rename to %r", target_path
            )
        return target_path

    def _move_log_to_pre_upload_path(self, log):
        """Move log file to pre upload path and rename if duplicates are found.

        :param log: Log to move.
        :type log: dict
        :return: Log with a new path and name.
        :rtype: dict
        """
        target_path = os.path.join(self.pre_upload_path, log["name"])
        self.logger.info("Moving log %r to %r", log, target_path)

        target_path = self._rename_log_file_if_already_exists(target_path, log)
        try:
            os.rename(log["file"], target_path)
        except OSError as error:
            if error.errno == errno.ENAMETOOLONG:
                target = Path(target_path)
                # Force the size of log name to 253 characters as to not crash due to filename
                # too long. 255 is, usually, the max size on Linux.
                target_path = os.path.join(
                    self.pre_upload_path,
                    target.name[: 253 - len(target.suffix)] + target.suffix,
                )
                self.logger.warning("Log name too long. Shortening to %r", target_path)
                target_path = self._rename_log_file_if_already_exists(target_path, log)
                os.rename(log["file"], target_path)
            else:
                raise
        log["file"] = target_path
        return log

    def gather_logs_for_executor(self, executor):
        """Gather and upload all logs for a single executor, connecting the logs to that execution.

        :param executor: Executor to gather logs from.
        :type executor: :obj:`etr.lib.executor.Executor`
        """
        with open(self.full_execution_log_path, "a+") as full_log:
            with open(executor.report_path) as report_log:
                full_log.write(report_log.read())

        for log, path in [*self.executor_logs, ("output.log", executor.report_path)]:
            filename, filepath = self._log_name_and_path(log, path, executor.test_name)
            if filename and filepath:
                log = self._move_log_to_pre_upload_path(
                    {
                        "file": filepath,
                        "name": filename,
                        "folder": self.log_storage_path,
                    }
                )
                log["uri"] = self._upload_log(
                    self.context, log["file"], log["name"], log["folder"]
                )
                self.logs.append(log)

    def gather_global_logs(self):
        """Gather and upload global ETR logs."""
        # Executor logs are fetched and stored into the global logs.
        # This is in order to try and fetch any stray logs after execution.
        for log, path in [*self.global_logs, *self.executor_logs]:
            filename, filepath = self._log_name_and_path(log, path)
            if filename and filepath:
                log = self._move_log_to_pre_upload_path(
                    {
                        "file": filepath,
                        "name": filename,
                        "folder": self.log_storage_path,
                    }
                )
                log["uri"] = self._upload_log(
                    self.context, log["file"], log["name"], log["folder"]
                )
                self.logs.append(log)

    @staticmethod
    def _compress_folder(absolute_folder_path):
        """Compress and remove folder from artifact path.

        Removal is done to avoid compressing the folder again
        and incrementally increasing the number of logs sent to
        log area or eiffel.

        :param absolute_folder_path: Path of folder to compress.
        :type absolute_folder_path: str
        :return: Tuple with zipfile path and filename.
        :rtype: tuple
        """
        zip_filename = "{}.zip".format(absolute_folder_path)
        with ZipFile(zip_filename, "w") as zip_file:
            for root, _, files in os.walk(absolute_folder_path):
                for _file in files:
                    filepath = os.path.relpath(os.path.join(root, _file))
                    zip_file.write(filepath)
        shutil.rmtree(absolute_folder_path, ignore_errors=True)
        return zip_filename, os.path.split(zip_filename)[1]
