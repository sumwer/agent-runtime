import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

rows = [json.loads(line) for line in Path('traces.jsonl').read_text().splitlines() if line.strip()]
df = pd.DataFrame(rows)
groups = {}
if not df.empty:
    # 真实 Opik 数据在 metadata.category；mock 数据在 error_type；都没有时按分数分桶。
    if 'metadata' in df:
        df['category'] = df['metadata'].apply(
            lambda m: (m or {}).get('category') if isinstance(m, dict) else None)
    key = None
    for candidate in ('category', 'error_type'):
        if candidate in df and df[candidate].notna().any():
            key = candidate
            break
    if key is None:
        df['score_bucket'] = pd.cut(df['score'], [-1, .2, .35, 1],
                                    labels=['below_0.2', '0.2_to_0.35', 'above_0.35'])
        key = 'score_bucket'
    df[key] = df[key].astype('object').fillna('other')
    examples_col = 'trace_id' if 'trace_id' in df else 'id'
    for label, group in df.groupby(key):
        groups[str(label)] = {'count': len(group), 'mean_score': float(group['score'].mean()),
                              'examples': group[examples_col].head(2).tolist()}
Path('out').mkdir(exist_ok=True)
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(list(groups), [g['count'] for g in groups.values()], color='#4C72B0')
ax.set(title='Bad case groups', ylabel='Count')
fig.tight_layout()
fig.savefig('out/groups.png', dpi=120)
summary = {'sample_count': len(rows), 'group_count': len(groups), 'group_key': key, 'groups': groups}
Path('out/groups.json').write_text(json.dumps(summary, ensure_ascii=False))
print(json.dumps(summary, ensure_ascii=False))
