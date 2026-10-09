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

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from opentelemetry import baggage, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from etos_test_runner.lib import tracing, testrunner
from etos_test_runner.lib.tracing import extract_launch_context, record_error, set_outcome


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


def test_tracing_uses_suite_runner_resources(monkeypatch):
    """Configured tracing detects process resources and preserves service identity."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=local")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(tracing, "configure_metrics", Mock())
    monkeypatch.setattr(tracing, "BatchSpanProcessor", Mock())
    monkeypatch.setattr(tracing, "OTLPSpanExporter", Mock())
    monkeypatch.setattr(tracing.trace, "get_tracer_provider", Mock(return_value=None))
    install = Mock()
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", install)

    resource = tracing.configure_tracing("test-version")

    assert resource.attributes["service.name"] == "etos-test-runner"
    assert resource.attributes["service.version"] == "test-version"
    assert resource.attributes["deployment.environment.name"] == "local"
    assert "process.pid" in resource.attributes
    install.assert_called_once()
    install.call_args.args[0].shutdown()


def test_metrics_configuration_is_idempotent(monkeypatch):
    """Repeated configuration preserves the existing SDK meter provider."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    provider = tracing.MeterProvider()
    monkeypatch.setattr(tracing.metrics, "get_meter_provider", lambda: provider)
    install = Mock()
    monkeypatch.setattr(tracing.metrics, "set_meter_provider", install)

    tracing.configure_metrics("test")

    install.assert_not_called()
    provider.shutdown()


def test_run_tests_does_not_emit_execution_events(monkeypatch):
    """Per-test execution retains results and logging without emitting span events."""
    runner = testrunner.TestRunner.__new__(testrunner.TestRunner)
    runner.suite = SimpleNamespace(testExecutions=[object()])
    runner.iut = Mock()
    runner.etos = Mock()
    runner.logger = Mock()
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
    assert runner.logger.info.call_count == 2
    span.add_event.assert_not_called()
