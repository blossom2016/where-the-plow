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
                db.upsert_vehicles(
                    [
                        {
                            "vehicle_id": "v1",
                            "description": "2222 SA PLOW TRUCK",
                            "vehicle_type": "SA PLOW TRUCK",
                        },
                        {
                            "vehicle_id": "v2",
                            "description": "2037 LOADER",
                            "vehicle_type": "LOADER",
                        },
                    ],
                    now,
                )
                db.insert_positions(
                    [
                        {
                            "vehicle_id": "v1",
                            "timestamp": ts,
                            "longitude": -52.73,
                            "latitude": 47.56,
                            "bearing": 135,
                            "speed": 13.4,
                            "is_driving": "maybe",
                        },
                        {
                            "vehicle_id": "v2",
                            "timestamp": ts,
                            "longitude": -52.80,
                            "latitude": 47.50,
                            "bearing": 0,
                            "speed": 0.0,
                            "is_driving": "no",
                        },
                    ],
                    now,
                )
                # Additional positions for v1 to enable coverage trail testing
                from datetime import timedelta

                ts2 = ts + timedelta(seconds=30)
                ts3 = ts + timedelta(seconds=60)
                db.insert_positions(
                    [
                        {
                            "vehicle_id": "v1",
                            "timestamp": ts2,
                            "longitude": -52.74,
                            "latitude": 47.57,
                            "bearing": 90,
                            "speed": 15.0,
                            "is_driving": "maybe",
                        },
                        {
                            "vehicle_id": "v1",
                            "timestamp": ts3,
                            "longitude": -52.75,
                            "latitude": 47.58,
                            "bearing": 180,
                            "speed": 20.0,
                            "is_driving": "maybe",
                        },
                    ],
                    now,
                )
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
    # v1's latest position is (-52.75, 47.58); use a radius that captures it
    resp = test_client.get("/vehicles/nearby?lat=47.58&lng=-52.75&radius=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["vehicle_id"] == "v1"


def test_get_vehicle_history(test_client):
    resp = test_client.get(
        "/vehicles/v1/history?since=2026-02-19T00:00:00Z&until=2026-02-20T00:00:00Z"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 1
    assert data["features"][0]["properties"]["vehicle_id"] == "v1"


def test_get_coverage(test_client):
    resp = test_client.get(
        "/coverage?since=2026-02-19T00:00:00Z&until=2026-02-20T00:00:00Z"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    # v1 has 3 positions (trail), v2 has 1 (excluded)
    assert len(data["features"]) == 1
    f = data["features"][0]
    assert f["geometry"]["type"] == "LineString"
    assert len(f["geometry"]["coordinates"]) >= 2
    assert f["properties"]["vehicle_id"] == "v1"
    assert "timestamps" in f["properties"]
    assert len(f["properties"]["timestamps"]) == len(f["geometry"]["coordinates"])


def test_get_stats(test_client):
    resp = test_client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_positions"] == 4
    assert data["total_vehicles"] == 2
    assert "db_size_bytes" in data
    assert data["db_size_bytes"] is not None
    assert data["db_size_bytes"] > 0


def test_openapi_spec(test_client):
    resp = test_client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec["paths"]
    assert "/vehicles" in paths
    assert "/vehicles/nearby" in paths
    assert "/coverage" in paths
    assert "/stats" in paths
