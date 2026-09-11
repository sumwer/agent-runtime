"""Reference analysis for dataset-distribution; run from /workspace."""
import json
import re
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


rows = [json.loads(line) for line in Path('dataset_items.jsonl').read_text(encoding='utf-8').splitlines()]


def text_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ('question', 'prompt', 'query', 'input', 'task'):
            if isinstance(value.get(key), str):
                return value[key]
    return ''


def normalise(value):
    return re.sub(r'\s+', ' ', value.strip().casefold())


texts = [text_of(row.get('input')) for row in rows]
lengths = [len(text) for text in texts if text]
duplicates = Counter(normalise(text) for text in texts if normalise(text))
duplicate_rows = sum(count - 1 for count in duplicates.values() if count > 1)
missing_expected = sum(row.get('expected_output') in (None, '', {}) for row in rows)
categories = Counter()
for row in rows:
    metadata = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
    value = metadata.get('category') or metadata.get('task_type') or metadata.get('domain')
    if value is not None:
        categories[str(value)] += 1
    for tag in row.get('tags') or []:
        categories[f'tag:{tag}'] += 1

sample_count = len(rows)
metrics = {
    'sample_count': sample_count,
    'duplicate_ratio': duplicate_rows / sample_count if sample_count else 0,
    'missing_expected_output_ratio': missing_expected / sample_count if sample_count else 0,
    'category_count': len(categories),
    'largest_category_ratio': max(categories.values()) / sample_count if categories and sample_count else 0,
}
print(json.dumps(metrics, ensure_ascii=False))

Path('out').mkdir(exist_ok=True)
if categories:
    labels, values = zip(*categories.most_common(12))
    plt.figure(figsize=(10, 5))
    plt.bar(labels, values)
    plt.xticks(rotation=35, ha='right')
    plt.ylabel('items')
    plt.title('Dataset category / tag distribution')
else:
    plt.figure(figsize=(8, 5))
    plt.hist(lengths, bins=min(20, max(1, len(lengths))))
    plt.xlabel('input characters')
    plt.ylabel('items')
    plt.title('Dataset input length distribution')
plt.tight_layout()
plt.savefig('out/dataset_distribution.png', dpi=150)
