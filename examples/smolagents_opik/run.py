"""Run a Smolagents task and export its OpenTelemetry trace to Opik."""

from __future__ import annotations

import argparse

from examples.smolagents_opik.config import require_configuration


DEFAULT_TASK = "Find the population of Paris and state the source in one sentence."


def configure_observability():
    """Configure the OTLP exporter before creating an agent.

    OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS are intentionally
    read by the standard exporter, rather than copied into source code.
    """
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from openinference.instrumentation.smolagents import SmolagentsInstrumentor

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    SmolagentsInstrumentor().instrument(tracer_provider=provider)
    return provider


def build_agent():
    from smolagents import CodeAgent, OpenAIServerModel, WebSearchTool

    return CodeAgent(
        tools=[WebSearchTool()],
        model=OpenAIServerModel(model_id="gpt-4o-mini"),
        stream_outputs=True,
        max_steps=6,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK)
    args = parser.parse_args()

    require_configuration()
    provider = configure_observability()
    try:
        print(build_agent().run(args.task))
    finally:
        # BatchSpanProcessor is asynchronous; flush before this short-lived process exits.
        provider.force_flush()
        provider.shutdown()


if __name__ == "__main__":
    main()
