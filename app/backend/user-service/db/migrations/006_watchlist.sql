CREATE TABLE IF NOT EXISTS watchlist_movies (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    movie_id uuid NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, movie_id)
);
CREATE INDEX IF NOT EXISTS watchlist_movies_order ON watchlist_movies(user_id, added_at DESC, movie_id);
CREATE OR REPLACE TRIGGER watchlist_movie_active BEFORE INSERT OR UPDATE ON watchlist_movies
FOR EACH ROW EXECUTE FUNCTION protect_watched_movie();
CREATE OR REPLACE TRIGGER watchlist_changed AFTER INSERT OR UPDATE OR DELETE ON watchlist_movies
FOR EACH ROW EXECUTE FUNCTION notify_watched_change();
CREATE OR REPLACE TRIGGER watchlist_truncated AFTER TRUNCATE ON watchlist_movies
FOR EACH STATEMENT EXECUTE FUNCTION notify_watched_truncate();
