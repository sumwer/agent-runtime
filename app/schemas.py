import math
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator


class Finding(BaseModel):
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    evidence: str | None = None


class AnalysisResult(BaseModel):
    skill_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    findings: list[Finding]
    metrics: dict[str, float]
    charts: list[str] = Field(default_factory=list)
    caveats: str = ''

    @field_validator('metrics')
    @classmethod
    def metrics_valid(cls, v):
        if 'sample_count' not in v:
            raise ValueError('metrics must include sample_count')
        if not all(math.isfinite(n) for n in v.values()):
            raise ValueError('metrics must be finite')
        if v['sample_count'] < 0 or not v['sample_count'].is_integer():
            raise ValueError('sample_count must be a nonnegative integer')
        return v

    @field_validator('charts')
    @classmethod
    def charts_valid(cls, v):
        for path in v:
            p = PurePosixPath(path)
            if p.is_absolute() or '..' in p.parts or '\\' in path or not p.parts or p.parts[0] != 'out':
                raise ValueError('charts must be relative paths under out/')
        return v
