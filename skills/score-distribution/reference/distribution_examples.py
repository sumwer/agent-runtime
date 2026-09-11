import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

rows = [json.loads(line) for line in Path('traces.jsonl').read_text().splitlines() if line.strip()]
scores = np.array([row['score'] for row in rows])
stats = {'sample_count': len(scores)}
# 真实 Opik 的维度在 metadata 里；没有 metadata 时只报总体分布。
for dimension in ('category', 'age_band'):
    buckets: dict[str, list[float]] = {}
    for row in rows:
        meta = row.get('metadata')
        name = (meta or {}).get(dimension) if isinstance(meta, dict) else None
        buckets.setdefault(name or 'unknown', []).append(row['score'])
    if any(name != 'unknown' for name in buckets):
        stats[f'by_{dimension}'] = {
            name: {'count': len(values), 'mean': round(float(np.mean(values)), 4),
                   'low_score_ratio': round(float((np.array(values) < .5).mean()), 4)}
            for name, values in sorted(buckets.items())}
if len(scores):
    stats.update(mean=float(scores.mean()), std=float(scores.std()),
                 low_score_ratio=float((scores < .5).mean()))
    stats.update({f'p{p}': float(np.percentile(scores, p)) for p in [5, 25, 50, 75, 95]})
Path('out').mkdir(exist_ok=True)
fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(scores, bins=30, color='#4C72B0')
ax.set(title='Score distribution', xlabel='Score', ylabel='Count')
fig.tight_layout()
fig.savefig('out/hist.png', dpi=120)
print(json.dumps(stats))
