"""Real DeepSeek execution with a controlled tool failure and local Opik export."""
import os
import argparse

from dotenv import dotenv_values

from examples.smolagents_opik.run import configure_observability


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fail-once', action='store_true')
    parser.add_argument('--allow-json', action='store_true', help='Allow JSON parsing for recovery comparison')
    args = parser.parse_args()
    config = {**dotenv_values('.env'), **os.environ}
    key = config.get('ANTHROPIC_API_KEY') or config.get('ANTHROPIC_AUTH_TOKEN')
    if not key:
        raise RuntimeError('Missing model credentials in .env')
    base = config.get('ANTHROPIC_BASE_URL', '')
    if base.rstrip('/') != 'https://api.deepseek.com/anthropic':
        raise RuntimeError('This local example requires the configured DeepSeek endpoint')
    os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = 'http://localhost:5173/api/v1/private/otel'
    os.environ['OTEL_EXPORTER_OTLP_HEADERS'] = 'Comet-Workspace=default,projectName=smolagents-observability-demo'
    # Prevent unrelated shell trace settings overriding the local destination.
    os.environ.pop('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', None)
    os.environ.pop('OTEL_EXPORTER_OTLP_TRACES_HEADERS', None)
    from smolagents import CodeAgent, OpenAIServerModel, tool

    calls = 0

    @tool
    def lookup_sales() -> str:
        """Return synthetic sales totals for the observability demonstration."""
        nonlocal calls
        calls += 1
        if args.fail_once and calls == 1:
            raise RuntimeError('Injected transient failure; retry lookup_sales once')
        return '{"january": 120, "february": 180}'

    provider = configure_observability()
    try:
        model = OpenAIServerModel(model_id='deepseek-chat', api_base='https://api.deepseek.com',
                                 api_key=key, max_tokens=2048, timeout=90)
        agent = CodeAgent(tools=[lookup_sales], model=model, max_steps=4,
                          additional_authorized_imports=['json'] if args.allow_json else [])
        result = agent.run('Call lookup_sales to obtain the sales numbers, then calculate the total '
                           'and percentage growth from January to February. Retry once if the tool fails. '
                           'Return a concise answer. Scenario: ' + ('transient-failure' if args.fail_once else 'normal')
                           + ('-allow-json' if args.allow_json else ''))
        print({'result': str(result), 'tool_calls': calls, 'scenario': args.fail_once})
    finally:
        provider.force_flush()
        provider.shutdown()


if __name__ == '__main__':
    main()
