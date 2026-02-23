# AGENTS.md

## Project overview

Where the Plow -- real-time and historical snowplow tracker for St. John's, NL.
Python FastAPI backend serving a vanilla JS/HTML/CSS frontend. DuckDB for
storage. No build step, no frontend framework.

Production: https://plow.jackharrhy.dev

## Architecture

- **Backend:** `src/where_the_plow/` -- FastAPI app (`main.py`), routes
  (`routes.py`), Pydantic models (`models.py`), DuckDB wrapper (`db.py`),
  AVL API client (`client.py`), background collector (`collector.py`),
  realtime snapshot builder (`snapshot.py`), file-based coverage cache
  (`cache.py`), config (`config.py`).
- **Frontend:** `src/where_the_plow/static/` -- three files only:
  `index.html`, `app.js`, `style.css`. MapLibre GL JS for the map,
  noUiSlider for time range controls. All loaded from CDN, no bundler.
- **Styling:** Plain CSS with custom properties defined in `:root`
  (`--color-*`, `--border-*`, `--font-sans`). Dark theme. Use the
  existing tokens -- don't hardcode colors.

## Database & migrations

DuckDB with the spatial extension. Schema is defined in `db.py`
`Database.init()` using `CREATE TABLE IF NOT EXISTS`.

**Important:** `CREATE TABLE IF NOT EXISTS` does NOT alter existing tables.
If you add columns to a table definition, existing production databases will
silently keep the old schema and inserts referencing new columns will fail.

When adding columns to existing tables, you MUST add an explicit migration
in `Database.init()` after the table creation block. The pattern:

1. Query `information_schema.columns` to check if the column exists.
2. Run `ALTER TABLE ... ADD COLUMN` if it doesn't.

See the existing migrations in `db.init()` for examples (e.g. `geom` on
`positions`, `ip`/`user_agent` on `viewports` and `signups`).

## Key conventions

- No frontend framework -- all DOM manipulation is vanilla JS with
  `getElementById` / `addEventListener`.
- Two main JS classes: `PlowMap` (map layer management) and `PlowApp`
  (application state and logic). Event wiring is at the bottom of `app.js`.
- Analytics/write endpoints (`/track`, `/signup`) use the `RateLimiter`
  class in `routes.py` for in-memory per-IP rate limiting, and store
  `ip` + `user_agent` for fingerprinting.
- `_client_ip(request)` helper in `routes.py` extracts IP from
  `X-Forwarded-For` with fallback to `request.client.host`.
- `README.md` documents the API endpoint table, environment variables,
  database schema, and stack. When adding or removing endpoints, update
  the API table in the README to match.

## Changelog

`CHANGELOG.md` at the project root is for **end users**, not developers.
Write in plain English -- no file paths, no code snippets, no technical
jargon. Each entry links to a GitHub commit range via
`[View changes](compare URL)` so technical users can drill in.

**Format:** Each entry is `## YYYY-MM-DD — Title` followed by a few
sentences, an optional `**Contributors:**` line (only for non-Jack
contributors), and a `[View changes]()` link. Increment the
`<!-- changelog-id: N -->` integer at the top whenever a new entry is added.

**When to update:** User-facing features, significant bug fixes, and new
data sources warrant a changelog entry. Internal refactors, code cleanup,
CI changes, and documentation do not.

**Agent behavior:** If a change looks changelog-worthy, mention it to the
user ("This might warrant a changelog entry") but do NOT add it
automatically. The user decides when to batch changes into an entry,
typically before finishing a branch. Reference GitHub issues with `(#N)`
when relevant.

**Generating HTML:** After editing `CHANGELOG.md`, run
`uv run python cli.py changelog` to regenerate the HTML fragment. The
Dockerfile does this automatically at build time.
