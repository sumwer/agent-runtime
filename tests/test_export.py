import json

import pytest

from app.config import settings
from app.tools.export_data import export_data_impl
from app.tools.mcp import call_json, open_session


async def test_mock_stdio_and_paging():
    async with open_session(settings.mcp_config()) as session:
        exps = await call_json(session, 'list_experiments', {})
        assert {e['id'] for e in exps} == {'exp-001', 'exp-002'}
        page = await call_json(session, 'get_traces', {'experiment_id': 'exp-001', 'page': 2, 'page_size': 100})
        assert page['total'] == 200 and len(page['items']) == 100


async def test_export_filter_and_cap(tmp_path):
    cfg = settings.mcp_config()
    result = await export_data_impl(cfg, 'traces', 'exp-001', tmp_path, filters={'max_score': .5})
    assert result['written'] == 75 and not result['truncated']
    assert set(result) == {'written', 'file', 'schema_hint', 'scanned', 'truncated'}
    assert all(json.loads(line)['score'] <= .5 for line in (tmp_path / 'traces.jsonl').read_text().splitlines())
    result = await export_data_impl(cfg, 'scores', 'exp-001', tmp_path, max_rows=80)
    assert result['written'] == 80 and result['truncated']


async def test_local_filter_on_scores(tmp_path):
    result = await export_data_impl(settings.mcp_config(), 'scores', 'exp-001', tmp_path,
                                   filters={'max_score': .5})
    assert result['written'] == 75


async def test_mcp_failure_retries():
    class Broken:
        calls = 0
        async def call_tool(self, *args):
            self.calls += 1
            raise ConnectionError('broken')
    session = Broken()
    with pytest.raises(RuntimeError):
        await call_json(session, 'get_traces', {})
    assert session.calls == 3
