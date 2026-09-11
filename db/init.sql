CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY,
    task TEXT NOT NULL,
    experiment_id TEXT,
    created_by TEXT,
    params JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed')),
    skill_used TEXT,
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status, created_at);
CREATE TABLE IF NOT EXISTS analysis_events (
    id BIGSERIAL PRIMARY KEY,
    analysis_id UUID NOT NULL REFERENCES analyses(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    event JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_analysis ON analysis_events(analysis_id, id);
