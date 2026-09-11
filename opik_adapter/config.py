"""适配层配置。

全部从进程环境读取：MCP stdio 子进程继承的是启动 API/Worker 的进程环境
（systemd 用 Environment=），不会读仓库里的 .env。
"""
from __future__ import annotations

import os

DEFAULTS = {
    'OPIK_API_BASE': 'http://localhost:5173/api',
    # 旧配置名（opik SDK 用），OPIK_API_BASE 未设置时兜底。
    'OPIK_URL_OVERRIDE': '',
    'OPIK_API_KEY': '',
    'OPIK_WORKSPACE': 'default',
    'OPIK_PROJECT_NAME': 'default',
    # 指定主评分类指标名；为空则取该条目第一个数值评分。
    'OPIK_SCORE_NAME': '',
    'OPIK_TIMEOUT_SECONDS': '30',
    # 单次任务缓存的实验条目上限，与 MAX_EXPORT_ROWS 搭配使用。
    'OPIK_MAX_ITEMS': '10000',
    'OPIK_MAX_EXPERIMENTS': '200',
}


def get(name: str) -> str:
    return os.environ.get(name) or DEFAULTS.get(name, '')


def api_base() -> str:
    return (get('OPIK_API_BASE') or get('OPIK_URL_OVERRIDE')).rstrip('/')


def api_key() -> str:
    return get('OPIK_API_KEY')


def workspace() -> str:
    return get('OPIK_WORKSPACE')


def project_name() -> str:
    return get('OPIK_PROJECT_NAME')


def score_name() -> str:
    return get('OPIK_SCORE_NAME')


def timeout_seconds() -> float:
    return float(get('OPIK_TIMEOUT_SECONDS') or 30)


def max_items() -> int:
    return max(1, int(get('OPIK_MAX_ITEMS') or 10000))


def max_experiments() -> int:
    return max(1, int(get('OPIK_MAX_EXPERIMENTS') or 200))
