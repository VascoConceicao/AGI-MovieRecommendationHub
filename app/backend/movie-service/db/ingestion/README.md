# Movie ingestion

VS Code → **Tasks: Run Task → ingest: movies**. Enter the number of **new** movies to add (default 100). The task starts Movie Service and its DB first.

Set `TMDB_READ_TOKEN` in Movie Service's ignored `.env` to your TMDB API read access token. This token is used only by ingestion. No provider calls happen in the running app.

```sh
sh app/backend/movie-service/db/ingestion/movies.sh --count 100
```

The script scans TMDB popular movies, skips known `(source, source_id)` pairs, fetches details/credits for new movies, and stops after adding the requested count. Each movie commits separately. Existing rows are never overwritten or deleted. One ingestion runs at a time. Temporary provider failures retry with bounded backoff. Invalid/incomplete records are skipped. A changing or exhausted provider list may yield fewer movies; the summary reports requested/added/skipped/failed counts. Exit 0 means requested count reached, 2 means exhaustion, 1 means the run stopped. Earlier inserts survive failure.

TMDB provides the initial real-movie source. Official references: [popular movies](https://developer.themoviedb.org/reference/movie-popular-list), [details](https://developer.themoviedb.org/reference/movie-details), [images](https://developer.themoviedb.org/docs/image-basics), [usage and attribution](https://developer.themoviedb.org/docs/faq). Use a suitable provider license. The profile credits footer was removed at user request. Provider usage and attribution requirements remain in the linked documentation.

JPEG posters download at width 500 into `movie-service/assets/posters/` (ignored), or the absolute `MOVIE_MEDIA_DIR` directory. Files use a SHA-256 content key and atomic rename. Movie DB stores only the key. Missing/failed images use the UI's local placeholder. Mount and back up this directory as persistent application storage in containers; ingestion and Movie Service must share it. Runtime never loads an external image URL. Reset keeps image files; they can be reused, and offline maintenance can remove unreferenced files when no ingestion is running.

Offline import, also useful for catalogs supplied by the agent:

```sh
sh app/backend/movie-service/db/ingestion/movies.sh --count 10 --file /absolute/path/movies.json
```

The file is a JSON array using the `POST /movies` payload below. No network requests in file mode. Existing local poster keys may be supplied; absent posters stay optional. Real metadata must come from the supplied dataset, not invented placeholders.

```json
{
  "source": "tmdb",
  "source_id": "550",
  "title": "Fight Club",
  "original_title": "Fight Club",
  "synopsis": "An office worker and a soap maker form an underground fight club.",
  "release_date": "1999-10-15",
  "duration_minutes": 139,
  "movie_type": "movie",
  "genres": ["Drama"],
  "actors": ["Brad Pitt", "Edward Norton"],
  "directors": ["David Fincher"],
  "languages": ["en"],
  "countries": ["US"],
  "poster_key": null
}
```

Future agents send the same required fields directly to Movie Service, with `Authorization: Bearer MOVIE_WRITE_TOKEN`. The app validates and stores supplied data; it does not enrich missing fields. Use the same canonical source/source ID as ingestion to avoid duplicate identities. The API returns 201 for new movies, 200 for an existing identity, 400 for incomplete/invalid data, 401 for invalid tokens, 404 when writes are disabled, or 503 during a pending reset/DB outage. Movie UUIDs are random and never reused after deletion. Unknown or foreign URLs are rejected; optional images may reference only already provisioned local JPEG keys.

Source, source ID, title, synopsis, genres, actors, directors, and positive duration_minutes are required. Missing optional metadata is stored as SQL NULL, including blank optional text and empty lists. Missing or zero TMDB runtime is rejected; ingestion continues to the next candidate. Supplied invalid values are still rejected. Watch time sums known runtimes; unknown runtimes add no minutes.

Ingestion rotates across TMDB genre-specific discovery feeds and deduplicates movies across genres. It keeps full genre metadata and continues after invalid/duplicate records until COUNT new movies are saved. Genre coverage is varied, not an exact quota (movies can have several genres). Source exhaustion returns failure with actual counts; it never reports a partial run as complete.
