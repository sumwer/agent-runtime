import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from opik_adapter import client, mapping
from opik_adapter import server as adapter

ROOT = Path(__file__).resolve().parents[1]

EXPERIMENT = {
    'id': 'exp-1',
    'name': 'safety-baseline',
    'dataset_id': 'ds-1',
    'dataset_name': 'minor-safety',
    'trace_count': 200,
    'dataset_item_count': 200,
    'feedback_scores': [{'name': 'accuracy', 'value': 0.62}],
    'created_at': '2026-09-01T10:00:00Z',
}

ITEM_PAGE = {
    'content': [
        {'id': 'di-1',
         'data': {'input': 'q1', 'expected_output': 'a1', 'metadata': {'category': 'violence'}},
         'experiment_items': [{'id': 'ei-1', 'experiment_id': 'exp-1', 'dataset_item_id': 'di-1',
                               'trace_id': 'tr-1', 'input': 'q1', 'output': 'bad',
                               'feedback_scores': [{'name': 'accuracy', 'value': 0.1},
                                                   {'name': 'toxicity', 'value': 0.9}]}]},
        {'id': 'di-2',
         'data': {'input': 'q2', 'expected_output': 'a2', 'metadata': {'category': 'self_harm'}},
         'experiment_items': [{'id': 'ei-2', 'experiment_id': 'exp-1', 'dataset_item_id': 'di-2',
                               'trace_id': 'tr-2', 'input': 'q2', 'output': 'ok',
                               'feedback_scores': [{'name': 'accuracy', 'value': 0.8}]}]},
    ],
    'page': 1,
    'size': 100,
    'total': 2,
}

DATASET = {'id': 'ds-1', 'name': 'minor-safety', 'dataset_items_count': 2,
           'experiment_count': 1, 'latest_version': {'version_name': 'v1', 'tags': ['eval']}}

DATASET_PAGE = {'content': [
    {'id': 'di-1', 'dataset_item_id': 'di-1', 'dataset_id': 'ds-1', 'source': 'sdk',
     'data': {'input': {'question': 'q1'}, 'expected_output': {'answer': 'a1'},
              'metadata': {'category': 'violence'}}, 'tags': ['safety']},
    {'id': 'di-2', 'dataset_item_id': 'di-2', 'dataset_id': 'ds-1', 'source': 'sdk',
     'data': {'input': {'question': 'q2'}, 'expected_output': {'answer': 'a2'},
              'metadata': {'category': 'self_harm'}}, 'tags': []},
], 'total': 2}


THREADS = {
    'content': [
        {'id': 'th-1', 'number_of_messages': 6, 'duration': 12.5, 'status': 'finished',
         'usage': {'total_tokens': 1200}, 'total_estimated_cost': 0.01,
         'feedback_scores': [{'name': 'task_success', 'value': 1.0}],
         'created_at': '2026-09-10T10:00:00Z'},
        {'id': 'th-2', 'number_of_messages': 2, 'duration': 3.0, 'status': 'unfinished',
         'usage': {'total_tokens': 300}, 'total_estimated_cost': 0.002,
         'feedback_scores': [], 'created_at': '2026-09-10T10:05:00Z'},
    ],
    'total': 2,
}

SPANS = {
    'content': [
        {'id': 'sp-1', 'trace_id': 'tr-1', 'parent_span_id': None, 'name': 'plan', 'type': 'llm',
         'model': 'gpt-x', 'provider': 'openai', 'duration': 1.2, 'ttft': 0.3,
         'total_estimated_cost': 0.002, 'error_info': None, 'start_time': '2026-09-10T10:00:01Z',
         'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}},
        {'id': 'sp-2', 'trace_id': 'tr-1', 'parent_span_id': 'sp-1', 'name': 'search', 'type': 'tool',
         'model': None, 'provider': None, 'duration': 0.4, 'ttft': None,
         'total_estimated_cost': None, 'start_time': '2026-09-10T10:00:02Z',
         'error_info': {'exception_type': 'TimeoutError', 'message': 'tool timeout'},
         'usage': {}},
    ],
    'total': 2,
}


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    # 桩数据没有 OPIK_SCORE_NAME 指向的指标，避免外部环境污染用例。
    monkeypatch.delenv('OPIK_SCORE_NAME', raising=False)
    adapter.clear_cache()
    yield
    adapter.clear_cache()


@pytest.fixture
def fake_opik(monkeypatch):
    calls = []

    async def find_experiment(experiment_id, transport=None):
        calls.append(('find', experiment_id))
        return EXPERIMENT

    async def experiment_item_page(dataset_id, experiment_id, page, size, transport=None):
        calls.append(('page', dataset_id, experiment_id, page, size))
        return (ITEM_PAGE['content'], ITEM_PAGE['total']) if page == 1 else ([], ITEM_PAGE['total'])

    async def find_dataset(dataset_id, transport=None):
        calls.append(('dataset', dataset_id))
        return DATASET

    async def dataset_item_page(dataset_id, page, size, transport=None):
        calls.append(('dataset_page', dataset_id, page, size))
        return (DATASET_PAGE['content'], DATASET_PAGE['total']) if page == 1 else ([], DATASET_PAGE['total'])

    monkeypatch.setattr(client, 'find_experiment', find_experiment)
    monkeypatch.setattr(client, 'experiment_item_page', experiment_item_page)
    monkeypatch.setattr(client, 'find_dataset', find_dataset)
    monkeypatch.setattr(client, 'dataset_item_page', dataset_item_page)
    return calls


def test_item_row_picks_preferred_score(monkeypatch):
    monkeypatch.setenv('OPIK_SCORE_NAME', 'accuracy')
    dataset_item, item = ITEM_PAGE['content'][0], ITEM_PAGE['content'][0]['experiment_items'][0]
    row = mapping.item_row(dataset_item, item)
    assert row['score'] == 0.1 and row['score_name'] == 'accuracy'
    assert row['scores'] == {'accuracy': 0.1, 'toxicity': 0.9}
    assert row['trace_id'] == 'tr-1' and row['metadata'] == {'category': 'violence'}
    assert mapping.keep(row, 0.0, 0.5) and not mapping.keep(row, 0.5, 1.0)
    assert not mapping.keep({'score': None}, 0.0, 1.0)


def _rows_with_scores(*score_sets):
    rows = []
    for index, scores in enumerate(score_sets):
        item = {'id': f'ei-{index}', 'trace_id': f'tr-{index}',
                'feedback_scores': [{'name': name, 'value': value} for name, value in scores.items()]}
        rows.append(mapping.item_row({'data': {}}, item))
    return rows


def test_primary_score_is_consistent_across_items():
    rows = _rows_with_scores({'safety': 0.1, 'quality': 0.5}, {'quality': 0.9},
                             {'safety': 0.3, 'quality': 0.2})
    assert mapping.primary_score_name(rows) == 'quality'
    mapping.apply_primary_score(rows, 'quality')
    assert [row['score'] for row in rows] == [0.5, 0.9, 0.2]
    assert {row['score_name'] for row in rows} == {'quality'}


def test_missing_primary_score_becomes_none():
    rows = _rows_with_scores({'safety': 0.4}, {'quality': 0.7}, {'safety': 0.2})
    mapping.apply_primary_score(rows, 'safety')
    assert [row['score'] for row in rows] == [0.4, None, 0.2]
    assert not mapping.keep(rows[1], 0.0, 1.0)


async def test_configured_score_name_must_exist(fake_opik, monkeypatch):
    monkeypatch.setenv('OPIK_SCORE_NAME', 'missing-metric')
    with pytest.raises(client.OpikError, match='missing-metric'):
        await adapter._get_traces('exp-1')


def test_paginate_bounds():
    with pytest.raises(ValueError):
        mapping.paginate([], 1, 0)
    with pytest.raises(ValueError):
        mapping.paginate([], 1, 101)
    assert mapping.paginate([{'a': 1}, {'a': 2}], 2, 1)['items'] == [{'a': 2}]


async def test_experiment_summary_averages():
    summary = mapping.experiment_summary(EXPERIMENT)
    assert summary['id'] == 'exp-1' and summary['avg_score'] == 0.62
    assert summary['dataset_name'] == 'minor-safety' and summary['item_count'] == 200


async def test_get_traces_pages_and_filters(fake_opik):
    page = await adapter._get_traces('exp-1', page=2, page_size=1)
    assert page['total'] == 2 and [row['id'] for row in page['items']] == ['ei-2']
    low = await adapter._get_traces('exp-1', max_score=0.5)
    assert [row['id'] for row in low['items']] == ['ei-1'] and low['total'] == 1


async def test_get_scores_shape(fake_opik):
    page = await adapter._get_scores('exp-1', page=1, page_size=50)
    assert page['total'] == 2
    assert {row['trace_id'] for row in page['items']} == {'tr-1', 'tr-2'}
    assert all(isinstance(row['score'], float) for row in page['items'])
    assert ('page', 'ds-1', 'exp-1', 1, 100) in fake_opik


async def test_list_experiments(monkeypatch):
    async def list_experiments(page=1, size=100, transport=None):
        return ([EXPERIMENT], 1) if page == 1 else ([], 1)

    monkeypatch.setattr(client, 'list_experiments', list_experiments)
    experiments = await adapter._list_experiments()
    assert experiments[0]['name'] == 'safety-baseline'


async def test_get_dataset_items_preserves_pre_evaluation_fields(fake_opik):
    page = await adapter._get_dataset_items('minor-safety', page=1, page_size=1)
    assert page['total'] == 2
    row = page['items'][0]
    assert row['input'] == {'question': 'q1'}
    assert row['expected_output'] == {'answer': 'a1'}
    assert row['metadata']['category'] == 'violence'
    assert ('dataset_page', 'ds-1', 1, 100) in fake_opik


async def test_list_datasets(monkeypatch):
    async def list_datasets(page=1, size=100, transport=None):
        return ([DATASET], 1) if page == 1 else ([], 1)
    monkeypatch.setattr(client, 'list_datasets', list_datasets)
    datasets = await adapter._list_datasets()
    assert datasets == [{'id': 'ds-1', 'name': 'minor-safety', 'item_count': 2,
                         'experiment_count': 1, 'version': 'v1', 'tags': ['eval'], 'created_at': None}]


class _FakeOpikHandler(BaseHTTPRequestHandler):
    """最小 Opik REST 桩：只回答实验列表和实验条目分页。"""

    def log_message(self, *args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        page = int(parse_qs(parsed.query).get('page', ['1'])[0])
        if parsed.path == '/api/v1/private/experiments':
            self._send({'content': [EXPERIMENT], 'total': 1} if page == 1 else {'content': [], 'total': 1})
        elif parsed.path.endswith('/items/experiments/items'):
            self._send(ITEM_PAGE if page == 1 else {'content': [], 'total': ITEM_PAGE['total']})
        elif parsed.path == '/api/v1/private/datasets':
            self._send({'content': [DATASET], 'total': 1} if page == 1 else {'content': [], 'total': 1})
        elif parsed.path.endswith('/items'):
            self._send(DATASET_PAGE if page == 1 else {'content': [], 'total': DATASET_PAGE['total']})
        elif parsed.path == '/api/v1/private/traces/threads':
            self._send(THREADS if page == 1 else {'content': [], 'total': THREADS['total']})
        elif parsed.path == '/api/v1/private/spans':
            self._send(SPANS if page == 1 else {'content': [], 'total': SPANS['total']})
        else:
            self.send_error(404)


async def test_export_against_fake_opik(tmp_path, monkeypatch):
    from app.tools.export_data import export_data_impl

    http = ThreadingHTTPServer(('127.0.0.1', 0), _FakeOpikHandler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    monkeypatch.setenv('OPIK_API_BASE', f'http://127.0.0.1:{http.server_address[1]}/api')
    cfg = {'transport': 'stdio', 'command': sys.executable, 'args': ['-m', 'opik_adapter.server'],
           'cwd': str(ROOT), 'env': dict(os.environ)}
    try:
        traces = await export_data_impl(cfg, 'traces', 'exp-1', tmp_path, max_rows=10)
        scores = await export_data_impl(cfg, 'scores', 'exp-1', tmp_path, filters={'max_score': 0.5})
        threads = await export_data_impl(cfg, 'threads', '', tmp_path)
        spans = await export_data_impl(cfg, 'spans', '', tmp_path)
        items = await export_data_impl(cfg, 'dataset_items', '', tmp_path, dataset_id='ds-1')
    finally:
        http.shutdown()
    assert traces['written'] == 2 and not traces['truncated']
    rows = [json.loads(line) for line in (tmp_path / 'traces.jsonl').read_text().splitlines()]
    assert {row['trace_id'] for row in rows} == {'tr-1', 'tr-2'}
    assert scores['written'] == 1 and set(scores['schema_hint']) == {'trace_id', 'score', 'name'}
    assert threads['written'] == 2 and spans['written'] == 2
    assert items['written'] == 2
    thread_rows = [json.loads(line) for line in (tmp_path / 'threads.jsonl').read_text().splitlines()]
    assert thread_rows[0]['number_of_messages'] == 6
    span_rows = [json.loads(line) for line in (tmp_path / 'spans.jsonl').read_text().splitlines()]
    assert {row['type'] for row in span_rows} == {'llm', 'tool'}


def test_thread_and_span_rows():
    thread = mapping.thread_row(THREADS['content'][0])
    assert thread['number_of_messages'] == 6 and thread['status'] == 'finished'
    assert thread['scores'] == {'task_success': 1.0}
    span = mapping.span_row(SPANS['content'][0])
    assert span['type'] == 'llm' and span['total_tokens'] == 120 and span['ttft'] == 0.3
    failed = mapping.span_row(SPANS['content'][1])
    assert failed['error'] == 'TimeoutError' and failed['prompt_tokens'] is None


async def test_get_threads_and_spans(monkeypatch):
    async def list_threads(page=1, size=100, transport=None):
        return ([mapping.thread_row(item) for item in THREADS['content']], 2) if page == 1 else ([], 2)

    async def list_spans(page=1, size=100, trace_id=None, transport=None):
        return ([mapping.span_row(item) for item in SPANS['content']], 2) if page == 1 else ([], 2)

    monkeypatch.setattr(client, 'list_threads', list_threads)
    monkeypatch.setattr(client, 'list_spans', list_spans)
    threads = await adapter._get_threads(page=1, page_size=1)
    assert threads['total'] == 2 and [t['id'] for t in threads['items']] == ['th-1']
    spans = await adapter._get_spans(page=2, page_size=1)
    assert spans['total'] == 2 and [s['id'] for s in spans['items']] == ['sp-2']
    assert await adapter._get_spans(page=1, page_size=5) is not None


async def test_export_rejects_bad_source_combinations(tmp_path):
    from app.tools.export_data import export_data_impl

    with pytest.raises(ValueError, match='experiment_id is required'):
        await export_data_impl({}, 'traces', '', tmp_path)
    with pytest.raises(ValueError, match='dataset_id is required'):
        await export_data_impl({}, 'dataset_items', '', tmp_path)
    with pytest.raises(ValueError, match='only apply to traces and scores'):
        await export_data_impl({}, 'threads', '', tmp_path, filters={'max_score': 0.5})
    with pytest.raises(ValueError, match='source must be one of'):
        await export_data_impl({}, 'unknown', 'exp-1', tmp_path)


async def test_real_opik_contract():
    """可选联调：RUN_REAL_OPIK=1 且 Opik 在跑时验证真实后端。

    需要 OPIK_PROJECT_NAME 指向有实验的项目；未设置时跑 default。
    """
    if os.getenv('RUN_REAL_OPIK') != '1':
        pytest.skip('set RUN_REAL_OPIK=1 with a running Opik')
    experiments = await adapter._list_experiments()
    assert experiments, 'no experiments found; check OPIK_PROJECT_NAME'
    rows = (await adapter._get_traces(experiments[0]['id'], 1, 10))['items']
    assert rows and all(isinstance(row['score'], float) for row in rows)
    assert len({row['score_name'] for row in rows}) == 1


async def test_stdio_schema_matches_exporter():
    from app.tools.mcp import open_session

    cfg = {'transport': 'stdio', 'command': sys.executable, 'args': ['-m', 'opik_adapter.server'],
           'cwd': str(ROOT), 'env': dict(os.environ)}
    async with open_session(cfg) as session:
        definitions = {tool.name: tool for tool in (await session.list_tools()).tools}
    assert {'list_experiments', 'list_datasets', 'get_dataset_items', 'get_traces', 'get_scores', 'get_threads', 'get_spans'} <= definitions.keys()
    for name in {'get_dataset_items', 'get_traces', 'get_scores', 'get_threads', 'get_spans'}:
        properties = definitions[name].inputSchema.get('properties', {})
        assert {'page', 'page_size'} <= properties.keys()
