import hmac
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import queue
from app.config import settings
from app.db import apply_schema, get_engine
from app.skills_loader import scan_skills


class AnalysisIn(BaseModel):
    task: str = Field(min_length=1, max_length=20000)
    experiment_id: str | None = Field(default=None, max_length=200)
    created_by: str | None = Field(default=None, max_length=200)
    params: dict = Field(default_factory=dict)


def verify_token(authorization: str | None = Header(default=None)):
    """No-op while API_TOKEN is empty; otherwise require a bearer token."""
    expected = settings.API_TOKEN
    if not expected:
        return
    if not authorization or not hmac.compare_digest(authorization, f'Bearer {expected}'):
        raise HTTPException(401, 'Invalid or missing API token')


def create_app(engine=None):
    eng = engine or get_engine()

    @asynccontextmanager
    async def lifespan(app):
        apply_schema(eng)
        yield

    app = FastAPI(title='Agent Runtime', lifespan=lifespan, dependencies=[Depends(verify_token)])

    @app.post('/analyses', status_code=202)
    def submit(body: AnalysisIn):
        return {'analysis_id': queue.create_analysis(**body.model_dump(), engine=eng)}

    @app.get('/analyses')
    def list_analyses(status: Literal['queued', 'running', 'succeeded', 'failed'] | None = None,
                      limit: int = Query(default=50, ge=1, le=200)):
        return queue.list_analyses(status, limit, eng)

    @app.get('/analyses/{analysis_id}')
    def analysis(analysis_id: UUID):
        row = queue.get_analysis(analysis_id, eng)
        if not row:
            raise HTTPException(404, 'Analysis not found')
        return row

    @app.get('/analyses/{analysis_id}/events')
    def events(analysis_id: UUID, limit: int = Query(default=200, ge=1, le=1000)):
        analysis(analysis_id)
        return queue.list_events(analysis_id, limit, eng)

    @app.get('/analyses/{analysis_id}/artifacts/{file_path:path}')
    def artifact(analysis_id: UUID, file_path: str):
        analysis(analysis_id)
        base = settings.ARTIFACTS_DIR.resolve() / str(analysis_id)
        target = (base / file_path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise HTTPException(404, 'Artifact not found')
        return FileResponse(target, filename=target.name)

    @app.get('/skills')
    def skills():
        return [{k: m[k] for k in ('name', 'description')} for m in scan_skills(settings.SKILLS_DIR)]

    return app


app = create_app()
