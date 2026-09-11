import asyncio
import socket
import sys

import httpx

from app.config import ROOT
from app.tools.export_data import export_data_impl


async def test_streamable_http_export(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'mock_mcp.server',
        '--transport', 'streamable-http', '--port', str(port), cwd=ROOT,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}/mcp'
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                try:
                    await client.get(url)
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(.05)
            else:
                raise AssertionError('HTTP mock failed to start')
        result = await export_data_impl({'transport': 'streamable_http', 'url': url},
                                       'traces', 'exp-001', tmp_path, max_rows=5)
        assert result['written'] == 5 and result['truncated']
    finally:
        process.terminate()
        await process.wait()
