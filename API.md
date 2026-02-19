# St. John's AVL (Automatic Vehicle Location) API

## Endpoint

```
https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query
```

ArcGIS REST API (v11.5) serving real-time vehicle location data for the City of St. John's fleet.

## Query Parameters

| Parameter | Value | Notes |
|---|---|---|
| `f` | `json` | Response format. Also supports `geojson` and `pbf` (binary) |
| `outFields` | `ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving` | Comma-separated field list |
| `outSR` | `4326` | Output spatial reference. `4326` = WGS84 (standard lat/lng) |
| `returnGeometry` | `true` | Include coordinates in response |
| `where` | SQL filter | e.g. `isDriving = 'maybe'` for active vehicles, or `1=1` for all |

### Example: All active vehicles

```
https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query
  ?f=json
  &outFields=ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving
  &outSR=4326
  &returnGeometry=true
  &where=isDriving = 'maybe'
```

### Example: All vehicles (active and inactive)

```
https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query
  ?f=json
  &outFields=ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving
  &outSR=4326
  &returnGeometry=true
  &where=1=1
```

## Response Shape

```jsonc
{
  "displayFieldName": "ID",
  "geometryType": "esriGeometryPoint",
  "spatialReference": {
    "wkid": 4326,          // WGS84
    "latestWkid": 4326
  },
  "fields": [
    // field metadata array (see below)
  ],
  "features": [
    {
      "attributes": {
        "ID": string,               // unique vehicle identifier (e.g. "281474984421544")
        "Description": string,      // human-readable label (e.g. "2222 SA PLOW TRUCK")
        "VehicleType": string,      // vehicle category (see values below)
        "LocationDateTime": number, // Unix timestamp in milliseconds
        "Bearing": number,          // direction of travel in degrees (0-360)
        "Speed": string,            // speed in km/h as string (e.g. "13.4")
        "isDriving": string         // driving status (see values below)
      },
      "geometry": {
        "x": number,  // longitude (e.g. -52.731)
        "y": number   // latitude (e.g. 47.564)
      }
    }
  ]
}
```

## Field Reference

| Field | Type | Description |
|---|---|---|
| `ID` | string | Unique vehicle identifier |
| `Description` | string | Human-readable vehicle label (unit number + type) |
| `VehicleType` | string | Vehicle category |
| `LocationDateTime` | number | Position timestamp (Unix ms) |
| `Bearing` | integer | Heading in degrees, 0 = north |
| `Speed` | string | Speed in km/h |
| `isDriving` | string | Current driving status |

## `isDriving` Values

| Value | Meaning |
|---|---|
| `maybe` | Vehicle is active / potentially moving |
| `no` | Vehicle is parked / inactive |

## `VehicleType` Values

| Value | Count (as of 2026-02-19) |
|---|---|
| `LOADER` | 54 |
| `TA PLOW TRUCK` | 32 |
| `SA PLOW TRUCK` | 9 |
| `PICKUP` | 8 |
| `MD DUMP TRUCK` | 4 |
| `GRADER` | 2 |
| `MD PICKUP` | 2 |
| `MD FLATBED` | 1 |

**Total fleet: 112 vehicles**

## Required Headers

The API requires a `Referer` header:

```
Referer: https://map.stjohns.ca/avl/
```

## Notes

- Max record count per request: 2000
- Native spatial reference is WGS84 (EPSG:4326); use `outSR=4326` to get standard lat/lng
- The `geometry` parameter (bounding box) is optional — omitting it returns all vehicles city-wide
- The `LocationDateTime` filter can be used for freshness (e.g. only vehicles seen in the last hour)
