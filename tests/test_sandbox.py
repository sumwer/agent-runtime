import asyncio
import subprocess

import pytest

from app.config import settings
from app.tools.sandbox import RetryLimitError, make_sandbox_tool, run_in_sandbox_impl


async def test_isolation_limits_and_artifacts(tmp_path, docker_ready):
    code = '''from pathlib import Path
import socket, subprocess
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == '1073741824'
assert Path('/sys/fs/cgroup/pids.max').read_text().strip() == '128'
assert Path('/sys/fs/cgroup/cpu.max').read_text().strip() == '100000 100000'
try:
    socket.create_connection(('1.1.1.1', 80), timeout=1)
except OSError:
    pass
else:
    raise AssertionError('network is enabled')
assert subprocess.run(['python', '-m', 'pip', '--version'], capture_output=True).returncode != 0
Path('out/hello.txt').write_text('hello')
print('verified')
'''
    result = await run_in_sandbox_impl(code, tmp_path, settings.SANDBOX_IMAGE, 15)
    assert result['exit_code'] == 0, result['stderr']
    assert result['artifacts'] == ['out/hello.txt']


async def test_timeout_and_memory_enforced(tmp_path, docker_ready):
    result = await run_in_sandbox_impl('import time; time.sleep(30)', tmp_path, settings.SANDBOX_IMAGE, 1)
    assert result['exit_code'] != 0
    result = await run_in_sandbox_impl('x = bytearray(2 * 1024**3)', tmp_path, settings.SANDBOX_IMAGE, 15)
    assert result['exit_code'] != 0


async def test_cancellation_removes_container(tmp_path, docker_ready):
    def names():
        return set(subprocess.check_output(['docker', 'ps', '-aq', '--filter',
                    'label=agent-runtime.sandbox=true'], text=True).split())
    before = names()
    task = asyncio.create_task(run_in_sandbox_impl('import time; time.sleep(60)',
                                                  tmp_path, settings.SANDBOX_IMAGE, 120))
    await asyncio.sleep(1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert names() == before


async def test_retry_limit(tmp_path, monkeypatch):
    async def failed(*args):
        return {'exit_code': 1, 'script': 'script.py', 'artifacts': [], 'stderr': 'bad', 'stdout': ''}
    monkeypatch.setattr('app.tools.sandbox.run_in_sandbox_impl', failed)
    tool = make_sandbox_tool(tmp_path)
    for _ in range(3):
        await tool.ainvoke({'code': 'bad'})
    with pytest.raises(RetryLimitError):
        await tool.ainvoke({'code': 'bad'})
