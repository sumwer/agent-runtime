---
name: metric-distribution
description: 分析单个评测实验的得分分布，包括总体统计（均值/标准差/分位数）、按类别与年龄段分组的指标分解，并自动生成结论。This skill should be used when the user asks about score distribution, percentiles, per-category breakdown, or overall quality of a single evaluation experiment（如"分析 baseline 的得分分布""看看各分类的表现""指标分布怎么样"）.
---

# 实验指标分布分析

对单个实验（experiment）的评分做分布统计与分组分解，输出结构化结论。

## 工作流程

1. **取数**：调用 MCP 工具 `get_experiment_items`，参数 `experiment_name` 传用户指定的实验名（未指定时先用 `list_experiments` 列出供用户确认或自行选择最相关的）。
2. **落盘**：把工具返回的 JSON 数组原样写入 `outputs/cache/<experiment_name>.items.json`（目录不存在则创建）。
3. **分析**：执行本 Skill 附带的脚本：

   ```bash
   python .claude/skills/metric-distribution/analyze.py \
     --input outputs/cache/<experiment_name>.items.json \
     --output outputs/cache/<experiment_name>.distribution.json
   ```

   可选参数 `--score-name quality` 只分析某一个指标；不传则分析全部指标。
4. **组装结果**：读取脚本输出的 JSON，按平台结果契约组装最终结果：
   - `skill` 固定为 `metric-distribution`
   - `inputs` 记录实际使用的 experiment_name 与 score_name
   - `metrics` 直接采用脚本输出的 `metrics` 字段
   - `findings` 直接采用脚本输出的 `findings`（可补充文字润色，但不得编造数据）
   - `artifacts` 采用脚本输出的 `artifacts`
5. 若取数为空或脚本抛错，结果 `status` 分别置为 `no_data` / `error`，并在 `findings` 中说明原因，禁止编造结论。

## 输出约定

脚本输出的 `metrics` 结构：

- `overall.<score_name>`：count / mean / std / min / p25 / p50 / p75 / p90 / max
- `by_category.<category>.<score_name>`：count / mean（按条目 metadata.category 分组）
- `by_age_band.<band>.<score_name>`：count / mean

`findings` 为自动生成的结论条目（{title, detail, evidence}），至少覆盖：表现最差的分类、表现最好的分类、是否存在长尾（p90 与 p50 差距过大）、低分（< 0.4）样本占比。
