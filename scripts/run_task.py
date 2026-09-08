#!/usr/bin/env python3
"""CLI 入口：提交自然语言分析任务，输出结构化结果 JSON。

用法：
    .venv/bin/python scripts/run_task.py "分析 baseline 实验的指标分布"
    .venv/bin/python scripts/run_task.py "对比 baseline 和 v2-safety-tuned 的差异" --output out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anyio  # noqa: E402

from agent_runtime.config import RESULTS_DIR  # noqa: E402
from agent_runtime.result_schema import ResultSchemaError  # noqa: E402
from agent_runtime.runtime import run_task  # noqa: E402


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """先写临时文件再原子改名，避免下游读到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="提交分析任务给云侧 Agent Runtime")
    parser.add_argument("task", help="自然语言分析任务")
    parser.add_argument("--output", default=None, help="结果 JSON 路径（默认 outputs/results/<时间戳>.json）")
    args = parser.parse_args()

    try:
        result = anyio.run(run_task, args.task)
    except ResultSchemaError as exc:
        print(f"[runtime] 结果不符合契约: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底
        print(f"[runtime] 任务执行失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    output = Path(args.output) if args.output else RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    atomic_write_json(output, result)
    print(f"[runtime] 结果已写入 {output}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
