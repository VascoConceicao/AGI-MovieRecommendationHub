CREATE TABLE IF NOT EXISTS recommendations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    movie_id uuid NOT NULL,
    reason text NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 5000),
    score double precision CHECK (score BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, movie_id)
);
CREATE INDEX IF NOT EXISTS recommendations_user_order
ON recommendations(user_id, score DESC NULLS LAST, created_at DESC, id);
CREATE INDEX IF NOT EXISTS recommendations_movie ON recommendations(movie_id);
