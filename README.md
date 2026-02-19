# Where the Plow

Real-time tracking of City of St. John's snowplow vehicles.

Polls the city's public AVL (Automatic Vehicle Location) API every 6 seconds, stores historical position data in DuckDB, serves it as GeoJSON, and visualizes it on a live map.

**Production:** https://plow.jackharrhy.dev

## Running

```
docker compose up -d
```

The app starts at `http://localhost:8000`. DuckDB data persists to `./data/plow.db`.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/plow.db` | Path to DuckDB database file |
| `POLL_INTERVAL` | `6` | Seconds between AVL API polls |
| `LOG_LEVEL` | `INFO` | Python log level |
| `AVL_API_URL` | St. John's AVL endpoint | Override the upstream API URL |

## API

All geo endpoints return GeoJSON. Full OpenAPI docs at [`/docs`](https://plow.jackharrhy.dev/docs).

| Endpoint | Description |
|---|---|
| `GET /vehicles` | Latest position for every vehicle |
| `GET /vehicles/nearby?lat=&lng=&radius=` | Vehicles within radius (meters) |
| `GET /vehicles/{id}/history?since=&until=` | Position history for one vehicle |
| `GET /coverage?since=&until=` | Per-vehicle LineString trails with timestamps |
| `GET /stats` | Collection statistics |
| `GET /health` | Health check |

## Database schema

DuckDB with the spatial extension.

```sql
CREATE TABLE vehicles (
    vehicle_id    VARCHAR PRIMARY KEY,
    description   VARCHAR,
    vehicle_type  VARCHAR,
    first_seen    TIMESTAMPTZ NOT NULL,
    last_seen     TIMESTAMPTZ NOT NULL
);

CREATE TABLE positions (
    id            BIGINT DEFAULT nextval('positions_seq'),
    vehicle_id    VARCHAR NOT NULL,
    timestamp     TIMESTAMPTZ NOT NULL,
    collected_at  TIMESTAMPTZ NOT NULL,
    longitude     DOUBLE NOT NULL,
    latitude      DOUBLE NOT NULL,
    geom          GEOMETRY,
    bearing       INTEGER,
    speed         DOUBLE,
    is_driving    VARCHAR,
    PRIMARY KEY (vehicle_id, timestamp)
);
```

Deduplication is by `(vehicle_id, timestamp)` composite key -- if the API returns the same `LocationDateTime` for a vehicle, the row is skipped.

## Stack

Python 3.12, FastAPI, DuckDB (spatial), httpx, MapLibre GL JS, Docker.
