# Mount Pearl AATracking API

**Status:** API confirmed working, not yet implemented
**GitHub issue:** #14
**Tracker URL:** (no public web UI found -- API only)
**API type:** AATracking REST API
**Platform:** Same backend as Provincial (gps5.aatracking.com)

## API Endpoint

```
GET https://gps5.aatracking.com/api/MtPearlPortal/GetPlows
```

No authentication, no special headers, no query parameters required.

## Response Shape

Returns a JSON array of vehicle objects:

```json
[
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
    "LOO_DESCRIPTION": "Large Snow Plow_Blue"
  }
]
```

### Field Details

| Field | Type | Notes |
|-------|------|-------|
| `VEH_ID` | int | Unique vehicle identifier within this portal |
| `VEH_NAME` | string | Short name e.g. "21-21D", "22-05L" |
| `VEH_UNIQUE_ID` | string | IMEI or device serial number |
| `VEH_EVENT_DATETIME` | string | ISO 8601 datetime **without timezone** -- assumed UTC or local |
| `VEH_EVENT_LATITUDE` | float | Latitude (WGS84) |
| `VEH_EVENT_LONGITUDE` | float | Longitude (WGS84) |
| `VEH_EVENT_HEADING` | float | Heading in degrees (0-360), can be decimal |
| `LOO_TYPE` | string | Vehicle category: "HEAVY_TYPE" |
| `LOO_CODE` | string | Icon code used by AATracking UI for marker selection |
| `VEH_SEG_TYPE` | string | Segment type: "ST" (unknown purpose) |
| `LOO_DESCRIPTION` | string | Human-readable type: "Large Snow Plow_Blue", "Large Loader" |

### Timestamp Notes

- The `VEH_EVENT_DATETIME` field is an ISO 8601 string **without timezone info**
- Alex's implementation treated it as UTC; this seems reasonable but may
  actually be Newfoundland time (needs verification during active storm)
- The timestamp IS present (unlike the Provincial API)

### Fields NOT Present (compared to St. John's)

- **No speed** -- the API does not return speed data
- **No isDriving equivalent** -- no way to know if the vehicle is actively
  moving from this API alone (could infer from position changes between polls)

## Polling Characteristics

- AATracking's own web UI polls every **30 seconds**
- Recommended poll interval: **30 seconds** (match upstream)
- No authentication required
- Observed vehicle count: **14 vehicles** (during active storm, Feb 2026)
- Vehicle types seen: "Large Snow Plow_Blue", "Large Loader"

## LOO_CODE / LOO_TYPE Mapping

These fields are used by AATracking's web UI for icon selection. We don't
need them for our purposes -- `LOO_DESCRIPTION` is sufficient for our
`vehicle_type` field. Known values:

| LOO_CODE | LOO_DESCRIPTION |
|----------|-----------------|
| `SnowPlowBlue_` | Large Snow Plow_Blue |
| `Loader_` | Large Loader |

## Map Center

- Center: (-52.81, 47.52)
- Zoom: 13
- Coverage: City of Mount Pearl municipal boundaries

## Normalization to Common Schema

| Common Field | Source Field | Transform |
|-------------|-------------|-----------|
| `vehicle_id` | `VEH_ID` | `str(VEH_ID)` |
| `description` | `VEH_NAME` | Direct |
| `vehicle_type` | `LOO_DESCRIPTION` | Direct |
| `timestamp` | `VEH_EVENT_DATETIME` | Parse ISO 8601, assume UTC if no tz |
| `latitude` | `VEH_EVENT_LATITUDE` | Direct |
| `longitude` | `VEH_EVENT_LONGITUDE` | Direct |
| `bearing` | `VEH_EVENT_HEADING` | `int(VEH_EVENT_HEADING)` |
| `speed` | N/A | `None` |
| `is_driving` | N/A | `None` (or infer from position deltas) |

## Relationship to Other AATracking Portals

Mount Pearl and Provincial plows use the **same AATracking backend**
(`gps5.aatracking.com`) with different portal names in the URL path:

- Mount Pearl: `/api/MtPearlPortal/GetPlows`
- Provincial: `/api/NewfoundlandPortal/GetPlows`

The field naming convention (`VEH_*`, `LOO_*`) is identical. Mt Pearl has
a superset of fields compared to Provincial (extra: `VEH_UNIQUE_ID`,
`VEH_EVENT_DATETIME`, `VEH_SEG_TYPE`).

A generic AATracking parser can handle both with conditional logic for
the missing fields.
