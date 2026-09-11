"""把 Opik 的实验/实验条目映射为运行时契约的行结构。

契约（app/tools/export_data.py）：
- get_traces 的行至少含 id 与数值 score
- get_scores 的行含 trace_id 与 score
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import config


def numeric_scores(item: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for score in item.get('feedback_scores') or []:
        name = score.get('name')
        value = score.get('value')
        if name is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        scores[str(name)] = float(value)
    return scores


def pick_score(scores: dict[str, float]) -> tuple[str | None, float | None]:
    preferred = config.score_name()
    if preferred and preferred in scores:
        return preferred, scores[preferred]
    for name, value in scores.items():
        return name, value
    return None, None


def primary_score_name(rows: list[dict[str, Any]]) -> str | None:
    """全实验共用的主评分类指标：出现次数最多，同次数取字典序。

    反馈评分的顺序在不同条目间不固定，逐条取第一个会把不同指标混在一列里。
    """
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row['scores'])
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))[0]


def apply_primary_score(rows: list[dict[str, Any]], name: str | None) -> None:
    """按主指标重写 score/score_name；没有该指标的条目记为 None，不与其他指标混算。"""
    for row in rows:
        value = row['scores'].get(name) if name else None
        row['score'] = value
        row['score_name'] = name if value is not None else None


def experiment_summary(experiment: dict[str, Any]) -> dict[str, Any]:
    averages = {s.get('name'): s.get('value') for s in (experiment.get('feedback_scores') or [])
                if s.get('name')}
    values = [v for v in averages.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return {
        'id': experiment.get('id'),
        'name': experiment.get('name'),
        'dataset_id': experiment.get('dataset_id'),
        'dataset_name': experiment.get('dataset_name'),
        'trace_count': experiment.get('trace_count'),
        'item_count': experiment.get('dataset_item_count'),
        'avg_score': sum(values) / len(values) if values else None,
        'scores': averages,
        'created_at': str(experiment.get('created_at')) if experiment.get('created_at') else None,
    }


def dataset_summary(dataset: dict[str, Any]) -> dict[str, Any]:
    latest = dataset.get('latest_version') if isinstance(dataset.get('latest_version'), dict) else {}
    return {
        'id': dataset.get('id'),
        'name': dataset.get('name'),
        'item_count': dataset.get('dataset_items_count'),
        'experiment_count': dataset.get('experiment_count'),
        'version': latest.get('version_name') or latest.get('version_hash'),
        'tags': dataset.get('tags') or latest.get('tags') or [],
        'created_at': str(dataset.get('created_at')) if dataset.get('created_at') else None,
    }


def dataset_item_row(item: dict[str, Any]) -> dict[str, Any]:
    """Preserve raw input/metadata/expected output for pre-evaluation distribution analysis."""
    data = item.get('data') if isinstance(item.get('data'), dict) else {}
    return {
        'id': item.get('id'),
        'dataset_item_id': item.get('dataset_item_id') or item.get('id'),
        'dataset_id': item.get('dataset_id'),
        'source': item.get('source'),
        'input': data.get('input'),
        'expected_output': data.get('expected_output'),
        'metadata': data.get('metadata'),
        'tags': item.get('tags') or [],
        'description': item.get('description'),
        'created_at': str(item.get('created_at')) if item.get('created_at') else None,
    }


def item_row(dataset_item: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    scores = numeric_scores(item)
    name, value = pick_score(scores)
    data = dataset_item.get('data') if isinstance(dataset_item.get('data'), dict) else {}
    created = item.get('created_at')
    # 实验条目的 input 形如 {"item": {...数据集条目...}, "version": ...}；
    # 真正的问题文本在 item.input 里，单独铺平一层供 Skill 使用。
    wrapped = item.get('input') if isinstance(item.get('input'), dict) else None
    inner = wrapped.get('item') if wrapped and isinstance(wrapped.get('item'), dict) else None
    return {
        'id': item.get('id'),
        'trace_id': item.get('trace_id'),
        'dataset_item_id': item.get('dataset_item_id'),
        'experiment_id': item.get('experiment_id'),
        'input': item.get('input'),
        'item_input': (inner or {}).get('input'),
        'version': (wrapped or {}).get('version'),
        'output': item.get('output'),
        'expected_output': data.get('expected_output'),
        'metadata': data.get('metadata'),
        'score': value,
        'score_name': name,
        'scores': scores,
        'duration': item.get('duration'),
        'created_at': str(created) if created else None,
    }


def thread_row(thread: dict[str, Any]) -> dict[str, Any]:
    """多轮会话：轮次数、时长、用量、成本与状态。"""
    scores = {s.get('name'): s.get('value') for s in (thread.get('feedback_scores') or [])
              if s.get('name') and isinstance(s.get('value'), (int, float))}
    return {
        'id': thread.get('id'),
        'number_of_messages': thread.get('number_of_messages'),
        'duration': thread.get('duration'),
        'status': thread.get('status'),
        'usage': thread.get('usage') or {},
        'total_estimated_cost': thread.get('total_estimated_cost'),
        'scores': scores,
        'created_at': str(thread.get('created_at')) if thread.get('created_at') else None,
    }


def span_row(span: dict[str, Any]) -> dict[str, Any]:
    """单步决策：LLM / 工具调用 / 普通步骤。"""
    usage = span.get('usage') or {}
    error = span.get('error_info') or {}
    return {
        'id': span.get('id'),
        'trace_id': span.get('trace_id'),
        'parent_span_id': span.get('parent_span_id'),
        'name': span.get('name'),
        'type': span.get('type'),
        'model': span.get('model'),
        'provider': span.get('provider'),
        'prompt_tokens': usage.get('prompt_tokens'),
        'completion_tokens': usage.get('completion_tokens'),
        'total_tokens': usage.get('total_tokens'),
        'duration': span.get('duration'),
        'ttft': span.get('ttft'),
        'total_estimated_cost': span.get('total_estimated_cost'),
        'error': error.get('exception_type') or error.get('message') if error else None,
        'start_time': str(span.get('start_time')) if span.get('start_time') else None,
    }


def keep(row: dict[str, Any], min_score: float | None, max_score: float | None) -> bool:
    if min_score is None and max_score is None:
        return True
    score = row.get('score')
    if score is None:
        return False
    return (min_score is None or score >= min_score) and (max_score is None or score <= max_score)


def paginate(rows: list[dict[str, Any]], page: int, page_size: int) -> dict[str, Any]:
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError('page >= 1 and 1 <= page_size <= 100 required')
    start = (page - 1) * page_size
    return {'items': rows[start:start + page_size], 'total': len(rows),
            'page': page, 'page_size': page_size}
