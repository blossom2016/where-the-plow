# Provincial AATracking API

**Status:** API confirmed working, not yet implemented
**GitHub issue:** #13
**Tracker URL:** https://gps5.aatracking.com/newfoundland/wintermaintenance.html
**API type:** AATracking REST API
**Platform:** Same backend as Mount Pearl (gps5.aatracking.com)

## API Endpoint

```
GET https://gps5.aatracking.com/api/NewfoundlandPortal/GetPlows
```

No authentication, no special headers, no query parameters required.

### Additional Endpoints (discovered in portal.js)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/NewfoundlandPortal/GetPlowEvents?intVehicleID={VEH_ID}` | Event history for a specific plow |
| `GET /api/NewfoundlandPortal/GetTrafficCameras` | Traffic camera locations |

#### Plow Events Response Shape

```json
[
  {
    "EVT_LATITUDE": 48.123,
    "EVT_LONGITUDE": -55.456,
    "EVT_HEADING": 90
  }
]
```

This could be useful for building historical trails from the AATracking
side, but we'd need to poll per-vehicle which doesn't scale well.

#### KMZ Road Coverage (from Google Cloud Storage)

The provincial tracker also displays road coverage via KMZ files:

- `https://storage.googleapis.com/aat_kmz/NEWFOUNDLAND_streets30.kmz` (30 min)
- `https://storage.googleapis.com/aat_kmz/NEWFOUNDLAND_streets60.kmz` (60 min)
- `https://storage.googleapis.com/aat_kmz/NEWFOUNDLAND_streets120.kmz` (120 min)
- `https://storage.googleapis.com/aat_kmz/NEWFOUNDLAND_streets240.kmz` (240 min)

These are pre-built by AATracking and could be interesting for coverage
display, but parsing KMZ is complex and outside our current scope.

## Response Shape

Returns a JSON array of vehicle objects:

```json
[
  {
    "VEH_ID": 15644,
    "VEH_NAME": "7452 F",
    "VEH_EVENT_LATITUDE": 48.986115,
    "VEH_EVENT_LONGITUDE": -55.55174,
    "VEH_EVENT_HEADING": 46.03,
    "LOO_TYPE": "TRUCK_TYPE",
    "LOO_CODE": "ng-Plow-Full-FS-Yellow_",
    "LOO_DESCRIPTION": "Large Plow Full Plow Side Yellow"
  }
]
```

### Field Details

| Field | Type | Notes |
|-------|------|-------|
| `VEH_ID` | int | Unique vehicle identifier within this portal |
| `VEH_NAME` | string | Short name e.g. "7452 F" |
| `VEH_EVENT_LATITUDE` | float | Latitude (WGS84) |
| `VEH_EVENT_LONGITUDE` | float | Longitude (WGS84) |
| `VEH_EVENT_HEADING` | float | Heading in degrees (0-360), can be decimal |
| `LOO_TYPE` | string | Vehicle category: "TRUCK_TYPE" |
| `LOO_CODE` | string | Icon code used by AATracking UI |
| `LOO_DESCRIPTION` | string | Human-readable type |

### Fields MISSING (compared to Mount Pearl)

- **No `VEH_EVENT_DATETIME`** -- no timestamp at all
- **No `VEH_UNIQUE_ID`** -- no device serial/IMEI
- **No `VEH_SEG_TYPE`** -- no segment type
- **No speed** -- same as Mt Pearl

This is the most limited API of all the sources. We must use `collected_at`
(the time we polled) as the timestamp.

### Deduplication Challenge

Without a timestamp, the `(vehicle_id, timestamp, source)` primary key
means: if a vehicle hasn't moved between two polls (same position), we'll
still insert a new row because `collected_at` differs each time.

Options to handle this:
1. **Accept the duplicates** -- positions are small, and the coverage
   trail query already downsamples. This is simplest.
2. **Check if position changed** -- before insert, compare with last known
   position for that vehicle. Only insert if lat/lng actually changed.
   More complex but saves storage.

Recommendation: Start with option 1. The 30-second poll interval and
time_bucket downsampling in coverage queries already handle this gracefully.

## Polling Characteristics

- AATracking's own web UI polls every **30 seconds**
- Recommended poll interval: **30 seconds**
- No authentication required
- Observed vehicle count: **5 vehicles** (Feb 2026, province-wide)
- Vehicles are spread across the entire island of Newfoundland
- Vehicle types seen: "Large Plow Full Plow Side Yellow"

## LOO_CODE Values Observed

| LOO_CODE | LOO_DESCRIPTION |
|----------|-----------------|
| `ng-Plow-Full-FS-Yellow_` | Large Plow Full Plow Side Yellow |

The provincial tracker's portal.js mentions that if `LOO_DESCRIPTION`
contains "Long", a larger icon (100px instead of 50px) is used. This
suggests there are vehicle types of varying sizes.

## Map Center

- Center: (-53.5, 48.5) -- approximate center of Newfoundland island
- Zoom: 7 (province-wide view)
- Coverage: All provincial highways in Newfoundland and Labrador

## Firebase Integration (in web UI only)

The provincial tracker also uses Firebase Realtime Database for route
completion tracking:

```javascript
// Firebase config from portal.js
{
  apiKey: "AIzaSyCAzWAiXYMUk7sPTPYXz9ghsCHxEOqvPdA",
  authDomain: "gps5udp.firebaseapp.com",
  databaseURL: "https://gps5udp.firebaseio.com",
  projectId: "gps5udp"
}
```

Path: `/routecompletion/{companyID}/streets`

This is used for real-time route completion updates but was commented out
in the current portal.js. Not useful for our purposes.

## Normalization to Common Schema

| Common Field | Source Field | Transform |
|-------------|-------------|-----------|
| `vehicle_id` | `VEH_ID` | `str(VEH_ID)` |
| `description` | `VEH_NAME` | Direct |
| `vehicle_type` | `LOO_DESCRIPTION` | Direct |
| `timestamp` | N/A | **Use `collected_at`** (time of poll) |
| `latitude` | `VEH_EVENT_LATITUDE` | Direct |
| `longitude` | `VEH_EVENT_LONGITUDE` | Direct |
| `bearing` | `VEH_EVENT_HEADING` | `int(VEH_EVENT_HEADING)` |
| `speed` | N/A | `None` |
| `is_driving` | N/A | `None` |

## Relationship to Mount Pearl

Uses the same AATracking backend. The parser can share most logic with
Mt Pearl, with conditional handling for missing fields:

```python
def parse_aatracking_response(data, collected_at=None):
    # If VEH_EVENT_DATETIME is present, parse it
    # Otherwise, fall back to collected_at
    ts = parse_datetime(item.get("VEH_EVENT_DATETIME")) or collected_at
```
