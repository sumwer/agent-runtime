#!/usr/bin/env python3
"""Bad Case 挖掘：按阈值筛选实验中的低分样本并导出明细 CSV。

只用标准库；输入 get_experiment_items 的 JSON，输出筛选结果与结论。
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Bad Case 挖掘")
    parser.add_argument("--input", required=True, help="get_experiment_items 输出的 JSON 文件")
    parser.add_argument("--output", required=True, help="结果 JSON 输出路径")
    parser.add_argument("--artifact-dir", default="outputs", help="明细 CSV 输出目录")
    parser.add_argument("--threshold", type=float, default=0.4, help="低分阈值（低于该值算 bad case）")
    parser.add_argument("--score-name", default=None, help="只按指定指标筛选（默认任一指标低于阈值即算）")
    parser.add_argument("--top", type=int, default=20, help="结论中列出的最严重样本数")
    args = parser.parse_args()

    items = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not items:
        result = {
            "status": "no_data",
            "metrics": {},
            "findings": [{"title": "无数据", "detail": "实验没有任何条目。", "evidence": {}}],
            "artifacts": [],
        }
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    badcases: list[dict[str, Any]] = []
    score_fail_counter: Counter[str] = Counter()
    total_by_score: Counter[str] = Counter()
    for item in items:
        meta = item.get("metadata") or {}
        scores = {
            s.get("name"): float(s.get("value", 0.0))
            for s in (item.get("feedback_scores") or [])
        }
        for name, value in scores.items():
            total_by_score[name] += 1
        failing = {
            name: value
            for name, value in scores.items()
            if value < args.threshold and (args.score_name is None or name == args.score_name)
        }
        for name in failing:
            score_fail_counter[name] += 1
        if failing:
            question = ""
            inp = item.get("input") or {}
            if isinstance(inp, dict):
                question = inp.get("question") or json.dumps(inp, ensure_ascii=False)
            else:
                question = str(inp)
            badcases.append(
                {
                    "dataset_item_id": item.get("dataset_item_id"),
                    "trace_id": item.get("trace_id"),
                    "seed_id": meta.get("seed_id"),
                    "category": meta.get("category", "unknown"),
                    "age_band": meta.get("age_band", "unknown"),
                    "scores": scores,
                    "failing_scores": failing,
                    "question": question,
                }
            )

    # 最严重的排在前面：失败指标最多、分数最低优先
    badcases.sort(key=lambda b: (len(b["failing_scores"]), min(b["failing_scores"].values())))
    total_count = len(items)
    ratio = len(badcases) / total_count if total_count else 0.0
    by_category = Counter(b["category"] for b in badcases)

    findings: list[dict[str, Any]] = []
    if not badcases:
        findings.append(
            {
                "title": "未发现 Bad Case",
                "detail": f"阈值 {args.threshold} 之下没有样本（共 {total_count} 条），该实验质量健康。",
                "evidence": {"threshold": args.threshold, "total_count": total_count},
            }
        )
    else:
        worst = badcases[0]
        findings.append(
            {
                "title": f"最严重样本：{worst['seed_id']}",
                "detail": f"失败指标 {list(worst['failing_scores'])}，得分 {worst['failing_scores']}；输入问题：{worst['question'][:80]}",
                "evidence": {"trace_id": worst["trace_id"], "scores": worst["scores"]},
            }
        )
        findings.append(
            {
                "title": f"Bad Case 集中在 {by_category.most_common(1)[0][0]}",
                "detail": f"共 {len(badcases)} 条（占比 {ratio:.1%}），其中 {by_category.most_common(1)[0][0]} 占 {by_category.most_common(1)[0][1]} 条。",
                "evidence": dict(by_category.most_common()),
            }
        )
        if score_fail_counter:
            findings.append(
                {
                    "title": "各指标失败次数",
                    "detail": "按指标统计低于阈值的次数，可定位是哪类能力不足。",
                    "evidence": dict(score_fail_counter.most_common()),
                }
            )

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    csv_path = artifact_dir / "badcases.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["seed_id", "category", "age_band", "scores", "failing_scores", "trace_id", "question"])
        for b in badcases:
            writer.writerow(
                [
                    b["seed_id"],
                    b["category"],
                    b["age_band"],
                    json.dumps(b["scores"], ensure_ascii=False),
                    json.dumps(b["failing_scores"], ensure_ascii=False),
                    b["trace_id"],
                    b["question"],
                ]
            )

    result = {
        "status": "success",
        "metrics": {
            "badcase_count": len(badcases),
            "total_count": total_count,
            "ratio": round(ratio, 4),
            "threshold": args.threshold,
            "by_category": dict(by_category.most_common()),
            "by_score_name": dict(score_fail_counter.most_common()),
        },
        "findings": findings,
        "artifacts": [str(csv_path)],
        "top_badcases": badcases[: args.top],
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[badcase-mining] 已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
