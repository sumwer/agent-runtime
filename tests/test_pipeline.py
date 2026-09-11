import json
import os

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import executor, queue
from app.config import settings
from app.main import create_app


@pytest.mark.parametrize('skill,chart,expected', [('badcase-analysis', 'groups.png', 75),
                                               ('score-distribution', 'hist.png', 200)])
async def test_full_pipeline_without_api_key(engine, docker_ready, monkeypatch, skill, chart, expected):
    # Scripted model still runs the production LangGraph, MCP transport, Docker and result validation.
    ref = next((settings.SKILLS_DIR / skill / 'reference').glob('*.py')).read_text()
    filters = {'max_score': .5} if skill == 'badcase-analysis' else {}
    class ScriptedModel:
        step = 0
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            calls = [
                ('read_skill', {'name': skill}),
                ('export_data', {'source': 'traces', 'experiment_id': 'exp-001', **filters}),
                ('run_in_sandbox', {'code': ref})]
            if self.step < len(calls):
                name, args = calls[self.step]
            else:
                sandbox = json.loads(messages[-1].content)
                stats = json.loads(sandbox['stdout'].strip().splitlines()[-1])
                name, args = 'submit_result', {'result_json': json.dumps({
                    'skill_id': skill, 'summary': 'Fixture analysis',
                    'findings': [{'title': 'Samples', 'detail': f"Analyzed {stats['sample_count']} rows"}],
                    'metrics': {k: v for k, v in stats.items() if isinstance(v, (int, float))},
                    'charts': [f'out/{chart}'], 'caveats': 'Deterministic mock data'})}
            self.step += 1
            return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': str(self.step)}])

    monkeypatch.setattr(executor, 'get_chat_model', ScriptedModel)
    with TestClient(create_app(engine)) as client:
        aid = client.post('/analyses', json={'task': skill, 'experiment_id': 'exp-001'}).json()['analysis_id']
        await executor.execute_analysis(queue.claim_next(engine), engine)
        row = client.get(f'/analyses/{aid}').json()
        assert row['status'] == 'succeeded', row['error']
        assert row['result']['metrics']['sample_count'] == expected
        image = client.get(f'/analyses/{aid}/artifacts/workspace/out/{chart}')
        assert image.status_code == 200 and image.content.startswith(b'\x89PNG')


@pytest.mark.e2e
@pytest.mark.skipif(os.getenv('RUN_LLM_E2E') != '1', reason='Set RUN_LLM_E2E=1 for paid model calls')
async def test_real_model_badcase(engine, docker_ready):
    aid = queue.create_analysis('分析 exp-001 的 bad case，阈值0.5，生成分组图表和改进建议',
                                'exp-001', engine=engine)
    await executor.execute_analysis(queue.claim_next(engine), engine)
    row = queue.get_analysis(aid, engine)
    assert row['status'] == 'succeeded', row['error']
    assert row['result']['skill_id'] == 'badcase-analysis'
    assert row['result']['metrics']['sample_count'] == 75
    assert row['result']['charts']
