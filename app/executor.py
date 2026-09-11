import asyncio
import json
import logging
import signal
from pathlib import Path

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph

from app import queue
from app.config import settings
from app.db import apply_schema, get_engine
from app.llm import get_chat_model
from app.prompts import build_system_prompt
from app.schemas import AnalysisResult
from app.skills_loader import make_skill_tools
from app.tools.export_data import make_export_tool
from app.tools.mcp import call_json, open_session
from app.tools.sandbox import RetryLimitError, make_sandbox_tool

log = logging.getLogger(__name__)


class ResultCollector:
    def __init__(self, workspace=None, loaded=None, exports=None, runs=None):
        self.result = None
        self.errors = 0
        self.workspace = workspace
        self.loaded = loaded
        self.exports = exports
        self.runs = runs


def make_submit_tool(collector):
    @tool
    def submit_result(result_json: str) -> dict:
        """Submit the final AnalysisResult JSON string. Success terminates the task immediately.
        Required: skill_id, summary, findings, metrics.sample_count, charts, caveats.
        """
        try:
            result = AnalysisResult.model_validate_json(result_json)
            if collector.loaded is not None and result.skill_id not in collector.loaded:
                raise ValueError('Load the selected skill before submitting')
            if collector.runs is not None and not any(r['exit_code'] == 0 for r in collector.runs):
                raise ValueError('At least one successful sandbox analysis is required')
            if collector.exports is not None:
                if not collector.exports:
                    raise ValueError('Export data before submitting')
                if result.metrics['sample_count'] > max(r['written'] for r in collector.exports.values()):
                    raise ValueError('sample_count exceeds exported data')
                if any(r['truncated'] for r in collector.exports.values()) and not result.caveats.strip():
                    raise ValueError('Truncated exports require caveats')
            if collector.workspace:
                root = Path(collector.workspace).resolve()
                for chart in result.charts:
                    target = (root / chart).resolve()
                    if not target.is_relative_to(root / 'out') or not target.is_file():
                        raise ValueError(f'Chart missing or outside workspace: {chart}')
            collector.result = result
            return {'ok': True}
        except ValueError as exc:
            collector.errors += 1
            if collector.errors >= 2:
                raise RetryLimitError('Result validation failed twice') from exc
            return {'ok': False, 'errors': str(exc)[:2000]}
    return submit_result


def make_discovery_tools(cfg, event_cb):
    @tool
    async def list_experiments() -> list:
        """Discover available experiments (at most 20 summaries)."""
        async with open_session(cfg) as session:
            return (await call_json(session, 'list_experiments', {}, event_cb))[:20]

    @tool
    async def list_datasets() -> list:
        """Discover evaluation datasets before choosing one for distribution analysis."""
        async with open_session(cfg) as session:
            return (await call_json(session, 'list_datasets', {}, event_cb))[:20]

    @tool
    async def sample_dataset_items(dataset_id: str) -> dict:
        """Read three raw dataset items to inspect the field schema before bulk export."""
        async with open_session(cfg) as session:
            payload = await call_json(session, 'get_dataset_items',
                {'dataset_id': dataset_id, 'page': 1, 'page_size': 3}, event_cb)
            return {'total': payload['total'], 'items': payload['items'][:3]}

    @tool
    async def sample_traces(experiment_id: str) -> dict:
        """Read three sample traces to understand the schema. Use export_data for bulk data."""
        async with open_session(cfg) as session:
            payload = await call_json(session, 'get_traces',
                {'experiment_id': experiment_id, 'page': 1, 'page_size': 3}, event_cb)
            return {'total': payload['total'], 'items': payload['items'][:3]}
    return [list_experiments, sample_traces, list_datasets, sample_dataset_items]


def build_graph(model, tools, collector, prompt, event_cb):
    bound = model.bind_tools(tools)
    by_name = {t.name: t for t in tools}

    async def agent_node(state):
        response = await bound.ainvoke([SystemMessage(content=prompt), *state['messages']])
        event_cb({'type': 'agent_step', 'tool_names': [t['name'] for t in response.tool_calls]})
        return {'messages': [response]}

    async def tools_node(state):
        messages = []
        # Sequential execution makes resource accounting and immediate submit termination exact.
        for call in state['messages'][-1].tool_calls:
            name = call['name']
            if name not in by_name:
                result = {'error': f'Unknown tool: {name}'}
            else:
                try:
                    if name not in {'list_skills', 'read_skill', 'list_experiments', 'sample_traces',
                                    'list_datasets', 'sample_dataset_items', 'submit_result'}:
                        if collector.loaded is not None and not collector.loaded:
                            raise ValueError('read_skill must be called first')
                    result = await by_name[name].ainvoke(call['args'])
                except (ValueError, TypeError) as exc:
                    result = {'error': str(exc)[:2000]}
            messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False),
                                        tool_call_id=call['id'], name=name))
            if collector.result is not None:
                break
        return {'messages': messages}

    graph = StateGraph(MessagesState)
    graph.add_node('agent', agent_node)
    graph.add_node('tools', tools_node)
    graph.add_edge(START, 'agent')
    graph.add_conditional_edges('agent', lambda s: 'tools' if s['messages'][-1].tool_calls else END)
    graph.add_conditional_edges('tools', lambda s: END if collector.result is not None else 'agent')
    return graph.compile()


async def default_agent_factory(analysis, workspace, event_cb):
    loaded, exports, runs = set(), {}, []
    collector = ResultCollector(workspace, loaded, exports, runs)
    skill_tools, lines = make_skill_tools(settings.SKILLS_DIR, loaded)
    cfg = settings.mcp_config()
    tools = [*skill_tools, *make_discovery_tools(cfg, event_cb),
             make_export_tool(workspace, cfg, event_cb, exports),
             make_sandbox_tool(workspace, event_cb, runs), make_submit_tool(collector)]
    return build_graph(get_chat_model(), tools, collector, build_system_prompt(lines), event_cb), collector, None


async def execute_analysis(analysis, engine=None, agent_factory=None):
    aid = str(analysis['id'])
    workspace = settings.ARTIFACTS_DIR.resolve() / aid / 'workspace'

    def event_cb(event):
        try:
            queue.append_event(aid, event, engine=engine)
        except Exception:
            log.exception('Could not write task event %s', aid)

    async def beat():
        while True:
            await asyncio.sleep(10)
            await asyncio.to_thread(queue.heartbeat, aid, engine)

    async def run():
        workspace.mkdir(parents=True, exist_ok=True)
        closer = None
        try:
            agent, collector, closer = await (agent_factory or default_agent_factory)(analysis, workspace, event_cb)
            message = json.dumps({'task': analysis['task'], 'experiment_id': analysis.get('experiment_id'),
                                  'params': analysis.get('params', {})}, ensure_ascii=False)
            await agent.ainvoke({'messages': [('user', message)]},
                               config={'recursion_limit': settings.RECURSION_LIMIT})
            if collector.result is None:
                raise RuntimeError('Agent ended without a valid submit_result')
            return collector.result
        finally:
            if closer:
                await closer()

    heartbeat = asyncio.create_task(beat())
    event_cb({'type': 'agent_started'})
    try:
        # Includes factory/MCP setup, model calls, tools and teardown.
        result = await asyncio.wait_for(run(), settings.TASK_TIMEOUT_SECONDS)
        payload = result.model_dump()
        target = workspace.parent / 'result.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(target)
        queue.set_status(aid, 'succeeded', result=payload, skill_used=result.skill_id, engine=engine)
    except asyncio.CancelledError:
        queue.set_status(aid, 'failed', error='Worker stopped', engine=engine)
        raise
    except Exception as exc:
        error = f'Task exceeded {settings.TASK_TIMEOUT_SECONDS}s' if isinstance(exc, TimeoutError) else f'{type(exc).__name__}: {exc}'
        queue.set_status(aid, 'failed', error=error[:2000], engine=engine)
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        event_cb({'type': 'agent_finished'})


async def run_worker_loop():
    engine = get_engine()
    apply_schema(engine)

    async def slot():
        while True:
            try:
                await asyncio.to_thread(queue.fail_stale, engine)
                analysis = await asyncio.to_thread(queue.claim_next, engine)
                if analysis:
                    await execute_analysis(analysis, engine)
                else:
                    await asyncio.sleep(1)
            except Exception as exc:
                log.warning('Worker iteration failed (%s); retrying', type(exc).__name__)
                await asyncio.sleep(2)

    tasks = [asyncio.create_task(slot()) for _ in range(settings.WORKER_CONCURRENCY)]
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: [t.cancel() for t in tasks])
        except NotImplementedError:
            pass
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker_loop())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
