-- Notifications are delivered only when the writing transaction commits.
CREATE OR REPLACE FUNCTION notify_watched_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM pg_notify('watched_history', OLD.user_id::text);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM pg_notify('watched_history', NEW.user_id::text);
    END IF;
    RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER watched_history_changed
AFTER INSERT OR UPDATE OR DELETE ON watched_movies
FOR EACH ROW EXECUTE FUNCTION notify_watched_change();

CREATE OR REPLACE FUNCTION notify_watched_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('watched_history', 'all');
    RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER watched_history_truncated
AFTER TRUNCATE ON watched_movies
FOR EACH STATEMENT EXECUTE FUNCTION notify_watched_truncate();
