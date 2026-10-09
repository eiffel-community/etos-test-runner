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
"""Bounded OpenTelemetry tracing for the test runner."""

import logging
import os
from functools import lru_cache
from typing import Mapping, Optional

from opentelemetry import context as otel_context
from opentelemetry import baggage, metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import (
    SERVICE_NAME,
    SERVICE_VERSION,
    OTELResourceDetector,
    ProcessResourceDetector,
    Resource,
    get_aggregated_resources,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_LOGGER = logging.getLogger(__name__)
TRACER_NAME = "etos-test-runner"
_PROPAGATOR = CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])


def extract_launch_context(environ: Optional[Mapping[str, str]] = None):
    """Extract W3C trace context from the runner's process environment.

    The provider-to-runner handoff uses uppercase environment names.  Values are
    copied into a W3C carrier without logging or recording the untrusted input.
    """
    environ = os.environ if environ is None else environ
    normalized = {}
    for key in ("traceparent", "tracestate", "baggage"):
        value = environ.get(key.upper()) or environ.get(key)
        if value:
            normalized[key] = value
    return _PROPAGATOR.extract(normalized, context=otel_context.Context())


def cluster_identity() -> str:
    """Use explicit ownership or propagated qualified launch baggage."""
    namespace = os.getenv("ETOS_NAMESPACE", "").strip()
    cluster = os.getenv("ETOS_CLUSTER", "").strip()
    if namespace and cluster and "/" not in namespace and "/" not in cluster:
        return f"{namespace}/{cluster}"
    identity = baggage.get_baggage("etos_cluster", extract_launch_context())
    if isinstance(identity, str) and len(identity.split("/")) == 2 and all(identity.split("/")):
        return identity
    return "unassigned"


def configure_tracing(version: str) -> Optional[Resource]:
    """Configure OTLP with suite-runner resource detectors and return its resource."""
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        _LOGGER.info("OpenTelemetry disabled by OTEL_SDK_DISABLED.")
        return None
    configure_metrics(version)
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        _LOGGER.info("OpenTelemetry not enabled. OTEL_EXPORTER_OTLP_ENDPOINT not set.")
        return None
    resource = get_aggregated_resources([OTELResourceDetector(), ProcessResourceDetector()]).merge(
        Resource.create({SERVICE_NAME: TRACER_NAME, SERVICE_VERSION: version})
    )
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
    _LOGGER.info("Using OpenTelemetry collector: %s", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    return resource


def configure_metrics(version: str) -> None:
    """Configure OTLP metrics without adding a local metrics endpoint."""
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return
    if isinstance(metrics.get_meter_provider(), MeterProvider):
        return
    if not (
        os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    ):
        return
    provider = MeterProvider(
        resource=Resource.create({SERVICE_NAME: TRACER_NAME, SERVICE_VERSION: version}),
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(),
                export_interval_millis=60_000,
                export_timeout_millis=1_000,
            )
        ],
    )
    metrics.set_meter_provider(provider)


@lru_cache(maxsize=1)
def milestone_instruments():
    """Create reusable instruments through the OpenTelemetry meter API."""
    meter = metrics.get_meter(TRACER_NAME)
    milestones = meter.create_counter(
        "etos.runner.milestones",
        description="Bounded test-runner lifecycle milestones.",
        unit="1",
    )
    phase_duration = meter.create_histogram(
        "etos.runner.phase.duration",
        description="Bounded test-runner lifecycle phase duration.",
        unit="s",
    )
    return milestones, phase_duration


def tracer():
    """Return the application tracer."""
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true" or not os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    ):
        return trace.NoOpTracerProvider().get_tracer(TRACER_NAME)
    return trace.get_tracer(TRACER_NAME)


def record_error(span: Span, exception: Exception) -> None:
    """Record a bounded operational error without copying exception text."""
    span.add_event("operation.error", {"exception.type": type(exception).__name__})
    span.set_status(Status(StatusCode.ERROR, type(exception).__name__))


def set_outcome(span: Span, verdict: str, conclusion: str) -> None:
    """Attach controlled verdict and conclusion values."""
    allowed_verdicts = {"passed", "failed", "inconclusive", "not_run", "unknown"}
    allowed_conclusions = {
        "successful",
        "failed",
        "completed",
        "infrastructure_failure",
        "execution_timeout",
        "observation_timeout",
        "cancelled",
        "recovered",
        "partial_cleanup",
        "unknown",
    }
    bounded_verdict = verdict.lower() if verdict.lower() in allowed_verdicts else "unknown"
    bounded_conclusion = (
        conclusion.lower() if conclusion.lower() in allowed_conclusions else "unknown"
    )
    span.set_attribute("etos.verdict", bounded_verdict)
    span.set_attribute("etos.conclusion", bounded_conclusion)
    span.add_event(
        "verdict.concluded",
        {"etos.verdict": bounded_verdict, "etos.conclusion": bounded_conclusion},
    )


def record_milestone(phase: str, outcome: str, duration_seconds: Optional[float] = None) -> None:
    """Record a bounded lifecycle metric with no run-specific dimensions."""
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return
    milestones, phase_duration = milestone_instruments()
    attributes = {"phase": phase, "outcome": outcome, "etos_cluster": cluster_identity()}
    milestones.add(1, attributes)
    if duration_seconds is not None:
        phase_duration.record(duration_seconds, attributes)


def flush() -> None:
    """Best-effort flush for short-lived runner processes."""
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if force_flush is not None:
        try:
            force_flush()
        except Exception:  # pylint:disable=broad-except
            _LOGGER.exception("Unable to flush OpenTelemetry spans.")
    metric_provider = metrics.get_meter_provider()
    metric_flush = getattr(metric_provider, "force_flush", None)
    if metric_flush is not None:
        try:
            metric_flush(timeout_millis=1_000)
        except Exception:  # pylint:disable=broad-except
            _LOGGER.exception("Unable to flush OpenTelemetry metrics.")
