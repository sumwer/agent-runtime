#!/usr/bin/env python3
"""实验得分分布分析：输入 get_experiment_items 的 JSON，输出分布统计与结论。

只用标准库，保持纯数据处理（输入 JSON、输出 JSON），便于单独测试与复用。
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

LOW_SCORE_THRESHOLD = 0.4


def percentile(sorted_values: list[float], p: float) -> float:
    """线性插值分位数。入参须已升序排序。"""
    if not sorted_values:
        raise ValueError("empty values")
    k = (len(sorted_values) - 1) * p
    lower = int(k)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = k - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def distribution(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 4),
        "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(ordered[0], 4),
        "p25": round(percentile(ordered, 0.25), 4),
        "p50": round(percentile(ordered, 0.50), 4),
        "p75": round(percentile(ordered, 0.75), 4),
        "p90": round(percentile(ordered, 0.90), 4),
        "max": round(ordered[-1], 4),
    }


def collect_rows(
    items: list[dict[str, Any]], score_name: str | None
) -> list[dict[str, Any]]:
    """把条目展开为 (score_name, value, category, age_band) 行。"""
    rows: list[dict[str, Any]] = []
    for item in items:
        meta = item.get("metadata") or {}
        for score in item.get("feedback_scores") or []:
            if score_name and score.get("name") != score_name:
                continue
            rows.append(
                {
                    "score_name": score.get("name"),
                    "value": float(score.get("value", 0.0)),
                    "category": meta.get("category", "unknown"),
                    "age_band": meta.get("age_band", "unknown"),
                    "seed_id": meta.get("seed_id"),
                }
            )
    if not rows:
        raise ValueError("输入数据中没有任何评分，无法分析分布")
    return rows


def grouped(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, dict[str, float | int]]]:
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        buckets[str(row[key])][row["score_name"]].append(row["value"])
    return {
        group: {name: distribution(values) for name, values in sorted(metrics.items())}
        for group, metrics in sorted(buckets.items())
    }


def build_findings(
    overall: dict[str, dict[str, float | int]],
    by_category: dict[str, dict[str, dict[str, float | int]]],
    low_ratio: float,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    # 以 quality 为主线给出主要结论；没有 quality 时取第一个指标
    primary = "quality" if "quality" in overall else next(iter(overall))
    cat_means = {
        cat: metrics[primary]["mean"]
        for cat, metrics in by_category.items()
        if primary in metrics
    }
    if cat_means:
        worst = min(cat_means, key=cat_means.get)  # type: ignore[arg-type]
        best = max(cat_means, key=cat_means.get)  # type: ignore[arg-type]
        findings.append(
            {
                "title": f"表现最差的分类：{worst}",
                "detail": f"{primary} 均值仅 {cat_means[worst]:.3f}，明显低于其他分类。",
                "evidence": {cat: round(v, 4) for cat, v in sorted(cat_means.items(), key=lambda kv: kv[1])},
            }
        )
        if worst != best:
            findings.append(
                {
                    "title": f"表现最好的分类：{best}",
                    "detail": f"{primary} 均值达 {cat_means[best]:.3f}。",
                    "evidence": {cat: round(v, 4) for cat, v in sorted(cat_means.items(), key=lambda kv: -kv[1])[:3]},
                }
            )

    stats = overall[primary]
    tail_gap = float(stats["p90"]) - float(stats["p50"])
    if tail_gap > 0.15:
        findings.append(
            {
                "title": f"{primary} 存在长尾",
                "detail": f"p50={stats['p50']:.3f} 但 p90={stats['p90']:.3f}，头部样本与中位差距 {tail_gap:.3f}，分布右偏明显。",
                "evidence": {"p50": stats["p50"], "p90": stats["p90"], "max": stats["max"]},
            }
        )
    findings.append(
        {
            "title": f"低分样本占比 {low_ratio:.1%}",
            "detail": f"{primary} 低于 {LOW_SCORE_THRESHOLD} 的样本占 {low_ratio:.1%}，"
            + ("需要重点关注。" if low_ratio > 0.1 else "整体健康。"),
            "evidence": {"threshold": LOW_SCORE_THRESHOLD, "ratio": round(low_ratio, 4)},
        }
    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="实验得分分布分析")
    parser.add_argument("--input", required=True, help="get_experiment_items 输出的 JSON 文件")
    parser.add_argument("--output", required=True, help="结果 JSON 输出路径")
    parser.add_argument("--score-name", default=None, help="只分析指定指标（默认全部分析）")
    args = parser.parse_args()

    items = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rows = collect_rows(items, args.score_name)
    score_names = sorted({r["score_name"] for r in rows})

    overall: dict[str, dict[str, float | int]] = {}
    low_ratios: dict[str, float] = {}
    for name in score_names:
        values = [r["value"] for r in rows if r["score_name"] == name]
        overall[name] = distribution(values)
        low_ratios[name] = sum(1 for v in values if v < LOW_SCORE_THRESHOLD) / len(values)

    result = {
        "status": "success",
        "metrics": {
            "overall": overall,
            "by_category": grouped(rows, "category"),
            "by_age_band": grouped(rows, "age_band"),
        },
        "findings": build_findings(overall, grouped(rows, "category"), low_ratios.get("quality", 0.0)),
        "artifacts": [],
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[metric-distribution] 已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
