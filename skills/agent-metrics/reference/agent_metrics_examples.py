"""多轮 agent 整体指标参考实现。

输入：沙箱工作目录下的 threads.jsonl 与 spans.jsonl（export_data 产物）。
输出：out/agent_metrics.png 与 out/agent_metrics.json。
缺字段时跳过对应指标并在 gaps 里记录，不臆造数值。
"""
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RUNNING_LOOP = 3  # 同名工具连续调用达到该次数视为潜在循环


def load(name):
    path = Path(f'{name}.jsonl')
    if not path.exists():
        return pd.DataFrame()
    return pd.DataFrame([json.loads(line) for line in path.read_text().splitlines() if line.strip()])


def _p(values, q):
    return float(np.percentile(values, q)) if len(values) else None


threads, spans = load('threads'), load('spans')
metrics, gaps = {}, []

metrics['sample_count'] = int(len(threads))
if threads.empty:
    gaps.append('threads.jsonl 为空：无多轮会话数据，只输出 span 级指标')
else:
    turns = pd.to_numeric(threads['number_of_messages'], errors='coerce').dropna()
    if len(turns):
        metrics.update(turn_mean=round(float(turns.mean()), 3), turn_median=float(turns.median()),
                       turn_p90=_p(turns.to_numpy(), 90))
    durations = pd.to_numeric(threads['duration'], errors='coerce').dropna()
    if len(durations):
        metrics['session_duration_p95'] = round(_p(durations.to_numpy(), 95), 3)
    if 'status' in threads:
        metrics['finished_ratio'] = round(float((threads['status'] == 'finished').mean()), 4)
    else:
        gaps.append('threads 缺少 status：无法计算完成率')
    if 'total_estimated_cost' in threads and threads['total_estimated_cost'].notna().any():
        metrics['cost_total'] = float(pd.to_numeric(threads['total_estimated_cost'],
                                                    errors='coerce').fillna(0).sum())
    else:
        gaps.append('threads 缺少 total_estimated_cost：成本指标不可用')

tool_stats = {}
if spans.empty:
    gaps.append('spans.jsonl 为空：无单步决策数据')
else:
    if 'type' in spans:
        metrics['step_count'] = int(len(spans))
        kinds = Counter(spans['type'].fillna('unknown'))
        metrics['llm_step_ratio'] = round(kinds.get('llm', 0) / len(spans), 4)
    else:
        gaps.append('spans 缺少 type：无法区分 LLM / 工具步骤')

    durations = pd.to_numeric(spans.get('duration'), errors='coerce').dropna() \
        if 'duration' in spans else pd.Series(dtype=float)
    if len(durations):
        metrics.update(latency_p50=round(float(durations.median()), 3),
                       latency_p95=round(_p(durations.to_numpy(), 95), 3))

    if 'error' in spans:
        metrics['error_rate'] = round(float(spans['error'].notna().mean()), 4)
    else:
        gaps.append('spans 缺少 error 字段：错误率按 0 处理')

    if 'total_tokens' in spans and spans['total_tokens'].notna().any():
        metrics['tokens_total'] = int(pd.to_numeric(spans['total_tokens'],
                                                    errors='coerce').fillna(0).sum())
    else:
        gaps.append('spans 缺少 usage/total_tokens：token 指标不可用')

    if 'type' in spans:
        tools = spans[spans['type'] == 'tool']
        tool_stats['calls'] = int(len(tools))
        if len(tools):
            failed = int(tools['error'].notna().sum()) if 'error' in tools else 0
            metrics.update(tool_calls=tool_stats['calls'],
                           tool_success_rate=round(1 - failed / len(tools), 4))
            metrics['tool_names_top'] = dict(Counter(tools['name'].fillna('unknown')).most_common(5))
        # 潜在循环：同一 trace 内同一工具名连续出现 >= RUNNING_LOOP 次
        loops = []
        for trace_id, group in tools.sort_values('start_time').groupby('trace_id'):
            run_name, run_len = None, 0
            for name in group['name'].fillna('unknown'):
                run_len = run_len + 1 if name == run_name else 1
                run_name = name
                if run_len >= RUNNING_LOOP:
                    loops.append({'trace_id': trace_id, 'tool': str(name), 'repeat': run_len})
                    break
        metrics['loop_suspects'] = loops[:10]

Path('out').mkdir(exist_ok=True)
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
if not threads.empty and 'number_of_messages' in threads:
    axes[0].hist(pd.to_numeric(threads['number_of_messages'], errors='coerce').dropna(),
                 bins=min(20, max(3, len(threads))), color='#4C72B0')
    axes[0].set(title='Turns per session', xlabel='turns', ylabel='sessions')
else:
    axes[0].text(.5, .5, 'no thread data', ha='center')
    axes[0].set_axis_off()
if 'tool_success_rate' in metrics:
    axes[1].bar(['success', 'failure'], [metrics['tool_success_rate'],
                                         1 - metrics['tool_success_rate']], color=['#55A868', '#C44E52'])
    axes[1].set(title=f"Tool calls (n={metrics.get('tool_calls', 0)})", ylabel='ratio')
else:
    axes[1].text(.5, .5, 'no tool spans', ha='center')
    axes[1].set_axis_off()
fig.tight_layout()
fig.savefig('out/agent_metrics.png', dpi=120)
summary = {'metrics': metrics, 'gaps': gaps, 'tool_stats': tool_stats}
Path('out/agent_metrics.json').write_text(json.dumps(summary, ensure_ascii=False))
print(json.dumps(summary, ensure_ascii=False))
