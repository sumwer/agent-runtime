"""Opik MCP Server —— 把本地自托管 Opik 的评测数据暴露给 Agent。

设计约定：
- 只做「取数」，不做任何分析；分析逻辑全部放在 Skill 脚本中。
- 取数失败一律向上抛明确错误，绝不返回空数据，避免 Agent 在无数据上编造结论。
- 纯逻辑函数（下划线开头）与 MCP 工具分离，便于单测直接调用。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

os.environ.setdefault("OPIK_URL_OVERRIDE", "http://localhost:5173/api")
os.environ.setdefault("OPIK_WORKSPACE", "default")
os.environ.setdefault("OPIK_PROJECT_NAME", "minor-safety-qlora")

import requests  # noqa: E402
from mcp.server import MCPServer  # noqa: E402  # mcp 2.x: FastMCP 已更名为 MCPServer

import opik  # noqa: E402

PROJECT = os.environ["OPIK_PROJECT_NAME"]
OPIK_API = os.environ["OPIK_URL_OVERRIDE"].rstrip("/")
REPORTS_DIR = ROOT / "data" / "reports"
HTTP_TIMEOUT = 30
# Opik REST 的 page 从 1 开始，传 0 会报错
FIRST_PAGE = 1

mcp = MCPServer("opik")


# --------------------------------------------------------------------------- 内部工具


def _get(path: str, **params: Any) -> dict[str, Any]:
    url = f"{OPIK_API}{path}"
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"Opik API {path} 返回 {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _project(project_name: str | None) -> str:
    return project_name or PROJECT


def _client() -> "opik.Opik":
    return opik.Opik()


def _score_dict(score: Any) -> dict[str, Any]:
    if isinstance(score, dict):
        return {"name": score.get("name"), "value": score.get("value")}
    return {"name": getattr(score, "name", None), "value": getattr(score, "value", None)}


def _experiment_id(experiment_name: str, project_name: str) -> str:
    data = _get("/v1/private/experiments", project_name=project_name, page=FIRST_PAGE, size=200)
    for exp in data.get("content", []):
        if exp.get("name") == experiment_name:
            return exp["id"]
    raise ValueError(f"未找到名为 '{experiment_name}' 的实验")


# --------------------------------------------------------------------------- 纯逻辑


def _list_experiments(project_name: str) -> list[dict[str, Any]]:
    data = _get("/v1/private/experiments", project_name=project_name, page=FIRST_PAGE, size=200)
    return [
        {
            "id": exp["id"],
            "name": exp["name"],
            "dataset_name": exp.get("dataset_name"),
            "trace_count": exp.get("trace_count"),
            "created_at": exp.get("created_at"),
        }
        for exp in data.get("content", [])
    ]


def _get_experiment(experiment_name: str, project_name: str) -> dict[str, Any]:
    data = _get("/v1/private/experiments", project_name=project_name, page=FIRST_PAGE, size=200)
    for exp in data.get("content", []):
        if exp.get("name") == experiment_name:
            return {
                "id": exp["id"],
                "name": exp["name"],
                "dataset_name": exp.get("dataset_name"),
                "dataset_id": exp.get("dataset_id"),
                "trace_count": exp.get("trace_count"),
                "metadata": exp.get("metadata"),
                "created_at": exp.get("created_at"),
            }
    raise ValueError(f"未找到名为 '{experiment_name}' 的实验")


def _get_experiment_items(experiment_name: str, project_name: str, limit: int) -> list[dict[str, Any]]:
    exp_id = _experiment_id(experiment_name, project_name)
    experiment = _client().get_experiment_by_id(exp_id)
    items = experiment.get_items()
    result = []
    for item in items[:limit]:
        data = item.dataset_item_data or {}
        result.append(
            {
                "id": item.id,
                "dataset_item_id": item.dataset_item_id,
                "trace_id": item.trace_id,
                "input": data.get("input"),
                "expected_output": data.get("expected_output"),
                "metadata": data.get("metadata"),
                "output": item.evaluation_task_output,
                "feedback_scores": [_score_dict(s) for s in (item.feedback_scores or [])],
            }
        )
    if not result:
        raise ValueError(f"实验 '{experiment_name}' 没有任何条目，无法进行分析")
    return result


def _search_traces(project_name: str, limit: int) -> list[dict[str, Any]]:
    traces = _client().search_traces(project_name=project_name, max_results=limit)
    return [
        {
            "id": t.id,
            "name": t.name,
            "start_time": str(getattr(t, "start_time", None)),
            "duration": getattr(t, "duration", None),
            "usage": getattr(t, "usage", None),
        }
        for t in traces
    ]


def _get_trace(trace_id: str) -> dict[str, Any]:
    trace = _get(f"/v1/private/traces/{trace_id}")
    spans = _client().search_spans(project_name=PROJECT, trace_id=trace_id)
    return {
        "id": trace.get("id"),
        "name": trace.get("name"),
        "input": trace.get("input"),
        "output": trace.get("output"),
        "usage": trace.get("usage"),
        "duration": trace.get("duration"),
        "spans": [
            {
                "id": s.id,
                "name": s.name,
                "type": getattr(s, "type", None),
                "metadata": getattr(s, "metadata", None),
                "feedback_scores": [
                    _score_dict(x) for x in (getattr(s, "feedback_scores", None) or [])
                ],
            }
            for s in spans
        ],
    }


def _get_scores(experiment_name: str, project_name: str, score_name: str | None) -> list[dict[str, Any]]:
    items = _get_experiment_items(experiment_name, project_name, limit=1000)
    rows = []
    for item in items:
        meta = item.get("metadata") or {}
        for score in item.get("feedback_scores") or []:
            if score_name and score.get("name") != score_name:
                continue
            rows.append(
                {
                    "dataset_item_id": item.get("dataset_item_id"),
                    "seed_id": meta.get("seed_id"),
                    "category": meta.get("category"),
                    "age_band": meta.get("age_band"),
                    "score_name": score.get("name"),
                    "value": score.get("value"),
                }
            )
    if not rows:
        raise ValueError(f"实验 '{experiment_name}' 未取到任何评分（score_name={score_name}）")
    return rows


def _list_reports() -> list[dict[str, Any]]:
    if not REPORTS_DIR.exists():
        return []
    reports = []
    for path in sorted(REPORTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        reports.append(
            {
                "id": data.get("id", path.stem),
                "title": data.get("title"),
                "generated_at": data.get("generated_at"),
                "versions": list((data.get("versions") or {}).keys()),
                "path": str(path),
            }
        )
    return reports


def _get_report(report_id: str) -> dict[str, Any]:
    path = REPORTS_DIR / f"{report_id}.json"
    if not path.exists():
        matches = [p for p in REPORTS_DIR.glob("*.json") if report_id in p.name]
        if not matches:
            raise FileNotFoundError(f"未找到报告 '{report_id}'")
        path = matches[0]
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- MCP 工具


@mcp.tool()
def list_experiments(project_name: str = "") -> list[dict[str, Any]]:
    """列出项目下的所有评测实验（id、名称、关联数据集、trace 数）。"""
    return _list_experiments(_project(project_name or None))


@mcp.tool()
def get_experiment(experiment_name: str, project_name: str = "") -> dict[str, Any]:
    """按名称获取单个实验的详情（含 id、数据集、trace 数）。"""
    return _get_experiment(experiment_name, _project(project_name or None))


@mcp.tool()
def get_experiment_items(experiment_name: str, limit: int = 100, project_name: str = "") -> list[dict]:
    """获取实验下每个条目的输入、期望输出、元数据与各项评分，用于分布/差异/BadCase 分析。"""
    return _get_experiment_items(experiment_name, _project(project_name or None), limit)


@mcp.tool()
def search_traces(project_name: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """列出项目中的 trace（id、名称、耗时、token 用量）。"""
    return _search_traces(_project(project_name or None), limit)


@mcp.tool()
def get_trace(trace_id: str) -> dict[str, Any]:
    """获取单条 trace 及其下所有 span（含 metadata 与 feedback scores）。"""
    return _get_trace(trace_id)


@mcp.tool()
def get_scores(experiment_name: str, score_name: str = "", project_name: str = "") -> list[dict]:
    """把实验的评分拉平为「条目 × 指标」的表格行，便于分组统计。"""
    return _get_scores(experiment_name, _project(project_name or None), score_name or None)


@mcp.tool()
def list_reports() -> list[dict[str, Any]]:
    """列出平台侧的评测报告（Opik 无原生 Report，本 PoC 以自定义 JSON 承载）。"""
    return _list_reports()


@mcp.tool()
def get_report(report_id: str) -> dict[str, Any]:
    """按报告 id 获取完整报告内容（含各版本汇总指标与分类维度指标）。"""
    return _get_report(report_id)


if __name__ == "__main__":
    mcp.run()
