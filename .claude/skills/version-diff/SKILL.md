---
name: version-diff
description: 对比两个评测实验（如 baseline 与新版模型）在同批数据上的指标差异，输出整体均值变化、按分类维度的提升/回退项、以及逐条配对差异 TopN。This skill should be used when the user asks to compare two experiments or model versions, find improvements or regressions between versions（如"对比 baseline 和 v2""哪些指标回退了""两个版本差异在哪"）.
---

# 版本差异对比

对同一数据集上两个实验的评分做配对对比，定位提升项与回退项。

## 工作流程

1. **确定实验对**：需要两个实验名（baseline / candidate）。用户未明确时，先调 MCP 工具 `list_experiments` 列出全部实验，按语义选择两个（如时间上先后、名称含 baseline/v2），并在结果 `inputs` 中说明选择理由。
2. **取数**：分别调用 MCP 工具 `get_experiment_items` 取两个实验的条目，写入：
   - `outputs/cache/<baseline_name>.items.json`
   - `outputs/cache/<candidate_name>.items.json`
3. **分析**：

   ```bash
   python .claude/skills/version-diff/analyze.py \
     --baseline outputs/cache/<baseline_name>.items.json \
     --candidate outputs/cache/<candidate_name>.items.json \
     --output outputs/cache/version-diff.json \
     [--top-n 5] [--score-name quality]
   ```

4. **组装结果**：`skill` 固定为 `version-diff`；`metrics` 取脚本输出的 `metrics`；`findings` 取脚本输出的 `findings`；`artifacts` 取脚本输出的 `artifacts`（含逐条差异明细 CSV）。
5. 取数为空或配对数为 0 时置 `status=no_data` 并说明；脚本抛错置 `error`。禁止在无配对数据时编造差异。

## 输出约定

- `metrics.overall`：每个指标在两个版本上的均值与绝对变化
- `metrics.by_category`：按分类的平均差异，正为提升、负为回退
- `metrics.paired`：paired_count / improved / regressed / unchanged 计数
- `findings`：至少包含「整体趋势」「Top 回退项」「Top 提升项」（若存在）
- `artifacts`：`outputs/` 下的逐条差异明细 CSV 路径

配对键为条目 metadata.seed_id；仅对两侧都存在的 seed_id 做配对。
