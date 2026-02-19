# Data Collection Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python service that polls the St. John's AVL API every 6 seconds, stores deduplicated vehicle positions in DuckDB, and serves them via FastAPI.

**Architecture:** Single process — FastAPI app with a background asyncio task that polls the AVL API. DuckDB for storage. Containerized with Docker.

**Tech Stack:** Python 3.12, uv, httpx, duckdb, FastAPI, uvicorn, Docker

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/where_the_plow/__init__.py`
- Create: `.gitignore`
- Create: `data/` (directory, gitignored)

**Step 1: Create pyproject.toml**

```toml
[project]
name = "where-the-plow"
version = "0.1.0"
description = "St. John's plow tracker — data collection and API"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "duckdb>=1.2",
    "fastapi>=0.115",
    "uvicorn>=0.34",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "ruff>=0.9",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/where_the_plow"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
```

**Step 2: Create .gitignore**

```
data/
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
.ruff_cache/
```

**Step 3: Create package init**

```python
# src/where_the_plow/__init__.py
```

Empty file.

**Step 4: Create data directory and tests directory**

```bash
mkdir -p data tests
```

**Step 5: Sync dependencies**

Run: `uv sync`
Expected: lockfile created, deps installed

**Step 6: Commit**

```bash
git init && git add -A && git commit -m "chore: project scaffolding with uv"
```

---

### Task 2: Config Module

**Files:**
- Create: `src/where_the_plow/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the test**

```python
# tests/test_config.py
import os
from where_the_plow.config import Settings


def test_default_settings():
    settings = Settings()
    assert settings.db_path == "/data/plow.db"
    assert settings.poll_interval == 6
    assert settings.log_level == "INFO"
    assert "MapServer" in settings.avl_api_url


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DB_PATH", "/tmp/test.db")
    monkeypatch.setenv("POLL_INTERVAL", "10")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.db_path == "/tmp/test.db"
    assert settings.poll_interval == 10
    assert settings.log_level == "DEBUG"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# src/where_the_plow/config.py
import os


class Settings:
    def __init__(self):
        self.db_path: str = os.environ.get("DB_PATH", "/data/plow.db")
        self.poll_interval: int = int(os.environ.get("POLL_INTERVAL", "6"))
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO")
        self.avl_api_url: str = os.environ.get(
            "AVL_API_URL",
            "https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query",
        )
        self.avl_referer: str = "https://map.stjohns.ca/avl/"


settings = Settings()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: config module with env var support"
```

---

### Task 3: Database Module

**Files:**
- Create: `src/where_the_plow/db.py`
- Create: `tests/test_db.py`

**Step 1: Write the tests**

```python
# tests/test_db.py
import os
import tempfile
from datetime import datetime, timezone

from where_the_plow.db import Database


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    db.init()
    return db, path


def test_init_creates_tables():
    db, path = make_db()
    tables = db.conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()
    table_names = {t[0] for t in tables}
    assert "vehicles" in table_names
    assert "positions" in table_names
    db.close()
    os.unlink(path)


def test_upsert_vehicles():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    vehicles = [
        {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
    ]
    db.upsert_vehicles(vehicles, now)

    rows = db.conn.execute("SELECT * FROM vehicles").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "v1"

    # Upsert again — should update last_seen
    later = datetime(2026, 3, 1, tzinfo=timezone.utc)
    db.upsert_vehicles(vehicles, later)
    rows = db.conn.execute("SELECT last_seen FROM vehicles WHERE vehicle_id='v1'").fetchone()
    assert rows[0] == later

    db.close()
    os.unlink(path)


def test_insert_positions_dedup():
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

    inserted = db.insert_positions(positions, now)
    assert inserted == 1

    # Same data again — should be deduped
    inserted = db.insert_positions(positions, now)
    assert inserted == 0

    total = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert total == 1

    db.close()
    os.unlink(path)


def test_get_stats_empty():
    db, path = make_db()
    stats = db.get_stats()
    assert stats["total_positions"] == 0
    assert stats["total_vehicles"] == 0
    db.close()
    os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# src/where_the_plow/db.py
import duckdb
from datetime import datetime, timezone


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn = duckdb.connect(path)

    def init(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                vehicle_id    VARCHAR PRIMARY KEY,
                description   VARCHAR,
                vehicle_type  VARCHAR,
                first_seen    TIMESTAMP NOT NULL,
                last_seen     TIMESTAMP NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS positions_seq
        """)
        self.conn.execute("""
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
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_time_geo
                ON positions (timestamp, latitude, longitude)
        """)

    def upsert_vehicles(self, vehicles: list[dict], now: datetime):
        for v in vehicles:
            self.conn.execute("""
                INSERT INTO vehicles (vehicle_id, description, vehicle_type, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (vehicle_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    vehicle_type = EXCLUDED.vehicle_type,
                    last_seen = EXCLUDED.last_seen
            """, [v["vehicle_id"], v["description"], v["vehicle_type"], now, now])

    def insert_positions(self, positions: list[dict], collected_at: datetime) -> int:
        if not positions:
            return 0
        count_before = self.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
        for p in positions:
            self.conn.execute("""
                INSERT OR IGNORE INTO positions
                    (vehicle_id, timestamp, collected_at, longitude, latitude, bearing, speed, is_driving)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                p["vehicle_id"],
                p["timestamp"],
                collected_at,
                p["longitude"],
                p["latitude"],
                p["bearing"],
                p["speed"],
                p["is_driving"],
            ])
        count_after = self.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
        return count_after - count_before

    def get_stats(self) -> dict:
        total_positions = self.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
        total_vehicles = self.conn.execute("SELECT count(*) FROM vehicles").fetchone()[0]
        result = {
            "total_positions": total_positions,
            "total_vehicles": total_vehicles,
        }
        if total_positions > 0:
            row = self.conn.execute(
                "SELECT min(timestamp), max(timestamp) FROM positions"
            ).fetchone()
            result["earliest"] = row[0]
            result["latest"] = row[1]
        return result

    def close(self):
        self.conn.close()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (all 4 tests)

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: DuckDB database module with dedup"
```

---

### Task 4: AVL API Client

**Files:**
- Create: `src/where_the_plow/client.py`
- Create: `tests/test_client.py`

**Step 1: Write the tests**

The client parses AVL API JSON responses into our internal format. Test with fixture data, no network calls.

```python
# tests/test_client.py
from where_the_plow.client import parse_avl_response


SAMPLE_RESPONSE = {
    "features": [
        {
            "attributes": {
                "ID": "281474984421544",
                "Description": "2222 SA PLOW TRUCK",
                "VehicleType": "SA PLOW TRUCK",
                "LocationDateTime": 1771491812000,
                "Bearing": 135,
                "Speed": "13.4",
                "isDriving": "maybe",
            },
            "geometry": {"x": -52.731, "y": 47.564},
        },
        {
            "attributes": {
                "ID": "281474992393189",
                "Description": "2037 LOADER",
                "VehicleType": "LOADER",
                "LocationDateTime": 1771492204000,
                "Bearing": 0,
                "Speed": "0.0",
                "isDriving": "no",
            },
            "geometry": {"x": -52.726, "y": 47.595},
        },
    ]
}


def test_parse_avl_response():
    vehicles, positions = parse_avl_response(SAMPLE_RESPONSE)
    assert len(vehicles) == 2
    assert len(positions) == 2

    assert vehicles[0]["vehicle_id"] == "281474984421544"
    assert vehicles[0]["description"] == "2222 SA PLOW TRUCK"
    assert vehicles[0]["vehicle_type"] == "SA PLOW TRUCK"

    assert positions[0]["vehicle_id"] == "281474984421544"
    assert positions[0]["longitude"] == -52.731
    assert positions[0]["latitude"] == 47.564
    assert positions[0]["bearing"] == 135
    assert positions[0]["speed"] == 13.4
    assert positions[0]["is_driving"] == "maybe"
    assert positions[0]["timestamp"].year == 2026


def test_parse_empty_response():
    vehicles, positions = parse_avl_response({"features": []})
    assert vehicles == []
    assert positions == []


def test_parse_speed_conversion():
    """Speed comes as string from API, should be parsed to float."""
    resp = {
        "features": [
            {
                "attributes": {
                    "ID": "1",
                    "Description": "test",
                    "VehicleType": "LOADER",
                    "LocationDateTime": 1771491812000,
                    "Bearing": 0,
                    "Speed": "25.7",
                    "isDriving": "maybe",
                },
                "geometry": {"x": -52.0, "y": 47.0},
            }
        ]
    }
    _, positions = parse_avl_response(resp)
    assert positions[0]["speed"] == 25.7
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# src/where_the_plow/client.py
from datetime import datetime, timezone

import httpx

from where_the_plow.config import settings


def parse_avl_response(data: dict) -> tuple[list[dict], list[dict]]:
    vehicles = []
    positions = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        geom = feature.get("geometry", {})

        vehicle_id = str(attrs["ID"])
        ts = datetime.fromtimestamp(
            attrs["LocationDateTime"] / 1000, tz=timezone.utc
        )

        vehicles.append({
            "vehicle_id": vehicle_id,
            "description": attrs.get("Description", ""),
            "vehicle_type": attrs.get("VehicleType", ""),
        })

        speed_raw = attrs.get("Speed", "0.0")
        try:
            speed = float(speed_raw)
        except (ValueError, TypeError):
            speed = 0.0

        positions.append({
            "vehicle_id": vehicle_id,
            "timestamp": ts,
            "longitude": geom.get("x", 0.0),
            "latitude": geom.get("y", 0.0),
            "bearing": attrs.get("Bearing", 0),
            "speed": speed,
            "is_driving": attrs.get("isDriving", ""),
        })

    return vehicles, positions


async def fetch_vehicles(client: httpx.AsyncClient) -> dict:
    params = {
        "f": "json",
        "outFields": "ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving",
        "outSR": "4326",
        "returnGeometry": "true",
        "where": "1=1",
    }
    headers = {
        "Referer": settings.avl_referer,
    }
    resp = await client.get(settings.avl_api_url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: AVL API client with response parser"
```

---

### Task 5: Collector Background Task

**Files:**
- Create: `src/where_the_plow/collector.py`
- Create: `tests/test_collector.py`

**Step 1: Write the test**

Test the single-tick logic (one poll cycle) without asyncio or network.

```python
# tests/test_collector.py
import os
import tempfile
from datetime import datetime, timezone

from where_the_plow.db import Database
from where_the_plow.collector import process_poll


SAMPLE_RESPONSE = {
    "features": [
        {
            "attributes": {
                "ID": "v1",
                "Description": "2222 SA PLOW TRUCK",
                "VehicleType": "SA PLOW TRUCK",
                "LocationDateTime": 1771491812000,
                "Bearing": 135,
                "Speed": "13.4",
                "isDriving": "maybe",
            },
            "geometry": {"x": -52.731, "y": 47.564},
        },
    ]
}


def test_process_poll_inserts_data():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    db.init()

    inserted = process_poll(db, SAMPLE_RESPONSE)
    assert inserted == 1

    # Verify vehicle was upserted
    row = db.conn.execute("SELECT * FROM vehicles WHERE vehicle_id='v1'").fetchone()
    assert row is not None
    assert row[1] == "2222 SA PLOW TRUCK"

    # Verify position was inserted
    row = db.conn.execute("SELECT * FROM positions WHERE vehicle_id='v1'").fetchone()
    assert row is not None

    db.close()
    os.unlink(path)


def test_process_poll_deduplicates():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    db.init()

    inserted1 = process_poll(db, SAMPLE_RESPONSE)
    inserted2 = process_poll(db, SAMPLE_RESPONSE)
    assert inserted1 == 1
    assert inserted2 == 0

    total = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert total == 1

    db.close()
    os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_collector.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# src/where_the_plow/collector.py
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from where_the_plow.client import fetch_vehicles, parse_avl_response
from where_the_plow.db import Database
from where_the_plow.config import settings

logger = logging.getLogger(__name__)


def process_poll(db: Database, response: dict) -> int:
    now = datetime.now(timezone.utc)
    vehicles, positions = parse_avl_response(response)
    db.upsert_vehicles(vehicles, now)
    inserted = db.insert_positions(positions, now)
    return inserted


async def run(db: Database):
    logger.info("Collector starting — polling every %ds", settings.poll_interval)

    stats = db.get_stats()
    logger.info(
        "DB stats: %d positions, %d vehicles",
        stats["total_positions"],
        stats["total_vehicles"],
    )

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await fetch_vehicles(client)
                features = response.get("features", [])
                inserted = process_poll(db, response)
                logger.info(
                    "Poll: %d vehicles seen, %d new positions",
                    len(features),
                    inserted,
                )
            except asyncio.CancelledError:
                logger.info("Collector shutting down")
                raise
            except Exception:
                logger.exception("Poll failed")

            await asyncio.sleep(settings.poll_interval)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_collector.py -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: collector background task with poll loop"
```

---

### Task 6: FastAPI App with Lifespan

**Files:**
- Create: `src/where_the_plow/main.py`
- Create: `tests/test_main.py`

**Step 1: Write the test**

```python
# tests/test_main.py
import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    with patch.dict(os.environ, {"DB_PATH": path}):
        # Re-import to pick up patched env
        from where_the_plow.config import Settings
        with patch("where_the_plow.main.settings", Settings()):
            with patch("where_the_plow.main.collector") as mock_collector:
                # Prevent actual polling during tests
                async def fake_run(db):
                    import asyncio
                    await asyncio.sleep(999999)

                mock_collector.run = fake_run

                from where_the_plow.main import app
                with TestClient(app) as client:
                    yield client

    os.unlink(path)


def test_health(test_client):
    resp = test_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "total_positions" in data
    assert "total_vehicles" in data
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# src/where_the_plow/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from where_the_plow import collector
from where_the_plow.config import settings
from where_the_plow.db import Database

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.db_path)
    db.init()
    app.state.db = db
    logger.info("Database initialized at %s", settings.db_path)

    task = asyncio.create_task(collector.run(db))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    db.close()
    logger.info("Shutdown complete")


app = FastAPI(title="Where the Plow", lifespan=lifespan)


@app.get("/health")
def health():
    db: Database = app.state.db
    stats = db.get_stats()
    return {"status": "ok", **stats}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_main.py -v`
Expected: PASS

**Step 5: Verify it runs manually**

Run: `DB_PATH=./data/plow.db uv run uvicorn where_the_plow.main:app --host 0.0.0.0 --port 8000`
Expected: Server starts, collector begins logging polls, `curl localhost:8000/health` returns stats.
Stop with Ctrl+C.

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: FastAPI app with lifespan and health endpoint"
```

---

### Task 7: Dockerfile and compose.yml

**Files:**
- Create: `Dockerfile`
- Create: `compose.yml`

**Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "where_the_plow.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Write compose.yml**

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

**Step 3: Build and test**

Run: `docker compose build`
Expected: Build succeeds

Run: `docker compose up`
Expected: Container starts, collector logs polls, health endpoint responds.

**Step 4: Commit**

```bash
git add -A && git commit -m "feat: Dockerfile and compose.yml"
```

---

### Task 8: Run All Tests, Lint, Verify

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 2: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors (fix any that appear)

**Step 3: Run format check**

Run: `uv run ruff format --check src/ tests/`
Expected: No formatting issues (fix any that appear)

**Step 4: Final commit if any fixes**

```bash
git add -A && git commit -m "chore: lint and format fixes"
```
