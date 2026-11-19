# User DB

Three tables. Only User Service accesses them.

## users

The account and login details.

- `id`: unique user ID.
- `username`: unique across all accounts, ignoring uppercase/lowercase.
- `email`: login email. Unique, ignoring uppercase/lowercase.
- `password_hash`: hashed password. Never the original password.
- `created_at`: account creation time.
- `updated_at`: last account update.

## user_profiles

The user's profile. One per account.

- `user_id`: links to `users.id`.
- `display_name`: name shown in the app. Can repeat across users.
- `bio`: optional short description.
- `updated_at`: last profile update.

Email and password hash stay in `users`, outside the public profile.

## user_sessions

Keeps users signed in. One user can have several sessions.

- `token_hash`: hash of the random session token.
- `user_id`: links to `users.id`.
- `created_at`: session creation time.
- `expires_at`: when the session stops working. Currently seven days.

Browser keeps the token in an HttpOnly cookie. DB keeps only its hash.
Logout deletes the current session.

## Clearing data

- **Users**: deletes accounts and their profiles/sessions.
- **Profiles**: deletes profiles. Accounts remain, but current login needs a profile.
- **Sessions**: signs everyone out. Accounts and profiles remain.
- **All**: clears all three tables. Table structure stays.

## Later

Watched history and preferences can get more tables here.
Movie details stay in Movie DB. Generated recommendations stay in Recommendation DB.

Migration `003_profile_history.sql` adds default avatar selection and `watched_movies`, plus internal cleanup receipts and retired movie IDs. `watched_movies` may be cleared directly; clearing all/users also removes it. Coordination tables survive resets to make retries safe and prevent old movie UUIDs being reused in history.
