import random


def build():
    rng = random.Random(42)
    data = {}
    for eid, count in [('exp-001', 200), ('exp-002', 150)]:
        rows = []
        for i in range(count):
            kind = ('timeout' if i < 30 else 'wrong_format' if i < 55 else 'refusal' if i < 75 else None)
            rows.append({'id': f'{eid}-t{i:04d}', 'experiment_id': eid,
                         'input': f'订单查询 {i}',
                         'output': {'timeout': '响应超时', 'wrong_format': '非法格式',
                                    'refusal': '抱歉，无法回答', None: '订单已发货'}[kind],
                         'error_type': kind,
                         'score': round(rng.uniform(0.05, 0.4) if kind else rng.uniform(0.6, 0.98), 3),
                         'latency_ms': rng.randint(3000, 9000) if kind == 'timeout' else rng.randint(300, 1500),
                         'test_group': 'A' if i % 2 else 'B'})
        rng.shuffle(rows)
        data[eid] = {'name': f'客服-agent-{eid}', 'traces': rows}
    return data
