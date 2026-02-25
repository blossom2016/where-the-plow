"""End-to-end test: scrape token, query AVL, parse into collector format.

Mimics what the collector will need to do after the auth change.
Outputs the vehicles/positions dicts in the same shape as parse_avl_response().

Usage:
    uv run python scripts/test_collector_flow.py
"""

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

AVL_PAGE_URL = "https://map.stjohns.ca/avl/"
AVL_QUERY_URL = "https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query"

# Same correction the real collector uses
_NST_CORRECTION = timedelta(hours=3, minutes=30)


def extract_token(html: str) -> str | None:
    match = re.search(r'token:\s*"(AAPT[^"]+)"', html)
    return match.group(1) if match else None


def fetch_token() -> str:
    resp = httpx.get(AVL_PAGE_URL, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    token = extract_token(resp.text)
    if not token:
        raise RuntimeError("Could not extract token from AVL page")
    return token


def query_avl(token: str) -> dict:
    params = {
        "f": "json",
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "where": "1=1",
        "token": token,
    }
    resp = httpx.get(AVL_QUERY_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"AVL query error: {data['error']}")
    return data


def parse_new_response(data: dict) -> tuple[list[dict], list[dict]]:
    """Parse the new AVL schema into the same shape as parse_avl_response().

    Key differences from old schema:
    - ID is gone -> use str(OBJECTID)
    - Description is gone -> use VehicleType as description
    - Speed is gone -> always None
    """
    vehicles = []
    positions = []

    for feature in data.get("features", []):
        attrs = feature.get("attributes", {})
        geom = feature.get("geometry", {})

        # Timestamp: same NST correction as before
        raw_ts = attrs.get("LocationDateTime", 0)
        naive_ts = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc)
        ts = naive_ts + _NST_CORRECTION

        vehicle_id = str(attrs.get("OBJECTID", ""))
        vehicle_type = attrs.get("VehicleType", "")

        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "description": vehicle_type,  # no separate description anymore
                "vehicle_type": vehicle_type,
            }
        )

        positions.append(
            {
                "vehicle_id": vehicle_id,
                "timestamp": ts.isoformat(),
                "longitude": geom.get("x", 0.0),
                "latitude": geom.get("y", 0.0),
                "bearing": attrs.get("Bearing", 0),
                "speed": None,  # no longer available
                "is_driving": attrs.get("isDriving", ""),
            }
        )

    return vehicles, positions


def main():
    print("Step 1: Fetch token from AVL page")
    token = fetch_token()
    print(f"  Got token: {token[:30]}...")

    print("\nStep 2: Query AVL with token")
    data = query_avl(token)
    feature_count = len(data.get("features", []))
    print(f"  Got {feature_count} features")

    print("\nStep 3: Parse into collector format")
    vehicles, positions = parse_new_response(data)

    print(f"\n  Vehicles ({len(vehicles)}):")
    for v in vehicles[:5]:
        print(f"    {json.dumps(v)}")
    if len(vehicles) > 5:
        print(f"    ... and {len(vehicles) - 5} more")

    print(f"\n  Positions ({len(positions)}):")
    for p in positions[:5]:
        print(f"    {json.dumps(p)}")
    if len(positions) > 5:
        print(f"    ... and {len(positions) - 5} more")

    # Verify the data looks reasonable
    print("\n" + "=" * 60)
    print("Validation")
    print("=" * 60)
    issues = []
    for p in positions:
        if p["longitude"] == 0.0 and p["latitude"] == 0.0:
            issues.append(f"  Vehicle {p['vehicle_id']}: zero coordinates")
        if p["speed"] is not None:
            issues.append(f"  Vehicle {p['vehicle_id']}: unexpected speed value")

    if issues:
        print("  Issues found:")
        for issue in issues:
            print(f"    {issue}")
    else:
        print("  All positions have valid coordinates")
        print("  Speed is None for all (as expected with new schema)")

    print(f"\n  Vehicle types seen: {sorted(set(v['vehicle_type'] for v in vehicles))}")
    print(f"\n  SUCCESS: End-to-end flow works with token + new schema")


if __name__ == "__main__":
    main()
