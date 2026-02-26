# Multi-Source Plow Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support plow data from multiple sources (St. John's, Mount Pearl, Provincial) on a single map, with per-source filtering across all endpoints.

**Architecture:** Add a `source` column to vehicles/positions tables. Refactor client.py into a parser registry with one parser per API shape. Refactor collector.py to spawn one asyncio task per source with independent poll intervals. Add `?source=` query param to all existing endpoints. Add `GET /sources` metadata endpoint. Update frontend legend with source toggles.

**Tech Stack:** Python/FastAPI, DuckDB (spatial), vanilla JS/MapLibre GL JS.

**Prior art:** Alex Gaudon's commit (b8c1a9e on alexgaudon/main) implemented Mt Pearl support but removed St. John's. We take the same general shape but keep all sources and do it cleanly.

**Research:** See `docs/research/` for detailed API documentation per source.

**Related issues:** #13 (Provincial), #14 (Mount Pearl), #15 (Paradise -- deferred), #16 (CBS -- deferred)

---

### Task 1: Source Registry in config.py

**Files:**
- Modify: `src/where_the_plow/config.py`
- Create: `tests/test_config.py` (extend existing)

**Step 1: Write the test**

In `tests/test_config.py`, add:

```python
from where_the_plow.config import settings, SOURCES

def test_sources_registry_has_required_sources():
    assert "st_johns" in SOURCES
    assert "mt_pearl" in SOURCES
    assert "provincial" in SOURCES

def test_source_config_has_required_fields():
    for name, src in SOURCES.items():
        assert src.name == name
        assert src.display_name
        assert src.api_url
        assert src.poll_interval > 0
        assert len(src.center) == 2
        assert src.zoom > 0
        assert src.parser in ("avl", "aatracking")

def test_st_johns_has_referer():
    assert SOURCES["st_johns"].referer is not None

def test_settings_still_has_legacy_fields():
    """Existing code references settings.avl_api_url — keep it working."""
    assert settings.avl_api_url
    assert settings.avl_referer
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

**Step 3: Implement the source registry**

In `src/where_the_plow/config.py`:

```python
import os
from dataclasses import dataclass, field


@dataclass
class SourceConfig:
    name: str
    display_name: str
    api_url: str
    poll_interval: int  # seconds
    center: tuple[float, float]  # (lng, lat)
    zoom: int
    parser: str  # "avl" or "aatracking"
    enabled: bool = True
    referer: str | None = None


SOURCES: dict[str, SourceConfig] = {
    "st_johns": SourceConfig(
        name="st_johns",
        display_name="St. John's",
        api_url=os.environ.get(
            "AVL_API_URL",
            "https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query",
        ),
        poll_interval=int(os.environ.get("POLL_INTERVAL", "6")),
        center=(-52.71, 47.56),
        zoom=12,
        parser="avl",
        referer="https://map.stjohns.ca/avl/",
        enabled=os.environ.get("SOURCE_ST_JOHNS_ENABLED", "true").lower() == "true",
    ),
    "mt_pearl": SourceConfig(
        name="mt_pearl",
        display_name="Mount Pearl",
        api_url=os.environ.get(
            "MT_PEARL_API_URL",
            "https://gps5.aatracking.com/api/MtPearlPortal/GetPlows",
        ),
        poll_interval=30,
        center=(-52.81, 47.52),
        zoom=13,
        parser="aatracking",
        enabled=os.environ.get("SOURCE_MT_PEARL_ENABLED", "true").lower() == "true",
    ),
    "provincial": SourceConfig(
        name="provincial",
        display_name="Provincial",
        api_url=os.environ.get(
            "PROVINCIAL_API_URL",
            "https://gps5.aatracking.com/api/NewfoundlandPortal/GetPlows",
        ),
        poll_interval=30,
        center=(-53.5, 48.5),
        zoom=7,
        parser="aatracking",
        enabled=os.environ.get("SOURCE_PROVINCIAL_ENABLED", "true").lower() == "true",
    ),
}


class Settings:
    def __init__(self):
        self.db_path: str = os.environ.get("DB_PATH", "/data/plow.db")
        self.poll_interval: int = int(os.environ.get("POLL_INTERVAL", "6"))
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO")
        # Legacy fields — still referenced by client.py for the AVL parser
        self.avl_api_url: str = SOURCES["st_johns"].api_url
        self.avl_referer: str = SOURCES["st_johns"].referer or ""


settings = Settings()
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_config.py -v
```

**Step 5: Commit**

```bash
git add src/where_the_plow/config.py tests/test_config.py
git commit -m "feat: add multi-source registry to config (#13, #14)"
```

---

### Task 2: AATracking Parser in client.py

**Files:**
- Modify: `src/where_the_plow/client.py`
- Modify: `tests/test_client.py`

**Step 1: Write the tests**

Add to `tests/test_client.py`:

```python
from where_the_plow.client import parse_aatracking_response

SAMPLE_MT_PEARL_RESPONSE = [
    {
        "VEH_ID": 17186,
        "VEH_NAME": "21-21D",
        "VEH_UNIQUE_ID": "358013097968953",
        "VEH_EVENT_DATETIME": "2026-02-23T02:47:04",
        "VEH_EVENT_LATITUDE": 47.520455,
        "VEH_EVENT_LONGITUDE": -52.8394317,
        "VEH_EVENT_HEADING": 144.2,
        "LOO_TYPE": "HEAVY_TYPE",
        "LOO_CODE": "SnowPlowBlue_",
        "VEH_SEG_TYPE": "ST",
        "LOO_DESCRIPTION": "Large Snow Plow_Blue",
    }
]

SAMPLE_PROVINCIAL_RESPONSE = [
    {
        "VEH_ID": 15644,
        "VEH_NAME": "7452 F",
        "VEH_EVENT_LATITUDE": 48.986115,
        "VEH_EVENT_LONGITUDE": -55.55174,
        "VEH_EVENT_HEADING": 46.03,
        "LOO_TYPE": "TRUCK_TYPE",
        "LOO_CODE": "ng-Plow-Full-FS-Yellow_",
        "LOO_DESCRIPTION": "Large Plow Full Plow Side Yellow",
    }
]


def test_parse_aatracking_with_timestamp():
    """Mt Pearl response includes VEH_EVENT_DATETIME."""
    vehicles, positions = parse_aatracking_response(SAMPLE_MT_PEARL_RESPONSE)
    assert len(vehicles) == 1
    assert len(positions) == 1

    assert vehicles[0]["vehicle_id"] == "17186"
    assert vehicles[0]["description"] == "21-21D"
    assert vehicles[0]["vehicle_type"] == "Large Snow Plow_Blue"

    assert positions[0]["vehicle_id"] == "17186"
    assert positions[0]["latitude"] == 47.520455
    assert positions[0]["longitude"] == -52.8394317
    assert positions[0]["bearing"] == 144
    assert positions[0]["speed"] is None
    assert positions[0]["is_driving"] is None
    assert positions[0]["timestamp"].year == 2026


def test_parse_aatracking_without_timestamp():
    """Provincial response has no VEH_EVENT_DATETIME — uses collected_at fallback."""
    collected_at = datetime(2026, 2, 23, 3, 0, 0, tzinfo=timezone.utc)
    vehicles, positions = parse_aatracking_response(
        SAMPLE_PROVINCIAL_RESPONSE, collected_at=collected_at
    )
    assert len(vehicles) == 1
    assert positions[0]["timestamp"] == collected_at
    assert positions[0]["latitude"] == 48.986115
    assert positions[0]["speed"] is None


def test_parse_aatracking_empty():
    vehicles, positions = parse_aatracking_response([])
    assert vehicles == []
    assert positions == []
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_client.py -v -k aatracking
```

**Step 3: Implement the parser**

Add to `src/where_the_plow/client.py`:

```python
def parse_aatracking_response(
    data: list, collected_at: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Parse AATracking portal response (Mt Pearl, Provincial).

    If VEH_EVENT_DATETIME is present, use it. Otherwise fall back to collected_at.
    """
    vehicles = []
    positions = []
    for item in data:
        vehicle_id = str(item["VEH_ID"])

        # Parse timestamp: present for Mt Pearl, absent for Provincial
        ts_str = item.get("VEH_EVENT_DATETIME")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ts = collected_at or datetime.now(timezone.utc)
        else:
            ts = collected_at or datetime.now(timezone.utc)

        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "description": item.get("VEH_NAME", ""),
                "vehicle_type": item.get("LOO_DESCRIPTION", "Unknown"),
            }
        )

        positions.append(
            {
                "vehicle_id": vehicle_id,
                "timestamp": ts,
                "longitude": item.get("VEH_EVENT_LONGITUDE", 0.0),
                "latitude": item.get("VEH_EVENT_LATITUDE", 0.0),
                "bearing": int(item.get("VEH_EVENT_HEADING", 0)),
                "speed": None,
                "is_driving": None,
            }
        )

    return vehicles, positions
```

Also add a generic fetch function:

```python
async def fetch_source(client: httpx.AsyncClient, source) -> dict | list:
    """Fetch data from any source. Returns raw JSON (dict for AVL, list for AATracking)."""
    headers = {}
    params = {}

    if source.parser == "avl":
        params = {
            "f": "json",
            "outFields": "ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving",
            "outSR": "4326",
            "returnGeometry": "true",
            "where": "1=1",
        }
        if source.referer:
            headers["Referer"] = source.referer

    resp = await client.get(
        source.api_url, params=params, headers=headers, timeout=10
    )
    resp.raise_for_status()
    return resp.json()
```

**Step 4: Run all client tests**

```bash
uv run pytest tests/test_client.py -v
```

**Step 5: Commit**

```bash
git add src/where_the_plow/client.py tests/test_client.py
git commit -m "feat: add AATracking parser and generic fetch_source (#13, #14)"
```

---

### Task 3: Database Schema Changes (source column)

**Files:**
- Modify: `src/where_the_plow/db.py`
- Modify: `tests/test_db.py`

This is the largest and most careful change. The `source` column is added to both `vehicles` and `positions`. The primary keys change:
- vehicles: `(vehicle_id)` -> `(vehicle_id, source)`
- positions: `(vehicle_id, timestamp)` -> `(vehicle_id, timestamp, source)`

Existing production data gets `DEFAULT 'st_johns'` via migration.

**Step 1: Write the tests**

Add to `tests/test_db.py`:

```python
def test_source_column_exists():
    db, path = make_db()
    cols = db.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='positions'"
    ).fetchall()
    col_names = {c[0] for c in cols}
    assert "source" in col_names

    cols = db.conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='vehicles'"
    ).fetchall()
    col_names = {c[0] for c in cols}
    assert "source" in col_names
    db.close()
    os.unlink(path)


def test_upsert_vehicles_with_source():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}],
        now,
        source="mt_pearl",
    )
    row = db.conn.execute(
        "SELECT source FROM vehicles WHERE vehicle_id='v1'"
    ).fetchone()
    assert row[0] == "mt_pearl"
    db.close()
    os.unlink(path)


def test_insert_positions_with_source():
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
            "speed": None,
            "is_driving": None,
        },
    ]
    inserted = db.insert_positions(positions, now, source="mt_pearl")
    assert inserted == 1
    row = db.conn.execute(
        "SELECT source FROM positions WHERE vehicle_id='v1'"
    ).fetchone()
    assert row[0] == "mt_pearl"
    db.close()
    os.unlink(path)


def test_same_vehicle_id_different_sources():
    """Two sources can have the same vehicle_id without collision."""
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "123", "description": "SJ Plow", "vehicle_type": "LOADER"}],
        now,
        source="st_johns",
    )
    db.upsert_vehicles(
        [{"vehicle_id": "123", "description": "MP Plow", "vehicle_type": "LOADER"}],
        now,
        source="mt_pearl",
    )

    count = db.conn.execute("SELECT count(*) FROM vehicles").fetchone()[0]
    assert count == 2

    db.insert_positions(
        [{"vehicle_id": "123", "timestamp": ts, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 0.0, "is_driving": "maybe"}],
        now,
        source="st_johns",
    )
    db.insert_positions(
        [{"vehicle_id": "123", "timestamp": ts, "longitude": -52.81, "latitude": 47.52, "bearing": 0, "speed": None, "is_driving": None}],
        now,
        source="mt_pearl",
    )

    count = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert count == 2

    db.close()
    os.unlink(path)


def test_get_latest_positions_with_source_filter():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "SJ", "vehicle_type": "LOADER"}],
        now, source="st_johns",
    )
    db.upsert_vehicles(
        [{"vehicle_id": "v2", "description": "MP", "vehicle_type": "LOADER"}],
        now, source="mt_pearl",
    )
    db.insert_positions(
        [{"vehicle_id": "v1", "timestamp": ts, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 10.0, "is_driving": "maybe"}],
        now, source="st_johns",
    )
    db.insert_positions(
        [{"vehicle_id": "v2", "timestamp": ts, "longitude": -52.81, "latitude": 47.52, "bearing": 0, "speed": None, "is_driving": None}],
        now, source="mt_pearl",
    )

    # No filter -> both
    all_rows = db.get_latest_positions(limit=200)
    assert len(all_rows) == 2

    # Filter -> one
    sj_rows = db.get_latest_positions(limit=200, source="st_johns")
    assert len(sj_rows) == 1
    assert sj_rows[0]["source"] == "st_johns"

    db.close()
    os.unlink(path)
```

**Step 2: Run tests to see them fail**

```bash
uv run pytest tests/test_db.py -v -k "source"
```

**Step 3: Implement schema changes**

This is the big change to `db.py`. Key modifications:

1. **Table definitions**: Add `source VARCHAR NOT NULL DEFAULT 'st_johns'` to both tables. Change vehicles PK to include source. Change positions PK to include source.
2. **Migration**: Check if `source` column exists, add it if not.
3. **`upsert_vehicles`**: Add `source` parameter, include in INSERT and ON CONFLICT.
4. **`insert_positions`**: Add `source` parameter, include in INSERT.
5. **All query methods**: Add optional `source` parameter. Add `source` to SELECT. Filter by source when provided.
6. **`_row_to_dict`**: Include `source` in the returned dict.

The vehicles table ON CONFLICT needs to change from `ON CONFLICT (vehicle_id)` to `ON CONFLICT (vehicle_id, source)`.

For positions, `INSERT OR IGNORE` deduplicates on the PK `(vehicle_id, timestamp, source)`.

All query methods that join vehicles on `p.vehicle_id = v.vehicle_id` need to also join on `p.source = v.source` to avoid cross-source joins. Actually -- since a vehicle_id is unique within a source, and positions already has the source column, the simplest approach is: read `source` from the positions table directly (it's on every row), and keep the vehicles join as-is but add source matching: `JOIN vehicles v ON p.vehicle_id = v.vehicle_id AND p.source = v.source`.

Every `_row_to_dict` call adds `source` as the 10th field.

**Step 4: Update existing tests to pass source**

The existing tests call `db.upsert_vehicles(vehicles, now)` without source. Change the signature to `source="st_johns"` as default so existing tests don't break:

```python
def upsert_vehicles(self, vehicles: list[dict], now: datetime, source: str = "st_johns"):
def insert_positions(self, positions: list[dict], collected_at: datetime, source: str = "st_johns") -> int:
```

Similarly, all query methods get `source: str | None = None` -- None means "all sources".

**Step 5: Run all DB tests**

```bash
uv run pytest tests/test_db.py -v
```

**Step 6: Commit**

```bash
git add src/where_the_plow/db.py tests/test_db.py
git commit -m "feat: add source column to vehicles/positions with filtering (#13, #14)"
```

---

### Task 4: Collector Refactoring

**Files:**
- Modify: `src/where_the_plow/collector.py`
- Modify: `tests/test_collector.py`

**Step 1: Write the tests**

Replace/extend `tests/test_collector.py`:

```python
from where_the_plow.collector import process_poll

def test_process_poll_st_johns():
    db, path = make_db()
    inserted = process_poll(db, SAMPLE_RESPONSE, source="st_johns", parser="avl")
    assert inserted == 1
    row = db.conn.execute("SELECT source FROM positions WHERE vehicle_id='v1'").fetchone()
    assert row[0] == "st_johns"
    db.close()
    os.unlink(path)

def test_process_poll_aatracking():
    db, path = make_db()
    response = [
        {
            "VEH_ID": 17186,
            "VEH_NAME": "21-21D",
            "VEH_EVENT_DATETIME": "2026-02-23T02:47:04",
            "VEH_EVENT_LATITUDE": 47.52,
            "VEH_EVENT_LONGITUDE": -52.84,
            "VEH_EVENT_HEADING": 144,
            "LOO_DESCRIPTION": "Large Snow Plow_Blue",
        }
    ]
    inserted = process_poll(db, response, source="mt_pearl", parser="aatracking")
    assert inserted == 1
    row = db.conn.execute("SELECT source FROM positions WHERE vehicle_id='17186'").fetchone()
    assert row[0] == "mt_pearl"
    db.close()
    os.unlink(path)
```

**Step 2: Implement**

Refactor `collector.py` to:

1. `process_poll(db, response, source, parser)` -- generic function that dispatches to the right parser based on `parser` string, then calls `db.upsert_vehicles` and `db.insert_positions` with the `source`.
2. `run(db, store)` -- spawns one `asyncio.create_task(poll_source(...))` per enabled source from `SOURCES`.
3. `poll_source(db, store, source_config)` -- independent loop per source with its own `httpx.AsyncClient`, poll interval, and error handling.

The realtime snapshot store changes from `store["realtime"] = snapshot` to `store["realtime"][source_name] = snapshot`.

**Step 3: Run all collector tests**

```bash
uv run pytest tests/test_collector.py -v
```

**Step 4: Commit**

```bash
git add src/where_the_plow/collector.py tests/test_collector.py
git commit -m "feat: per-source collector tasks with independent poll intervals (#13, #14)"
```

---

### Task 5: Snapshot Changes

**Files:**
- Modify: `src/where_the_plow/snapshot.py`
- Modify: `tests/test_snapshot.py`

**Step 1: Update snapshot to accept source filter**

`build_realtime_snapshot(db, source=None)` adds optional source parameter.
When called per-source in the collector, each snapshot contains only that source's data.
The `source` field is included in each Feature's properties.

```python
def build_realtime_snapshot(db: Database, source: str | None = None) -> dict:
    rows = db.get_latest_positions_with_trails(trail_points=6, source=source)
    features = []
    for r in rows:
        ts = r["timestamp"]
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["longitude"], r["latitude"]],
            },
            "properties": {
                "vehicle_id": r["vehicle_id"],
                "description": r["description"],
                "vehicle_type": r["vehicle_type"],
                "speed": r["speed"],
                "bearing": r["bearing"],
                "is_driving": r["is_driving"],
                "timestamp": ts_str,
                "trail": r["trail"],
                "source": r.get("source", "st_johns"),
            },
        })
    return {"type": "FeatureCollection", "features": features}
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_snapshot.py -v
```

**Step 3: Commit**

```bash
git add src/where_the_plow/snapshot.py tests/test_snapshot.py
git commit -m "feat: add source field to realtime snapshot (#13, #14)"
```

---

### Task 6: Models Update

**Files:**
- Modify: `src/where_the_plow/models.py`
- Modify: `tests/test_models.py`

**Step 1: Add source field to FeatureProperties and CoverageProperties**

```python
class FeatureProperties(BaseModel):
    # ... existing fields ...
    source: str = Field(
        "st_johns",
        description="Data source identifier",
        json_schema_extra={"example": "st_johns"},
    )

class CoverageProperties(BaseModel):
    # ... existing fields ...
    source: str = Field(
        "st_johns",
        description="Data source identifier",
        json_schema_extra={"example": "st_johns"},
    )
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_models.py -v
```

**Step 3: Commit**

```bash
git add src/where_the_plow/models.py tests/test_models.py
git commit -m "feat: add source field to GeoJSON feature models (#13, #14)"
```

---

### Task 7: Routes Update

**Files:**
- Modify: `src/where_the_plow/routes.py`
- Modify: `tests/test_routes.py`

**Step 1: Add GET /sources endpoint**

```python
@router.get(
    "/sources",
    summary="Available data sources",
    description="Returns metadata about each configured plow data source.",
    tags=["sources"],
)
def get_sources():
    from where_the_plow.config import SOURCES
    return {
        name: {
            "display_name": src.display_name,
            "center": list(src.center),
            "zoom": src.zoom,
            "enabled": src.enabled,
        }
        for name, src in SOURCES.items()
        if src.enabled
    }
```

**Step 2: Add `source` query param to all vehicle/coverage endpoints**

Every endpoint gets:

```python
source: str | None = Query(
    None, description="Filter by data source (e.g. 'st_johns', 'mt_pearl', 'provincial')"
),
```

The `/vehicles` endpoint's cached snapshot logic changes:
- If `source` is specified and `after` is None, return `store["realtime"][source]`
- If `source` is None and `after` is None, combine all snapshots
- Otherwise fall through to DB query with source filter

The `_rows_to_feature_collection` helper adds `source` to FeatureProperties from `r.get("source", "st_johns")`.

The `/coverage` endpoint passes `source` to `db.get_coverage_trails(since, until, source=source)`.

**Step 3: Update /vehicles/{vehicle_id}/history**

Since vehicle IDs can collide across sources, the `source` param becomes important here. If not provided, it queries all sources (which could return data from multiple sources if IDs collide -- acceptable).

**Step 4: Run route tests**

```bash
uv run pytest tests/test_routes.py -v
```

**Step 5: Commit**

```bash
git add src/where_the_plow/routes.py tests/test_routes.py
git commit -m "feat: add source filtering to all endpoints, add GET /sources (#13, #14)"
```

---

### Task 8: Frontend - Source Legend & Filtering

**Files:**
- Modify: `src/where_the_plow/static/app.js`
- Modify: `src/where_the_plow/static/index.html`
- Modify: `src/where_the_plow/static/style.css`

**Step 1: Fetch /sources on startup**

In `app.js`, on init, fetch `/sources` and store the result. Use it to:
- Build source toggle checkboxes in the legend
- Know which sources exist for the UI

**Step 2: Add source toggles to the legend**

In the existing legend panel, add a "Sources" section above the vehicle type section. Each source gets a checkbox with the `display_name`. All enabled by default.

**Step 3: Filter vehicles by source**

When building the map layer, check each feature's `properties.source` against the enabled sources. Filter out features from disabled sources.

The existing vehicle type filtering already uses `properties.vehicle_type` -- source filtering is an additional layer on top.

**Step 4: Source-specific styling**

Each source gets a subtle visual distinction. Options:
- Different marker border colors per source
- A small source badge on the popup
- Source name shown in the vehicle detail popup

The simplest approach: add source name to the popup info when a vehicle is clicked.

**Step 5: Map bounds**

On load, if multiple sources are active and have vehicles, fit the map bounds to include all visible vehicles rather than hardcoding St. John's center.

Fallback: if no vehicles are visible, use the center/zoom from the first enabled source.

**Step 6: Commit**

```bash
git add src/where_the_plow/static/app.js src/where_the_plow/static/index.html src/where_the_plow/static/style.css
git commit -m "feat: frontend source filtering, legend toggles, multi-source map (#13, #14)"
```

---

### Task 9: Update README

**Files:**
- Modify: `README.md`

Add the new `/sources` endpoint to the API table. Update the description to mention multi-source support. Note the new environment variables for enabling/disabling sources.

**Commit:**

```bash
git add README.md
git commit -m "docs: update README with multi-source endpoints and config"
```

---

### Task 10: Integration Test

**Step 1: Run the full test suite**

```bash
uv run pytest -v
```

Fix any failures.

**Step 2: Manual smoke test**

```bash
uv run python cli.py dev
```

- Open http://localhost:8000
- Verify vehicles from St. John's appear
- Verify vehicles from Mt Pearl appear (if active)
- Verify vehicles from Provincial appear (if active)
- Check the legend has source toggles
- Toggle sources on/off
- Click a vehicle -- verify source is shown in popup
- Check /sources endpoint returns correct data
- Check /vehicles?source=st_johns returns filtered data
- Check /coverage?source=mt_pearl works

**Step 3: Final commit if needed**

---

### Task Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Source registry in config.py | `config.py`, `test_config.py` |
| 2 | AATracking parser in client.py | `client.py`, `test_client.py` |
| 3 | Database schema changes (source column) | `db.py`, `test_db.py` |
| 4 | Collector refactoring (per-source tasks) | `collector.py`, `test_collector.py` |
| 5 | Snapshot source support | `snapshot.py`, `test_snapshot.py` |
| 6 | Models update (source field) | `models.py`, `test_models.py` |
| 7 | Routes update (source filtering + /sources) | `routes.py`, `test_routes.py` |
| 8 | Frontend (legend toggles, filtering, map) | `app.js`, `index.html`, `style.css` |
| 9 | README update | `README.md` |
| 10 | Integration test | All |

### Deferred Work

- **Paradise (#15):** Parser ready to implement but API returns empty data. Enable once testable.
- **CBS (#16):** Proprietary Geotab SPA, needs browser-based reverse engineering. See `docs/research/cbs-geotab.md`.
- **Coverage cache invalidation:** The file cache in `cache.py` keys on `(since, until)` but doesn't account for source. May need `source` added to cache key.
- **Search viewbox expansion:** The Nominatim search proxy hardcodes a St. John's viewbox. Could expand based on active sources.
