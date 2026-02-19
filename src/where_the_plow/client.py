from datetime import datetime, timezone

import httpx

from where_the_plow.config import settings


def parse_avl_response(data: dict) -> tuple[list[dict], list[dict]]:
    vehicles = []
    positions = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        geom = feature.get("geometry", {})

        vehicle_id = str(attrs["ID"])
        ts = datetime.fromtimestamp(attrs["LocationDateTime"] / 1000, tz=timezone.utc)

        vehicles.append(
            {
                "vehicle_id": vehicle_id,
                "description": attrs.get("Description", ""),
                "vehicle_type": attrs.get("VehicleType", ""),
            }
        )

        speed_raw = attrs.get("Speed", "0.0")
        try:
            speed = float(speed_raw)
        except (ValueError, TypeError):
            speed = 0.0

        positions.append(
            {
                "vehicle_id": vehicle_id,
                "timestamp": ts,
                "longitude": geom.get("x", 0.0),
                "latitude": geom.get("y", 0.0),
                "bearing": attrs.get("Bearing", 0),
                "speed": speed,
                "is_driving": attrs.get("isDriving", ""),
            }
        )

    return vehicles, positions


async def fetch_vehicles(client: httpx.AsyncClient) -> dict:
    params = {
        "f": "json",
        "outFields": "ID,Description,VehicleType,LocationDateTime,Bearing,Speed,isDriving",
        "outSR": "4326",
        "returnGeometry": "true",
        "where": "1=1",
    }
    headers = {
        "Referer": settings.avl_referer,
    }
    resp = await client.get(
        settings.avl_api_url, params=params, headers=headers, timeout=10
    )
    resp.raise_for_status()
    return resp.json()
