-- Asynchronous recommendation generation jobs: shared, durable state for the API and the worker.
CREATE TABLE IF NOT EXISTS generation_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    source text NOT NULL CHECK (source IN ('auto', 'user_requested')),
    criteria jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    heartbeat_at timestamptz,
    finished_at timestamptz,
    claimed_by text,
    recommendation_count integer CHECK (recommendation_count >= 0),
    outcome text,
    attempts integer,
    used_fallback boolean,
    fallback_reason text,
    duration_seconds double precision,
    error text
);
-- At most one active (queued or running) generation per user and source, enforced by the database.
CREATE UNIQUE INDEX IF NOT EXISTS generation_jobs_one_active ON generation_jobs(user_id, source)
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS generation_jobs_queue ON generation_jobs(status, created_at);
