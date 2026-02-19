# tests/test_db.py
import os
import tempfile
from datetime import datetime, timezone

from where_the_plow.db import Database


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # DuckDB needs to create the file itself
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
    rows = db.conn.execute(
        "SELECT last_seen FROM vehicles WHERE vehicle_id='v1'"
    ).fetchone()
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


def test_init_loads_spatial_extension():
    db, path = make_db()
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


def test_get_stats_empty():
    db, path = make_db()
    stats = db.get_stats()
    assert stats["total_positions"] == 0
    assert stats["total_vehicles"] == 0
    db.close()
    os.unlink(path)


def test_get_latest_positions():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
            {
                "vehicle_id": "v2",
                "description": "Plow 2",
                "vehicle_type": "SA PLOW TRUCK",
            },
        ],
        now,
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts1,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts2,
                "longitude": -52.74,
                "latitude": 47.57,
                "bearing": 90,
                "speed": 10.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts1,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 180,
                "speed": 5.0,
                "is_driving": "no",
            },
        ],
        now,
    )

    features = db.get_latest_positions(limit=200)
    assert len(features) == 2
    v1 = next(f for f in features if f["vehicle_id"] == "v1")
    assert abs(v1["longitude"] - (-52.74)) < 0.001

    db.close()
    os.unlink(path)


def test_get_latest_positions_pagination():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
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
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    page1 = db.get_latest_positions(limit=1)
    assert len(page1) == 1

    db.close()
    os.unlink(path)


def test_get_nearby_vehicles():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Near", "vehicle_type": "LOADER"},
            {"vehicle_id": "v2", "description": "Far", "vehicle_type": "LOADER"},
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
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts,
                "longitude": -53.00,
                "latitude": 47.00,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

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

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}], now
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts1,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts2,
                "longitude": -52.74,
                "latitude": 47.57,
                "bearing": 90,
                "speed": 5.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v1",
                "timestamp": ts3,
                "longitude": -52.75,
                "latitude": 47.58,
                "bearing": 180,
                "speed": 10.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    history = db.get_vehicle_history("v1", since=ts1, until=ts3, limit=200)
    assert len(history) == 3
    assert history[0]["timestamp"] <= history[1]["timestamp"]

    db.close()
    os.unlink(path)


def test_get_coverage():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 6, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"},
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
        ],
        now,
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts1,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "maybe",
            },
            {
                "vehicle_id": "v2",
                "timestamp": ts2,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 0,
                "speed": 5.0,
                "is_driving": "maybe",
            },
        ],
        now,
    )

    coverage = db.get_coverage(since=ts1, until=ts2, limit=200)
    assert len(coverage) == 2

    db.close()
    os.unlink(path)


def test_get_coverage_trails():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 30, tzinfo=timezone.utc)
    ts3 = datetime(2026, 2, 19, 12, 1, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [
            {
                "vehicle_id": "v1",
                "description": "Plow 1",
                "vehicle_type": "TA PLOW TRUCK",
            },
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
        ],
        now,
    )
    db.insert_positions(
        [
            {
                "vehicle_id": "v1",
                "timestamp": ts1,
                "longitude": -52.73,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 10.0,
                "is_driving": "maybe",
            },
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
            # v2 has only one position — should be excluded (no trail)
            {
                "vehicle_id": "v2",
                "timestamp": ts1,
                "longitude": -52.80,
                "latitude": 47.50,
                "bearing": 0,
                "speed": 0.0,
                "is_driving": "no",
            },
        ],
        now,
    )

    trails = db.get_coverage_trails(since=ts1, until=ts3)
    assert len(trails) == 1  # only v1 has a trail
    trail = trails[0]
    assert trail["vehicle_id"] == "v1"
    assert trail["vehicle_type"] == "TA PLOW TRUCK"
    assert trail["description"] == "Plow 1"
    assert len(trail["coordinates"]) == 3
    assert len(trail["timestamps"]) == 3
    assert trail["coordinates"][0] == [-52.73, 47.56]
    assert trail["timestamps"][0] <= trail["timestamps"][1]

    db.close()
    os.unlink(path)


def test_get_coverage_trails_downsampling():
    """Positions closer than 30s apart should be downsampled."""
    db, path = make_db()
    now = datetime.now(timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}],
        now,
    )
    # Insert 10 positions 6s apart (total 54s span)
    positions = []
    for i in range(10):
        ts = datetime(2026, 2, 19, 12, 0, i * 6, tzinfo=timezone.utc)
        positions.append(
            {
                "vehicle_id": "v1",
                "timestamp": ts,
                "longitude": -52.73 + i * 0.001,
                "latitude": 47.56,
                "bearing": 0,
                "speed": 10.0,
                "is_driving": "maybe",
            }
        )
    db.insert_positions(positions, now)

    since = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 2, 19, 12, 0, 54, tzinfo=timezone.utc)
    trails = db.get_coverage_trails(since=since, until=until)
    assert len(trails) == 1
    # With 30s downsampling: keep t=0, skip t=6..24, keep t=30, skip t=36..48, keep t=54
    # Should have ~3 points, not 10
    assert len(trails[0]["coordinates"]) < 10
    assert len(trails[0]["coordinates"]) >= 2

    db.close()
    os.unlink(path)
