# src/where_the_plow/routes.py
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from where_the_plow import cache


# ── Generic in-memory rate limiter ────────────────────


class RateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string (typically IP)."""

    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        self._hits[key] = [t for t in bucket if now - t < self.window]
        if len(self._hits[key]) >= self.max_hits:
            return True
        self._hits[key].append(now)
        return False


_signup_limiter = RateLimiter(max_hits=3, window_seconds=1800)  # 3 per 30 min
_viewport_limiter = RateLimiter(max_hits=60, window_seconds=300)  # 60 per 5 min


def _client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )


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
    SignupRequest,
    StatsResponse,
    ViewportTrack,
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
    # Return cached realtime snapshot if available and no pagination cursor
    store = getattr(request.app.state, "store", {})
    if after is None and "realtime" in store:
        return JSONResponse(content=store["realtime"])

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

    # Check file cache (only hits for fully-historical queries)
    cached = cache.get(since, until)
    if cached is not None:
        trails = cached
    else:
        trails = db.get_coverage_trails(since=since, until=until)
        cache.put(since, until, trails)

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


@router.post(
    "/track",
    status_code=204,
    summary="Track viewport focus",
    description="Records an anonymous viewport focus event for analytics. "
    "Called by the frontend when a user settles on a map area.",
    tags=["analytics"],
)
def track_viewport(request: Request, body: ViewportTrack):
    ip = _client_ip(request)

    if _viewport_limiter.is_limited(ip):
        return Response(status_code=429)

    user_agent = request.headers.get("user-agent", "")
    db = request.app.state.db
    sw = body.bounds.get("sw", [0, 0])
    ne = body.bounds.get("ne", [0, 0])
    db.insert_viewport(
        ip=ip,
        user_agent=user_agent,
        zoom=body.zoom,
        center_lng=body.center[0],
        center_lat=body.center[1],
        sw_lng=sw[0],
        sw_lat=sw[1],
        ne_lng=ne[0],
        ne_lat=ne[1],
    )
    return Response(status_code=204)


@router.post(
    "/signup",
    status_code=204,
    summary="Email signup",
    description="Records an email signup for notifications about plow tracking, "
    "new projects, or the Silicon Harbour newsletter.",
    tags=["signup"],
)
def signup(request: Request, body: SignupRequest):
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if _signup_limiter.is_limited(ip):
        return Response(status_code=429)

    db = request.app.state.db
    db.insert_signup(
        email=body.email,
        ip=ip,
        user_agent=user_agent,
        notify_plow=body.notify_plow,
        notify_projects=body.notify_projects,
        notify_siliconharbour=body.notify_siliconharbour,
        note=body.note,
    )
    return Response(status_code=204)
