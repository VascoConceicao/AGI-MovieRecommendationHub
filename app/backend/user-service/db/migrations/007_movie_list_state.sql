-- Watched history wins when old data appears in both lists.
DELETE FROM watchlist_movies l USING watched_movies w
WHERE l.user_id=w.user_id AND l.movie_id=w.movie_id;

CREATE OR REPLACE FUNCTION enforce_movie_list_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock_shared(150004);
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.user_id::text, 42));
    IF TG_TABLE_NAME = 'watched_movies' THEN
        DELETE FROM watchlist_movies WHERE user_id=NEW.user_id AND movie_id=NEW.movie_id;
    ELSIF EXISTS (SELECT 1 FROM watched_movies WHERE user_id=NEW.user_id AND movie_id=NEW.movie_id) THEN
        RAISE EXCEPTION 'Movie is already watched' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER watched_state BEFORE INSERT OR UPDATE ON watched_movies
FOR EACH ROW EXECUTE FUNCTION enforce_movie_list_state();
CREATE OR REPLACE TRIGGER watchlist_state BEFORE INSERT OR UPDATE ON watchlist_movies
FOR EACH ROW EXECUTE FUNCTION enforce_movie_list_state();
