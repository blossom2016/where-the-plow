# tests/test_collector.py
import os
import tempfile

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


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    db = Database(path)
    db.init()
    return db, path


def test_process_poll_inserts_data():
    db, path = make_db()

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
    db, path = make_db()

    inserted1 = process_poll(db, SAMPLE_RESPONSE)
    inserted2 = process_poll(db, SAMPLE_RESPONSE)
    assert inserted1 == 1
    assert inserted2 == 0

    total = db.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
    assert total == 1

    db.close()
    os.unlink(path)
