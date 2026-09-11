---
name: agent-metrics
description: 汇总被评 agent 的整体指标，重点是多轮决策：轮次与收敛、工具调用成功率与路径、延迟与 token 成本、失败与异常会话。
---

# Agent 整体指标（多轮决策）

1. 先用 list_experiments 确认项目与实验，再取多轮数据：
   `export_data(source="threads")`（会话级，一次会话一行：轮次、时长、usage、state）与
   `export_data(source="spans")`（单步决策：type=llm 的模型调用、type=tool 的工具调用、
   usage 里的 token、duration、error）。两者都是项目级，不需要 experiment_id，
   也不支持 min_score/max_score。
2. 生成沙箱 Python 计算三类指标（缺字段就跳过并在 caveats 说明，不得编造）：
   - 会话与收敛：会话数、轮次 mean/median/P90、轮次分布、status=finished 占比、
     平均与 P95 会话时长、会话总成本；
   - 决策与工具：每会话步数、工具调用数、工具成功率（无 error 占比）、
     工具使用分布 TopN、重复调用/循环检测（同一 trace 内同名工具连续 ≥3 次）、
     决策路径 TopN（span name 序列）、LLM 步占比；
   - 效率与风险：span 延迟 P50/P95、LLM 与工具耗时占比、token 与成本按类型拆分、
     错误 span 数与 error 率、失败发生在第几轮、异常会话（轮次或成本超 P95）。
3. 用参考代码产出 out/agent_metrics.png（轮次分布 + 工具成功率）与 out/agent_metrics.json。
4. submit_result：skill_id=agent-metrics；metrics 必含 sample_count（会话数）、
   turn_mean、tool_success_rate、error_rate、latency_p95（无对应数据的指标不要出现）；
   findings 的 evidence 写具体 thread id / trace_id；charts=["out/agent_metrics.png"]。
   caveats 写清时间窗、样本量、usage/error 字段缺失比例与方法局限。
5. 零会话或没有 tool 类型 span 时明确报告缺什么（例如「项目无多轮会话数据」），
   只输出可得指标，不做推测性结论。
