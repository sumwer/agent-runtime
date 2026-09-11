---
name: score-distribution
description: 查看实验分数分布、直方图、分位数、各测试维度均值、异常点和低分占比。
---

# Score 分布统计

1. sample_traces 确认字段，export_data(source="traces", experiment_id=目标实验) 导出。
2. 生成 Python 经 run_in_sandbox 执行，统计均值、标准差、P5/P25/P50/P75/P95、
   低分(<0.5)占比，以及 metadata.category / metadata.age_band 维度切片
   （真实 Opik）；mock 数据若无 metadata 则只报总体分布。产出 out/hist.png。
3. findings 解释分布、维度差异、异常样本，避免把相关性说成因果。
4. submit_result：skill_id=score-distribution，metrics 必含 sample_count、mean、p50、
   low_score_ratio。charts=["out/hist.png"]，截断必须在 caveats 说明。
5. 零样本仍运行脚本确认，sample_count=0，不计算分位数，不报告虚构分布。
