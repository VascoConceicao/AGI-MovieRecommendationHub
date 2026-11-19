# Sample users

VS Code: **Tasks: Run Task → ingest: users**. Enter the sample count and max watched movies per user. Admin is extra. The task starts User and Movie services and their databases first.

Or from the repo root:

```sh
sh app/backend/user-service/db/ingestion/users.sh --count 1000 --max-watched 10
```

- Default: 1,000 sample users plus admin, with profiles. No sessions.
- New profiles get a random avatar from 1–10, including admin. Reruns preserve existing avatar choices.
- Admin: `admin@admin.com` / `admin`. Always ensured separately. No permission roles yet.
- Templates in `assets/`: `first_names.json`, `last_names.json`, `usernames.json`, `email_domains.json`, `passwords.json`. Edit lists for different sample data.
- Random combinations are repeatable per user number. Reruns skip recreating existing generated accounts, but can fill their sample watched history. Smaller counts do not delete users. Keep templates unchanged for the same users on reruns.
- Email example: `sofia.silva42@mail.example.test`. Display name: `Sofia Silva`. Username is stored separately and unique across all accounts, ignoring case. Email is independently unique.
- Each user gets a generated password, stored in DB as an Argon2id hash with its own salt.
- Login details: `user-service/.run/ingestion-users.csv`. Local, ignored by Git. Contains initial sample passwords, which are predictable development data. Later password changes are not reflected here.
- Old `Sample User 0001` accounts from this script are converted to the new names/emails/passwords, keeping their IDs.
- Reads `user-service/.env`. DB changes commit together; DB errors roll back. Direct shell runs need existing account tables.

## Random watched history

`--max-watched` defaults to 10. Each sample user, including admin, gets a repeatable random target from zero to `min(maximum, available movies)`. Movie IDs come from Movie Service `/movies/ids`, never direct Movie DB access. No new movies are created by user ingestion. Empty catalog means zero watched movies; use `--max-watched 0` to disable history seeding and skip the catalog request entirely.

Reruns preserve existing watched rows and add only enough randomly selected, distinct movies to reach that user's target. The same maximum/catalog gives stable targets; reruns do not accumulate extra history. Lowering the maximum never deletes history. Existing rows already over the target stay unchanged. Recorded watched dates remain null because these are generated samples, not real viewing timestamps. SSE notifications update open profiles after the ingestion transaction commits.

Set `MOVIE_SERVICE_URL` in User Service `.env` for another internal Movie Service address. If the service is unavailable, ingestion fails before changing users; start it or use max 0. Deleted/retired movie IDs are excluded, and history insertion coordinates with catalog cleanup. Negative maximums are rejected.

--max-watchlist (default 10, 0 disables) seeds a random 0..max watchlist per sample user/admin, excluding watched movies. Reruns preserve existing lists and avoid duplicate growth. Disable both movie seeds using --max-watched 0 --max-watchlist 0.
