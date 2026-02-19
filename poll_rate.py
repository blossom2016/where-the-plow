# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx",
# ]
# ///
"""
Polls the St. John's AVL endpoint every 3 seconds to measure how frequently
vehicle positions actually change. Runs for ~2 minutes by default.

Usage:
    uv run poll_rate.py [--duration 120] [--interval 3]

Output:
    - Live per-tick summary showing how many vehicles changed position
    - Final report with update frequency stats per vehicle
"""

import argparse
import time
import json
import sys
from datetime import datetime, timezone

import httpx

URL = (
    "https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query"
    "?f=json"
    "&outFields=ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving"
    "&outSR=4326"
    "&returnGeometry=true"
    "&where=isDriving%20%3D%20%27maybe%27"
)

HEADERS = {
    "Referer": "https://map.stjohns.ca/avl/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def fetch_vehicles(client: httpx.Client) -> dict[str, dict]:
    """Fetch current active vehicles, keyed by ID."""
    resp = client.get(URL, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    vehicles = {}
    for f in data.get("features", []):
        attrs = f["attributes"]
        geom = f.get("geometry", {})
        vehicles[attrs["ID"]] = {
            "description": attrs.get("Description", ""),
            "vehicle_type": attrs.get("VehicleType", ""),
            "location_dt": attrs.get("LocationDateTime"),
            "bearing": attrs.get("Bearing"),
            "speed": attrs.get("Speed"),
            "x": geom.get("x"),
            "y": geom.get("y"),
        }
    return vehicles


def diff_snapshots(prev: dict[str, dict], curr: dict[str, dict]) -> dict:
    """Compare two snapshots, return which vehicles changed and how."""
    changed = {}
    for vid, data in curr.items():
        if vid not in prev:
            changed[vid] = {"type": "appeared", "description": data["description"]}
        else:
            old = prev[vid]
            diffs = {}
            if old["x"] != data["x"] or old["y"] != data["y"]:
                diffs["position"] = {
                    "from": (old["x"], old["y"]),
                    "to": (data["x"], data["y"]),
                }
            if old["location_dt"] != data["location_dt"]:
                diffs["location_dt"] = {
                    "from": old["location_dt"],
                    "to": data["location_dt"],
                }
            if old["bearing"] != data["bearing"]:
                diffs["bearing"] = {"from": old["bearing"], "to": data["bearing"]}
            if old["speed"] != data["speed"]:
                diffs["speed"] = {"from": old["speed"], "to": data["speed"]}
            if diffs:
                changed[vid] = {
                    "type": "updated",
                    "description": data["description"],
                    **diffs,
                }

    for vid in prev:
        if vid not in curr:
            changed[vid] = {
                "type": "disappeared",
                "description": prev[vid]["description"],
            }

    return changed


def main():
    parser = argparse.ArgumentParser(description="Poll AVL endpoint to measure update rate")
    parser.add_argument("--duration", type=int, default=120, help="How long to poll in seconds (default: 120)")
    parser.add_argument("--interval", type=int, default=3, help="Poll interval in seconds (default: 3)")
    args = parser.parse_args()

    duration = args.duration
    interval = args.interval
    total_ticks = duration // interval

    print(f"Polling every {interval}s for {duration}s ({total_ticks} ticks)")
    print(f"Filtering: isDriving = 'maybe' (active vehicles only)")
    print("-" * 70)

    client = httpx.Client()

    # Per-vehicle tracking: how many ticks each vehicle had a change
    vehicle_update_counts: dict[str, int] = {}
    vehicle_descriptions: dict[str, str] = {}
    vehicle_types: dict[str, str] = {}
    tick_change_counts: list[int] = []
    ticks_with_changes = 0

    try:
        prev = fetch_vehicles(client)
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{now}] Initial fetch: {len(prev)} active vehicles")

        for tick in range(1, total_ticks + 1):
            time.sleep(interval)
            try:
                curr = fetch_vehicles(client)
            except Exception as e:
                now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(f"[{now}] Tick {tick}: ERROR - {e}")
                tick_change_counts.append(0)
                continue

            changes = diff_snapshots(prev, curr)
            tick_change_counts.append(len(changes))
            now = datetime.now(timezone.utc).strftime("%H:%M:%S")

            if changes:
                ticks_with_changes += 1
                updated = [v for v in changes.values() if v["type"] == "updated"]
                appeared = [v for v in changes.values() if v["type"] == "appeared"]
                disappeared = [v for v in changes.values() if v["type"] == "disappeared"]

                parts = []
                if updated:
                    parts.append(f"{len(updated)} updated")
                if appeared:
                    parts.append(f"{len(appeared)} appeared")
                if disappeared:
                    parts.append(f"{len(disappeared)} disappeared")

                print(f"[{now}] Tick {tick:3d}: {len(curr)} vehicles | {', '.join(parts)}")

                # Track per-vehicle updates
                for vid, change in changes.items():
                    if change["type"] == "updated":
                        vehicle_update_counts[vid] = vehicle_update_counts.get(vid, 0) + 1
                        vehicle_descriptions[vid] = change["description"]
                    # Track descriptions/types from current data
                    if vid in curr:
                        vehicle_descriptions[vid] = curr[vid]["description"]
                        vehicle_types[vid] = curr[vid]["vehicle_type"]
            else:
                print(f"[{now}] Tick {tick:3d}: {len(curr)} vehicles | no changes")

            prev = curr

    except KeyboardInterrupt:
        print("\n\nInterrupted early.")
    finally:
        client.close()

    # Final report
    actual_ticks = len(tick_change_counts)
    if actual_ticks == 0:
        print("\nNo data collected.")
        return

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Total ticks polled:        {actual_ticks}")
    print(f"Ticks with changes:        {ticks_with_changes} ({ticks_with_changes/actual_ticks*100:.1f}%)")
    print(f"Ticks with no changes:     {actual_ticks - ticks_with_changes}")
    print(f"Avg changes per tick:      {sum(tick_change_counts)/actual_ticks:.1f}")
    print(f"Max changes in one tick:   {max(tick_change_counts)}")
    print()

    if vehicle_update_counts:
        print(f"Vehicles that changed at least once: {len(vehicle_update_counts)}")
        print()
        print("Per-vehicle update frequency (sorted by most updates):")
        print(f"  {'Vehicle':<30} {'Type':<16} {'Updates':>8} {'Rate':>10}")
        print(f"  {'-'*30} {'-'*16} {'-'*8} {'-'*10}")
        for vid, count in sorted(vehicle_update_counts.items(), key=lambda x: -x[1]):
            desc = vehicle_descriptions.get(vid, vid)
            vtype = vehicle_types.get(vid, "?")
            rate = f"~{actual_ticks * interval / count:.0f}s"
            print(f"  {desc:<30} {vtype:<16} {count:>8} {rate:>10}")

    print()
    print("Interpretation:")
    if ticks_with_changes / actual_ticks > 0.8:
        print(f"  Data updates very frequently. Polling every {interval}s is reasonable.")
    elif ticks_with_changes / actual_ticks > 0.4:
        effective = actual_ticks * interval // ticks_with_changes if ticks_with_changes else 0
        print(f"  Data updates moderately. Consider polling every ~{effective}s instead.")
    else:
        effective = actual_ticks * interval // ticks_with_changes if ticks_with_changes else 0
        print(f"  Data updates infrequently. Polling every ~{effective}s would be sufficient.")


if __name__ == "__main__":
    main()
