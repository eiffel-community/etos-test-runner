================
ETOS Test Runner
================

.. image:: https://img.shields.io/badge/Stage-Sandbox-yellow.svg
  :target: https://github.com/eiffel-community/community/blob/master/PROJECT_LIFECYCLE.md#stage-sandbox

ETOS (Eiffel Test Orchestration System) Test Runner


Description
===========

The ETOS Test Runner is responsible for executing test suites in ETOS.
ETR should, ideally, be executed within a test runner docker container.


Installation
============

   pip install etos_test_runner


Prebuilt local container
=======================

Commit the intended changes, then run ``make docker-build``. This builds only
``HEAD`` (including in a Git worktree), not staged or uncommitted files.
The default image tag is ``etos-test-runner:local-<12-character-commit>``;
override it with ``IMG=etos-test-runner:<unique-non-latest-tag>`` if needed.
``make docker-test`` validates that image locally without an ETOS service or
Kubernetes cluster. It requires Docker and Python, but no Python test dependencies.

The Dockerfile inherits the Ubuntu Noble base runner's Python 3.13 virtual
environment, etos user (UID/GID 3705), tools, artifact paths and separate test
framework virtual environment. Dependencies are installed at build time using
``requirements.lock`` as constraints. Startup runs ``etos_test_runner.etr``
directly, forwarding arguments and ignoring runtime ``DEV`` / ``ETR_VERSION``
installation overrides. The package's ``lib/executor.sh`` still executes tests.

Git archive substitutes ``.git_archival.txt`` using ``.gitattributes`` so
setuptools-scm derives the package version from the committed revision without
copying ``.git``. The full commit is also recorded in the image's
``org.opencontainers.image.revision`` label. Use ``make docker-build`` rather
than ``docker build .``; the latter deliberately fails with unsubstituted metadata.
Builds need access to the base image and Python dependency indexes; runner
startup does not install the runner package. Test commands may still need
their own dependencies and network access.

Load the image with ``kind load docker-image <image> --name <cluster>`` and
select it in each suite execution's ``environment.testRunner``. See the ETOS
local installation guide for the complete suite workflow.


Telemetry
=========

Set ``OTEL_EXPORTER_OTLP_ENDPOINT`` to enable tracing and correlated logging.
Like the suite runner, initialization uses OpenTelemetry environment and process
resource detectors with the test runner's service name and installed version. 

Suite-level lifecycle spans and bounded phase/outcome metrics are retained;
individual test executions do not emit tracing events. Metrics use the
``OTEL_EXPORTER_OTLP_ENDPOINT`` endpoint or ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``
and expose no local scrape endpoint.

Without an endpoint, or with ``OTEL_SDK_DISABLED=true``, tracing, metrics and
logs are no-op.


Contribute
==========

- Issue Tracker: https://github.com/eiffel-community/etos/issues
- Source Code: https://github.com/eiffel-community/etos-test-runner


Support
=======

If you are having issues, please let us know.
There is a mailing list at: etos-maintainers@googlegroups.com or just write an Issue.
