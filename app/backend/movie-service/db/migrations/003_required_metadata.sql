-- Enforce required metadata for new writes without deleting older incomplete rows.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'movies'::regclass AND conname = 'movies_required_metadata') THEN
        ALTER TABLE movies ADD CONSTRAINT movies_required_metadata CHECK (
            synopsis IS NOT NULL AND length(trim(synopsis)) > 0
            AND genres IS NOT NULL AND cardinality(genres) > 0
            AND actors IS NOT NULL AND cardinality(actors) > 0
            AND directors IS NOT NULL AND cardinality(directors) > 0
        ) NOT VALID;
    END IF;
END $$;
