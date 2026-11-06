import math
import threading
import time

import requests


class LocationSearchError(RuntimeError):
    pass


_lock = threading.Lock()
_last_request_at = 0.0


def search_locations(query):
    global _last_request_at
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 200:
        raise ValueError("invalid_location_query")

    with _lock:
        now = time.monotonic()
        if now - _last_request_at < 1:
            raise LocationSearchError("location_search_rate_limited")
        _last_request_at = now

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query.strip(), "format": "jsonv2", "limit": 5},
            headers={"User-Agent": "Flutu.eu event calendar location search"},
            timeout=8,
        )
        response.raise_for_status()
        results = response.json()
    except requests.RequestException:
        raise LocationSearchError("location_search_unavailable") from None

    if not isinstance(results, list):
        raise LocationSearchError("location_search_unavailable")

    locations = []
    for result in results[:5]:
        try:
            latitude = float(result["lat"])
            longitude = float(result["lon"])
            label = result["display_name"]
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            continue
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or not isinstance(label, str):
            continue
        locations.append({"label": label, "latitude": latitude, "longitude": longitude})
    return locations