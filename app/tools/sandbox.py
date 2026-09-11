import asyncio
import os
from pathlib import Path
from uuid import uuid4

from langchain_core.tools import tool

from app.config import settings


class RetryLimitError(RuntimeError):
    pass


async def _drain(reader):
    tail = b''
    while chunk := await reader.read(16384):
        tail = (tail + chunk)[-8000:]
    return tail.decode('utf-8', errors='replace')


async def _remove_container(name):
    proc = await asyncio.create_subprocess_exec('docker', 'rm', '-f', name,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(proc.wait(), 10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def run_in_sandbox_impl(code, workspace, image, timeout_s=120, script_name='script.py'):
    workspace = Path(workspace).resolve()
    if Path(script_name).name != script_name or not script_name.endswith('.py'):
        raise ValueError('Invalid script name')
    workspace.mkdir(parents=True, exist_ok=True)
    out = workspace / 'out'
    script = workspace / script_name
    if out.is_symlink() or script.is_symlink():
        raise ValueError('Sandbox path cannot be a symlink')
    out.mkdir(exist_ok=True)
    script.write_text(code, encoding='utf-8')
    before = {p.relative_to(workspace).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
              for p in out.rglob('*') if p.is_file() and not p.is_symlink()}
    name = f'agent-sandbox-{uuid4().hex}'
    cmd = ['docker', 'run', '--rm', '--name', name,
           '--label', 'agent-runtime.sandbox=true', '--network', 'none', '--memory', '1g',
           '--memory-swap', '1g', '--cpus', '1', '--pids-limit', '128', '--cap-drop', 'ALL',
           '--security-opt', 'no-new-privileges', '--read-only',
           '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m',
           '--user', f'{os.getuid()}:{os.getgid()}' if hasattr(os, 'getuid') else '1000:1000',
           '-v', f'{workspace}:/workspace', '-w', '/workspace', image,
           'timeout', str(timeout_s), 'python', script_name]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
    stdout_task = asyncio.create_task(_drain(proc.stdout))
    stderr_task = asyncio.create_task(_drain(proc.stderr))
    try:
        try:
            await asyncio.wait_for(proc.wait(), timeout_s + 10)
        except asyncio.TimeoutError:
            await _remove_container(name)
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            return {'exit_code': -1, 'stdout': await stdout_task, 'stderr': 'host timeout',
                    'script': script_name, 'artifacts': []}
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        artifacts = []
        for p in out.rglob('*'):
            if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(out):
                continue
            relative = p.relative_to(workspace).as_posix()
            if before.get(relative) != (p.stat().st_mtime_ns, p.stat().st_size):
                artifacts.append(relative)
        return {'exit_code': proc.returncode, 'stdout': stdout, 'stderr': stderr,
                'script': script_name, 'artifacts': sorted(artifacts)}
    finally:
        # Removing the named container is necessary even if the client was cancelled.
        await asyncio.shield(_remove_container(name))
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)


def make_sandbox_tool(workspace, event_cb=None, runs=None):
    counter, failures = 0, 0

    @tool
    async def run_in_sandbox(code: str) -> dict:
        """Execute generated Python in an isolated Docker container (no network, 1 CPU, 1 GiB).
        Read JSONL in /workspace; write charts into out/. On failure fix stderr and retry at
        most 3 times. Installed libraries: pandas, numpy, matplotlib, scipy. No pip installs.
        """
        nonlocal counter, failures
        counter += 1
        result = await run_in_sandbox_impl(code, workspace, settings.SANDBOX_IMAGE,
            settings.SANDBOX_TIMEOUT_SECONDS, f'script_{counter}.py')
        failures = failures + 1 if result['exit_code'] else 0
        if runs is not None:
            runs.append(result)
        if event_cb:
            event_cb({'type': 'sandbox_run', 'script': result['script'],
                      'exit_code': result['exit_code'], 'artifacts': result['artifacts'],
                      'consecutive_failures': failures})
        if failures >= 4:
            raise RetryLimitError('Sandbox script failed after 3 retries')
        return result
    return run_in_sandbox
