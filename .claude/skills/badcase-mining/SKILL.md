---
name: badcase-mining
description: 从评测实验中挖掘低分 Bad Case，按指标阈值筛选样本并导出含输入问题的明细清单。This skill should be used when the user asks to find bad cases, low-scoring samples, failures, or worst-performing items in an evaluation（如"找出 bad case""哪些样本得分很低""挖一下失败样例"）.
---

# Bad Case 挖掘

按阈值筛选实验中的低分样本，输出可定位的明细清单与分布摘要。

## 工作流程

1. **取数**：调用 MCP 工具 `get_experiment_items`，参数 `experiment_name` 传用户指定的实验名（未指定时先 `list_experiments` 选择，并在 `inputs` 中说明）。条目 JSON 写入 `outputs/cache/<experiment_name>.items.json`。
2. **分析**：

   ```bash
   python .claude/skills/badcase-mining/analyze.py \
     --input outputs/cache/<experiment_name>.items.json \
     --output outputs/cache/badcases.json \
     --artifact-dir outputs \
     [--threshold 0.4] [--score-name quality] [--top 20]
   ```

3. **组装结果**：`skill` 固定为 `badcase-mining`；`inputs` 记录 experiment_name、threshold、score_name；`metrics` 取脚本输出；`findings` 取脚本输出；`artifacts` 取脚本输出的 CSV 路径（可用 MCP `get_trace` 对典型 bad case 追溯 trace/span 细节，把 trace_id 放入 evidence）。
4. 若没有低于阈值的样本，`status=success` 但 `metrics.badcase_count=0`，并在 `findings` 中明确说明"未发现低于阈值的样本"；取数为空置 `no_data`。

## 输出约定

- `metrics.badcase_count` / `metrics.total_count` / `metrics.ratio`
- `metrics.by_category`：bad case 在各分类上的数量分布
- `metrics.by_score_name`：各指标各自低于阈值的数量
- `findings`：最严重样本、bad case 集中的分类、与输入问题的对应关系
- `artifacts`：bad case 明细 CSV（含 seed_id、category、scores、输入问题文本）
