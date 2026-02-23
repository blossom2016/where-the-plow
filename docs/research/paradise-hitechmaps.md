# Paradise HitechMaps API

**Status:** API confirmed reachable, returns empty data (seasonal)
**GitHub issue:** #15
**Tracker URL:** https://hitechmaps.com/townparadise/
**API type:** PHP backend, simple JSON REST
**Platform:** HitechMaps (likely Geotab-based backend)

## API Endpoint

```
GET https://hitechmaps.com/townparadise/db.php
```

No authentication, no special headers, no query parameters.
The frontend fetches with `{cache: "no-cache"}`.

## Response Shape

Returns a JSON array of vehicle objects. When no plows are active, returns
an empty array `[]`.

**Expected shape** (from JavaScript source analysis -- no live sample
available as of Feb 2026):

```json
[
  {
    "VID": "12345",
    "Latitude": 47.5235,
    "longitude": -52.8693,
    "Speed": 35,
    "Bearing": 180,
    "IsDeviceCommunicating": 1,
    "Ignition": 1,
    "DeviceName": "Plow Truck 1",
    "TruckType": "Loaders",
    "CurrentStateDuration": "00:15:30",
    "DateTime": "2026-02-23T02:47:04"
  }
]
```

### Field Details

| Field | Type | Notes |
|-------|------|-------|
| `VID` | string/number | Unique vehicle identifier |
| `Latitude` | float | **Capital L** -- latitude (WGS84) |
| `longitude` | float | **Lowercase l** -- longitude (WGS84). Note the inconsistent casing! |
| `Speed` | number | Current speed; 0 = stationary |
| `Bearing` | number | Direction in degrees; **-1 = unknown/unavailable** |
| `IsDeviceCommunicating` | 0 or 1 | Whether the GPS device is online |
| `Ignition` | 0 or 1 | Whether the vehicle ignition is on |
| `DeviceName` | string | Human-readable vehicle name |
| `TruckType` | string | Vehicle type; empty string = unknown, "Loaders" = loader |
| `CurrentStateDuration` | string | How long in current state (format unclear, likely HH:MM:SS) |
| `DateTime` | string | Timestamp of the latest GPS update |

### Key Quirks

1. **Inconsistent field casing**: `Latitude` (capital L) vs `longitude`
   (lowercase l). This is a bug in their API, not a convention.
2. **Bearing of -1**: When bearing is unknown, the API returns -1 instead
   of null. Their frontend uses the previous known bearing as fallback.
3. **Empty when inactive**: Unlike St. John's which always shows vehicles,
   Paradise only returns data when plows are actively operating.

## Frontend Behavior (from source analysis)

- **Map center:** `{ lat: 47.5235, lng: -52.8693 }` at zoom 14
- **Poll interval:** 5000ms (5 seconds)
- **Marker colors:**
  - Default: `#4CBB17` (green)
  - Empty TruckType: Yellow
  - Several conditions (not communicating, ignition off, speed 0) have
    **commented-out** red coloring -- all vehicles currently appear green/yellow
- **Plow icon:** Custom SVG rotated by bearing, flipped horizontally when
  bearing <= 180
- **Boundary polygon:** A small polygon is defined in the source (Paradise
  area coordinates) but its usage is unclear

## Polling Characteristics

- Their frontend polls every **5 seconds**
- Recommended poll interval: **10-15 seconds** (compromise between
  freshness and being a good neighbor)
- No authentication required
- Vehicle count: **Unknown** (API returns empty during research period)
- Coverage: Town of Paradise municipal boundaries

## Availability Concerns

This API only returns data when plows are actively out. During periods
between storms, it returns an empty array. The collector should handle
this gracefully (log and continue, don't treat empty as an error).

## Normalization to Common Schema

| Common Field | Source Field | Transform |
|-------------|-------------|-----------|
| `vehicle_id` | `VID` | `str(VID)` |
| `description` | `DeviceName` | Direct |
| `vehicle_type` | `TruckType` | Direct (empty string -> "Unknown") |
| `timestamp` | `DateTime` | Parse ISO 8601 |
| `latitude` | `Latitude` | Direct (note: capital L) |
| `longitude` | `longitude` | Direct (note: lowercase l) |
| `bearing` | `Bearing` | Direct, but map -1 to `None` |
| `speed` | `Speed` | Direct (float) |
| `is_driving` | Derived | Derive from `Ignition` + `Speed`: if `Ignition == 1 and Speed > 0` -> "maybe", else "no" |

### Additional Fields Available (not in common schema)

| Field | Use |
|-------|-----|
| `IsDeviceCommunicating` | Could be used to filter out stale vehicles |
| `Ignition` | Used to derive is_driving |
| `CurrentStateDuration` | Could be shown in vehicle details popup |

## Implementation Priority

**Low priority** for initial multi-source implementation because:
1. Returns empty data most of the time
2. Can't verify the parser against live data
3. Different platform from the other sources (can't share parser code)

Recommended to implement the parser but disable the source by default
until it can be tested during an active storm.

## Map Center

- Center: (-52.87, 47.52)
- Zoom: 14
- Coverage: Town of Paradise municipal boundaries
