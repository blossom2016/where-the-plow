# Coverage Playback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add coverage playback mode with per-vehicle LineString trails, time range slider, and recency-based opacity rendering.

**Architecture:** Replace the existing `/coverage` endpoint with one returning downsampled per-vehicle LineStrings with parallel timestamp arrays. Frontend gets a mode toggle (Realtime/Coverage) and a range slider that re-renders cached trails client-side.

**Tech Stack:** Python/FastAPI, DuckDB, Pydantic, MapLibre GL JS

---

### Task 1: Pydantic Models for Coverage Response

**Files:**
- Modify: `src/where_the_plow/models.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_coverage_feature_collection():
    from where_the_plow.models import (
        CoverageFeature,
        CoverageFeatureCollection,
        CoverageProperties,
        LineStringGeometry,
    )

    fc = CoverageFeatureCollection(
        features=[
            CoverageFeature(
                geometry=LineStringGeometry(
                    coordinates=[[-52.73, 47.56], [-52.74, 47.57]]
                ),
                properties=CoverageProperties(
                    vehicle_id="v1",
                    vehicle_type="TA PLOW TRUCK",
                    description="2307 TA PLOW TRUCK",
                    timestamps=["2026-02-19T10:00:05Z", "2026-02-19T10:00:35Z"],
                ),
            )
        ]
    )
    assert fc.type == "FeatureCollection"
    assert len(fc.features) == 1
    assert fc.features[0].geometry.type == "LineString"
    assert len(fc.features[0].properties.timestamps) == 2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_coverage_feature_collection -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `src/where_the_plow/models.py`:

```python
class LineStringGeometry(BaseModel):
    type: str = Field(default="LineString")
    coordinates: list[list[float]] = Field(
        ..., description="Array of [longitude, latitude] coordinate pairs"
    )


class CoverageProperties(BaseModel):
    vehicle_id: str = Field(..., description="Unique vehicle identifier")
    vehicle_type: str = Field(..., description="Vehicle category")
    description: str = Field(..., description="Human-readable vehicle label")
    timestamps: list[str] = Field(
        ...,
        description="ISO 8601 timestamps parallel to coordinates array",
    )


class CoverageFeature(BaseModel):
    type: str = Field(default="Feature")
    geometry: LineStringGeometry
    properties: CoverageProperties


class CoverageFeatureCollection(BaseModel):
    type: str = Field(default="FeatureCollection")
    features: list[CoverageFeature]
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/where_the_plow/models.py tests/test_models.py
git commit -m "feat: add Pydantic models for coverage LineString response"
```

---

### Task 2: Database Method for Coverage Trails

**Files:**
- Modify: `src/where_the_plow/db.py` — replace `get_coverage` method
- Test: `tests/test_db.py` — replace `test_get_coverage`

**Step 1: Write the failing test**

Replace `test_get_coverage` in `tests/test_db.py` with:

```python
def test_get_coverage_trails():
    db, path = make_db()
    now = datetime.now(timezone.utc)
    ts1 = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 19, 12, 0, 30, tzinfo=timezone.utc)
    ts3 = datetime(2026, 2, 19, 12, 1, 0, tzinfo=timezone.utc)

    db.upsert_vehicles(
        [
            {"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "TA PLOW TRUCK"},
            {"vehicle_id": "v2", "description": "Plow 2", "vehicle_type": "LOADER"},
        ],
        now,
    )
    db.insert_positions(
        [
            {"vehicle_id": "v1", "timestamp": ts1, "longitude": -52.73, "latitude": 47.56, "bearing": 0, "speed": 10.0, "is_driving": "maybe"},
            {"vehicle_id": "v1", "timestamp": ts2, "longitude": -52.74, "latitude": 47.57, "bearing": 90, "speed": 15.0, "is_driving": "maybe"},
            {"vehicle_id": "v1", "timestamp": ts3, "longitude": -52.75, "latitude": 47.58, "bearing": 180, "speed": 20.0, "is_driving": "maybe"},
            # v2 has only one position — should be excluded (no trail)
            {"vehicle_id": "v2", "timestamp": ts1, "longitude": -52.80, "latitude": 47.50, "bearing": 0, "speed": 0.0, "is_driving": "no"},
        ],
        now,
    )

    trails = db.get_coverage_trails(since=ts1, until=ts3)
    assert len(trails) == 1  # only v1 has a trail
    trail = trails[0]
    assert trail["vehicle_id"] == "v1"
    assert trail["vehicle_type"] == "TA PLOW TRUCK"
    assert trail["description"] == "Plow 1"
    assert len(trail["coordinates"]) == 3
    assert len(trail["timestamps"]) == 3
    assert trail["coordinates"][0] == [-52.73, 47.56]
    assert trail["timestamps"][0] <= trail["timestamps"][1]

    db.close()
    os.unlink(path)


def test_get_coverage_trails_downsampling():
    """Positions closer than 30s apart should be downsampled."""
    db, path = make_db()
    now = datetime.now(timezone.utc)

    db.upsert_vehicles(
        [{"vehicle_id": "v1", "description": "Plow 1", "vehicle_type": "LOADER"}],
        now,
    )
    # Insert 10 positions 6s apart (total 54s span)
    positions = []
    for i in range(10):
        ts = datetime(2026, 2, 19, 12, 0, i * 6, tzinfo=timezone.utc)
        positions.append({
            "vehicle_id": "v1", "timestamp": ts,
            "longitude": -52.73 + i * 0.001, "latitude": 47.56,
            "bearing": 0, "speed": 10.0, "is_driving": "maybe",
        })
    db.insert_positions(positions, now)

    since = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 2, 19, 12, 0, 54, tzinfo=timezone.utc)
    trails = db.get_coverage_trails(since=since, until=until)
    assert len(trails) == 1
    # With 30s downsampling: keep t=0, skip t=6..24, keep t=30, skip t=36..48, keep t=54
    # Should have ~3 points, not 10
    assert len(trails[0]["coordinates"]) < 10
    assert len(trails[0]["coordinates"]) >= 2

    db.close()
    os.unlink(path)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_coverage_trails tests/test_db.py::test_get_coverage_trails_downsampling -v`
Expected: FAIL with AttributeError

**Step 3: Write minimal implementation**

Replace `get_coverage` in `src/where_the_plow/db.py` with:

```python
def get_coverage_trails(
    self,
    since: datetime,
    until: datetime,
    min_interval_s: float = 30.0,
) -> list[dict]:
    """Get per-vehicle LineString trails in a time range, downsampled."""
    query = """
        SELECT p.vehicle_id, p.timestamp, p.longitude, p.latitude,
               v.description, v.vehicle_type
        FROM positions p
        JOIN vehicles v ON p.vehicle_id = v.vehicle_id
        WHERE p.timestamp >= $1
        AND p.timestamp <= $2
        ORDER BY p.vehicle_id, p.timestamp ASC
    """
    rows = self.conn.execute(query, [since, until]).fetchall()

    # Group by vehicle
    from itertools import groupby
    from operator import itemgetter

    trails = []
    for vid, group in groupby(rows, key=itemgetter(0)):
        points = list(group)
        if len(points) < 2:
            continue

        # Downsample: keep first point, then skip until >= min_interval_s
        sampled = [points[0]]
        for pt in points[1:]:
            elapsed = (pt[1] - sampled[-1][1]).total_seconds()
            if elapsed >= min_interval_s:
                sampled.append(pt)
        # Always include the last point
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])

        if len(sampled) < 2:
            continue

        trails.append({
            "vehicle_id": vid,
            "description": sampled[0][4],
            "vehicle_type": sampled[0][5],
            "coordinates": [[p[2], p[3]] for p in sampled],
            "timestamps": [
                p[1].isoformat() if isinstance(p[1], datetime) else str(p[1])
                for p in sampled
            ],
        })

    return trails
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/where_the_plow/db.py tests/test_db.py
git commit -m "feat: add get_coverage_trails DB method with downsampling"
```

---

### Task 3: Coverage API Route

**Files:**
- Modify: `src/where_the_plow/routes.py` — replace `/coverage` endpoint
- Test: `tests/test_routes.py` — update `test_get_coverage`

**Step 1: Write the failing test**

Replace `test_get_coverage` in `tests/test_routes.py` with:

```python
def test_get_coverage(test_client):
    resp = test_client.get(
        "/coverage?since=2026-02-19T00:00:00Z&until=2026-02-20T00:00:00Z"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    # With only 1 position per vehicle in seed data, no trails (need >= 2)
    assert len(data["features"]) == 0
```

Also add a second test with enough seed data for a trail. Add more positions in the fixture by adding these lines after the existing `db.insert_positions(...)` call in the `test_client` fixture:

```python
# Add more positions for v1 to test coverage trails
from datetime import timedelta
ts2 = ts + timedelta(seconds=30)
ts3 = ts + timedelta(seconds=60)
db.insert_positions(
    [
        {
            "vehicle_id": "v1",
            "timestamp": ts2,
            "longitude": -52.74,
            "latitude": 47.57,
            "bearing": 90,
            "speed": 15.0,
            "is_driving": "maybe",
        },
        {
            "vehicle_id": "v1",
            "timestamp": ts3,
            "longitude": -52.75,
            "latitude": 47.58,
            "bearing": 180,
            "speed": 20.0,
            "is_driving": "maybe",
        },
    ],
    now,
)
```

Then add a test:

```python
def test_get_coverage_has_trails(test_client):
    resp = test_client.get(
        "/coverage?since=2026-02-19T00:00:00Z&until=2026-02-20T00:00:00Z"
    )
    data = resp.json()
    assert len(data["features"]) == 1
    f = data["features"][0]
    assert f["geometry"]["type"] == "LineString"
    assert len(f["geometry"]["coordinates"]) >= 2
    assert f["properties"]["vehicle_id"] == "v1"
    assert "timestamps" in f["properties"]
    assert len(f["properties"]["timestamps"]) == len(f["geometry"]["coordinates"])
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_routes.py::test_get_coverage tests/test_routes.py::test_get_coverage_has_trails -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Replace the `/coverage` endpoint in `src/where_the_plow/routes.py`:

```python
from where_the_plow.models import (
    # ... existing imports ...,
    CoverageFeature,
    CoverageFeatureCollection,
    CoverageProperties,
    LineStringGeometry,
)

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
```

Remove the old pagination imports/params from this endpoint — coverage trails don't paginate.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_routes.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/where_the_plow/routes.py tests/test_routes.py src/where_the_plow/models.py
git commit -m "feat: replace /coverage endpoint with per-vehicle LineString trails"
```

---

### Task 4: Frontend — Mode Toggle and Coverage Panel

**Files:**
- Modify: `src/where_the_plow/static/index.html`

No automated tests — manual verification.

**Step 1: Add CSS for mode toggle and coverage panel**

Add to `<style>` section:

```css
#mode-toggle {
  display: flex;
  margin: 8px 0;
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.15);
}
#mode-toggle button {
  flex: 1;
  padding: 5px 0;
  border: none;
  background: transparent;
  color: #9ca3af;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
#mode-toggle button.active {
  background: rgba(96, 165, 250, 0.25);
  color: #f9fafb;
}
#mode-toggle button:hover:not(.active) {
  background: rgba(255,255,255,0.05);
}
#coverage-panel {
  display: none;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.12);
}
#coverage-panel label {
  color: #9ca3af;
  font-size: 12px;
}
#time-slider {
  width: 100%;
  margin: 6px 0;
  accent-color: #60a5fa;
}
#slider-label {
  color: #f9fafb;
  font-size: 12px;
  text-align: center;
  display: block;
}
#coverage-loading {
  color: #9ca3af;
  font-size: 12px;
  display: none;
}
```

**Step 2: Add HTML for mode toggle and coverage panel**

In the info panel, after the API docs link and before `#vehicle-count`:

```html
<div id="mode-toggle">
  <button id="btn-realtime" class="active">Realtime</button>
  <button id="btn-coverage">Coverage</button>
</div>
```

After `#vehicle-detail`, add:

```html
<div id="coverage-panel">
  <label>Up to:</label>
  <span id="slider-label"></span>
  <input type="range" id="time-slider" min="0" max="1000" value="1000" />
  <div id="coverage-loading">Loading coverage data...</div>
</div>
```

**Step 3: Add mode switching JavaScript**

```javascript
let currentMode = 'realtime';
let refreshInterval = null;
let coverageData = null; // cached /coverage response
let coverageSince = null; // Date
let coverageUntil = null; // Date

const btnRealtime = document.getElementById('btn-realtime');
const btnCoverage = document.getElementById('btn-coverage');
const coveragePanel = document.getElementById('coverage-panel');
const timeSlider = document.getElementById('time-slider');
const sliderLabel = document.getElementById('slider-label');
const coverageLoading = document.getElementById('coverage-loading');

const VEHICLE_COLORS = {
  'SA PLOW TRUCK': '#2563eb',
  'TA PLOW TRUCK': '#2563eb',
  'LOADER': '#ea580c',
  'GRADER': '#16a34a',
};
const DEFAULT_COLOR = '#6b7280';

function vehicleColor(type) {
  return VEHICLE_COLORS[type] || DEFAULT_COLOR;
}

btnRealtime.addEventListener('click', () => switchMode('realtime'));
btnCoverage.addEventListener('click', () => switchMode('coverage'));

async function switchMode(mode) {
  if (mode === currentMode) return;
  currentMode = mode;

  btnRealtime.classList.toggle('active', mode === 'realtime');
  btnCoverage.classList.toggle('active', mode === 'coverage');

  if (mode === 'realtime') {
    enterRealtime();
  } else {
    await enterCoverage();
  }
}

function enterRealtime() {
  // Remove coverage layers
  clearCoverageLayers();
  coveragePanel.style.display = 'none';
  coverageData = null;

  // Show realtime layers
  if (map.getLayer('vehicle-circles')) {
    map.setLayoutProperty('vehicle-circles', 'visibility', 'visible');
  }
  document.getElementById('vehicle-count').style.display = '';

  // Restart auto-refresh
  startAutoRefresh();
}

async function enterCoverage() {
  // Stop auto-refresh
  stopAutoRefresh();

  // Hide realtime layers
  closeDetail();
  if (map.getLayer('vehicle-circles')) {
    map.setLayoutProperty('vehicle-circles', 'visibility', 'none');
  }
  document.getElementById('vehicle-count').style.display = 'none';

  // Show coverage panel
  coveragePanel.style.display = 'block';
  coverageLoading.style.display = 'block';
  timeSlider.value = 1000;

  // Fetch coverage data
  coverageUntil = new Date();
  coverageSince = new Date(coverageUntil.getTime() - ONE_DAY_MS);
  const resp = await fetch(
    `/coverage?since=${coverageSince.toISOString()}&until=${coverageUntil.toISOString()}`
  );
  coverageData = await resp.json();
  coverageLoading.style.display = 'none';

  // Render at full extent
  renderCoverage(1000);
}
```

**Step 4: Add coverage rendering JavaScript**

```javascript
function sliderToTime(val) {
  // Map slider 0–1000 to since–until
  const range = coverageUntil.getTime() - coverageSince.getTime();
  return new Date(coverageSince.getTime() + (val / 1000) * range);
}

timeSlider.addEventListener('input', (e) => {
  renderCoverage(parseInt(e.target.value));
});

function clearCoverageLayers() {
  if (map.getLayer('coverage-lines')) map.removeLayer('coverage-lines');
  if (map.getSource('coverage-lines')) map.removeSource('coverage-lines');
}

function renderCoverage(sliderVal) {
  if (!coverageData) return;

  const cutoff = sliderToTime(sliderVal);
  sliderLabel.textContent = formatTimestamp(cutoff.toISOString());

  const sinceMs = coverageSince.getTime();
  const rangeMs = cutoff.getTime() - sinceMs;

  const segmentFeatures = [];

  for (const feature of coverageData.features) {
    const coords = feature.geometry.coordinates;
    const timestamps = feature.properties.timestamps;
    const color = vehicleColor(feature.properties.vehicle_type);

    for (let i = 0; i < coords.length - 1; i++) {
      const tMs = new Date(timestamps[i]).getTime();
      const tNextMs = new Date(timestamps[i + 1]).getTime();

      // Only include segments where the end point is within the cutoff
      if (tNextMs > cutoff.getTime()) break;

      const progress = rangeMs > 0 ? (tMs - sinceMs) / rangeMs : 1;
      const opacity = 0.15 + progress * 0.65;

      segmentFeatures.push({
        type: 'Feature',
        geometry: {
          type: 'LineString',
          coordinates: [coords[i], coords[i + 1]],
        },
        properties: { seg_opacity: opacity, seg_color: color },
      });
    }
  }

  const data = { type: 'FeatureCollection', features: segmentFeatures };

  const source = map.getSource('coverage-lines');
  if (source) {
    source.setData(data);
  } else {
    map.addSource('coverage-lines', { type: 'geojson', data });
    map.addLayer({
      id: 'coverage-lines',
      type: 'line',
      source: 'coverage-lines',
      paint: {
        'line-color': ['get', 'seg_color'],
        'line-width': 3,
        'line-opacity': ['get', 'seg_opacity'],
      },
    });
  }
}
```

**Step 5: Refactor auto-refresh to be start/stoppable**

Replace the current `setInterval(...)` with:

```javascript
function startAutoRefresh() {
  if (refreshInterval) return;
  refreshInterval = setInterval(async () => {
    if (currentMode !== 'realtime') return;
    try {
      const rawData = await fetchVehicles();
      const freshData = filterRecentFeatures(rawData);
      map.getSource('vehicles').setData(freshData);
      updateVehicleCount(freshData);
      updateDetailFromData(freshData);
      refreshTrail();
    } catch (err) {
      console.error('Failed to refresh vehicles:', err);
    }
  }, 6000);
}

function stopAutoRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = null;
  }
}
```

In the `map.on('load')` callback, replace the inline `setInterval` with a call to `startAutoRefresh()`.

**Step 6: Verify manually**

1. Open http://localhost:8000 — should default to Realtime mode
2. Click "Coverage" — should fetch data, show slider, render trails
3. Drag slider left — trails should shrink, older segments should fade
4. Click "Realtime" — should return to live vehicle dots

**Step 7: Commit**

```bash
git add src/where_the_plow/static/index.html
git commit -m "feat: add coverage playback mode with range slider and recency gradient"
```

---

### Task 5: Run Full Test Suite and Lint

**Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: all PASS

**Step 2: Run lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean

**Step 3: Fix any issues found**

**Step 4: Final commit if needed**

```bash
git add -A
git commit -m "chore: lint and test cleanup"
```
