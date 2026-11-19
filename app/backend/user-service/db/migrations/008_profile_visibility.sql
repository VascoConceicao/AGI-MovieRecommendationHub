-- Adding the default backfills existing profiles once. Reruns preserve privacy choices.
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT true;
