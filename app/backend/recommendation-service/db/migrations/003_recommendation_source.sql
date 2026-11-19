ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'auto' CHECK (source IN ('auto', 'user_requested'));
ALTER TABLE recommendations DROP CONSTRAINT IF EXISTS recommendations_user_id_movie_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS recommendations_user_movie_source ON recommendations(user_id, movie_id, source);
