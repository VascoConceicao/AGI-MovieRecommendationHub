-- Preserve legacy rows; require a valid runtime on all new or updated rows.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'movies'::regclass AND conname = 'movies_required_duration') THEN
        ALTER TABLE movies ADD CONSTRAINT movies_required_duration
            CHECK (duration_minutes IS NOT NULL AND duration_minutes BETWEEN 1 AND 10000) NOT VALID;
    END IF;
END $$;
