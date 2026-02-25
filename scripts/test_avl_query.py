"""Test AVL query with and without token, and compare field schemas.

Shows exactly what changed: which fields are gone, which are new,
and what the response looks like with the new schema.

Usage:
    uv run python scripts/test_avl_query.py
"""

import json
import re
import httpx

AVL_PAGE_URL = "https://map.stjohns.ca/avl/"
AVL_QUERY_URL = "https://map.stjohns.ca/mapsrv/rest/services/AVL/MapServer/0/query"


def extract_token(html: str) -> str | None:
    match = re.search(r'token:\s*"(AAPT[^"]+)"', html)
    return match.group(1) if match else None


# Fields the collector currently requests
OLD_FIELDS = "ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving"


def query_avl(token: str | None = None, out_fields: str = "*") -> dict:
    params = {
        "f": "json",
        "outFields": out_fields,
        "outSR": "4326",
        "returnGeometry": "true",
        "where": "1=1",
    }
    if token:
        params["token"] = token

    resp = httpx.get(AVL_QUERY_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def main():
    # Step 1: Get token
    print("=" * 60)
    print("Step 1: Extract token from AVL page")
    print("=" * 60)
    page = httpx.get(AVL_PAGE_URL, follow_redirects=True, timeout=15)
    token = extract_token(page.text)
    if not token:
        print("FAIL: Could not extract token")
        return
    print(f"  Token: {token[:30]}...")

    # Step 2: Try without token
    print()
    print("=" * 60)
    print("Step 2: Query WITHOUT token (should fail)")
    print("=" * 60)
    result = query_avl(token=None)
    if "error" in result:
        print(f"  Expected error: {result['error']}")
    else:
        print(f"  Unexpected success! {len(result.get('features', []))} features")

    # Step 3: Try with token + old fields
    print()
    print("=" * 60)
    print("Step 3: Query with token + OLD field names")
    print("=" * 60)
    print(f"  Requesting: {OLD_FIELDS}")
    result = query_avl(token=token, out_fields=OLD_FIELDS)
    if "error" in result:
        print(f"  Error: {result['error']}")
    else:
        features = result.get("features", [])
        print(f"  Got {len(features)} features")
        if features:
            print(
                f"  Sample attributes: {json.dumps(features[0]['attributes'], indent=4)}"
            )

    # Step 4: Try with token + wildcard fields
    print()
    print("=" * 60)
    print("Step 4: Query with token + ALL fields (outFields=*)")
    print("=" * 60)
    result = query_avl(token=token, out_fields="*")
    if "error" in result:
        print(f"  Error: {result['error']}")
        return

    features = result.get("features", [])
    print(f"  Got {len(features)} features")

    # Show schema
    fields = result.get("fields", [])
    print(f"\n  Available fields ({len(fields)}):")
    for f in fields:
        print(f"    {f['name']:25s} {f['type']:30s} (alias: {f.get('alias', '')})")

    if features:
        print(f"\n  Sample feature:")
        print(f"    attributes: {json.dumps(features[0]['attributes'], indent=6)}")
        print(f"    geometry:   {json.dumps(features[0]['geometry'], indent=6)}")

    # Step 5: Compare old vs new schema
    print()
    print("=" * 60)
    print("Step 5: Schema comparison")
    print("=" * 60)
    old_set = set(OLD_FIELDS.split(","))
    new_set = {f["name"] for f in fields}

    missing = old_set - new_set
    added = new_set - old_set
    kept = old_set & new_set

    print(f"  Fields REMOVED (in old, not in new): {missing or 'none'}")
    print(f"  Fields ADDED   (in new, not in old): {added or 'none'}")
    print(f"  Fields KEPT    (in both):            {kept or 'none'}")

    # Step 6: Show what the collector will need to adapt to
    print()
    print("=" * 60)
    print("Step 6: Impact on collector")
    print("=" * 60)
    print("  The collector currently uses these fields from each feature:")
    print("    vehicle_id    <- attrs.ID          (REMOVED)")
    print("    description   <- attrs.Description (REMOVED)")
    print("    vehicle_type  <- attrs.VehicleType  (still exists)")
    print("    timestamp     <- attrs.LocationDateTime (still exists)")
    print("    bearing       <- attrs.Bearing      (still exists)")
    print("    speed         <- attrs.Speed         (REMOVED)")
    print("    is_driving    <- attrs.isDriving     (still exists)")
    print()
    print("  New fields available: OBJECTID, SymbolURL, Width, Height")
    print()
    print("  Suggested mapping:")
    print("    vehicle_id    <- OBJECTID (integer, was string)")
    print("    description   <- VehicleType (no separate description anymore)")
    print("    vehicle_type  <- VehicleType")
    print("    speed         <- not available (always None)")


if __name__ == "__main__":
    main()
