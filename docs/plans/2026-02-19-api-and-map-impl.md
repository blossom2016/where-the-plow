# API & Map Frontend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add DuckDB spatial support, a paginated GeoJSON API with OpenAPI annotations, and a MapLibre GL JS map frontend to the existing plow tracker.

**Architecture:** Extend the existing FastAPI app with new routes (in routes.py), Pydantic response models (in models.py), new DB query methods with DuckDB spatial, and a single-file MapLibre frontend served as static HTML.

**Tech Stack:** DuckDB spatial extension, FastAPI with Pydantic v2 response models, MapLibre GL JS (CDN), OpenFreeMap tiles

---

### Task 1: DuckDB Spatial Extension + Schema Migration

**Files:**
- Modify: `src/where_the_plow/db.py`
- Modify: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_init_loads_spatial_extension():
    db, path = make_db()
    # Verify spatial extension is loaded by using ST_Point
    result = db.conn.execute("SELECT ST_AsText(ST_Point(1.0, 2.0))").fetchone()
    assert result[0] == "POINT (1 2)"
    db.close()
    os.unlink(path)


def test_positions_has_geom_column():
    db, path = make_db()
    cols = db.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='positions'"
    ).fetchall()
    col_names = {c[0] for c in cols}
    assert "geom" in col_names
    db.close()
    os.unlink(path)


def test_insert_positions_populates_geom():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    positions = [
        {
            "vehicle_id": "v1",
            "timestamp": ts,
            "longitude": -52.73,
            "latitude": 47.56,
            "bearing": 135,
            "speed": 13.4,
            "is_driving": "maybe",
        },
    ]
    db.insert_positions(positions, now)
    row = db.conn.execute(
        "SELECT ST_X(geom), ST_Y(geom) FROM positions WHERE vehicle_id='v1'"
    ).fetchone()
    assert abs(row[0] - (-52.73)) < 0.001
    assert abs(row[1] - 47.56) < 0.001
    db.close()
    os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — spatial functions not found, geom column not found

**Step 3: Update db.py**

In `db.py`, update `init()` to install+load spatial, add geom column to CREATE TABLE, add backfill migration. Update `insert_positions()` to populate geom via ST_Point.

Changes to `init()`:
```python
def init(self):
    self.conn.execute("INSTALL spatial")
    self.conn.execute("LOAD spatial")

    # ... existing CREATE TABLE vehicles ...

    # ... existing CREATE SEQUENCE ...

    self.conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
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
        )
    """)

    # ... existing CREATE INDEX ...

    # Migration: add geom column to existing tables that lack it
    cols = self.conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='positions' AND column_name='geom'"
    ).fetchall()
    if not cols:
        self.conn.execute("ALTER TABLE positions ADD COLUMN geom GEOMETRY")

    # Backfill geom for existing rows
    self.conn.execute(
        "UPDATE positions SET geom = ST_Point(longitude, latitude) WHERE geom IS NULL"
    )
```

Changes to `insert_positions()` — update the INSERT to include geom:
```python
self.conn.execute("""
    INSERT OR IGNORE INTO positions
        (vehicle_id, timestamp, collected_at, longitude, latitude, geom, bearing, speed, is_driving)
    VALUES (?, ?, ?, ?, ?, ST_Point(?, ?), ?, ?, ?)
""", [
    p["vehicle_id"], p["timestamp"], collected_at,
    p["longitude"], p["latitude"],
    p["longitude"], p["latitude"],  # for ST_Point
    p["bearing"], p["speed"], p["is_driving"],
])
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All tests pass (old + 3 new)

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: DuckDB spatial extension with geom column and backfill migration"
```

---

### Task 2: Pydantic Response Models

**Files:**
- Create: `src/where_the_plow/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
from where_the_plow.models import (
    PointGeometry,
    FeatureProperties,
    Feature,
    Pagination,
    FeatureCollection,
    StatsResponse,
)


def test_point_geometry():
    g = PointGeometry(coordinates=[-52.73, 47.56])
    assert g.type == "Point"
    assert g.coordinates == [-52.73, 47.56]


def test_feature():
    f = Feature(
        geometry=PointGeometry(coordinates=[-52.73, 47.56]),
        properties=FeatureProperties(
            vehicle_id="v1",
            description="Test Plow",
            vehicle_type="LOADER",
            speed=13.4,
            bearing=135,
            is_driving="maybe",
            timestamp="2026-02-19T12:00:00Z",
        ),
    )
    assert f.type == "Feature"
    assert f.geometry.coordinates[0] == -52.73


def test_feature_collection_with_pagination():
    fc = FeatureCollection(
        features=[],
        pagination=Pagination(limit=200, count=0, has_more=False),
    )
    assert fc.type == "FeatureCollection"
    assert fc.pagination.has_more is False
    assert fc.pagination.next_cursor is None


def test_stats_response():
    s = StatsResponse(
        total_positions=100,
        total_vehicles=10,
        active_vehicles=5,
    )
    assert s.total_positions == 100
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# src/where_the_plow/models.py
from datetime import datetime
from pydantic import BaseModel, Field


class PointGeometry(BaseModel):
    type: str = Field(default="Point", json_schema_extra={"example": "Point"})
    coordinates: list[float] = Field(
        ...,
        description="[longitude, latitude]",
        json_schema_extra={"example": [-52.731, 47.564]},
    )


class FeatureProperties(BaseModel):
    vehicle_id: str = Field(..., description="Unique vehicle identifier")
    description: str = Field(..., description="Human-readable vehicle label", json_schema_extra={"example": "2222 SA PLOW TRUCK"})
    vehicle_type: str = Field(..., description="Vehicle category", json_schema_extra={"example": "SA PLOW TRUCK"})
    speed: float | None = Field(None, description="Speed in km/h")
    bearing: int | None = Field(None, description="Heading in degrees (0-360)")
    is_driving: str | None = Field(None, description="Driving status: 'maybe' or 'no'")
    timestamp: str = Field(..., description="Position timestamp (ISO 8601)")


class Feature(BaseModel):
    type: str = Field(default="Feature")
    geometry: PointGeometry
    properties: FeatureProperties


class Pagination(BaseModel):
    limit: int = Field(..., description="Requested page size")
    count: int = Field(..., description="Number of features in this page")
    next_cursor: str | None = Field(None, description="Cursor for next page (ISO 8601 timestamp)")
    has_more: bool = Field(..., description="Whether more results exist beyond this page")


class FeatureCollection(BaseModel):
    type: str = Field(default="FeatureCollection")
    features: list[Feature]
    pagination: Pagination


class StatsResponse(BaseModel):
    total_positions: int = Field(..., description="Total position records stored")
    total_vehicles: int = Field(..., description="Total unique vehicles seen")
    active_vehicles: int = Field(0, description="Vehicles currently active (isDriving='maybe')")
    earliest: str | None = Field(None, description="Earliest position timestamp")
    latest: str | None = Field(None, description="Latest position timestamp")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (all 4)

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: Pydantic response models for GeoJSON and pagination"
```

---

### Task 3: Database Query Methods

**Files:**
- Modify: `src/where_the_plow/db.py`
- Modify: `tests/test_db.py`

**Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_get_latest_positions():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)

    db.upsert_vehicles([
        {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
        {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "SA PLOW TRUCK"},
    ], now)
    db.insert_positions([
        {"vehicle_id": "v1", "timestamp": ts1, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 0.0, "is_driving": "maybe"},
        {"vehicle_id": "v1", "timestamp": ts2, "longitude": -52.74, "latitude": 47.57, "bearing": 90, "speed": 10.0, "is_driving": "maybe"},
        {"vehicle_id": "v2", "timestamp": ts1, "longitude": -52.80, "latitude": 47.50, "bearing": 180, "speed": 5.0, "is_driving": "no"},
    ], now)

    features = db.get_latest_positions(limit=200)
    assert len(features) == 2
    # v1 should have the latest position (ts2)
    v1 = next(f for f in features if f["vehicle_id"] == "v1")
    assert abs(v1["longitude"] - (-52.74)) < 0.001

    db.close()
    os.unlink(path)


def test_get_latest_positions_pagination():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles([
        {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
        {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
    ], now)
    db.insert_positions([
        {"vehicle_id": "v1", "timestamp": ts, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 0.0, "is_driving": "maybe"},
        {"vehicle_id": "v2", "timestamp": ts, "longitude": -52.80, "latitude": 47.50, "bearing": 0, "speed": 0.0, "is_driving": "maybe"},
    ], now)

    page1 = db.get_latest_positions(limit=1)
    assert len(page1) == 1

    db.close()
    os.unlink(path)


def test_get_nearby_vehicles():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles([
        {"vehicle_id": "v1", "description": "Near", "vehicle_type": "LOADER"},
        {"vehicle_id": "v2", "description": "Far", "vehicle_type": "LOADER"},
    ], now)
    db.insert_positions([
        {"vehicle_id": "v1", "timestamp": ts, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 0.0, "is_driving": "maybe"},
        {"vehicle_id": "v2", "timestamp": ts, "longitude": -53.00, "latitude": 47.00, "bearing": 0, "speed": 0.0, "is_driving": "maybe"},
    ], now)

    # 1km radius around v1's position — should only find v1
    results = db.get_nearby_vehicles(lat=47.56, lng=-52.73, radius_m=1000, limit=200)
    assert len(results) == 1
    assert results[0]["vehicle_id"] == "v1"

    db.close()
    os.unlink(path)


def test_get_vehicle_history():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)
    ts3 = datetime(2026, 2, 19, 12, 0, 12, tzinfo=timezone.utc)

    db.upsert_vehicles([{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now)
    db.insert_positions([
        {"vehicle_id": "v1", "timestamp": ts1, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 0.0, "is_driving": "maybe"},
        {"vehicle_id": "v1", "timestamp": ts2, "longitude": -52.74, "latitude": 47.57, "bearing": 90, "speed": 5.0, "is_driving": "maybe"},
        {"vehicle_id": "v1", "timestamp": ts3, "longitude": -52.75, "latitude": 47.58, "bearing": 180, "speed": 10.0, "is_driving": "maybe"},
    ], now)

    history = db.get_vehicle_history("v1", since=ts1, until=ts3, limit=200)
    assert len(history) == 3
    # Should be ordered by timestamp ascending
    assert history[0]["timestamp"] <= history[1]["timestamp"]

    db.close()
    os.unlink(path)


def test_get_coverage():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)

    db.upsert_vehicles([
        {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
        {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
    ], now)
    db.insert_positions([
        {"vehicle_id": "v1", "timestamp": ts1, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 0.0, "is_driving": "maybe"},
        {"vehicle_id": "v2", "timestamp": ts2, "longitude": -52.80, "latitude": 47.50, "bearing": 0, "speed": 5.0, "is_driving": "maybe"},
    ], now)

    coverage = db.get_coverage(since=ts1, until=ts2, limit=200)
    assert len(coverage) == 2

    db.close()
    os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — methods not found

**Step 3: Add query methods to db.py**

Add these methods to the Database class:

```python
def get_latest_positions(self, limit: int = 200, after: datetime | None = None) -> list[dict]:
    query = """
        WITH latest AS (
            SELECT DISTINCT ON (p.vehicle_id)
                p.vehicle_id, p.timestamp, p.longitude, p.latitude,
                p.bearing, p.speed, p.is_driving,
                v.description, v.vehicle_type
            FROM positions p
            JOIN vehicles v ON p.vehicle_id = v.vehicle_id
            ORDER BY p.vehicle_id, p.timestamp DESC
        )
        SELECT * FROM latest
        WHERE ($1 IS NULL OR timestamp > $1)
        ORDER BY timestamp ASC
        LIMIT $2
    """
    rows = self.conn.execute(query, [after, limit]).fetchall()
    return [self._row_to_dict(r) for r in rows]

def get_nearby_vehicles(self, lat: float, lng: float, radius_m: float,
                        limit: int = 200, after: datetime | None = None) -> list[dict]:
    # Convert meters to approximate degrees (at ~47.5° latitude)
    # 1 degree latitude ≈ 111,320m, 1 degree longitude ≈ 111,320 * cos(lat)
    radius_deg = radius_m / 111320.0
    query = """
        WITH latest AS (
            SELECT DISTINCT ON (p.vehicle_id)
                p.vehicle_id, p.timestamp, p.longitude, p.latitude,
                p.bearing, p.speed, p.is_driving, p.geom,
                v.description, v.vehicle_type
            FROM positions p
            JOIN vehicles v ON p.vehicle_id = v.vehicle_id
            ORDER BY p.vehicle_id, p.timestamp DESC
        )
        SELECT vehicle_id, timestamp, longitude, latitude, bearing, speed,
               is_driving, description, vehicle_type
        FROM latest
        WHERE ST_DWithin(geom, ST_Point($1, $2), $3)
        AND ($4 IS NULL OR timestamp > $4)
        ORDER BY timestamp ASC
        LIMIT $5
    """
    rows = self.conn.execute(query, [lng, lat, radius_deg, after, limit]).fetchall()
    return [self._row_to_dict(r) for r in rows]

def get_vehicle_history(self, vehicle_id: str, since: datetime, until: datetime,
                        limit: int = 200, after: datetime | None = None) -> list[dict]:
    query = """
        SELECT p.vehicle_id, p.timestamp, p.longitude, p.latitude,
               p.bearing, p.speed, p.is_driving,
               v.description, v.vehicle_type
        FROM positions p
        JOIN vehicles v ON p.vehicle_id = v.vehicle_id
        WHERE p.vehicle_id = $1
        AND p.timestamp >= $2
        AND p.timestamp <= $3
        AND ($4 IS NULL OR p.timestamp > $4)
        ORDER BY p.timestamp ASC
        LIMIT $5
    """
    rows = self.conn.execute(query, [vehicle_id, since, until, after, limit]).fetchall()
    return [self._row_to_dict(r) for r in rows]

def get_coverage(self, since: datetime, until: datetime,
                 limit: int = 200, after: datetime | None = None) -> list[dict]:
    query = """
        SELECT p.vehicle_id, p.timestamp, p.longitude, p.latitude,
               p.bearing, p.speed, p.is_driving,
               v.description, v.vehicle_type
        FROM positions p
        JOIN vehicles v ON p.vehicle_id = v.vehicle_id
        WHERE p.timestamp >= $1
        AND p.timestamp <= $2
        AND ($3 IS NULL OR p.timestamp > $3)
        ORDER BY p.timestamp ASC
        LIMIT $4
    """
    rows = self.conn.execute(query, [since, until, after, limit]).fetchall()
    return [self._row_to_dict(r) for r in rows]

def _row_to_dict(self, row) -> dict:
    return {
        "vehicle_id": row[0],
        "timestamp": row[1],
        "longitude": row[2],
        "latitude": row[3],
        "bearing": row[4],
        "speed": row[5],
        "is_driving": row[6],
        "description": row[7],
        "vehicle_type": row[8],
    }
```

Also update `get_stats` to include `active_vehicles`:
```python
def get_stats(self) -> dict:
    total_positions = self.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    total_vehicles = self.conn.execute("SELECT count(*) FROM vehicles").fetchone()[0]
    active_vehicles = self.conn.execute(
        "SELECT count(DISTINCT vehicle_id) FROM positions WHERE is_driving = 'maybe'"
    ).fetchone()[0]
    result = {
        "total_positions": total_positions,
        "total_vehicles": total_vehicles,
        "active_vehicles": active_vehicles,
    }
    if total_positions > 0:
        row = self.conn.execute(
            "SELECT min(timestamp), max(timestamp) FROM positions"
        ).fetchone()
        result["earliest"] = row[0]
        result["latest"] = row[1]
    return result
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: DB query methods for latest positions, nearby, history, coverage"
```

---

### Task 4: API Routes with OpenAPI Annotations

**Files:**
- Create: `src/where_the_plow/routes.py`
- Modify: `src/where_the_plow/main.py`
- Create: `tests/test_routes.py`

**Step 1: Write the tests**

```python
# tests/test_routes.py
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    with patch.dict(os.environ, {"DB_PATH": path}):
        with patch("where_the_plow.collector.run", new_callable=AsyncMock) as mock_run:
            async def hang_forever(db):
                import asyncio
                await asyncio.Event().wait()
            mock_run.side_effect = hang_forever

            import importlib
            import where_the_plow.config
            importlib.reload(where_the_plow.config)
            import where_the_plow.main
            importlib.reload(where_the_plow.main)

            with TestClient(where_the_plow.main.app) as client:
                # Seed some data
                db = where_the_plow.main.app.state.db
                now = datetime.now(timezone.utc)
                ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
                db.upsert_vehicles([
                    {"vehicle_id": "v1", "description": "2222 SA PLOW TRUCK", "vehicle_type": "SA PLOW TRUCK"},
                    {"vehicle_id": "v2", "description": "2037 LOADER", "vehicle_type": "LOADER"},
                ], now)
                db.insert_positions([
                    {"vehicle_id": "v1", "timestamp": ts, "longitude": -52.73, "latitude": 47.56, "bearing": 135, "speed": 13.4, "is_driving": "maybe"},
                    {"vehicle_id": "v2", "timestamp": ts, "longitude": -52.80, "latitude": 47.50, "bearing": 0, "speed": 0.0, "is_driving": "no"},
                ], now)
                yield client

    if os.path.exists(path):
        os.unlink(path)


def test_get_vehicles(test_client):
    resp = test_client.get("/vehicles")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    assert "pagination" in data
    assert data["pagination"]["count"] == 2

    f = data["features"][0]
    assert f["type"] == "Feature"
    assert f["geometry"]["type"] == "Point"
    assert len(f["geometry"]["coordinates"]) == 2
    assert "vehicle_id" in f["properties"]


def test_get_vehicles_pagination(test_client):
    resp = test_client.get("/vehicles?limit=1")
    data = resp.json()
    assert len(data["features"]) == 1
    assert data["pagination"]["count"] == 1
    assert data["pagination"]["has_more"] is True
    assert data["pagination"]["next_cursor"] is not None


def test_get_vehicles_nearby(test_client):
    resp = test_client.get("/vehicles/nearby?lat=47.56&lng=-52.73&radius=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    # Only v1 is within 1km
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["vehicle_id"] == "v1"


def test_get_vehicle_history(test_client):
    resp = test_client.get("/vehicles/v1/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 1
    assert data["features"][0]["properties"]["vehicle_id"] == "v1"


def test_get_coverage(test_client):
    resp = test_client.get("/coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2


def test_get_stats(test_client):
    resp = test_client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_positions"] == 2
    assert data["total_vehicles"] == 2


def test_openapi_spec(test_client):
    resp = test_client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec["paths"]
    assert "/vehicles" in paths
    assert "/vehicles/nearby" in paths
    assert "/coverage" in paths
    assert "/stats" in paths
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routes.py -v`
Expected: FAIL — routes don't exist

**Step 3: Write routes.py**

```python
# src/where_the_plow/routes.py
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Request

from where_the_plow.models import (
    Feature,
    FeatureCollection,
    FeatureProperties,
    Pagination,
    PointGeometry,
    StatsResponse,
)

router = APIRouter()

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


def _rows_to_feature_collection(rows: list[dict], limit: int) -> FeatureCollection:
    features = []
    for r in rows:
        ts_str = r["timestamp"].isoformat() if isinstance(r["timestamp"], datetime) else str(r["timestamp"])
        features.append(Feature(
            geometry=PointGeometry(coordinates=[r["longitude"], r["latitude"]]),
            properties=FeatureProperties(
                vehicle_id=r["vehicle_id"],
                description=r["description"],
                vehicle_type=r["vehicle_type"],
                speed=r["speed"],
                bearing=r["bearing"],
                is_driving=r["is_driving"],
                timestamp=ts_str,
            ),
        ))

    has_more = len(features) == limit
    next_cursor = features[-1].properties.timestamp if has_more else None

    return FeatureCollection(
        features=features,
        pagination=Pagination(
            limit=limit,
            count=len(features),
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


@router.get(
    "/vehicles",
    response_model=FeatureCollection,
    summary="Current vehicle positions",
    description="Returns the latest known position for every vehicle as a GeoJSON FeatureCollection.",
    tags=["vehicles"],
)
def get_vehicles(
    request: Request,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"),
    after: datetime | None = Query(None, description="Cursor: return features after this timestamp (ISO 8601)"),
):
    db = request.app.state.db
    rows = db.get_latest_positions(limit=limit, after=after)
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/vehicles/nearby",
    response_model=FeatureCollection,
    summary="Nearby vehicles",
    description="Returns vehicles within a radius of a given point. Uses spatial indexing for fast lookups.",
    tags=["vehicles"],
)
def get_vehicles_nearby(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Latitude", json_schema_extra={"example": 47.56}),
    lng: float = Query(..., ge=-180, le=180, description="Longitude", json_schema_extra={"example": -52.73}),
    radius: float = Query(500, ge=1, le=5000, description="Radius in meters"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"),
    after: datetime | None = Query(None, description="Cursor: return features after this timestamp (ISO 8601)"),
):
    db = request.app.state.db
    rows = db.get_nearby_vehicles(lat=lat, lng=lng, radius_m=radius, limit=limit, after=after)
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/vehicles/{vehicle_id}/history",
    response_model=FeatureCollection,
    summary="Vehicle position history",
    description="Returns the position history for a single vehicle over a time range.",
    tags=["vehicles"],
)
def get_vehicle_history(
    request: Request,
    vehicle_id: str,
    since: datetime | None = Query(None, description="Start of time range (ISO 8601). Default: 4 hours ago."),
    until: datetime | None = Query(None, description="End of time range (ISO 8601). Default: now."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"),
    after: datetime | None = Query(None, description="Cursor: return features after this timestamp (ISO 8601)"),
):
    db = request.app.state.db
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - timedelta(hours=4)
    if until is None:
        until = now
    rows = db.get_vehicle_history(vehicle_id, since=since, until=until, limit=limit, after=after)
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/coverage",
    response_model=FeatureCollection,
    summary="Position coverage",
    description="Returns all recorded positions within a time range. Useful for heatmap visualization.",
    tags=["coverage"],
)
def get_coverage(
    request: Request,
    since: datetime | None = Query(None, description="Start of time range (ISO 8601). Default: 4 hours ago."),
    until: datetime | None = Query(None, description="End of time range (ISO 8601). Default: now."),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"),
    after: datetime | None = Query(None, description="Cursor: return features after this timestamp (ISO 8601)"),
):
    db = request.app.state.db
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - timedelta(hours=4)
    if until is None:
        until = now
    rows = db.get_coverage(since=since, until=until, limit=limit, after=after)
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Collection statistics",
    description="Returns aggregate statistics about collected data.",
    tags=["stats"],
)
def get_stats(request: Request):
    db = request.app.state.db
    stats = db.get_stats()
    earliest = stats.get("earliest")
    latest = stats.get("latest")
    return StatsResponse(
        total_positions=stats["total_positions"],
        total_vehicles=stats["total_vehicles"],
        active_vehicles=stats.get("active_vehicles", 0),
        earliest=earliest.isoformat() if earliest else None,
        latest=latest.isoformat() if latest else None,
    )
```

**Step 4: Wire routes into main.py**

Update `main.py` to include the router and add OpenAPI metadata:

```python
from where_the_plow.routes import router

app = FastAPI(
    title="Where the Plow",
    description="Real-time and historical plow tracker for the City of St. John's. "
                "All geo endpoints return GeoJSON FeatureCollections with cursor-based pagination.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_routes.py -v`
Expected: All 8 tests pass

Run: `uv run pytest -v`
Expected: Full suite passes

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: GeoJSON API routes with pagination and OpenAPI annotations"
```

---

### Task 5: MapLibre Frontend

**Files:**
- Create: `src/where_the_plow/static/index.html`
- Modify: `src/where_the_plow/main.py` (add static file serving + root route)

**Step 1: Create index.html**

A single-file MapLibre frontend. Full-screen map centered on St. John's, vehicle markers, auto-refresh, popups, and a link to /docs.

The HTML file should:
- Load MapLibre GL JS from CDN (unpkg)
- Center map on St. John's (~47.56, -52.71), zoom ~12
- Use OpenFreeMap tiles (https://tiles.openfreemap.org/styles/liberty)
- On map load, fetch /vehicles and add as GeoJSON source
- Render circle markers, colored by vehicle_type
- Rotate markers by bearing
- setInterval every 6000ms to re-fetch /vehicles and update source
- Click marker → popup with description, speed, bearing, timestamp
- Small "API Docs" link in bottom-right corner pointing to /docs

**Step 2: Update main.py to serve static files and root route**

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).parent / "static"

# After app creation:
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))
```

**Step 3: Manual verification**

Run: `DB_PATH=./data/plow.db uv run uvicorn where_the_plow.main:app --reload --port 8000`
Open: http://localhost:8000/
Expected: Map loads, vehicles appear as markers, auto-refresh works, popups work, /docs link works.

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: MapLibre GL JS map frontend with live vehicle tracking"
```

---

### Task 6: Update Dockerfile

**Files:**
- Modify: `Dockerfile`

**Step 1: Update Dockerfile**

The static directory needs to be included in the Docker image. The current `COPY src/ src/` should already handle it since `static/` is inside `src/where_the_plow/`.

Verify the Dockerfile still works. No changes should be needed, but confirm.

**Step 2: Build and test**

Run: `docker compose build && docker compose up -d`
Run: `curl -s http://localhost:8000/vehicles | python3 -m json.tool | head -30`
Expected: GeoJSON FeatureCollection response

**Step 3: Commit (only if Dockerfile changed)**

```bash
git add -A && git commit -m "chore: update Dockerfile for static files"
```

---

### Task 7: OpenAPI Spec Review

**Step 1: Fetch and review the OpenAPI spec**

Run: `curl -s http://localhost:8000/openapi.json | python3 -m json.tool`

Verify:
- All 5 endpoints present (/vehicles, /vehicles/nearby, /vehicles/{vehicle_id}/history, /coverage, /stats)
- Each endpoint has summary and description
- Query parameters have descriptions, types, constraints (ge/le), and examples
- Response schemas reference the Pydantic models correctly
- Tags are applied (vehicles, coverage, stats)

**Step 2: Check Swagger UI**

Open: http://localhost:8000/docs
Verify: All endpoints visible, try executing each one, responses match schemas.

**Step 3: Fix any issues found and commit**

```bash
git add -A && git commit -m "chore: OpenAPI spec review fixes"
```

---

### Task 8: Final Verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 2: Lint and format**

Run: `uv run ruff check src/ tests/`
Run: `uv run ruff format --check src/ tests/`
Expected: Clean

**Step 3: Docker build**

Run: `docker compose build`
Expected: Builds successfully

**Step 4: Fix any issues and commit**

```bash
git add -A && git commit -m "chore: final lint and format fixes"
```
