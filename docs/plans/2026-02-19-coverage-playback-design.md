# Coverage Playback Design

## Goal

Add a coverage playback mode to the frontend that visualizes where plows have been over the last 24 hours. A growing-window range slider lets users scrub through time, accumulating trails on the map with recency-based color/opacity gradients.

## Architecture

Two modes in the frontend: **Realtime** (existing) and **Coverage** (new). A toggle in the info panel switches between them. Each mode owns its own map layers and panel content.

The existing `/coverage` endpoint is replaced with a new one that returns per-vehicle LineString trails with parallel timestamp arrays. The server downsamples positions (~1 point per 30s) to keep payloads manageable. The frontend fetches all data once on mode entry, then the slider re-renders client-side with no additional API calls.

## API: `GET /coverage`

**Parameters:**
- `since` (ISO 8601, default: 24h ago) — start of window
- `until` (ISO 8601, default: now) — end of window

**Response:** GeoJSON FeatureCollection where each Feature is a LineString (one per vehicle that moved in the window).

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "LineString",
        "coordinates": [[-52.73, 47.56], [-52.74, 47.57], ...]
      },
      "properties": {
        "vehicle_id": "281474992037549",
        "vehicle_type": "TA PLOW TRUCK",
        "description": "2307 TA PLOW TRUCK",
        "timestamps": ["2026-02-19T10:00:05Z", "2026-02-19T10:00:35Z", ...]
      }
    }
  ]
}
```

The `timestamps` array is parallel to `coordinates` — each entry is the time the vehicle was at that coordinate. Vehicles with only one position in the window are omitted (no trail to draw).

**Downsampling:** Skip positions where the previous one was < 30s ago. This keeps ~2880 points per vehicle per 24h (~72k total for 25 active vehicles).

## Frontend: Mode Toggle

A segmented toggle below the title: `[Realtime] [Coverage]`

**Switching to Coverage:**
1. Stop the 6-second auto-refresh interval
2. Hide realtime layers (vehicle-circles, any active trail)
3. Close vehicle detail panel
4. Fetch `/coverage?since=24h_ago&until=now` once
5. Store the full response in memory
6. Show coverage panel: range slider + time label
7. Render trails up to slider position

**Switching to Realtime:**
1. Remove all coverage layers/sources
2. Hide coverage panel
3. Show realtime layers
4. Restart auto-refresh

## Frontend: Range Slider

- Slider range: `since` (left, fixed at 24h ago) to `until` (right, now)
- Slider value represents the current playback position
- Starts at the right (full window visible)
- Label above slider: "Up to: Feb 19, 2:30 PM"
- As slider moves left, trails shrink; as it moves right, they accumulate

## Frontend: Rendering Coverage Trails

For each vehicle LineString in the cached data:
1. Find the subset of coordinates/timestamps where `timestamp <= slider_position`
2. Split into individual 2-point line segments
3. Assign each segment an opacity based on recency: `(segment_time - since) / (slider_position - since)` mapped to range 0.15–0.8
4. Render as a line layer with per-feature opacity (same technique as the realtime trail)

Color: use the same vehicle-type color scheme as realtime dots, so plow trucks are blue, loaders orange, etc.

## Pydantic Models

New models for the coverage response (separate from the existing Point-based FeatureCollection):

- `LineStringGeometry` — `type: "LineString"`, `coordinates: list[list[float]]`
- `CoverageProperties` — `vehicle_id`, `vehicle_type`, `description`, `timestamps: list[str]`
- `CoverageFeature` — `type: "Feature"`, `geometry: LineStringGeometry`, `properties: CoverageProperties`
- `CoverageFeatureCollection` — `type: "FeatureCollection"`, `features: list[CoverageFeature]`
