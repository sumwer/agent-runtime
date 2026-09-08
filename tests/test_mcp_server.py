"""MCP 取数连通性冒烟测试：确认每个取数工具都能从 Opik 拿到非空数据。

运行： agent-runtime/.venv/bin/python -m pytest tests/test_mcp_server.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from mcp_server import opik_mcp  # noqa: E402


def test_list_experiments() -> None:
    experiments = opik_mcp._list_experiments(opik_mcp.PROJECT)
    assert experiments, "应能列出实验"
    names = {e["name"] for e in experiments}
    assert {"baseline", "v2-safety-tuned"} <= names, f"缺少预期实验: {names}"


def test_get_experiment_items() -> None:
    items = opik_mcp._get_experiment_items("baseline", opik_mcp.PROJECT, 100)
    assert len(items) == 30
    assert items[0]["feedback_scores"], "条目必须带评分"
    assert items[0]["metadata"]["category"], "条目必须带分类维度"


def test_two_versions_have_different_scores() -> None:
    """两个版本的分数必须不同，否则版本差异分析无从谈起。"""
    base = opik_mcp._get_scores("baseline", opik_mcp.PROJECT, "quality")
    cand = opik_mcp._get_scores("v2-safety-tuned", opik_mcp.PROJECT, "quality")
    base_values = [r["value"] for r in base]
    cand_values = [r["value"] for r in cand]
    assert base_values != cand_values, "两个版本的 quality 分数不应完全相同"


def test_get_scores_shape() -> None:
    rows = opik_mcp._get_scores("v2-safety-tuned", opik_mcp.PROJECT, None)
    assert rows
    assert {r["score_name"] for r in rows} >= {"quality", "safety", "age_fit"}
    assert all(r["category"] for r in rows)


def test_reports() -> None:
    reports = opik_mcp._list_reports()
    assert reports, "应能列出自定义报告"
    report = opik_mcp._get_report(reports[0]["id"])
    assert "versions" in report


def test_search_traces() -> None:
    traces = opik_mcp._search_traces(opik_mcp.PROJECT, 5)
    assert traces


def test_get_trace() -> None:
    items = opik_mcp._get_experiment_items("baseline", opik_mcp.PROJECT, 1)
    trace = opik_mcp._get_trace(items[0]["trace_id"])
    assert trace["id"] == items[0]["trace_id"]
    assert trace["spans"], "trace 应包含 span"
