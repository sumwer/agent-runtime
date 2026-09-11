import json
from uuid import uuid4

from sqlalchemy import text

from app.db import get_engine


def create_analysis(task, experiment_id=None, created_by=None, params=None, engine=None):
    aid = str(uuid4())
    with (engine or get_engine()).begin() as conn:
        conn.execute(text('''INSERT INTO analyses(id,task,experiment_id,created_by,params)
            VALUES (CAST(:id AS uuid),:task,:experiment_id,:created_by,CAST(:params AS jsonb))'''),
            dict(id=aid, task=task, experiment_id=experiment_id, created_by=created_by,
                 params=json.dumps(params or {})))
    return aid


def _row(row):
    if row is None:
        return None
    result = dict(row)
    result['id'] = str(result['id'])
    return result


def claim_next(engine=None):
    with (engine or get_engine()).begin() as conn:
        return _row(conn.execute(text('''UPDATE analyses SET status='running',
            started_at=now(), heartbeat_at=now()
            WHERE id=(SELECT id FROM analyses WHERE status='queued'
                ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING *''')).mappings().first())


def set_status(analysis_id, status, *, error=None, result=None, skill_used=None, engine=None):
    if status not in {'succeeded', 'failed'}:
        raise ValueError('Only terminal transitions are supported')
    with (engine or get_engine()).begin() as conn:
        return conn.execute(text('''UPDATE analyses SET status=:status,error=:error,
            result=CAST(:result AS jsonb),skill_used=:skill,finished_at=now()
            WHERE id=CAST(:id AS uuid) AND status='running' '''),
            dict(id=str(analysis_id), status=status, error=error,
                 result=json.dumps(result) if result is not None else None, skill=skill_used)).rowcount


def get_analysis(analysis_id, engine=None):
    with (engine or get_engine()).connect() as conn:
        return _row(conn.execute(text('SELECT * FROM analyses WHERE id=CAST(:id AS uuid)'),
                                 {'id': str(analysis_id)}).mappings().first())


def list_analyses(status=None, limit=50, engine=None):
    with (engine or get_engine()).connect() as conn:
        # Filter is appended only when given: ":status IS NULL" leaves psycopg unable to
        # infer the parameter type and the listing 500s.
        sql = 'SELECT * FROM analyses'
        params = {'limit': limit}
        if status is not None:
            sql += ' WHERE status=:status'
            params['status'] = status
        sql += ' ORDER BY created_at DESC LIMIT :limit'
        return [_row(r) for r in conn.execute(text(sql), params).mappings()]


def append_event(analysis_id, event, engine=None):
    with (engine or get_engine()).begin() as conn:
        conn.execute(text('''INSERT INTO analysis_events(analysis_id,event)
            VALUES(CAST(:id AS uuid),CAST(:event AS jsonb))'''),
            {'id': str(analysis_id), 'event': json.dumps(event, default=str)})


def list_events(analysis_id, limit=200, engine=None):
    with (engine or get_engine()).connect() as conn:
        return [dict(r) for r in conn.execute(text('''SELECT id,ts,event FROM analysis_events
            WHERE analysis_id=CAST(:id AS uuid) ORDER BY id LIMIT :limit'''),
            {'id': str(analysis_id), 'limit': limit}).mappings()]


def heartbeat(analysis_id, engine=None):
    with (engine or get_engine()).begin() as conn:
        conn.execute(text("UPDATE analyses SET heartbeat_at=now() WHERE id=CAST(:id AS uuid) AND status='running'"),
                     {'id': str(analysis_id)})


def fail_stale(engine=None, seconds=90):
    with (engine or get_engine()).begin() as conn:
        return conn.execute(text('''UPDATE analyses SET status='failed',finished_at=now(),
            error='worker heartbeat expired; submit a new task'
            WHERE status='running' AND heartbeat_at < now()-(:seconds * interval '1 second')'''),
            {'seconds': seconds}).rowcount
