# Decisions

## Confirmed

- Search sits next to Profile and handles both movies and users.
- User requested All / Movies / Users filter buttons styled like the supplied reference. Default to All, show active selection, and preserve the query when switching filters.
- Existing users become public; new users default public. Owners can choose private. Private profiles never appear in user search.
- Search results open another user's profile or movie details.
- Movie details include movie info and Add to my list / Mark as watched buttons, using existing watchlist and watched behavior.
- Keep service database ownership and runtime local-catalog constraints.
- One implementation phase covers this connected feature. User chose current-conversation execution. Recommended model/effort remained advisory; session model/effort not exposed.

## Implementation Decisions

- Public profile reads require a signed-in session and return only ID, username, display name, avatar, bio, and paginated watched movie IDs/dates. User expanded this: public profiles now expose Their list, Watched movies, and Recommendations. No email, credentials, or sessions.
- Private and missing profiles both return 404 on direct links. Visibility and public history are read in one database snapshot; subsequent reads recheck visibility. Owner profile endpoints remain available.
- Search uses literal, case-insensitive substrings: movie title/original title and username/display name. Separate Movies and Users sections each use 25 items per page, including All. User withdrew the request for infinite scroll and fewer user results.
- Fetch up to 1,000 results per type only when the requested 25-item page needs them. Cache only the current batch per type; no heading totals, full preload, or infinite scrolling.
- Empty search browses all movies/public users in a seeded random order, stable across page changes. UUID tie-breaks keep order deterministic for unchanged data. Catalog/privacy changes are reflected on each request.
- Privacy is a reusable common switch with rounded track and sliding thumb. No bottom text, per user request.
- Movie details show available catalog metadata. List/watched actions toggle: remove from My list or mark as not watched when already saved. Adding watched movies to My list stays blocked in UI and backend. Status loads before enabling controls. Mark watched removes the movie from My list through existing backend behavior.

- Their list is the default public-profile tab. Each tab is read-only for the viewed user; movie actions always affect the signed-in viewer. Recommendations are read via the owning service, with visibility checked before and after the remote call.

- Added per-section movie title/original-title search for all public and own-profile tabs. Filter before pagination; keep recommendation source selection. Search query max 200 characters. Public visibility rechecked after remote reads.

## Pending

- None. User accepted the completed work and requested closure directly on development.

## Model Guidance

- Codex: gpt-6.1-sol with medium effort is supported by this session's native agent tool.
- Claude Code: sonnet alias; access and resolved version Unverified in this Codex session. Effort is advisory.
- Guidance checked during task creation: [Codex models](https://learn.chatgpt.com/docs/models), [Claude model configuration](https://code.claude.com/docs/en/model-config).
- No comparative total-token measurements available for this task. Choices favor reliable completion; no token-efficiency ranking claimed. Reassess if scope changes.

- Default poster: use one bundled SVG when artwork is absent or fails to load; existing artwork stays unchanged. This does not create catalog records for unknown movies.

- Final UI includes the profile-avatar navigation, random default avatars, and explicit watched-to-list move from parallel work. User result pages fill grid rows (at least 25); batches remain at most 1,000. Included in the authorized full-worktree push.
