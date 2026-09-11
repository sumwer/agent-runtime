import json
from pathlib import Path

from langchain_core.tools import tool

from app.config import settings
from app.tools.mcp import call_json, open_session


EXPERIMENT_SOURCES = {'traces', 'scores'}
PROJECT_SOURCES = {'threads', 'spans'}
DATASET_SOURCES = {'dataset_items'}


async def export_data_impl(mcp_cfg, source, experiment_id, workspace, max_rows=5000,
                           filters=None, event_cb=None, dataset_id=''):
    if source not in EXPERIMENT_SOURCES | PROJECT_SOURCES | DATASET_SOURCES:
        raise ValueError(f'source must be one of {sorted(EXPERIMENT_SOURCES | PROJECT_SOURCES | DATASET_SOURCES)}')
    if source in EXPERIMENT_SOURCES and not experiment_id:
        raise ValueError(f'experiment_id is required for source={source}')
    if source in DATASET_SOURCES and not dataset_id:
        raise ValueError(f'dataset_id is required for source={source}')
    if not 1 <= max_rows <= settings.MAX_EXPORT_ROWS:
        raise ValueError(f'max_rows must be between 1 and {settings.MAX_EXPORT_ROWS}')
    filters = filters or {}
    if set(filters) - {'max_score', 'min_score'}:
        raise ValueError('Unsupported filter')
    if source in PROJECT_SOURCES | DATASET_SOURCES and any(value is not None for value in filters.values()):
        raise ValueError('min_score/max_score only apply to traces and scores')
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / f'{source}.jsonl'
    temp = workspace / f'.{source}.jsonl.tmp'
    if target.is_symlink() or temp.is_symlink():
        raise ValueError('Export destination must not be a symlink')
    written, scanned, page, hint = 0, 0, 1, []
    total = None
    truncated = False
    # Scan cap also bounds work when a server cannot filter and every row is rejected.
    scan_cap = settings.MAX_EXPORT_ROWS
    try:
        async with open_session(mcp_cfg) as session:
            definitions = (await session.list_tools()).tools
            definition = next((d for d in definitions if d.name == f'get_{source}'), None)
            if definition is None:
                raise ValueError(f'MCP does not expose get_{source}')
            properties = definition.inputSchema.get('properties', {})
            if not {'page', 'page_size'} <= properties.keys():
                raise ValueError('MCP must support pagination; configure an adapter for this server')
            server_filters = {k: v for k, v in filters.items() if k in properties and v is not None}
            with temp.open('w', encoding='utf-8') as out:
                while scanned < scan_cap and written < max_rows:
                    args = dict(page=page, page_size=100, **server_filters)
                    if source in EXPERIMENT_SOURCES:
                        args['experiment_id'] = experiment_id
                    elif source in DATASET_SOURCES:
                        args['dataset_id'] = dataset_id
                    payload = await call_json(session, f'get_{source}', args, event_cb)
                    items = payload['items']
                    total = int(payload['total'])
                    if not isinstance(items, list) or len(items) > 100 or total < 0:
                        raise ValueError('Invalid MCP pagination response')
                    for row in items:
                        if scanned >= scan_cap or written >= max_rows:
                            break
                        scanned += 1
                        score = row.get('score')
                        if any(value is not None for value in filters.values()) and score is None:
                            raise ValueError('score is required for local filtering')
                        if filters.get('max_score') is not None and score > filters['max_score']:
                            continue
                        if filters.get('min_score') is not None and score < filters['min_score']:
                            continue
                        if not hint:
                            hint = sorted(row)
                        out.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                        written += 1
                    if not items or page * 100 >= total:
                        truncated = scanned < total
                        break
                    page += 1
                else:
                    truncated = total is not None and scanned < total
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    result = {'written': written, 'file': target.name, 'schema_hint': hint,
              'scanned': scanned, 'truncated': truncated}
    if event_cb:
        event_cb({'type': 'export_data', 'source': source, **result})
    return result


def make_export_tool(workspace, mcp_cfg, event_cb=None, exports=None):
    @tool
    async def export_data(source: str, experiment_id: str = '', dataset_id: str = '', max_rows: int = 5000,
                          max_score: float | None = None, min_score: float | None = None) -> dict:
        """Export dataset_items (need dataset_id), traces/scores (need experiment_id), or
        threads/spans (project-wide) directly to workspace JSONL, without sending data to the model.
        threads are multi-turn sessions, spans are LLM/tool decision steps.
        max_rows limits output. Scores use inclusive min_score/max_score filters.
        Report truncated data in the result caveats. Returned file is relative to /workspace.
        """
        result = await export_data_impl(mcp_cfg, source, experiment_id, workspace, max_rows,
                                       {'max_score': max_score, 'min_score': min_score}, event_cb, dataset_id)
        if exports is not None:
            exports[source] = result
        return result
    return export_data
