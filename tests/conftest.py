import os
import shutil
import subprocess

import pytest


def pytest_ignore_collect(collection_path, config):
    # Legacy tests import a separate MCP 2.x/Opik environment and hit real services.
    return collection_path.name == 'test_mcp_server.py' and os.getenv('RUN_LEGACY_OPIK') != '1'


@pytest.fixture
def engine():
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from app.config import settings
    from app.db import apply_schema, get_engine
    url = settings.TEST_DATABASE_URL
    if not (make_url(url).database or '').endswith('_test'):
        pytest.fail('TEST_DATABASE_URL must target a database ending in _test')
    eng = get_engine(url)
    try:
        with eng.connect() as conn:
            conn.execute(text('SELECT 1'))
    except Exception:
        pytest.skip('Test Postgres unavailable')
    apply_schema(eng)
    with eng.begin() as conn:
        conn.execute(text('TRUNCATE analysis_events, analyses'))
    return eng


@pytest.fixture
def docker_ready():
    from app.config import settings
    if not shutil.which('docker'):
        pytest.skip('Docker unavailable')
    try:
        result = subprocess.run(['docker', 'image', 'inspect', settings.SANDBOX_IMAGE],
                                capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        pytest.skip('Docker unavailable')
    if result.returncode:
        pytest.skip('Build sandbox image first')


@pytest.fixture(autouse=True)
def isolate_artifacts(tmp_path, monkeypatch, request):
    if request.node.path.name == 'test_mcp_server.py':
        return
    from app.config import settings
    monkeypatch.setattr(settings, 'ARTIFACTS_DIR', tmp_path / 'artifacts')
    monkeypatch.setattr(settings, 'MCP_TRANSPORT', 'stdio')
    monkeypatch.setattr(settings, 'MCP_STDIO_CMD', '')
