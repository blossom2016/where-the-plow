# St. John's AVL API

**Status:** Implemented (current sole source)
**GitHub issue:** N/A (original)
**Tracker URL:** https://map.stjohns.ca/avl/
**API type:** ArcGIS REST MapServer

## API Endpoint

```
GET https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query
```

### Required Parameters

| Param | Value |
|-------|-------|
| `f` | `json` |
| `outFields` | `ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving` |
| `outSR` | `4326` |
| `returnGeometry` | `true` |
| `where` | `1=1` |

### Required Headers

| Header | Value | Notes |
|--------|-------|-------|
| `Referer` | `https://map.stjohns.ca/avl/` | **Required** -- request fails without it |

## Response Shape

```json
{
  "features": [
    {
      "attributes": {
        "ID": 12345,
        "Description": "2222 SA PLOW TRUCK",
        "VehicleType": "SA PLOW TRUCK",
        "LocationDateTime": 1708000000000,
        "Bearing": 180,
        "Speed": "45.2",
        "isDriving": "maybe"
      },
      "geometry": {
        "x": -52.731,
        "y": 47.564
      }
    }
  ]
}
```

### Field Details

| Field | Type | Notes |
|-------|------|-------|
| `ID` | int | Unique vehicle identifier |
| `Description` | string | e.g. "2222 SA PLOW TRUCK" |
| `VehicleType` | string | e.g. "SA PLOW TRUCK" |
| `LocationDateTime` | int | Epoch milliseconds -- **see timestamp quirk below** |
| `Bearing` | int | Heading 0-360 degrees |
| `Speed` | string | Speed as a string, must be parsed to float |
| `isDriving` | string | "maybe" or "no" |
| `geometry.x` | float | Longitude (WGS84) |
| `geometry.y` | float | Latitude (WGS84) |

## Timestamp Quirk

The `LocationDateTime` field returns epoch-millisecond timestamps that
**represent Newfoundland Standard Time (UTC-3:30) but are encoded as if
they were UTC**. To get the real UTC time, you must add 3 hours and 30
minutes to the parsed datetime.

```python
_NST_CORRECTION = timedelta(hours=3, minutes=30)
ts = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc) + _NST_CORRECTION
```

## Polling Characteristics

- Our current poll interval: **6 seconds**
- No authentication required (just the Referer header)
- Typical vehicle count during storms: ~20-30 vehicles
- Vehicle types seen: SA PLOW TRUCK, SIDEWALK PLOW, LOADER, etc.

## Map Center

- Center: (-52.71, 47.56)
- Zoom: 12
- Coverage: City of St. John's municipal boundaries

## Normalization to Common Schema

| Common Field | Source Field | Transform |
|-------------|-------------|-----------|
| `vehicle_id` | `ID` | `str(ID)` |
| `description` | `Description` | Direct |
| `vehicle_type` | `VehicleType` | Direct |
| `timestamp` | `LocationDateTime` | Epoch-ms parse + NST correction |
| `latitude` | `geometry.y` | Direct |
| `longitude` | `geometry.x` | Direct |
| `bearing` | `Bearing` | Direct (int) |
| `speed` | `Speed` | `float(Speed)` -- parse from string |
| `is_driving` | `isDriving` | Direct |
