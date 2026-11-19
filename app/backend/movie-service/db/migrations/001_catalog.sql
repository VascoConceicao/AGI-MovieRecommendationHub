CREATE TABLE IF NOT EXISTS movies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    source_id text NOT NULL,
    title text NOT NULL,
    original_title text NOT NULL,
    synopsis text NOT NULL,
    release_date date NOT NULL,
    duration_minutes integer NOT NULL CHECK (duration_minutes > 0),
    movie_type text NOT NULL,
    genres text[] NOT NULL,
    actors text[] NOT NULL,
    directors text[] NOT NULL,
    languages text[] NOT NULL,
    countries text[] NOT NULL,
    poster_key text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS movies_release_date ON movies(release_date);
CREATE INDEX IF NOT EXISTS movies_duration ON movies(duration_minutes);
CREATE INDEX IF NOT EXISTS movies_genres ON movies USING gin(genres);
CREATE INDEX IF NOT EXISTS movies_actors ON movies USING gin(actors);
CREATE TABLE IF NOT EXISTS catalog_resets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    movie_ids jsonb NOT NULL,
    deleted_count integer NOT NULL,
    completed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalog_one_pending_reset ON catalog_resets ((true)) WHERE NOT completed;
