import pytest

from examples.smolagents_opik.config import missing_configuration, require_configuration


def test_configuration_reports_only_missing_names():
    environment = {
        "OPENAI_API_KEY": "key",
        "OTEL_EXPORTER_OTLP_ENDPOINT": " https://opik.example/otel ",
        "OTEL_EXPORTER_OTLP_HEADERS": "",
    }
    assert missing_configuration(environment) == ["OTEL_EXPORTER_OTLP_HEADERS"]


def test_configuration_never_includes_credential_values_in_error():
    with pytest.raises(RuntimeError) as error:
        require_configuration({"OPENAI_API_KEY": "secret-value"})
    assert "secret-value" not in str(error.value)
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in str(error.value)
