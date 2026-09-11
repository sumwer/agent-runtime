import asyncio
import json
from contextlib import asynccontextmanager

from langchain_mcp_adapters.client import MultiServerMCPClient


@asynccontextmanager
async def open_session(cfg):
    # Session setup, use and teardown stay in the same asyncio task (AnyIO cancel scopes).
    client = MultiServerMCPClient({'opik': cfg})
    async with client.session('opik') as session:
        yield session


def decode_result(raw):
    if raw.isError:
        raise RuntimeError('MCP tool returned an error')
    if raw.structuredContent is not None:
        payload = raw.structuredContent
        return payload.get('result', payload)
    blocks = [b.text for b in raw.content if getattr(b, 'type', '') == 'text']
    if len(blocks) != 1:
        raise ValueError('Expected one JSON MCP text block')
    return json.loads(blocks[0])


async def call_json(session, name, args, event_cb=None):
    for attempt in range(3):
        try:
            raw = await session.call_tool(name, args)
            result = decode_result(raw)
            if event_cb:
                event_cb({'type': 'mcp_call', 'tool': name, 'attempt': attempt + 1, 'ok': True})
            return result
        except Exception as exc:
            if event_cb:
                event_cb({'type': 'mcp_call', 'tool': name, 'attempt': attempt + 1,
                          'ok': False, 'error_type': type(exc).__name__})
            if attempt == 2:
                raise RuntimeError(f'MCP {name} failed after 2 retries') from exc
            await asyncio.sleep(0.1 * (attempt + 1))
