#!/usr/bin/env python3
"""版本差异对比：对同一数据集上两个实验的评分做配对对比。

只用标准库；输入两份 get_experiment_items 的 JSON，输出差异统计、结论与明细 CSV。
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def index_by_seed(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """以 metadata.seed_id 为键建立 {seed_id: {score_name: value, ...}} 索引。"""
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        meta = item.get("metadata") or {}
        seed_id = meta.get("seed_id")
        if not seed_id:
            continue
        scores = {
            s.get("name"): float(s.get("value", 0.0))
            for s in (item.get("feedback_scores") or [])
        }
        index[str(seed_id)] = {
            "category": meta.get("category", "unknown"),
            "scores": scores,
            "input": (item.get("input") or {}),
        }
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="两个实验的版本差异对比")
    parser.add_argument("--baseline", required=True, help="基线实验的 items JSON")
    parser.add_argument("--candidate", required=True, help="候选实验的 items JSON")
    parser.add_argument("--output", required=True, help="结果 JSON 输出路径")
    parser.add_argument("--artifact-dir", default="outputs", help="明细 CSV 输出目录")
    parser.add_argument("--top-n", type=int, default=5, help="提升/回退 TopN")
    parser.add_argument("--score-name", default=None, help="只对比指定指标")
    args = parser.parse_args()

    baseline = index_by_seed(json.loads(Path(args.baseline).read_text(encoding="utf-8")))
    candidate = index_by_seed(json.loads(Path(args.candidate).read_text(encoding="utf-8")))

    common = sorted(set(baseline) & set(candidate))
    if not common:
        print("两个实验没有可配对的条目（seed_id 无交集）", file=__import__("sys").stderr)
        result = {
            "status": "no_data",
            "metrics": {},
            "findings": [
                {
                    "title": "无可配对条目",
                    "detail": "两个实验的条目 seed_id 没有交集，无法做版本差异对比。",
                    "evidence": {
                        "baseline_count": len(baseline),
                        "candidate_count": len(candidate),
                    },
                }
            ],
            "artifacts": [],
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    score_names = sorted(
        {n for v in baseline.values() for n in v["scores"]}
        | {n for v in candidate.values() for n in v["scores"]}
    )
    if args.score_name:
        score_names = [n for n in score_names if n == args.score_name]

    # 逐条差异（candidate - baseline）
    diffs: list[dict[str, Any]] = []
    for seed_id in common:
        b, c = baseline[seed_id], candidate[seed_id]
        for name in score_names:
            bv, cv = b["scores"].get(name), c["scores"].get(name)
            if bv is None or cv is None:
                continue
            diffs.append(
                {
                    "seed_id": seed_id,
                    "category": b["category"],
                    "score_name": name,
                    "baseline": round(bv, 4),
                    "candidate": round(cv, 4),
                    "delta": round(cv - bv, 4),
                }
            )

    # 总体：每指标两版均值与变化
    overall = {}
    for name in score_names:
        b_vals = [baseline[s]["scores"].get(name) for s in common]
        c_vals = [candidate[s]["scores"].get(name) for s in common]
        b_vals = [v for v in b_vals if v is not None]
        c_vals = [v for v in c_vals if v is not None]
        if not b_vals or not c_vals:
            continue
        b_mean, c_mean = statistics.fmean(b_vals), statistics.fmean(c_vals)
        overall[name] = {
            "baseline_mean": round(b_mean, 4),
            "candidate_mean": round(c_mean, 4),
            "delta": round(c_mean - b_mean, 4),
        }

    # 按分类：平均差异
    by_category: dict[str, dict[str, float]] = defaultdict(dict)
    for name in score_names:
        buckets: dict[str, list[float]] = defaultdict(list)
        for d in diffs:
            if d["score_name"] == name:
                buckets[d["category"]].append(d["delta"])
        for cat, values in buckets.items():
            by_category[cat][name] = round(statistics.fmean(values), 4)

    # 配对计数（以主指标 quality 统计）
    primary = "quality" if "quality" in score_names else (score_names[0] if score_names else None)
    paired_stats = {"paired_count": 0, "improved": 0, "regressed": 0, "unchanged": 0}
    if primary:
        for d in diffs:
            if d["score_name"] != primary:
                continue
            paired_stats["paired_count"] += 1
            if d["delta"] > 0.005:
                paired_stats["improved"] += 1
            elif d["delta"] < -0.005:
                paired_stats["regressed"] += 1
            else:
                paired_stats["unchanged"] += 1

    # TopN 提升 / 回退（主指标）
    primary_diffs = [d for d in diffs if primary and d["score_name"] == primary]
    primary_diffs.sort(key=lambda d: d["delta"], reverse=True)
    top_improved = primary_diffs[: args.top_n]
    top_regressed = sorted(primary_diffs, key=lambda d: d["delta"])[: args.top_n]

    findings: list[dict[str, Any]] = []
    if primary and primary in overall:
        delta = overall[primary]["delta"]
        direction = "提升" if delta > 0 else ("回退" if delta < 0 else "持平")
        findings.append(
            {
                "title": f"整体{direction}：{primary} 均值变化 {delta:+.4f}",
                "detail": (
                    f"候选版本 {primary} 均值 {overall[primary]['candidate_mean']:.4f}，"
                    f"基线 {overall[primary]['baseline_mean']:.4f}；"
                    f"配对 {paired_stats['paired_count']} 条中提升 {paired_stats['improved']}、"
                    f"回退 {paired_stats['regressed']}、持平 {paired_stats['unchanged']}。"
                ),
                "evidence": overall[primary] | paired_stats,
            }
        )
    if top_regressed and top_regressed[0]["delta"] < -0.005:
        findings.append(
            {
                "title": "Top 回退项",
                "detail": "以下条目在候选版本中明显变差：",
                "evidence": top_regressed[: args.top_n],
            }
        )
    if top_improved and top_improved[0]["delta"] > 0.005:
        findings.append(
            {
                "title": "Top 提升项",
                "detail": "以下条目在候选版本中明显变好：",
                "evidence": top_improved[: args.top_n],
            }
        )
    regressed_cats = {
        cat: values[primary]
        for cat, values in by_category.items()
        if primary in values and values[primary] < -0.02
    }
    if regressed_cats:
        findings.append(
            {
                "title": "分类级回退",
                "detail": f"以下分类的 {primary} 平均分低于基线：",
                "evidence": regressed_cats,
            }
        )

    # 明细 CSV（制品）
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    csv_path = artifact_dir / "version-diff-details.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["seed_id", "category", "score_name", "baseline", "candidate", "delta"]
        )
        writer.writeheader()
        writer.writerows(diffs)

    result = {
        "status": "success",
        "metrics": {
            "overall": overall,
            "by_category": {k: dict(v) for k, v in sorted(by_category.items())},
            "paired": paired_stats,
        },
        "findings": findings,
        "artifacts": [str(csv_path)],
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[version-diff] 已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
