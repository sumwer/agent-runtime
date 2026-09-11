---
name: badcase-analysis
description: 分析 bad case、低分原因、错误归因，按错误类型分组并给出证据和改进建议。
---

# Bad Case 归因分析

1. 用 sample_traces 确认实验和字段，随后 export_data(source="traces", experiment_id=目标实验,
   max_score=params.score_threshold 或默认 0.5)。过滤为闭区间 ≤ 阈值。
2. 生成沙箱 Python 按维度分组，优先级：metadata.category（真实 Opik：substance_use / self_harm 等）
   > error_type（mock 数据）> score 区间分桶。两者都没有时按分数分桶。
   统计样本量、组数、组平均分、metadata.age_band 分布和延迟；每组最多取两条代表。
3. 使用参考代码，按真实字段调整；输出 out/groups.png 和统计摘要。
   代表样本用 trace_id 作为证据，问题文本在 item_input（output 在 Opik 里只是 trace 引用）。
4. 结合代表样本归纳共性、疑似原因、可执行建议。规则分组不是因果证明，写明局限。
5. submit_result：skill_id=badcase-analysis，metrics 必含 sample_count、group_count，
   findings 的 evidence 是具体 trace ID 字符串，charts=["out/groups.png"]。
   caveats 写清过滤条件、样本量、截断、所用分组维度与方法局限；没有样本时只报告空数据，不做归因。
