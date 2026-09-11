"""Read the demo project's persisted traces and spans from local Opik."""
import json
import urllib.parse
import urllib.request


PROJECT = 'smolagents-observability-demo'


def get(path, **params):
    query = urllib.parse.urlencode({'project_name': PROJECT, 'size': 100, **params})
    request = urllib.request.Request('http://localhost:5173/api/v1/private/' + path + '?' + query,
                                     headers={'Comet-Workspace': 'default'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def main():
    traces = get('traces')
    if not traces.get('content'):
        raise RuntimeError('No persisted traces found')
    for trace in traces['content']:
        spans = get('spans', trace_id=trace['id'])
        print(json.dumps({
            'trace': {k: trace.get(k) for k in ('id', 'name', 'start_time', 'end_time', 'duration',
                                              'input', 'output', 'usage', 'error_info', 'total_estimated_cost')},
            'span_count': spans.get('total'),
            'spans': [{k: span.get(k) for k in ('id', 'parent_span_id', 'name', 'type', 'model',
                                               'duration', 'usage', 'error_info', 'total_estimated_cost')}
                      for span in spans.get('content', [])],
        }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
