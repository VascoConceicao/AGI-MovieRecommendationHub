ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS avatar_id integer NOT NULL DEFAULT 1 CHECK (avatar_id BETWEEN 1 AND 10);
CREATE TABLE IF NOT EXISTS watched_movies (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    movie_id uuid NOT NULL,
    watched_at timestamptz,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, movie_id)
);
CREATE INDEX IF NOT EXISTS watched_movies_history ON watched_movies(user_id, recorded_at DESC, movie_id);
CREATE TABLE IF NOT EXISTS retired_movie_ids (movie_id uuid PRIMARY KEY);
CREATE TABLE IF NOT EXISTS watched_cleanup_operations (
    operation_id uuid PRIMARY KEY,
    deleted_rows integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Serialize future watched writes with catalog cleanup, including direct inserts.
CREATE OR REPLACE FUNCTION protect_watched_movie() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock_shared(150004);
    IF EXISTS (SELECT 1 FROM retired_movie_ids WHERE movie_id = NEW.movie_id) THEN
        RAISE EXCEPTION 'Movie was removed from catalog' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER watched_movie_active BEFORE INSERT OR UPDATE ON watched_movies
FOR EACH ROW EXECUTE FUNCTION protect_watched_movie();
