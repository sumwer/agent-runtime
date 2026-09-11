import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app import queue
from app.config import settings
from app.executor import ResultCollector, build_graph, execute_analysis, make_submit_tool
from app.schemas import AnalysisResult

VALID = {'skill_id': 'badcase-analysis', 'summary': 'summary', 'findings': [],
         'metrics': {'sample_count': 0}}


async def test_submit_ends_graph_before_next_tool():
    collector = ResultCollector()
    effects = []

    @tool
    def unwanted() -> str:
        """Must never be called after submit."""
        effects.append(True)
        return 'bad'

    class Model:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return AIMessage(content='', tool_calls=[
                {'name': 'submit_result', 'args': {'result_json': json.dumps(VALID)}, 'id': '1'},
                {'name': 'unwanted', 'args': {}, 'id': '2'}])

    graph = build_graph(Model(), [make_submit_tool(collector), unwanted], collector, 'test', lambda _: None)
    await graph.ainvoke({'messages': [('user', 'go')]})
    assert collector.result and not effects


async def test_setup_included_in_deadline(engine, monkeypatch):
    monkeypatch.setattr(settings, 'TASK_TIMEOUT_SECONDS', .05)
    aid = queue.create_analysis('timeout', engine=engine)
    analysis = queue.claim_next(engine)
    async def slow(*args):
        await asyncio.sleep(10)
    await execute_analysis(analysis, engine, slow)
    row = queue.get_analysis(aid, engine)
    assert row['status'] == 'failed' and 'exceeded' in row['error']


async def test_result_persisted(engine):
    aid = queue.create_analysis('fake', engine=engine)
    analysis = queue.claim_next(engine)
    async def factory(*args):
        collector = ResultCollector()
        class Agent:
            async def ainvoke(self, *args, **kwargs):
                collector.result = AnalysisResult.model_validate(VALID)
        return Agent(), collector, None
    await execute_analysis(analysis, engine, factory)
    assert queue.get_analysis(aid, engine)['status'] == 'succeeded'
    path = settings.ARTIFACTS_DIR / aid / 'result.json'
    assert json.loads(path.read_text())['metrics']['sample_count'] == 0
    assert len(queue.list_events(aid, engine=engine)) == 2
