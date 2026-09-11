import json

import pytest

from app.executor import ResultCollector, make_submit_tool
from app.schemas import AnalysisResult
from app.skills_loader import load_skill_body, scan_skills
from app.config import Settings, settings
from app.tools.sandbox import RetryLimitError

VALID = {'skill_id': 'badcase-analysis', 'summary': 'summary', 'findings': [],
         'metrics': {'sample_count': 0}}


@pytest.mark.parametrize('metrics', [{}, {'sample_count': -1}, {'sample_count': .5},
                                     {'sample_count': float('nan')}, {'sample_count': 1, 'mean': float('inf')}])
def test_reject_invalid_metrics(metrics):
    with pytest.raises(ValueError):
        AnalysisResult.model_validate({**VALID, 'metrics': metrics})


@pytest.mark.parametrize('chart', ['../x', '/out/x', 'out/../../x', 'out\\x'])
def test_reject_chart_escape(chart):
    with pytest.raises(ValueError):
        AnalysisResult.model_validate({**VALID, 'charts': [chart]})


def test_load_references():
    assert len(scan_skills(settings.SKILLS_DIR)) == 3
    assert 'fig.savefig' in load_skill_body('badcase-analysis', settings.SKILLS_DIR)
    agent_metrics = load_skill_body('agent-metrics', settings.SKILLS_DIR)
    assert 'fig.savefig' in agent_metrics and 'threads.jsonl' in agent_metrics


def test_validation_retry_limit():
    submit = make_submit_tool(ResultCollector())
    assert not submit.invoke({'result_json': '{}'})['ok']
    with pytest.raises(RetryLimitError):
        submit.invoke({'result_json': '{}'})


def test_submit_requires_real_chart(tmp_path):
    collector = ResultCollector(workspace=tmp_path)
    submit = make_submit_tool(collector)
    assert not submit.invoke({'result_json': json.dumps({**VALID, 'charts': ['out/missing.png']})})['ok']


def test_legacy_model_and_explicit_override():
    assert Settings(_env_file=None, ANTHROPIC_MODEL='deepseek-chat[1m]').MODEL == 'deepseek-chat'
    assert Settings(_env_file=None, MODEL='explicit', ANTHROPIC_MODEL='legacy').MODEL == 'explicit'
