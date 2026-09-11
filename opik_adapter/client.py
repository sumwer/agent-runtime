"""Opik REST 客户端（httpx）。

只调用 opik-mcp 自身使用的 /v1/private 端点，不引入 opik SDK：
- GET /v1/private/experiments：实验列表，Spring 分页 {content, total}
- GET /v1/private/datasets/{dataset_id}/items/experiments/items：
  数据集条目及其实验条目（trace_id、input/output、feedback_scores）

失败一律抛错，不返回空数据，避免 Agent 在无数据上编造结论。
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from . import config

PAGE_SIZE = 100


class OpikError(RuntimeError):
    """Opik REST 返回错误或响应结构异常。"""


def _headers() -> dict[str, str]:
    headers = {'Accept': 'application/json'}
    if config.api_key():
        headers['Authorization'] = config.api_key()
    if config.workspace():
        headers['Comet-Workspace'] = config.workspace()
    return headers


def _clean(params: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (params or {}).items() if v not in (None, '')}


async def get_json(path: str, params: dict[str, Any] | None = None, transport=None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=config.timeout_seconds(), transport=transport) as http:
        response = await http.get(f'{config.api_base()}/{path.lstrip("/")}',
                                  params=_clean(params), headers=_headers())
    if response.status_code >= 400:
        raise OpikError(f'Opik API {path} returned {response.status_code}: {response.text[:300]}')
    return response.json()


def _content(data: dict[str, Any], path: str) -> tuple[list[dict[str, Any]], int]:
    content = data.get('content')
    if not isinstance(content, list):
        raise OpikError(f'Opik API {path} response has no content list')
    return content, int(data.get('total') or 0)


async def list_experiments(page: int = 1, size: int = PAGE_SIZE,
                           transport=None) -> tuple[list[dict[str, Any]], int]:
    data = await get_json('/v1/private/experiments',
                          {'project_name': config.project_name(), 'page': page, 'size': size},
                          transport=transport)
    return _content(data, '/v1/private/experiments')


async def find_experiment(experiment_id: str, transport=None) -> dict[str, Any]:
    """按 id 或名称解析实验，返回实验对象（含 dataset_id）。"""
    wanted = str(experiment_id)
    for page in range(1, config.max_experiments() // PAGE_SIZE + 2):
        experiments, total = await list_experiments(page=page, size=PAGE_SIZE, transport=transport)
        for experiment in experiments:
            if experiment.get('id') == wanted or experiment.get('name') == wanted:
                return experiment
        if len(experiments) < PAGE_SIZE or page * PAGE_SIZE >= total:
            break
    raise OpikError(f'Experiment {wanted!r} not found in project {config.project_name()!r}')


async def list_threads(page: int = 1, size: int = PAGE_SIZE,
                       transport=None) -> tuple[list[dict[str, Any]], int]:
    """GET /v1/private/traces/threads：多轮会话（一次会话 = 一个 thread）。"""
    data = await get_json('/v1/private/traces/threads',
                          {'project_name': config.project_name(), 'page': page, 'size': size},
                          transport=transport)
    return _content(data, '/v1/private/traces/threads')


async def list_spans(page: int = 1, size: int = PAGE_SIZE, trace_id: str | None = None,
                     transport=None) -> tuple[list[dict[str, Any]], int]:
    """GET /v1/private/spans：LLM / 工具调用等 span，按项目查询（后端按项目分片）。"""
    data = await get_json('/v1/private/spans',
                          {'project_name': config.project_name(), 'page': page, 'size': size,
                           'trace_id': trace_id}, transport=transport)
    return _content(data, '/v1/private/spans')


async def experiment_item_page(dataset_id: str, experiment_id: str, page: int, size: int,
                               transport=None) -> tuple[list[dict[str, Any]], int]:
    path = f'/v1/private/datasets/{dataset_id}/items/experiments/items'
    data = await get_json(path, {'experiment_ids': json.dumps([experiment_id]), 'page': page,
                                 'size': size, 'truncate': 'true'}, transport=transport)
    return _content(data, path)
