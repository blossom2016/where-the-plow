# src/where_the_plow/routes.py
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Request

from where_the_plow.models import (
    CoverageFeature,
    CoverageFeatureCollection,
    CoverageProperties,
    Feature,
    FeatureCollection,
    FeatureProperties,
    LineStringGeometry,
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
        ts_str = (
            r["timestamp"].isoformat()
            if isinstance(r["timestamp"], datetime)
            else str(r["timestamp"])
        )
        features.append(
            Feature(
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
            )
        )

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
    description="Returns the latest known position for every vehicle as a GeoJSON "
    "FeatureCollection with cursor-based pagination.",
    tags=["vehicles"],
)
def get_vehicles(
    request: Request,
    limit: int = Query(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"
    ),
    after: datetime | None = Query(
        None, description="Cursor: return features after this timestamp (ISO 8601)"
    ),
):
    db = request.app.state.db
    rows = db.get_latest_positions(limit=limit, after=after)
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/vehicles/nearby",
    response_model=FeatureCollection,
    summary="Nearby vehicles",
    description="Returns current vehicle positions within a radius of a given point. "
    "Uses DuckDB spatial ST_DWithin for fast lookups.",
    tags=["vehicles"],
)
def get_vehicles_nearby(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius: float = Query(500, ge=1, le=5000, description="Radius in meters"),
    limit: int = Query(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"
    ),
    after: datetime | None = Query(
        None, description="Cursor: return features after this timestamp (ISO 8601)"
    ),
):
    db = request.app.state.db
    rows = db.get_nearby_vehicles(
        lat=lat, lng=lng, radius_m=radius, limit=limit, after=after
    )
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/vehicles/{vehicle_id}/history",
    response_model=FeatureCollection,
    summary="Vehicle position history",
    description="Returns the position history for a single vehicle over a time range "
    "as a GeoJSON FeatureCollection.",
    tags=["vehicles"],
)
def get_vehicle_history(
    request: Request,
    vehicle_id: str,
    since: datetime | None = Query(
        None, description="Start of time range (ISO 8601). Default: 4 hours ago."
    ),
    until: datetime | None = Query(
        None, description="End of time range (ISO 8601). Default: now."
    ),
    limit: int = Query(
        DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max features per page"
    ),
    after: datetime | None = Query(
        None, description="Cursor: return features after this timestamp (ISO 8601)"
    ),
):
    db = request.app.state.db
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - timedelta(hours=4)
    if until is None:
        until = now
    rows = db.get_vehicle_history(
        vehicle_id, since=since, until=until, limit=limit, after=after
    )
    return _rows_to_feature_collection(rows, limit)


@router.get(
    "/coverage",
    response_model=CoverageFeatureCollection,
    summary="Coverage trails",
    description="Returns per-vehicle LineString trails within a time range, "
    "downsampled to ~1 point per 30 seconds. Each feature includes a "
    "parallel timestamps array for recency-based visualization.",
    tags=["coverage"],
)
def get_coverage(
    request: Request,
    since: datetime | None = Query(
        None, description="Start of time range (ISO 8601). Default: 24 hours ago."
    ),
    until: datetime | None = Query(
        None, description="End of time range (ISO 8601). Default: now."
    ),
):
    db = request.app.state.db
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - timedelta(hours=24)
    if until is None:
        until = now
    trails = db.get_coverage_trails(since=since, until=until)
    features = [
        CoverageFeature(
            geometry=LineStringGeometry(coordinates=t["coordinates"]),
            properties=CoverageProperties(
                vehicle_id=t["vehicle_id"],
                vehicle_type=t["vehicle_type"],
                description=t["description"],
                timestamps=t["timestamps"],
            ),
        )
        for t in trails
    ]
    return CoverageFeatureCollection(features=features)


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Collection statistics",
    description="Returns aggregate statistics about the collected plow tracking data.",
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
        db_size_bytes=stats.get("db_size_bytes"),
    )
