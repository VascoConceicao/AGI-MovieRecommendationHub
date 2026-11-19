-- New profiles get a random avatar; restarts preserve existing selections.
ALTER TABLE user_profiles ALTER COLUMN avatar_id SET DEFAULT (floor(random() * 10) + 1)::integer;
