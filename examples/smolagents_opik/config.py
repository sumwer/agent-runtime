"""Environment validation kept dependency-free so it can be tested locally."""

from __future__ import annotations

import os
from collections.abc import Mapping


REQUIRED_ENVIRONMENT = (
    "OPENAI_API_KEY",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
)


def missing_configuration(environment: Mapping[str, str] | None = None) -> list[str]:
    """Return required settings that are absent or blank, without reading their values."""
    source = os.environ if environment is None else environment
    return [name for name in REQUIRED_ENVIRONMENT if not source.get(name, "").strip()]


def require_configuration(environment: Mapping[str, str] | None = None) -> None:
    missing = missing_configuration(environment)
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
