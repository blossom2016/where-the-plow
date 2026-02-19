# Data Collection Platform Design

## Context

The City of St. John's exposes real-time vehicle location data (plows, loaders, graders) via an ArcGIS REST API. The API serves ~112 vehicles and updates every ~6 seconds. We want to collect this data continuously and serve it through our own API.

**Goal:** Build a data collection platform that captures plow positions over time, enabling proximity alerts, coverage analysis, and historical pattern queries.

## Architecture

Single Python service running in Docker. On startup it begins background polling of the AVL API and writing deduplicated positions to DuckDB. The same process serves a FastAPI HTTP API for querying collected data.

```
┌──────────────────────────────────────┐
│           Docker Container           │
│                                      │
│  ┌────────────┐   ┌───────────────┐  │
│  │  Collector  │──>│    DuckDB     │  │
│  │  (6s loop)  │   │ /data/plow.db │  │
│  └────────────┘   └───────────────┘  │
│                          ▲           │
│  ┌────────────┐          │           │
│  │  FastAPI    │──────────┘           │
│  │  (uvicorn)  │                     │
│  └────────────┘                      │
│        ▲                             │
└────────│─────────────────────────────┘
         │              │
    HTTP clients    /data volume
                    (host mount)
```

## Stack

- Python 3.12+, managed by uv
- httpx — HTTP client for AVL API
- duckdb — embedded analytical database
- FastAPI + uvicorn — HTTP API server
- Docker + docker-compose

## Data Model

### `vehicles` table

Dimension table. One row per vehicle, upserted on each poll.

```sql
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id    VARCHAR PRIMARY KEY,
    description   VARCHAR,
    vehicle_type  VARCHAR,
    first_seen    TIMESTAMP NOT NULL,
    last_seen     TIMESTAMP NOT NULL
);
```

### `positions` table

Time-series fact table. One row per position *change*. Deduplication is handled by the primary key — if the API returns the same vehicle with the same `LocationDateTime`, it's the same data point and the insert is skipped.

```sql
CREATE SEQUENCE IF NOT EXISTS positions_seq;

CREATE TABLE IF NOT EXISTS positions (
    id            BIGINT DEFAULT nextval('positions_seq'),
    vehicle_id    VARCHAR NOT NULL,
    timestamp     TIMESTAMP NOT NULL,
    collected_at  TIMESTAMP NOT NULL,
    longitude     DOUBLE NOT NULL,
    latitude      DOUBLE NOT NULL,
    bearing       INTEGER,
    speed         DOUBLE,
    is_driving    VARCHAR,

    PRIMARY KEY (vehicle_id, timestamp)
);
```

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_positions_time_geo
    ON positions (timestamp, latitude, longitude);
```

### Deduplication strategy

The AVL API returns the same `LocationDateTime` for a vehicle until it reports a new position. Stationary vehicles (parked plows, `isDriving='no'`) keep the same timestamp for hours. The `(vehicle_id, timestamp)` primary key means repeated polls of a stationary vehicle produce no new rows. Only actual position changes generate inserts.

This avoids spatial distance checks entirely — the API's own timestamp is the change signal.

## Collector Logic

```
on startup:
  - init DuckDB schema
  - log DB stats (total positions, date range, vehicle count)

every 6 seconds:
  1. GET all vehicles from AVL API (where=1=1)
  2. For each vehicle:
     a. UPSERT vehicles table (update last_seen, description if changed)
     b. INSERT OR IGNORE into positions table (PK handles dedup)
  3. Log: X new positions inserted, Y vehicles seen

on error:
  - log the error, continue on next tick
  - no crash, no gaps beyond the missed poll

on shutdown (SIGTERM/SIGINT):
  - cancel collector task
  - close DuckDB connection cleanly
```

## Project Structure

```
where-the-plow/
├── API.md                        # AVL API documentation
├── ONE_LINE.md                   # Quick-copy URL
├── poll_rate.py                  # Rate test script (standalone, uv script)
├── pyproject.toml                # uv project config
├── docs/
│   └── plans/
│       └── 2026-02-19-data-collection-design.md
├── src/
│   └── where_the_plow/
│       ├── __init__.py
│       ├── main.py               # FastAPI app + lifespan (starts collector)
│       ├── collector.py          # Background polling task
│       ├── client.py             # AVL API client (httpx)
│       ├── db.py                 # DuckDB schema init + insert/query logic
│       └── config.py             # Settings from env vars
├── Dockerfile
├── compose.yml
└── data/                         # gitignored, DuckDB file lives here
    └── plow.db
```

## Configuration

All settings via environment variables with defaults:

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/plow.db` | Path to DuckDB database file |
| `POLL_INTERVAL` | `6` | Seconds between API polls |
| `AVL_API_URL` | (the full St. John's URL) | AVL endpoint base URL |
| `LOG_LEVEL` | `INFO` | Logging level |

## Container Setup

**Dockerfile:**
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ src/
CMD ["uv", "run", "uvicorn", "where_the_plow.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**compose.yml:**
```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    environment:
      - DB_PATH=/data/plow.db
      - POLL_INTERVAL=6
    restart: unless-stopped
```

## Data Volume Estimates

- ~12 active vehicles during operations, updating every ~6s = ~120 rows/min
- ~100 inactive vehicles, not generating rows (deduped)
- Per row: ~100 bytes
- Per hour of active operations: ~7,200 rows = ~720 KB
- Per day (assuming 12 hours of plow operations): ~86,400 rows = ~8.6 MB
- Per season (5 months): ~1.3 GB

DuckDB handles this comfortably in a single file.

## Future Use Cases

These are planned but not part of the initial build. The data model supports all of them without schema changes (except where noted).

### 1. Proximity Notifications ("plow near me")

- New table: `subscriptions(user_id, latitude, longitude, radius_m, notify_method)`
- After each collector batch, check new positions against active subscriptions
- Notification delivery TBD (push, webhook, email)
- First consumer feature to build after collection is stable

### 2. Coverage Heatmaps

- Aggregation query on `positions`: grid the city, count positions per cell in a time window
- DuckDB spatial extension or simple lat/lng binning
- No schema changes needed

### 3. Street-Level Tracking ("has my street been plowed?")

- Requires OpenStreetMap street network data for St. John's
- Snap GPS points to nearest street segments
- Additional table or column for street segment IDs
- Heaviest lift — separate phase

### 4. Historical Patterns ("when does my area get plowed?")

- Query accumulated multi-storm data for a given area
- Requires some storm event tagging (even manual)
- The `collected_at` vs `timestamp` distinction supports this

## What's NOT in Scope

- User authentication (add later when multi-user notifications land)
- Weather data integration (manual storm tagging is sufficient initially)
- Mobile app (API-first, clients come later)
- Rate limiting on the FastAPI side (no external traffic initially)
