# Coverage playback controls

## Overview

Add media-style playback controls to the coverage view, allowing users to animate coverage data over time (like Environment Canada's weather radar). Includes a follow-vehicle mode that tracks a selected vehicle during playback.

## State

`PlowApp` gains a `playback` object:

```js
{
    playing: false,
    startVal: 0,      // left handle position at play start
    endVal: 1000,      // right handle position at play start
    speed: 15,         // seconds to complete playback
    followVehicleId: null,
    startTime: null,   // Date.now() when playback started
    animFrame: null,   // requestAnimationFrame ID
}
```

## HTML controls

Below `#time-slider`, a new `#playback-controls` div:

- **Play** button -- starts playback, locks UI
- **Stop** button -- exits playback, unlocks UI
- **Speed** `<select>`: "15s" (default), "30s", "1m", "5m", "Realtime"
- **Follow** `<select>`: "None" (default), then vehicle descriptions from coverage data

## UI locking

When playing:
- Slider handles are disabled (`timeSliderEl.setAttribute("disabled", true)`)
- Time presets, date picker, view toggle (lines/heatmap) are disabled
- Speed dropdown is locked (can't change mid-playback)
- Follow dropdown remains interactive (can start/stop following mid-playback)

Stop unlocks everything.

## Animation loop

1. On play: record `startVal` (left handle), `endVal` (right handle).
2. Set right handle to `startVal` (empty view -- start of playback).
3. Compute `durationMs` from speed: 15000, 30000, 60000, 300000, or for "Realtime" the actual time span (`coverageUntil - coverageSince`) * `(endVal - startVal) / 1000`.
4. `requestAnimationFrame` loop:
   - `elapsed = Date.now() - startTime`
   - `progress = Math.min(elapsed / durationMs, 1)`
   - `currentVal = startVal + progress * (endVal - startVal)`
   - `timeSliderEl.noUiSlider.set([startVal, currentVal])` -- triggers existing `renderCoverage` via the slider's `update` handler
   - If following a vehicle, interpolate position and `easeTo`
   - If `progress >= 1`: stop animation, set right handle to `endVal`, set `playing = false`, re-enable controls

No auto-loop -- playback stops at the end, user must press play again.

## Follow vehicle

### Dropdown population

Populated from `this.coverageData.features` when:
- Coverage data loads
- Type filter checkboxes change

Extracts unique `(vehicle_id, description)` pairs, filtered by current type filter. Sorted alphabetically by description.

### Camera behavior

On each animation frame when following:
1. Convert `currentVal` to a time via `sliderToTime`.
2. Search the followed vehicle's trail segments for the one containing that time.
3. Interpolate position between nearest coordinates using timestamp proportion.
4. `map.easeTo({ center: [lng, lat], duration: 300 })` -- 300ms ease smooths frame-to-frame jumps.
5. If vehicle has no position at current time (in a gap), skip the pan.

Selecting "None" stops following; map stays wherever it is.

## Implementation plan

### Step 1: HTML + CSS
- Add `#playback-controls` div below `#time-slider` in index.html
- Style play/stop buttons as icon buttons, dropdowns match existing theme
- Add a hint: "Animate coverage data over time"

### Step 2: PlowApp playback state
- Add `playback` object to constructor
- Add `startPlayback()` method: lock UI, record positions, start rAF loop
- Add `stopPlayback()` method: cancel rAF, unlock UI, restore handle
- Add `playbackTick()` method: the per-frame logic

### Step 3: Follow vehicle
- Add `populateFollowDropdown()` method, called after coverage load and filter change
- Add `interpolateVehiclePosition(vehicleId, time)` method
- Integrate into `playbackTick()`: if following, interpolate + easeTo

### Step 4: Event wiring
- Play button calls `startPlayback()`
- Stop button calls `stopPlayback()`
- Speed dropdown reads value into `playback.speed` before play
- Follow dropdown sets `playback.followVehicleId`

### Step 5: UI locking
- `lockPlaybackUI()` / `unlockPlaybackUI()` helpers
- Disable: slider, presets, date picker, view toggle, speed dropdown
- Keep interactive: follow dropdown, stop button
