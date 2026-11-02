# Copyright 2026 Axis Communications AB.
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
"""Tests for bounded test-runner tracing helpers."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from opentelemetry import baggage, trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from etos_test_runner import etr
from etos_test_runner.lib import executor as executor_module
from etos_test_runner.lib import tracing, testrunner
from etos_test_runner.lib.tracing import (
    extract_launch_context,
    inject_context,
    record_error,
    set_outcome,
)


def test_extract_launch_context_uses_w3c_parent():
    """The uppercase runner environment carrier becomes the incoming W3C parent."""
    context = extract_launch_context(
        {
            "TRACEPARENT": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "BAGGAGE": "testrun_id=run-1,custom_correlation=value",
        }
    )

    span = trace.get_current_span(context)
    assert span.get_span_context().trace_id == int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
    assert span.get_span_context().span_id == int("00f067aa0ba902b7", 16)
    assert baggage.get_all(context) == {
        "testrun_id": "run-1",
        "custom_correlation": "value",
    }


def test_extract_launch_context_accepts_provider_lowercase_keys():
    """Provider-generated lowercase W3C environment keys remain correlated."""
    context = extract_launch_context(
        {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "baggage": "testrun_id=run-1,custom_correlation=value",
        }
    )

    span = trace.get_current_span(context)
    assert span.get_span_context().trace_id == int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
    assert span.get_span_context().span_id == int("00f067aa0ba902b7", 16)
    assert baggage.get_baggage("custom_correlation", context) == "value"


def test_inject_context_exports_execution_span_and_launch_state() -> None:
    """Test subprocess context is the execution span with inherited trace state and baggage."""
    parent_context = extract_launch_context(
        {
            "TRACEPARENT": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "TRACESTATE": "congo=t61rcWkgMzE",
            "BAGGAGE": "testrun_id=run-1",
        }
    )
    provider = TracerProvider()
    span = provider.get_tracer("test").start_span("etos.runner.execute", context=parent_context)

    environment = inject_context(span, parent_context)

    assert environment["TRACEPARENT"].split("-")[2] == f"{span.get_span_context().span_id:016x}"
    assert environment["TRACESTATE"] == "congo=t61rcWkgMzE"
    assert environment["BAGGAGE"] == "testrun_id=run-1"
    span.end()
    provider.shutdown()


def test_startup_span_is_active_during_plugin_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup operations run with the startup span as their current context.

    :param monkeypatch: Pytest fixture for replacing runner dependencies.
    """
    provider = TracerProvider()
    runner = etr.ETR.__new__(etr.ETR)
    runner.trace_context = extract_launch_context({})
    runner.etos = Mock()
    runner.etos.config.get.return_value = "suite-1"
    runner.environment_id = "environment-1"
    runner.environment_url = "https://example.test/suite"
    suite = SimpleNamespace(iut=Mock())
    test_runner = Mock()

    monkeypatch.setattr(etr.FORMAT_CONFIG, "identifier", "suite-1", raising=False)
    monkeypatch.setattr(etr, "EventPublisher", Mock())
    monkeypatch.setattr(etr, "tracer", lambda: provider.get_tracer("test"))
    monkeypatch.setattr(etr, "record_milestone", Mock())
    monkeypatch.setattr(etr, "flush", Mock())
    monkeypatch.setattr(etr, "Iut", Mock())
    monkeypatch.setattr(etr, "TestRunner", Mock(return_value=test_runner))
    monkeypatch.setattr(runner, "download_and_load", Mock(return_value=suite))
    monkeypatch.setattr(runner, "configure_eiffel_publisher", Mock())

    def check_startup_context() -> None:
        """Verify plugin loading has the startup span active."""
        assert trace.get_current_span().name == "etos.runner.startup"

    monkeypatch.setattr(runner, "load_plugins", check_startup_context)

    runner.run_etr()

    test_runner.execute.assert_called_once_with()
    provider.shutdown()


def test_execution_span_is_active_during_test_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test test execution uses the execution span as its current context."""
    provider = TracerProvider()
    runner = testrunner.TestRunner.__new__(testrunner.TestRunner)
    runner.trace_context = extract_launch_context({})
    runner.suite = SimpleNamespace(name="suite")
    setattr(runner, "_result", True)
    setattr(runner, "_outcome", {"verdict": "PASSED", "conclusion": "SUCCESSFUL"})
    setattr(runner, "_active_execution_span", None)
    runner.trace_environment = {}
    runner.verdict_matcher = Mock()
    runner.verdict_matcher.evaluate.return_value = None
    runner.logger = Mock()
    runner.log_area = Mock()
    runner.etos = Mock()
    runner.etos.config.get.return_value = 0
    runner.etos.events.send_test_suite_finished.return_value = SimpleNamespace(pretty="finished")
    setattr(runner.etos.publisher, "_deliveries", [])

    started = SimpleNamespace(meta=SimpleNamespace(event_id="sub-suite-1"))
    monkeypatch.setattr(testrunner, "tracer", lambda: provider.get_tracer("test"))
    monkeypatch.setattr(testrunner, "record_milestone", Mock())
    monkeypatch.setattr(testrunner, "flush", Mock())
    monkeypatch.setattr(runner, "_test_suite_triggered", Mock())
    monkeypatch.setattr(runner, "test_suite_started", Mock(return_value=started))
    monkeypatch.setattr(runner, "_test_suite_started", Mock())
    monkeypatch.setattr(runner, "environment", Mock())
    execution_context = {}

    def run_tests(_workspace: Mock) -> None:
        """Capture the current span while running tests."""
        active_span = trace.get_current_span()
        execution_context["name"] = active_span.name
        execution_context["span_id"] = active_span.get_span_context().span_id

    monkeypatch.setattr(runner, "_run_and_finalize", run_tests)
    workspace = MagicMock()
    workspace.__enter__.return_value = Mock()
    monkeypatch.setattr(testrunner, "Workspace", Mock(return_value=workspace))

    assert runner.execute() == 0
    assert execution_context["name"] == "etos.runner.execute"
    assert (
        runner.trace_environment["TRACEPARENT"].split("-")[2]
        == f"{execution_context['span_id']:016x}"
    )
    assert trace.get_current_span().get_span_context().is_valid is False
    provider.shutdown()


def test_executor_passes_trace_environment_to_test_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test process inherits its environment and receives the execution trace carrier.

    :param monkeypatch: Pytest fixture for controlling the parent environment.
    :param tmp_path: Temporary test workspace directory.
    """
    trace_environment = {
        "TRACEPARENT": "00-trace-execution",
        "TRACESTATE": "vendor=value",
        "BAGGAGE": "testrun_id=run-1",
    }

    process = Mock(returncode=0)
    test_executor = executor_module.Executor.__new__(executor_module.Executor)
    test_executor.test = SimpleNamespace(execution=SimpleNamespace(checkout=[]))
    test_executor.report_path = "test_output.log"
    test_executor.logger = Mock()
    test_executor.test_regex = {}
    test_executor.trace_environment = trace_environment
    iterable_call = Mock(return_value=iter([(process, "finished")]))
    setattr(test_executor, "_build_environment_command", Mock(return_value=[]))
    setattr(test_executor, "_pre_execution", Mock())
    setattr(test_executor, "_build_test_command", Mock(return_value="test command"))
    setattr(test_executor, "_iterable_call", iterable_call)
    workspace = MagicMock()
    workspace.test_directory.return_value.__enter__.return_value = tmp_path
    monkeypatch.setenv("ETR_PARENT_VARIABLE", "inherited")

    test_executor.execute(workspace, retries=1)

    environment = iterable_call.call_args.kwargs["env"]
    assert environment["ETR_PARENT_VARIABLE"] == "inherited"
    assert all(environment[key] == value for key, value in trace_environment.items())


def test_outcome_is_bounded_and_does_not_record_free_text():
    """Custom verdict strings cannot become high-cardinality span data."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    span = provider.get_tracer("test").start_span("execution")

    set_outcome(span, "a-user-defined-verdict", "a-user-defined-conclusion")
    span.end()

    finished = exporter.get_finished_spans()[0]
    assert finished.attributes["etos.verdict"] == "unknown"
    assert finished.attributes["etos.conclusion"] == "unknown"
    assert "a-user-defined-verdict" not in repr(finished.events)


def test_record_error_keeps_exception_text_out_of_telemetry():
    """Operational errors carry only a bounded exception type."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    span = provider.get_tracer("test").start_span("startup")

    record_error(span, ValueError("secret test output and URL"))
    span.end()

    finished = exporter.get_finished_spans()[0]
    assert finished.status.status_code.name == "ERROR"
    assert finished.events[0].attributes == {"exception.type": "ValueError"}
    assert "secret test output" not in repr(finished)


def test_milestone_metrics_use_only_phase_and_outcome(monkeypatch):
    """Milestone metrics do not acquire run, test, URL, or exception dimensions."""
    counter = Mock()
    histogram = Mock()
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(tracing, "milestone_instruments", lambda: (counter, histogram))
    monkeypatch.setattr(tracing, "cluster_identity", lambda: "unassigned")

    tracing.record_milestone("execution", "successful", 1.25)

    labels = {"phase": "execution", "outcome": "successful", "etos_cluster": "unassigned"}
    counter.add.assert_called_once_with(1, labels)
    histogram.record.assert_called_once_with(1.25, labels)


@pytest.mark.parametrize("namespace", ["first", "second"])
def test_milestones_route_to_launch_cluster(monkeypatch, namespace):
    """Same-named clusters in different namespaces stay distinct."""
    counter, histogram = Mock(), Mock()
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.delenv("ETOS_NAMESPACE", raising=False)
    monkeypatch.delenv("ETOS_CLUSTER", raising=False)
    monkeypatch.setenv("BAGGAGE", f"etos_cluster={namespace}/shared,testrun_id=not-a-label")
    monkeypatch.setattr(tracing, "milestone_instruments", lambda: (counter, histogram))
    tracing.record_milestone("execution", "successful", 1.25)
    labels = {"phase": "execution", "outcome": "successful", "etos_cluster": f"{namespace}/shared"}
    counter.add.assert_called_once_with(1, labels)
    histogram.record.assert_called_once_with(1.25, labels)


def test_bare_launch_cluster_is_unassigned(monkeypatch):
    """Legacy bare baggage is not guessed into an arbitrary namespace."""
    monkeypatch.delenv("ETOS_NAMESPACE", raising=False)
    monkeypatch.delenv("ETOS_CLUSTER", raising=False)
    monkeypatch.setenv("BAGGAGE", "etos_cluster=shared")
    assert tracing.cluster_identity() == "unassigned"


@pytest.mark.parametrize("disabled", ["true", "TRUE", ""])
def test_unconfigured_or_disabled_tracing_is_noop(monkeypatch, disabled):
    """Disabled or unconfigured tracing cannot export even with an existing SDK."""
    monkeypatch.setenv("OTEL_SDK_DISABLED", disabled)
    if disabled:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    else:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    provider = Mock()
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", provider)
    configure_metrics = Mock()
    monkeypatch.setattr(tracing, "configure_metrics", configure_metrics)

    assert tracing.configure_tracing("test") is None
    with tracing.tracer().start_as_current_span("disabled") as span:
        assert not span.is_recording()
    provider.assert_not_called()
    if disabled:
        configure_metrics.assert_not_called()


@pytest.mark.parametrize(
    ("generic_protocol", "traces_protocol", "expected_exporter"),
    [("http/protobuf", "grpc", "grpc"), ("http/protobuf", None, "http")],
)
@pytest.mark.parametrize(
    "endpoint",
    ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"],
)
def test_tracing_uses_suite_runner_resources(
    monkeypatch, generic_protocol, traces_protocol, expected_exporter, endpoint
):
    """Configured tracing detects process resources and preserves service identity."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv(endpoint, "http://localhost:4317")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", generic_protocol)
    if traces_protocol:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", traces_protocol)
    else:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", raising=False)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=local")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(tracing, "configure_metrics", Mock())
    monkeypatch.setattr(tracing, "BatchSpanProcessor", Mock())
    grpc_exporter = Mock()
    http_exporter = Mock()
    grpc_exporter_class = Mock(return_value=grpc_exporter)
    http_exporter_class = Mock(return_value=http_exporter)
    monkeypatch.setattr(tracing, "OTLPSpanExporter", grpc_exporter_class)
    monkeypatch.setattr(tracing, "HttpOTLPSpanExporter", http_exporter_class)
    monkeypatch.setattr(tracing.trace, "get_tracer_provider", Mock(return_value=None))
    install = Mock()
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", install)

    resource = tracing.configure_tracing("test-version")

    assert resource.attributes["service.name"] == "etos-test-runner"
    assert resource.attributes["service.version"] == "test-version"
    assert resource.attributes["deployment.environment.name"] == "local"
    assert "process.pid" in resource.attributes
    expected_class = http_exporter_class if expected_exporter == "http" else grpc_exporter_class
    other_class = grpc_exporter_class if expected_exporter == "http" else http_exporter_class
    expected_class.assert_called_once_with()
    other_class.assert_not_called()
    install.assert_called_once()
    install.call_args.args[0].shutdown()


def test_tracer_uses_traces_specific_endpoint(monkeypatch):
    """A traces-specific endpoint enables the application tracer."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://localhost:4318")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    application_tracer = Mock()
    monkeypatch.setattr(tracing.trace, "get_tracer", Mock(return_value=application_tracer))

    assert tracing.tracer() is application_tracer


def test_metrics_configuration_is_idempotent(monkeypatch):
    """Repeated configuration preserves the existing SDK meter provider."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    provider = tracing.MeterProvider()
    monkeypatch.setattr(tracing.metrics, "get_meter_provider", lambda: provider)
    install = Mock()
    monkeypatch.setattr(tracing.metrics, "set_meter_provider", install)
    instrument = Mock()
    monkeypatch.setattr(tracing.SystemMetricsInstrumentor, "instrument", instrument)

    tracing.configure_metrics("test")

    install.assert_not_called()
    instrument.assert_not_called()
    provider.shutdown()


@pytest.mark.parametrize(
    "endpoint", ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"]
)
def test_default_runtime_metrics(monkeypatch, endpoint):
    """System and process metrics use the configured OTLP provider and service resource."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setenv(endpoint, "http://localhost:4317")
    monkeypatch.setattr(tracing.metrics, "get_meter_provider", Mock(return_value=None))
    install = Mock()
    monkeypatch.setattr(tracing.metrics, "set_meter_provider", install)
    monkeypatch.setattr(tracing, "OTLPMetricExporter", Mock())
    reader = InMemoryMetricReader()
    monkeypatch.setattr(tracing, "PeriodicExportingMetricReader", Mock(return_value=reader))

    try:
        tracing.configure_metrics("test-version")

        install.assert_called_once()
        data = reader.get_metrics_data()
        names = {
            metric.name
            for resource_metrics in data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
        }
        assert any(name.startswith("system.") for name in names)
        assert any(name.startswith("process.runtime.") for name in names)
        assert all(
            resource_metrics.resource.attributes["service.name"] == "etos-test-runner"
            and resource_metrics.resource.attributes["service.version"] == "test-version"
            for resource_metrics in data.resource_metrics
        )
    finally:
        tracing.SystemMetricsInstrumentor().uninstrument()
        if install.called:
            install.call_args.args[0].shutdown()


@pytest.mark.parametrize(
    ("generic_protocol", "metrics_protocol", "expected_exporter"),
    [
        ("http/protobuf", None, "http"),
        ("http/protobuf", "grpc", "grpc"),
    ],
)
def test_metrics_protocol_selection(
    monkeypatch, generic_protocol, metrics_protocol, expected_exporter
):
    """Metric-specific protocol overrides the generic OTLP protocol."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", generic_protocol)
    if metrics_protocol:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", metrics_protocol)
    else:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(tracing.metrics, "get_meter_provider", Mock(return_value=None))

    # pylint: disable=too-few-public-methods
    class FakeMeterProvider(tracing.MeterProvider):
        """Capture the meter provider configuration without starting exporters."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.kwargs = kwargs

    meter_provider_class = FakeMeterProvider
    monkeypatch.setattr(tracing, "MeterProvider", meter_provider_class)
    set_meter_provider = Mock()
    monkeypatch.setattr(tracing.metrics, "set_meter_provider", set_meter_provider)
    reader = Mock()
    monkeypatch.setattr(tracing, "PeriodicExportingMetricReader", Mock(return_value=reader))
    grpc_exporter = Mock()
    http_exporter = Mock()
    grpc_exporter_class = Mock(return_value=grpc_exporter)
    http_exporter_class = Mock(return_value=http_exporter)
    monkeypatch.setattr(tracing, "OTLPMetricExporter", grpc_exporter_class)
    monkeypatch.setattr(tracing, "HttpOTLPMetricExporter", http_exporter_class)
    instrumentor = Mock()
    monkeypatch.setattr(tracing, "SystemMetricsInstrumentor", Mock(return_value=instrumentor))

    tracing.configure_metrics("test-version")

    expected_class = http_exporter_class if expected_exporter == "http" else grpc_exporter_class
    expected_class.assert_called_once_with()
    (
        grpc_exporter_class if expected_exporter == "http" else http_exporter_class
    ).assert_not_called()
    meter_provider = set_meter_provider.call_args.args[0]
    assert reader is meter_provider.kwargs["metric_readers"][0]
    set_meter_provider.assert_called_once_with(meter_provider)
    instrumentor.instrument.assert_called_once_with(meter_provider=meter_provider)


@pytest.mark.parametrize("disabled", ["true", "TRUE", ""])
def test_unconfigured_or_disabled_runtime_metrics(monkeypatch, disabled):
    """Unconfigured or disabled telemetry does not start runtime instrumentation."""
    monkeypatch.setenv("OTEL_SDK_DISABLED", disabled)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
    if disabled:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://localhost:4317")
    monkeypatch.setattr(tracing.metrics, "get_meter_provider", Mock(return_value=None))
    install = Mock()
    monkeypatch.setattr(tracing.metrics, "set_meter_provider", install)
    instrument = Mock()
    monkeypatch.setattr(tracing.SystemMetricsInstrumentor, "instrument", instrument)

    tracing.configure_metrics("test-version")

    install.assert_not_called()
    instrument.assert_not_called()


def test_run_tests_does_not_emit_execution_events(monkeypatch):
    """Per-test execution retains results and logging without emitting span events."""
    runner = testrunner.TestRunner.__new__(testrunner.TestRunner)
    runner.suite = SimpleNamespace(testExecutions=[object()])
    runner.iut = Mock()
    runner.etos = Mock()
    runner.logger = Mock()
    runner.trace_environment = {"TRACEPARENT": "00-trace-execution"}
    span = Mock()
    monkeypatch.setattr(runner, "_active_execution_span", span, raising=False)
    executor = Mock(result=True, returncode=0, results={})
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=executor)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(testrunner, "Executor", factory)
    workspace = Mock()

    assert runner.run_tests(workspace) == (True, [0])
    executor.execute.assert_called_once_with(workspace)
    assert factory.call_args.kwargs["trace_environment"] == runner.trace_environment
    assert runner.logger.info.call_count == 2
    span.add_event.assert_not_called()
