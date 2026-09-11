"""Opik MCP 适配服务：对外提供运行时契约的三个工具。

为什么不直接接官方 opik-mcp：它只暴露 read/list/write/schema，
list/read 返回的是给人看的文本表格，且没有「实验条目」（trace × 评分）接口，
无法稳定映射成 {items, total}。这里直接调用 opik-mcp 自己使用的 /v1/private REST
端点，输出结构化分页数据。

运行：python -m opik_adapter.server [--transport streamable-http] [--port 8766]
"""
from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from . import client, config, mapping

mcp = FastMCP('opik')

# 每进程缓存：stdio 模式下一个任务起一个子进程，缓存随进程结束释放；
# HTTP 常驻模式下数据在进程重启前不会刷新。
_CACHE: dict[str, list[dict]] = {}
_LOCK = asyncio.Lock()


async def _rows(experiment_id: str) -> list[dict]:
    key = str(experiment_id)
    if key in _CACHE:
        return _CACHE[key]
    async with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        experiment = await client.find_experiment(key)
        dataset_id = experiment.get('dataset_id')
        resolved = experiment.get('id') or key
        if not dataset_id:
            raise client.OpikError(
                f'Experiment {key!r} has no dataset_id; only dataset-backed experiments are supported')
        rows: list[dict] = []
        cap = config.max_items()
        page = 1
        while len(rows) < cap:
            content, total = await client.experiment_item_page(dataset_id, resolved, page, client.PAGE_SIZE)
            if not content:
                break
            for dataset_item in content:
                for item in dataset_item.get('experiment_items') or []:
                    if len(rows) >= cap:
                        break
                    rows.append(mapping.item_row(dataset_item, item))
                if len(rows) >= cap:
                    break
            if len(rows) >= cap or page * client.PAGE_SIZE >= total:
                break
            page += 1
        mapping.apply_primary_score(rows, _primary_name(rows))
        _CACHE[key] = rows
        return rows


def _primary_name(rows: list[dict]) -> str | None:
    """主评分类指标：OPIK_SCORE_NAME 优先，否则取全实验出现最多的指标。"""
    preferred = config.score_name()
    available = {name for row in rows for name in row['scores']}
    if preferred and available and preferred not in available:
        raise client.OpikError(
            f'OPIK_SCORE_NAME={preferred!r} not present in this experiment; available: {sorted(available)}')
    return preferred or mapping.primary_score_name(rows)


async def _list_experiments() -> list[dict]:
    experiments: list[dict] = []
    cap = config.max_experiments()
    page = 1
    while len(experiments) < cap:
        content, total = await client.list_experiments(page=page, size=client.PAGE_SIZE)
        if not content:
            break
        experiments.extend(mapping.experiment_summary(item) for item in content)
        if page * client.PAGE_SIZE >= total:
            break
        page += 1
    return experiments[:cap]


async def _get_traces(experiment_id: str, page: int = 1, page_size: int = 50,
                      min_score: float | None = None, max_score: float | None = None) -> dict:
    rows = [row for row in await _rows(experiment_id) if mapping.keep(row, min_score, max_score)]
    return mapping.paginate(rows, page, page_size)


async def _get_scores(experiment_id: str, page: int = 1, page_size: int = 50) -> dict:
    rows = [{'trace_id': row['trace_id'], 'score': row['score'], 'name': row['score_name']}
            for row in await _rows(experiment_id)]
    return mapping.paginate(rows, page, page_size)


async def _collect(kind: str, fetch) -> list[dict]:
    """项目级数据（threads / spans）的一次性拉取 + 缓存，与实验条目同理。"""
    if kind in _CACHE:
        return _CACHE[kind]
    async with _LOCK:
        if kind in _CACHE:
            return _CACHE[kind]
        rows: list[dict] = []
        cap = config.max_items()
        page = 1
        while len(rows) < cap:
            content, total = await fetch(page, client.PAGE_SIZE)
            if not content:
                break
            rows.extend(content)
            if page * client.PAGE_SIZE >= total:
                break
            page += 1
        rows = rows[:cap]
        _CACHE[kind] = rows
        return rows


async def _get_threads(page: int = 1, page_size: int = 50) -> dict:
    async def fetch(page_number, size):
        content, total = await client.list_threads(page=page_number, size=size)
        return [mapping.thread_row(item) for item in content], total

    return mapping.paginate(await _collect('threads', fetch), page, page_size)


async def _get_spans(page: int = 1, page_size: int = 50) -> dict:
    async def fetch(page_number, size):
        content, total = await client.list_spans(page=page_number, size=size)
        return [mapping.span_row(item) for item in content], total

    return mapping.paginate(await _collect('spans', fetch), page, page_size)


@mcp.tool()
async def list_experiments() -> list[dict]:
    """List evaluation experiments with dataset, trace count and average scores."""
    return await _list_experiments()


@mcp.tool()
async def get_traces(experiment_id: str, page: int = 1, page_size: int = 50,
                     max_score: float | None = None, min_score: float | None = None) -> dict:
    """Page experiment items (trace per dataset item); optional score filters are inclusive."""
    return await _get_traces(experiment_id, page, page_size, min_score, max_score)


@mcp.tool()
async def get_scores(experiment_id: str, page: int = 1, page_size: int = 50) -> dict:
    """Page trace IDs and numerical scores."""
    return await _get_scores(experiment_id, page, page_size)


@mcp.tool()
async def get_threads(page: int = 1, page_size: int = 50) -> dict:
    """Page multi-turn sessions (threads) of the project: turns, duration, usage, status."""
    return await _get_threads(page, page_size)


@mcp.tool()
async def get_spans(page: int = 1, page_size: int = 50) -> dict:
    """Page decision steps (spans): LLM and tool calls with tokens, latency, cost and errors."""
    return await _get_spans(page, page_size)


def clear_cache() -> None:
    _CACHE.clear()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--transport', choices=['stdio', 'streamable-http'], default='stdio')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    mcp.settings.host = '127.0.0.1'
    mcp.settings.port = args.port
    mcp.run(transport=args.transport)
