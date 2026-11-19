ALTER TABLE users ADD COLUMN IF NOT EXISTS username varchar(80);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_unique ON users (lower(username));

-- Keep existing accounts. Resolve repeated email prefixes with numbered suffixes.
DO $$
DECLARE
    account record;
    base text;
    candidate text;
    suffix integer;
BEGIN
    FOR account IN SELECT id, email FROM users WHERE username IS NULL ORDER BY created_at, id LOOP
        base := left(regexp_replace(lower(split_part(account.email, '@', 1)), '[^a-z0-9_.-]', '', 'g'), 64);
        IF base = '' THEN base := 'user'; END IF;
        candidate := base;
        suffix := 0;
        WHILE EXISTS (SELECT 1 FROM users WHERE lower(username) = candidate) LOOP
            suffix := suffix + 1;
            candidate := base || '-' || suffix;
        END LOOP;
        UPDATE users SET username = candidate WHERE id = account.id;
    END LOOP;
END $$;

ALTER TABLE users ALTER COLUMN username SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'users'::regclass AND conname = 'users_username_format') THEN
        ALTER TABLE users ADD CONSTRAINT users_username_format CHECK (username ~ '^[A-Za-z0-9_.-]{1,80}$');
    END IF;
END $$;
