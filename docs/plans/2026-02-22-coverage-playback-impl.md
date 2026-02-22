# Coverage Playback Controls Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add media-style playback controls to the coverage view that animate coverage data over time, with a follow-vehicle mode.

**Architecture:** Playback reuses the existing dual-range slider and `renderCoverage` pipeline. A `requestAnimationFrame` loop advances the right slider handle from the left handle's position to its original position over a configurable duration. Follow-vehicle interpolates coordinates from the coverage data and uses `map.easeTo` for smooth camera tracking.

**Tech Stack:** Vanilla JS, MapLibre GL JS, noUiSlider (already loaded), HTML/CSS

**Design doc:** `docs/plans/2026-02-22-coverage-playback-controls.md`

---

### Task 1: HTML playback controls

**Files:**
- Modify: `src/where_the_plow/static/index.html:70-71` (between `#time-slider` and `#coverage-loading`)

**Step 1: Add playback controls HTML**

After `<div id="time-slider"></div>` and before `<div id="coverage-loading">`, add:

```html
<div id="playback-controls">
    <div class="playback-row">
        <button id="btn-play" title="Play">&#9654;</button>
        <button id="btn-stop" title="Stop" disabled>&#9632;</button>
        <select id="playback-speed" title="Playback speed">
            <option value="15" selected>15s</option>
            <option value="30">30s</option>
            <option value="60">1m</option>
            <option value="300">5m</option>
            <option value="realtime">Realtime</option>
        </select>
    </div>
    <div class="playback-row">
        <label class="playback-label">Follow:</label>
        <select id="playback-follow" title="Follow vehicle">
            <option value="">None</option>
        </select>
    </div>
</div>
```

**Step 2: Verify HTML renders**

Run: `uv run cli.py dev`, open browser, switch to Coverage mode. Confirm the new controls appear below the slider (unstyled).

---

### Task 2: CSS for playback controls

**Files:**
- Modify: `src/where_the_plow/static/style.css` (after the `#slider-label` block, around line 280)

**Step 1: Add playback styles**

```css
/* -- Playback controls ---------------------------------------- */

#playback-controls {
    margin-top: 8px;
    padding-top: 8px;
    border-top: var(--border-subtle);
}

.playback-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
}

.playback-label {
    color: var(--color-text-secondary);
    font-size: 12px;
    flex-shrink: 0;
}

#btn-play,
#btn-stop {
    width: 28px;
    height: 28px;
    border: var(--border-medium);
    border-radius: 4px;
    background: var(--color-input-bg);
    color: var(--color-text);
    font-size: 12px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
}

#btn-play:hover:not(:disabled),
#btn-stop:hover:not(:disabled) {
    background: var(--color-hover-bg);
    border-color: rgba(255, 255, 255, 0.25);
}

#btn-play:disabled,
#btn-stop:disabled {
    opacity: 0.4;
    cursor: default;
}

#playback-speed,
#playback-follow {
    flex: 1;
    min-width: 0;
    background: var(--color-input-bg);
    color: var(--color-text);
    border: var(--border-medium);
    border-radius: 4px;
    padding: 4px 6px;
    font-size: 12px;
    font-family: var(--font-sans);
}

#playback-speed:disabled,
#playback-follow:disabled {
    opacity: 0.4;
}
```

**Step 2: Verify styling**

Confirm controls look consistent with the dark panel theme.

---

### Task 3: JS DOM refs and PlowApp playback state

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Add DOM refs**

After the existing coverage DOM refs block (around line 548, near `const btnLines`), add:

```js
const btnPlay = document.getElementById("btn-play");
const btnStop = document.getElementById("btn-stop");
const playbackSpeedSelect = document.getElementById("playback-speed");
const playbackFollowSelect = document.getElementById("playback-follow");
```

**Step 2: Add playback state to PlowApp constructor**

In the `PlowApp` constructor, after `this.coverageView = "lines";`, add:

```js
// Playback
this.playback = {
    playing: false,
    startVal: 0,
    endVal: 1000,
    durationMs: 15000,
    followVehicleId: null,
    startTime: null,
    animFrame: null,
};
```

---

### Task 4: UI locking helpers

**Files:**
- Modify: `src/where_the_plow/static/app.js` (new methods on PlowApp)

**Step 1: Add lockPlaybackUI and unlockPlaybackUI methods**

Add these to PlowApp, before the `switchMode` method:

```js
/* -- Playback UI locking ---------------------------------- */

lockPlaybackUI() {
    timeSliderEl.setAttribute("disabled", true);
    timeRangePresets.querySelectorAll("button").forEach(b => b.disabled = true);
    coverageDateInput.disabled = true;
    btnLines.disabled = true;
    btnHeatmap.disabled = true;
    playbackSpeedSelect.disabled = true;
    btnPlay.disabled = true;
    btnStop.disabled = false;
}

unlockPlaybackUI() {
    timeSliderEl.removeAttribute("disabled");
    timeRangePresets.querySelectorAll("button").forEach(b => b.disabled = false);
    coverageDateInput.disabled = false;
    btnLines.disabled = false;
    btnHeatmap.disabled = false;
    playbackSpeedSelect.disabled = false;
    btnPlay.disabled = false;
    btnStop.disabled = true;
}
```

---

### Task 5: Playback start/stop/tick methods

**Files:**
- Modify: `src/where_the_plow/static/app.js` (new methods on PlowApp)

**Step 1: Add startPlayback method**

```js
startPlayback() {
    if (!this.coverageData || this.playback.playing) return;

    const vals = timeSliderEl.noUiSlider.get().map(Number);
    this.playback.startVal = vals[0];
    this.playback.endVal = vals[1];

    // Compute duration
    const speedVal = playbackSpeedSelect.value;
    if (speedVal === "realtime") {
        const rangeMs = this.coverageUntil.getTime() - this.coverageSince.getTime();
        const fraction = (this.playback.endVal - this.playback.startVal) / 1000;
        this.playback.durationMs = rangeMs * fraction;
    } else {
        this.playback.durationMs = parseInt(speedVal) * 1000;
    }

    // Set right handle to start (empty view)
    timeSliderEl.noUiSlider.set([this.playback.startVal, this.playback.startVal]);

    this.playback.playing = true;
    this.playback.startTime = Date.now();
    this.lockPlaybackUI();
    this.playbackTick();
}
```

**Step 2: Add stopPlayback method**

```js
stopPlayback() {
    this.playback.playing = false;
    if (this.playback.animFrame) {
        cancelAnimationFrame(this.playback.animFrame);
        this.playback.animFrame = null;
    }
    this.unlockPlaybackUI();
}
```

**Step 3: Add playbackTick method**

```js
playbackTick() {
    if (!this.playback.playing) return;

    const elapsed = Date.now() - this.playback.startTime;
    const progress = Math.min(elapsed / this.playback.durationMs, 1);
    const currentVal = this.playback.startVal + progress * (this.playback.endVal - this.playback.startVal);

    timeSliderEl.noUiSlider.set([this.playback.startVal, currentVal]);

    // Follow vehicle
    if (this.playback.followVehicleId) {
        const time = this.sliderToTime(currentVal);
        const pos = this.interpolateVehiclePosition(this.playback.followVehicleId, time);
        if (pos) {
            this.map.map.easeTo({ center: pos, duration: 300 });
        }
    }

    if (progress >= 1) {
        this.playback.playing = false;
        this.playback.animFrame = null;
        this.unlockPlaybackUI();
        return;
    }

    this.playback.animFrame = requestAnimationFrame(() => this.playbackTick());
}
```

---

### Task 6: Follow-vehicle dropdown population

**Files:**
- Modify: `src/where_the_plow/static/app.js` (new method on PlowApp)

**Step 1: Add populateFollowDropdown method**

```js
populateFollowDropdown() {
    const select = playbackFollowSelect;
    const currentVal = select.value;
    select.innerHTML = '<option value="">None</option>';

    if (!this.coverageData) return;

    const filter = this.buildTypeFilter();
    const seen = new Map();
    for (const f of this.coverageData.features) {
        const vid = f.properties.vehicle_id;
        if (seen.has(vid)) continue;
        // Apply type filter check
        if (filter) {
            const vt = f.properties.vehicle_type;
            if (filter === false) continue;
            if (!this.isTypeVisible(vt)) continue;
        }
        seen.set(vid, f.properties.description);
    }

    const sorted = [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    for (const [vid, desc] of sorted) {
        const opt = document.createElement("option");
        opt.value = vid;
        opt.textContent = desc;
        select.appendChild(opt);
    }

    // Restore selection if still valid
    if ([...select.options].some(o => o.value === currentVal)) {
        select.value = currentVal;
    } else {
        select.value = "";
        this.playback.followVehicleId = null;
    }
}
```

**Step 2: Add isTypeVisible helper**

```js
isTypeVisible(vehicleType) {
    for (const row of document.querySelectorAll("#legend-vehicles .legend-row")) {
        const cb = row.querySelector(".legend-check");
        if (!cb.checked) continue;
        const types = row.dataset.types;
        if (types === "__OTHER__") {
            if (!KNOWN_TYPES.includes(vehicleType)) return true;
        } else if (types.split(",").includes(vehicleType)) {
            return true;
        }
    }
    return false;
}
```

**Step 3: Call populateFollowDropdown after coverage data loads**

In `loadCoverageForRange`, after `this.applyTypeFilters();`, add:

```js
this.populateFollowDropdown();
```

**Step 4: Call populateFollowDropdown after type filter changes**

In the legend checkbox event handler (around line 1005), after `app.applyTypeFilters();`, add:

```js
app.populateFollowDropdown();
```

---

### Task 7: Vehicle position interpolation

**Files:**
- Modify: `src/where_the_plow/static/app.js` (new method on PlowApp)

**Step 1: Add interpolateVehiclePosition method**

```js
interpolateVehiclePosition(vehicleId, time) {
    if (!this.coverageData) return null;
    const timeMs = time.getTime();
    let bestPos = null;

    for (const feature of this.coverageData.features) {
        if (feature.properties.vehicle_id !== vehicleId) continue;
        const coords = feature.geometry.coordinates;
        const timestamps = feature.properties.timestamps;

        for (let i = 0; i < timestamps.length - 1; i++) {
            const t0 = new Date(timestamps[i]).getTime();
            const t1 = new Date(timestamps[i + 1]).getTime();
            if (timeMs >= t0 && timeMs <= t1) {
                const frac = (timeMs - t0) / (t1 - t0);
                return [
                    coords[i][0] + frac * (coords[i + 1][0] - coords[i][0]),
                    coords[i][1] + frac * (coords[i + 1][1] - coords[i][1]),
                ];
            }
            // Track the closest position before timeMs
            if (t0 <= timeMs) bestPos = coords[i];
            if (t1 <= timeMs) bestPos = coords[i + 1];
        }
    }
    return bestPos; // null if vehicle has no data, or last known position before timeMs
}
```

---

### Task 8: Event wiring

**Files:**
- Modify: `src/where_the_plow/static/app.js` (event wiring section, after line ~1003)

**Step 1: Wire play, stop, and follow events**

Add after the legend checkbox handler:

```js
// Playback controls
btnPlay.addEventListener("click", () => app.startPlayback());
btnStop.addEventListener("click", () => app.stopPlayback());
playbackFollowSelect.addEventListener("change", () => {
    app.playback.followVehicleId = playbackFollowSelect.value || null;
});
```

---

### Task 9: Integration with existing flows

**Files:**
- Modify: `src/where_the_plow/static/app.js`

**Step 1: Stop playback when switching modes**

In `enterRealtime()`, at the top add:

```js
this.stopPlayback();
```

**Step 2: Stop playback when loading new coverage data**

In `loadCoverageForRange()`, before the fetch, add:

```js
this.stopPlayback();
```

**Step 3: Disable play button until data is loaded**

In `enterCoverage()`, after `coveragePanelEl.style.display = "block";`, add:

```js
btnPlay.disabled = true;
```

In `loadCoverageForRange()`, after `this.applyTypeFilters();`, add:

```js
btnPlay.disabled = false;
```

---

### Task 10: Verify and commit

**Step 1: Run tests**

```bash
uv run pytest -v
```

Expected: All 48 tests pass (no backend changes).

**Step 2: Manual browser test**

1. Open coverage mode, select 24h preset
2. Narrow the slider handles to a sub-range
3. Press Play -- right handle should animate from left handle to its original position
4. Verify stop button works mid-playback
5. Try each speed setting (15s, 30s, 1m, 5m, realtime)
6. Select a vehicle in Follow dropdown, press Play -- map should pan to follow it
7. Uncheck a type in legend -- follow dropdown should update
8. Switch to heatmap view, press Play -- should animate heatmap
9. Switch to realtime mode and back -- playback state should be clean

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: add coverage playback controls with follow-vehicle mode"
```
