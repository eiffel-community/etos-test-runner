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
FROM ghcr.io/eiffel-community/etos-base-test-runner:ubuntu-noble

ARG ETR_REVISION
LABEL org.opencontainers.image.revision="${ETR_REVISION}"

COPY --chown=3705:3705 . /home/etos/runner-source/
RUN test -n "$ETR_REVISION" && \
    grep -Fx "node: $ETR_REVISION" /home/etos/runner-source/.git_archival.txt && \
    UV_CACHE_DIR=/home/etos/.cache/uv \
    TMPDIR=/home/etos/runner-source \
    uv pip install --python /home/etos/.venv/bin/python \
        --constraint /home/etos/runner-source/requirements.lock \
        /home/etos/runner-source && \
    rm -rf /home/etos/runner-source /home/etos/.cache/uv

# Bypass the base installer; DEV and ETR_VERSION must not replace the baked package.
ENTRYPOINT ["/home/etos/.venv/bin/python", "-m", "etos_test_runner.etr"]
