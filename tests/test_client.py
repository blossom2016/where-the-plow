from where_the_plow.client import parse_avl_response


SAMPLE_RESPONSE = {
    "features": [
        {
            "attributes": {
                "ID": "281474984421544",
                "Description": "2222 SA PLOW TRUCK",
                "VehicleType": "SA PLOW TRUCK",
                "LocationDateTime": 1771491812000,
                "Bearing": 135,
                "Speed": "13.4",
                "isDriving": "maybe",
            },
            "geometry": {"x": -52.731, "y": 47.564},
        },
        {
            "attributes": {
                "ID": "281474992393189",
                "Description": "2037 LOADER",
                "VehicleType": "LOADER",
                "LocationDateTime": 1771492204000,
                "Bearing": 0,
                "Speed": "0.0",
                "isDriving": "no",
            },
            "geometry": {"x": -52.726, "y": 47.595},
        },
    ]
}


def test_parse_avl_response():
    vehicles, positions = parse_avl_response(SAMPLE_RESPONSE)
    assert len(vehicles) == 2
    assert len(positions) == 2

    assert vehicles[0]["vehicle_id"] == "281474984421544"
    assert vehicles[0]["description"] == "2222 SA PLOW TRUCK"
    assert vehicles[0]["vehicle_type"] == "SA PLOW TRUCK"

    assert positions[0]["vehicle_id"] == "281474984421544"
    assert positions[0]["longitude"] == -52.731
    assert positions[0]["latitude"] == 47.564
    assert positions[0]["bearing"] == 135
    assert positions[0]["speed"] == 13.4
    assert positions[0]["is_driving"] == "maybe"
    assert positions[0]["timestamp"].year == 2026


def test_parse_empty_response():
    vehicles, positions = parse_avl_response({"features": []})
    assert vehicles == []
    assert positions == []


def test_parse_speed_conversion():
    """Speed comes as string from API, should be parsed to float."""
    resp = {
        "features": [
            {
                "attributes": {
                    "ID": "1",
                    "Description": "test",
                    "VehicleType": "LOADER",
                    "LocationDateTime": 1771491812000,
                    "Bearing": 0,
                    "Speed": "25.7",
                    "isDriving": "maybe",
                },
                "geometry": {"x": -52.0, "y": 47.0},
            }
        ]
    }
    _, positions = parse_avl_response(resp)
    assert positions[0]["speed"] == 25.7
