#!/usr/bin/env python3
"""本地 Opik REST 桩：离线开发/验收多轮 agent 指标用，不写入真实 Opik。

只实现适配层用到的端点，分页与字段形如 Opik：
  /v1/private/experiments                                 实验列表
  /v1/private/datasets/{id}/items/experiments/items       实验条目（trace × 评分）
  /v1/private/traces/threads                              多轮会话
  /v1/private/spans                                       单步决策（LLM / 工具）

    .venv-runtime/bin/python scripts/dev_opik_stub.py --port 8770
    OPIK_API_BASE=http://127.0.0.1:8770/api OPIK_PROJECT_NAME=agent-metrics-demo ...
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EXPERIMENTS = [{
    'id': 'exp-agent-1', 'name': 'agent-multiturn-demo', 'dataset_id': 'ds-agent',
    'dataset_name': 'agent-tasks', 'trace_count': 4, 'dataset_item_count': 4,
    'feedback_scores': [{'name': 'task_success', 'value': 0.25}],
    'created_at': '2026-09-10T09:00:00Z',
}]

DATASET_ITEMS = [{
    'id': f'di-{i}', 'data': {'input': {'question': f'任务 {i}'}, 'expected_output': {'answer': 'ok'},
                              'metadata': {'category': 'multi_turn', 'seed_id': f'task_{i}'}},
    'experiment_items': [{'id': f'ei-{i}', 'experiment_id': 'exp-agent-1', 'dataset_item_id': f'di-{i}',
                          'trace_id': f'tr-{i}', 'input': {'item': {'input': {'question': f'任务 {i}'}}},
                          'output': {'output': f'tr-{i}'},
                          'feedback_scores': [{'name': 'task_success', 'value': 0.25 if i == 3 else 1.0}]}],
} for i in range(4)]

TOOL_NAMES = ['search', 'calculator', 'db_query']
THREADS = []
SPANS = []

for session in range(4):
    trace_id = f'tr-{session}'
    turns = [3, 5, 6, 9][session]
    finished = session != 3
    THREADS.append({
        'id': f'th-{session}', 'number_of_messages': turns,
        'duration': [4.0, 9.5, 12.0, 41.0][session],
        'status': 'finished' if finished else 'unfinished',
        'usage': {'total_tokens': 500 + 300 * turns}, 'total_estimated_cost': 0.004 * turns,
        'feedback_scores': [{'name': 'task_success', 'value': 0.25 if session == 3 else 1.0}],
        'created_at': f'2026-09-10T09:0{session}:00Z',
    })
    for step in range(turns):
        is_tool = step % 2 == 0
        name = 'plan' if step == 0 else (TOOL_NAMES[(step // 2) % 3] if is_tool else 'answer')
        error = None
        if session == 1 and step == 2:
            error = {'exception_type': 'TimeoutError', 'message': 'tool timeout'}
        if session == 3 and 4 <= step <= 6:
            name, is_tool = 'search', True  # 连续重复 → 供循环检测
        SPANS.append({
            'id': f'sp-{session}-{step}', 'trace_id': trace_id,
            'parent_span_id': f'sp-{session}-{step - 1}' if step else None,
            'name': name, 'type': 'llm' if not is_tool else 'tool',
            'model': 'deepseek-chat' if not is_tool else None, 'provider': 'deepseek' if not is_tool else None,
            'usage': ({} if is_tool else {'prompt_tokens': 100 + step * 20,
                                          'completion_tokens': 30 + step * 5,
                                          'total_tokens': 130 + step * 25}),
            'duration': round(0.4 + step * 0.15, 3), 'ttft': 0.2 if not is_tool else None,
            'total_estimated_cost': None if is_tool else 0.0007, 'error_info': error,
            'start_time': f'2026-09-10T09:0{session}:{step:02d}Z',
        })


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _page(self, rows, query):
        page = int(parse_qs(query).get('page', ['1'])[0])
        size = int(parse_qs(query).get('size', ['100'])[0])
        start = (page - 1) * size
        return {'content': rows[start:start + size], 'page': page, 'size': size, 'total': len(rows)}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/v1/private/experiments':
            self._send(self._page(EXPERIMENTS, parsed.query))
        elif parsed.path.endswith('/items/experiments/items'):
            self._send(self._page(DATASET_ITEMS, parsed.query))
        elif parsed.path == '/api/v1/private/traces/threads':
            self._send(self._page(THREADS, parsed.query))
        elif parsed.path == '/api/v1/private/spans':
            trace_id = parse_qs(parsed.query).get('trace_id', [None])[0]
            rows = [s for s in SPANS if trace_id is None or s['trace_id'] == trace_id]
            self._send(self._page(rows, parsed.query))
        else:
            self.send_error(404)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    print(f'Opik stub on http://127.0.0.1:{args.port}/api '
          f'({len(THREADS)} threads, {len(SPANS)} spans)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
