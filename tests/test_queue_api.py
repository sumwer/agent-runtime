from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import queue
from app.config import settings
from app.main import create_app


def test_claim_skips_actual_lock(engine):
    first = queue.create_analysis('one', engine=engine)
    second = queue.create_analysis('two', engine=engine)
    with engine.begin() as conn:
        conn.execute(text('SELECT id FROM analyses WHERE id=CAST(:id AS uuid) FOR UPDATE'), {'id': first})
        assert queue.claim_next(engine)['id'] == second
    assert queue.claim_next(engine)['id'] == first


def test_concurrent_claim_exactly_once(engine):
    ids = {queue.create_analysis(str(i), engine=engine) for i in range(12)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        claimed = list(pool.map(lambda _: queue.claim_next(engine), range(18)))
    actual = [r['id'] for r in claimed if r]
    assert len(actual) == len(set(actual)) == 12
    assert set(actual) == ids


def test_list_analyses_with_and_without_status(engine):
    with TestClient(create_app(engine)) as client:
        client.post('/analyses', json={'task': 'listed'})
        rows = client.get('/analyses').json()
        assert [row['task'] for row in rows] == ['listed']
        assert [row['task'] for row in client.get('/analyses?status=queued').json()] == ['listed']
        assert client.get('/analyses?status=succeeded').json() == []


def test_api_and_artifact_containment(engine):
    with TestClient(create_app(engine)) as client:
        response = client.post('/analyses', json={'task': 'analyze'})
        assert response.status_code == 202
        aid = response.json()['analysis_id']
        assert client.get(f'/analyses/{aid}').json()['status'] == 'queued'
        assert len(client.get('/skills').json()) == 4
        assert client.get('/analyses/not-a-uuid').status_code == 422
        assert client.get('/analyses?limit=-1').status_code == 422
        base = settings.ARTIFACTS_DIR / aid
        base.mkdir(parents=True)
        (base / 'result.json').write_text('{}')
        sibling = settings.ARTIFACTS_DIR / f'{aid}-other'
        sibling.mkdir()
        (sibling / 'secret.txt').write_text('secret')
        (base / 'link').symlink_to(sibling / 'secret.txt')
        assert client.get(f'/analyses/{aid}/artifacts/result.json').status_code == 200
        assert client.get(f'/analyses/{aid}/artifacts/link').status_code == 404
        assert client.get(f'/analyses/{aid}/artifacts/%2E%2E%2F{aid}-other%2Fsecret.txt').status_code == 404


def test_stale_worker_and_terminal_transition(engine):
    aid = queue.create_analysis('stale', engine=engine)
    queue.claim_next(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE analyses SET heartbeat_at=now()-interval '5 minutes'"))
    assert queue.fail_stale(engine) == 1
    assert queue.get_analysis(aid, engine)['status'] == 'failed'
    assert queue.set_status(aid, 'succeeded', result={}, engine=engine) == 0
