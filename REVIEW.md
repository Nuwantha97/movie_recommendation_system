# Movie recommendation system review

Reviewed on 18 November 2026 against the local movie catalog. A Drama tag search returned 100 ranked movies, and the API served the first two pages successfully. The issues below affect which inputs users can search for, which results they see, and whether a fresh deployment works.

## Search and recommendations

**Resolved on 19 November 2026.** Both movie pickers accept two characters and an optional release year. Examples verified against PostgreSQL include *Up 2009*, *AI 2001*, and *Inception 2010*. One-character queries return no suggestions. The eight findings below record the original behavior.

The updated system served the existing catalog of 1,186,821 movies on a Windows host with **7.8 GiB of usable RAM** and PostgreSQL in Docker. All five startup warmups succeeded. Four simultaneous requests, including a genre filter, a language filter, a plot description, and a Korean director tag, each returned 100 results. On the second run they took **2.7 to 10.1 seconds**. Across two runs the highest observed backend working set was **2,441 MiB**. PostgreSQL's container used **578 MiB** at the sampled point. This check used an existing index and cached model. Initial index construction and sustained traffic require separate measurements.

| Impact | Finding | Evidence |
| --- | --- | --- |
| High | A late response can put movies from an earlier search into the current search. Requesting page two, starting a new search, and then receiving the old page response writes that page into the new result set. It stays there on subsequent visits to page two. | Reproduced with the UI's page handler and a delayed response. The state update accepts the response without checking its request ID. [App.jsx](frontend/src/App.jsx#L239) |
| Medium | The tag picker offers some names the recommender cannot use. I selected the Korean director 강경화 from the local catalog. Using that tag alone raised the error for a query with no usable signal. The text cleanup removes every character in this name. | Verified against tag search and the recommendation query builder. The training and serving vocabulary need consistent handling for these names. [soup.py](backend/app/services/soup.py#L16) and [query_builder.py](backend/app/services/query_builder.py#L152) |
| Medium | Users cannot find one- or two-character movie titles by typing the full title. The local catalog contains *Up*, but the movie-search endpoint returned HTTP 200 with an empty list. Both movie pickers also require three characters. | [movies.py](backend/app/api/movies.py#L43), [HeroExplore.jsx](frontend/src/components/HeroExplore.jsx#L87) and [QueryPanel.jsx](frontend/src/components/QueryPanel.jsx#L97) |
| Medium | Selecting a genre changes ranking even though the form describes genres as strict filters. The client also appends each selected genre to the scoring tags. With 30 tags and one genre, the form enabled submission and produced 31 tags. The backend rejected that request. | Reproduced with the frontend request builder and backend validator. [query.js](frontend/src/query.js#L71), [QueryPanel.jsx](frontend/src/components/QueryPanel.jsx#L236) and [schemas.py](backend/app/schemas.py#L16) |
| Medium | Missing similarity data is displayed as a measured zero. A tags-only Drama request returned a plot score of `0.0` for the first movie, even though the request supplied no plot signal. The API schema and score display both support an absent value. | [fusion.py](backend/app/services/fusion.py#L51), [schemas.py](backend/app/schemas.py#L89) and [ScoreBar.jsx](frontend/src/components/ScoreBar.jsx#L2) |
| Medium | Custom page sizes break explanations. With five results per page, the results endpoint returned page two at offset five. The explanations endpoint rejected that same offset with HTTP 422 because it allows only multiples of 20. This affects API clients using custom page sizes. | Reproduced through both API routes. [recommend.py](backend/app/api/recommend.py#L90) |
| Medium | A frontend hosted on a different origin can lose pagination and explanations. Both requests send `Cache-Control` and `Pragma`. The backend's CORS header list omits both. The default same-origin proxy avoids this path. | [api.js](frontend/src/api.js#L190) and [main.py](backend/app/main.py#L100) |
| Low | Users receive no indication when a selected movie supplied no usable tags or plot. The ranking service produces a warning, but the frontend discards the warnings field when reading the response. | [recommender.py](backend/app/services/recommender.py#L45) and [api.js](frontend/src/api.js#L179) |

## Deployment

These findings come from the checked-in deployment files. Testing used the existing local database.

| Impact | Finding | Evidence |
| --- | --- | --- |
| High | The documented local and manual production commands leave a fresh PostgreSQL volume without the movie catalog. Pulling the dump places it on disk. Neither command imports it, and the database service has no initialization mount. Movie search and recommender startup require the missing tables. The automated bootstrap has a separate restore step. | [README.md](README.md#L10), [docker-compose.yml](docker-compose.yml#L12) and [bootstrap.sh](deploy/bootstrap.sh#L144) |
| High | The production proxy ignores the configured public hostname. Caddy reads `SITE_ADDRESS` from its container environment, but Compose never passes that variable to the proxy. Caddy therefore uses its `localhost` fallback. | [docker-compose.yml](docker-compose.yml#L57) and [Caddyfile](deploy/Caddyfile#L1) |
| High | The deployed backend connects with the PostgreSQL initialization account, which has administrator privileges. Compose constructs the connection string from that account even when the documented read-only role has been created. The role creation script also assigns the same hard-coded password on each installation. | [docker-compose.yml](docker-compose.yml#L32) and [create_app_role.sql](database/create_app_role.sql#L2) |
| Medium | An interrupted catalog restore can be treated as complete. Bootstrap checks only whether the `movies` table exists. A failure after table creation can leave an incomplete catalog that the next run skips. The import also omits `ON_ERROR_STOP`, allowing SQL errors to go unreported by the shell. | [bootstrap.sh](deploy/bootstrap.sh#L138) |

## Verification

- The frontend production build and ESLint both passed.
- Backend test discovery ran 61 checks against the local setup. There were 58 passes, one failed assertion, one discovery error, and one skip. The eight-request concurrency check and the 450-request memory test passed. All 55 randomized filter cases matched PostgreSQL.
- The failed assertion expects more than 180 movies in common between two rankings. The configured result cap is 100, and all 100 movies matched in this run. The test needs to derive its threshold from the result count. [test_tie_break_plot.py](backend/tests/test_tie_break_plot.py#L88) and [config.py](backend/app/config.py#L35)
- The discovery error came from the local, Git-ignored `backend/tests/test1.py`. It calls the ranking pipeline while being imported, before opening the database pool. The skipped test chose a seed whose plot had already been suppressed.
- A local API check reproduced the cross-origin pagination failure. The backend returned HTTP 400 to the browser's preflight request. Local API checks used the existing catalog and model assets. Public deployment and external Gemini explanation generation were outside the runtime checks.
