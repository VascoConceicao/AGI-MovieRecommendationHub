-- Keep identity/title required; unknown metadata is NULL.
ALTER TABLE movies
    ALTER COLUMN original_title DROP NOT NULL,
    ALTER COLUMN synopsis DROP NOT NULL,
    ALTER COLUMN release_date DROP NOT NULL,
    ALTER COLUMN duration_minutes DROP NOT NULL,
    ALTER COLUMN movie_type DROP NOT NULL,
    ALTER COLUMN genres DROP NOT NULL,
    ALTER COLUMN actors DROP NOT NULL,
    ALTER COLUMN directors DROP NOT NULL,
    ALTER COLUMN languages DROP NOT NULL,
    ALTER COLUMN countries DROP NOT NULL;
