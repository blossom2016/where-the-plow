# Torbay PlowTracker (Skyhawk / ConnectAnywhere)

**Status:** API reverse-engineered, not yet implemented
**GitHub issue:** TBD
**Tracker URL:** https://torbay.plowtracker.com/
**API type:** GeoServer WMS/WMTS (WFS disabled)
**Platform:** Skyhawk PlowTracker (plowtracker.com)

## Architecture

The Torbay plow tracker is a white-label Angular SPA built by Skyhawk
Technologies. It uses:

- **Frontend:** Angular SPA with ArcGIS JS SDK 4.18
- **Config:** Static JSON on S3 (`site_properties.json`)
- **Map tiles:** GeoServer WMTS via `gs-ca-lb.connectanywhere.co`
- **Map style:** ArcGIS basemap with WMTS overlays

The same PlowTracker platform is used by multiple municipalities
including Pittsburgh, Dieppe, Westland, and others. Each deployment
has its own subdomain (`{city}.plowtracker.com`) and S3 bucket.

## Config Endpoint

```
GET https://v2pubsite-torbay-plows.s3.ca-central-1.amazonaws.com/site_properties.json
```

No authentication required. Returns the full site configuration.

### Key Config Fields

| Field | Value |
|-------|-------|
| `refreshInterval` | `60` (seconds) |
| `startingLatitude` | `47.658` |
| `startingLongitude` | `-52.735` |
| `startingZoom` | `13` |
| `vehicleLayer` | `public-site-ws-697a2ba5d7cf39115c936fc7:vehicle_positions` |
| `vehicleLayerStyle` | `vehicle_locations_style` |
| `showTravel` | `true` |
| `showSpreading` | `true` |
| `showDeadheading` | `true` |
| `showPlowing` | `false` |
| `minutesList` | `[720, 480, 360, 240, 120, 60, 0]` |

### GeoServer Details

| Field | Value |
|-------|-------|
| Base URL | `https://gs-ca-lb.connectanywhere.co/geoserver` |
| Workspace | `public-site-ws-697a2ba5d7cf39115c936fc7` |
| WMTS template | `{base}/gwc/service/wmts/rest/{LayerName}/{Style}/EPSG:900913/...` |

## Available Services

| Service | Status |
|---------|--------|
| WMS | Enabled (GetMap, GetCapabilities) |
| WMTS | Enabled (tile serving) |
| WFS | **Disabled** ("Service WFS is disabled") |
| REST API | Requires authentication (401) |

## Data Access Strategy: WMS KML

Since WFS is disabled, the best approach for getting vector data is WMS
GetMap with KML output format:

```
GET https://gs-ca-lb.connectanywhere.co/geoserver/public-site-ws-697a2ba5d7cf39115c936fc7/wms
    ?service=WMS
    &version=1.1.1
    &request=GetMap
    &layers=public-site-ws-697a2ba5d7cf39115c936fc7:vehicle_positions
    &styles=vehicle_locations_style
    &srs=EPSG:4326
    &bbox=-52.9,47.5,-52.6,47.8
    &width=256
    &height=256
    &format=application/vnd.google-earth.kml+xml
```

This returns a KML document. When no vehicles are active, the KML
contains an empty `<Folder>`. When vehicles are present, each should
appear as a KML Placemark with coordinates.

**Confirmed working** (Feb 2026, late night -- returned empty KML
because no plows were active, but the endpoint responded correctly).

### Historical Trail Layers

The site also exposes historical trail layers via WMTS/WMS, following
the naming pattern `{workspace}:{activity}_{minutes}`:

| Layer | Activity | Description |
|-------|----------|-------------|
| `travel_60` | travel | Plow travel in last 60 minutes |
| `travel_120` | travel | Plow travel in last 120 minutes |
| `spreading_60` | spreading | Salting/sanding in last 60 minutes |
| `spreading_120` | spreading | Salting/sanding in last 120 minutes |
| `deadheading_60` | deadheading | Salt/sander travel in last 60 minutes |
| `deadheading_120` | deadheading | Salt/sander travel in last 120 minutes |
| ... | ... | Up to 720 minutes for each activity |

These could also be queried via WMS GetMap with KML output to get trail
line geometries for coverage display.

## KML Response Shape (Expected)

When vehicles are active, the KML should contain Placemarks. The exact
shape needs to be confirmed during an active storm, but based on the
GeoServer layer name (`vehicle_positions`) and the frontend legend
("Vehicle Locations"), expect something like:

```xml
<Placemark>
  <name>Vehicle Name</name>
  <description>...</description>
  <Point>
    <coordinates>-52.735,47.658,0</coordinates>
  </Point>
</Placemark>
```

The KML may or may not include extended data fields (bearing, speed,
timestamp). This needs to be verified with live data.

## What We Don't Know

1. **Exact KML Placemark shape** -- no live vehicles observed during
   research (late night). Needs confirmation during active plowing.
2. **Whether KML includes metadata** -- bearing, speed, timestamps, or
   vehicle names may be in `<ExtendedData>` or `<description>`.
3. **Whether trail layers return useful line data** -- the track layers
   (travel, spreading, deadheading) should return LineString geometries
   but this needs live confirmation.
4. **Rate limits** -- unknown, but the configured `refreshInterval` of
   60 seconds suggests that's a reasonable poll rate.
5. **Vehicle count** -- unknown until observed during a storm.

## Implementation Plan

### Parser: `plowtracker`

1. **Fetch**: Single GET to the WMS endpoint with KML output format
2. **Parse**: Parse KML XML to extract Placemark coordinates and any
   metadata from `<ExtendedData>` or `<description>` fields
3. **Normalize**: Map to the common schema:
   - `vehicle_id`: From Placemark name or an ID field
   - `latitude`/`longitude`: From coordinates
   - `timestamp`: From KML data if available, else `collected_at`
   - `bearing`/`speed`: From extended data if available, else defaults
   - `vehicle_type`: `"SA PLOW TRUCK"` (only plows tracked)
   - `is_driving`: Derive from extended data if available

### Config

- `api_url`: The full WMS GetMap URL with KML format
- `poll_interval`: 60 seconds (matches their `refreshInterval`)
- `center`: (-52.735, 47.658)
- `zoom`: 13
- **Start disabled by default** until KML shape is confirmed with live
  data during an active storm

### Dependencies

- Python stdlib `xml.etree.ElementTree` for KML parsing (no new deps)

## Brittleness Concerns

1. **Workspace ID** (`697a2ba5d7cf39115c936fc7`) is a hash that could
   change if the deployment is recreated. The `site_properties.json`
   config file contains this dynamically, so a more resilient approach
   could fetch config on startup.
2. **WMS KML output** is not the primary intended use of this endpoint
   (it serves WMTS tiles to the frontend). The KML format could be
   removed or change without notice.
3. **BBOX must cover the municipality** -- if bounds are too small,
   vehicles outside the query area won't be returned.

## Reusability

The PlowTracker platform (Skyhawk) is used by multiple municipalities.
The same WMS/KML approach would work for any deployment -- only the
subdomain, workspace ID, and BBOX change. The `site_properties.json`
config provides all needed values programmatically.

Known PlowTracker deployments from the JS bundle:
- Pittsburgh (`pittsburgh.plowtracker.com`)
- Dieppe (`dieppe-staging.plowtracker.com`)
- Westland (`westland.plowtracker.com`)

## Map Center

- Center: (-52.735, 47.658)
- Zoom: 13
- Coverage: Town of Torbay
- Boundaries: N 47.723, S 47.599, E -52.646, W -52.852
