import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

# The AVL API returns epoch-millisecond timestamps that represent
# Newfoundland Standard Time (UTC-3:30) but are encoded as if they were UTC.
# To get the real UTC time we must add the 3:30 offset back.
_NST_CORRECTION = timedelta(hours=3, minutes=30)

# The AVL page embeds an ArcGIS API key via esriId.registerToken().
# We scrape it and cache it; the page is public so this is stable.
_AVL_TOKEN_PAGE = "https://map.stjohns.ca/avl/"
_AVL_TOKEN_RE = re.compile(r'token:\s*"(AAPT[^"]+)"')
_AVL_TOKEN_TTL = timedelta(hours=1)


class AvlTokenManager:
    """Scrapes and caches the ArcGIS API token from the public AVL page."""

    def __init__(self):
        self._token: str | None = None
        self._fetched_at: datetime | None = None

    @property
    def _expired(self) -> bool:
        if self._token is None or self._fetched_at is None:
            return True
        return datetime.now(timezone.utc) - self._fetched_at > _AVL_TOKEN_TTL

    async def get_token(self, client: httpx.AsyncClient) -> str:
        """Return a cached token, refreshing from the AVL page if stale."""
        if not self._expired:
            return self._token  # type: ignore[return-value]
        return await self._refresh(client)

    async def invalidate_and_refresh(self, client: httpx.AsyncClient) -> str:
        """Force a fresh token fetch (e.g. after a 499 Token Required)."""
        self._token = None
        self._fetched_at = None
        return await self._refresh(client)

    async def _refresh(self, client: httpx.AsyncClient) -> str:
        logger.info("Fetching AVL token from %s", _AVL_TOKEN_PAGE)
        resp = await client.get(_AVL_TOKEN_PAGE, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        match = _AVL_TOKEN_RE.search(resp.text)
        if not match:
            raise RuntimeError(
                "Could not extract ArcGIS token from AVL page — "
                "the page format may have changed"
            )
        token = match.group(1)
        self._token = token
        self._fetched_at = datetime.now(timezone.utc)
        logger.info("AVL token refreshed (%d chars)", len(token))
        return token


# Module-level singleton so all AVL poll loops share one cached token.
avl_token_manager = AvlTokenManager()


# ── AVL (St. John's) response models ────────────────────────────────


class AvlGeometry(BaseModel):
    x: float = 0.0
    y: float = 0.0


class AvlAttributes(BaseModel):
    OBJECTID: int
    VehicleType: str = ""
    LocationDateTime: int
    Bearing: int = 0
    isDriving: str = ""


class AvlFeature(BaseModel):
    attributes: AvlAttributes
    geometry: AvlGeometry = AvlGeometry()


class AvlResponse(BaseModel):
    features: list[AvlFeature] = []


# ── AATracking (Mt Pearl / Provincial) response models ───────────────

# Map LOO_TYPE to normalized vehicle types matching St. John's AVL.
_AATRACKING_TYPE_MAP = {
    "HEAVY_TYPE": "LOADER",
    "TRUCK_TYPE": "SA PLOW TRUCK",
}


class AATrackingItem(BaseModel):
    VEH_ID: int
    VEH_NAME: str = ""
    VEH_EVENT_DATETIME: datetime | None = None
    VEH_EVENT_LATITUDE: float = 0.0
    VEH_EVENT_LONGITUDE: float = 0.0
    VEH_EVENT_HEADING: float | None = 0.0
    LOO_TYPE: str = ""
    LOO_DESCRIPTION: str = ""

    @field_validator("VEH_EVENT_DATETIME", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        """Handle missing, null, or malformed datetime strings."""
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                return None
        return v

    @property
    def vehicle_type(self) -> str:
        return _AATRACKING_TYPE_MAP.get(self.LOO_TYPE, self.LOO_TYPE or "Unknown")

    @property
    def description(self) -> str:
        if self.LOO_DESCRIPTION:
            return f"{self.VEH_NAME} ({self.LOO_DESCRIPTION})"
        return self.VEH_NAME

    @property
    def bearing(self) -> int:
        try:
            return int(self.VEH_EVENT_HEADING)
        except (ValueError, TypeError):
            return 0


# ── Parsers ──────────────────────────────────────────────────────────


def parse_avl_response(data: dict) -> tuple[list[dict], list[dict]]:
    response = AvlResponse.model_validate(data)

    vehicles = []
    positions = []
    for feature in response.features:
        attrs = feature.attributes
        geom = feature.geometry

        naive_ts = datetime.fromtimestamp(
            attrs.LocationDateTime / 1000, tz=timezone.utc
        )
        ts = naive_ts + _NST_CORRECTION

        vehicle_id = str(attrs.OBJECTID)

        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "description": attrs.VehicleType,
                "vehicle_type": attrs.VehicleType,
            }
        )

        positions.append(
            {
                "vehicle_id": vehicle_id,
                "timestamp": ts,
                "longitude": geom.x,
                "latitude": geom.y,
                "bearing": attrs.Bearing,
                "speed": None,
                "is_driving": attrs.isDriving,
            }
        )

    return vehicles, positions


def parse_aatracking_response(
    data: list, collected_at: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Parse AATracking portal response (Mt Pearl, Provincial).

    Items that fail validation (missing VEH_ID, bad types) are silently
    skipped — a single bad record shouldn't break the entire poll.
    """
    vehicles = []
    positions = []
    for raw_item in data:
        try:
            item = AATrackingItem.model_validate(raw_item)
        except Exception:
            continue

        ts = item.VEH_EVENT_DATETIME or collected_at or datetime.now(timezone.utc)

        vehicles.append(
            {
                "vehicle_id": str(item.VEH_ID),
                "description": item.description,
                "vehicle_type": item.vehicle_type,
            }
        )

        positions.append(
            {
                "vehicle_id": str(item.VEH_ID),
                "timestamp": ts,
                "longitude": item.VEH_EVENT_LONGITUDE,
                "latitude": item.VEH_EVENT_LATITUDE,
                "bearing": item.bearing,
                "speed": None,
                "is_driving": None,
            }
        )

    return vehicles, positions


async def fetch_source(client: httpx.AsyncClient, source) -> dict | list:
    """Fetch data from any source. Returns raw JSON (dict for AVL, list for AATracking)."""
    headers = {}
    params = {}

    if source.parser == "avl":
        token = await avl_token_manager.get_token(client)
        params = {
            "f": "json",
            "outFields": "*",
            "outSR": "4326",
            "returnGeometry": "true",
            "where": "1=1",
            "token": token,
        }
        if source.referer:
            headers["Referer"] = source.referer

    resp = await client.get(source.api_url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # ArcGIS returns 200 with an error body when the token is bad/expired.
    if isinstance(data, dict) and "error" in data:
        code = data["error"].get("code")
        if code in (498, 499):
            logger.warning("AVL token rejected (code %s), refreshing", code)
            token = await avl_token_manager.invalidate_and_refresh(client)
            params["token"] = token
            resp = await client.get(
                source.api_url, params=params, headers=headers, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

    return data
