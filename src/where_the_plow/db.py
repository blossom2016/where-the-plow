# src/where_the_plow/db.py
import os

import duckdb
from datetime import datetime
from itertools import groupby
from operator import itemgetter


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn = duckdb.connect(path)

    def init(self):
        self.conn.execute("INSTALL spatial")
        self.conn.execute("LOAD spatial")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                vehicle_id    VARCHAR PRIMARY KEY,
                description   VARCHAR,
                vehicle_type  VARCHAR,
                first_seen    TIMESTAMPTZ NOT NULL,
                last_seen     TIMESTAMPTZ NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS positions_seq
        """)
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
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_time_geo
                ON positions (timestamp, latitude, longitude)
        """)

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

    def upsert_vehicles(self, vehicles: list[dict], now: datetime):
        for v in vehicles:
            self.conn.execute(
                """
                INSERT INTO vehicles (vehicle_id, description, vehicle_type, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (vehicle_id) DO UPDATE SET
                    description = EXCLUDED.description,
                    vehicle_type = EXCLUDED.vehicle_type,
                    last_seen = EXCLUDED.last_seen
            """,
                [v["vehicle_id"], v["description"], v["vehicle_type"], now, now],
            )

    def insert_positions(self, positions: list[dict], collected_at: datetime) -> int:
        if not positions:
            return 0
        count_before = self.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
        for p in positions:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO positions
                    (vehicle_id, timestamp, collected_at, longitude, latitude, geom, bearing, speed, is_driving)
                VALUES (?, ?, ?, ?, ?, ST_Point(?, ?), ?, ?, ?)
            """,
                [
                    p["vehicle_id"],
                    p["timestamp"],
                    collected_at,
                    p["longitude"],
                    p["latitude"],
                    p["longitude"],
                    p["latitude"],
                    p["bearing"],
                    p["speed"],
                    p["is_driving"],
                ],
            )
        count_after = self.conn.execute("SELECT count(*) FROM positions").fetchone()[0]
        return count_after - count_before

    def get_latest_positions(
        self, limit: int = 200, after: datetime | None = None
    ) -> list[dict]:
        """Get the latest position for each vehicle."""
        query = """
            WITH ranked AS (
                SELECT p.vehicle_id, p.timestamp, p.longitude, p.latitude,
                       p.bearing, p.speed, p.is_driving,
                       v.description, v.vehicle_type,
                       ROW_NUMBER() OVER (PARTITION BY p.vehicle_id ORDER BY p.timestamp DESC) as rn
                FROM positions p
                JOIN vehicles v ON p.vehicle_id = v.vehicle_id
            )
            SELECT vehicle_id, timestamp, longitude, latitude, bearing, speed,
                   is_driving, description, vehicle_type
            FROM ranked
            WHERE rn = 1
            AND ($1 IS NULL OR timestamp > $1)
            ORDER BY timestamp ASC
            LIMIT $2
        """
        rows = self.conn.execute(query, [after, limit]).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_nearby_vehicles(
        self,
        lat: float,
        lng: float,
        radius_m: float,
        limit: int = 200,
        after: datetime | None = None,
    ) -> list[dict]:
        """Get latest vehicle positions within radius_m meters of (lat, lng)."""
        radius_deg = radius_m / 111320.0
        query = """
            WITH ranked AS (
                SELECT p.vehicle_id, p.timestamp, p.longitude, p.latitude,
                       p.bearing, p.speed, p.is_driving, p.geom,
                       v.description, v.vehicle_type,
                       ROW_NUMBER() OVER (PARTITION BY p.vehicle_id ORDER BY p.timestamp DESC) as rn
                FROM positions p
                JOIN vehicles v ON p.vehicle_id = v.vehicle_id
            )
            SELECT vehicle_id, timestamp, longitude, latitude, bearing, speed,
                   is_driving, description, vehicle_type
            FROM ranked
            WHERE rn = 1
            AND ST_DWithin(geom, ST_Point($1, $2), $3)
            AND ($4 IS NULL OR timestamp > $4)
            ORDER BY timestamp ASC
            LIMIT $5
        """
        rows = self.conn.execute(query, [lng, lat, radius_deg, after, limit]).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_vehicle_history(
        self,
        vehicle_id: str,
        since: datetime,
        until: datetime,
        limit: int = 200,
        after: datetime | None = None,
    ) -> list[dict]:
        """Get position history for a single vehicle in a time range."""
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
        rows = self.conn.execute(
            query, [vehicle_id, since, until, after, limit]
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_coverage(
        self,
        since: datetime,
        until: datetime,
        limit: int = 200,
        after: datetime | None = None,
    ) -> list[dict]:
        """Get all positions in a time range."""
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

    def get_coverage_trails(
        self,
        since: datetime,
        until: datetime,
        min_interval_s: float = 30.0,
        max_gap_s: float = 120.0,
    ) -> list[dict]:
        """Get per-vehicle LineString trails in a time range, downsampled and gap-split."""
        query = """
            SELECT p.vehicle_id, p.timestamp, p.longitude, p.latitude,
                   v.description, v.vehicle_type
            FROM positions p
            JOIN vehicles v ON p.vehicle_id = v.vehicle_id
            WHERE p.timestamp >= $1
            AND p.timestamp <= $2
            ORDER BY p.vehicle_id, p.timestamp ASC
        """
        rows = self.conn.execute(query, [since, until]).fetchall()

        trails = []
        for vid, group in groupby(rows, key=itemgetter(0)):
            points = list(group)
            if len(points) < 2:
                continue

            # Downsample: keep first point, then skip until >= min_interval_s
            sampled = [points[0]]
            for pt in points[1:]:
                elapsed = (pt[1] - sampled[-1][1]).total_seconds()
                if elapsed >= min_interval_s:
                    sampled.append(pt)
            # Always include the last point
            if sampled[-1] != points[-1]:
                sampled.append(points[-1])

            if len(sampled) < 2:
                continue

            # Split at gaps > max_gap_s
            segments = []
            current_segment = [sampled[0]]
            for pt in sampled[1:]:
                gap = (pt[1] - current_segment[-1][1]).total_seconds()
                if gap > max_gap_s:
                    if len(current_segment) >= 2:
                        segments.append(current_segment)
                    current_segment = [pt]
                else:
                    current_segment.append(pt)
            if len(current_segment) >= 2:
                segments.append(current_segment)

            description = sampled[0][4]
            vehicle_type = sampled[0][5]

            for seg in segments:
                trails.append(
                    {
                        "vehicle_id": vid,
                        "description": description,
                        "vehicle_type": vehicle_type,
                        "coordinates": [[p[2], p[3]] for p in seg],
                        "timestamps": [
                            p[1].isoformat()
                            if isinstance(p[1], datetime)
                            else str(p[1])
                            for p in seg
                        ],
                    }
                )

        return trails

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

    def get_stats(self) -> dict:
        total_positions = self.conn.execute(
            "SELECT count(*) FROM positions"
        ).fetchone()[0]
        total_vehicles = self.conn.execute("SELECT count(*) FROM vehicles").fetchone()[
            0
        ]
        active_vehicles = self.conn.execute(
            "SELECT count(DISTINCT vehicle_id) FROM positions WHERE is_driving = 'maybe'"
        ).fetchone()[0]
        try:
            db_size_bytes = os.path.getsize(self.path)
        except OSError:
            db_size_bytes = None
        result = {
            "total_positions": total_positions,
            "total_vehicles": total_vehicles,
            "active_vehicles": active_vehicles,
            "db_size_bytes": db_size_bytes,
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
