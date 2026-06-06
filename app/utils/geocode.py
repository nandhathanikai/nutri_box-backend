"""
Geocoding utility for Nutribox delivery system.
Converts customer location information (address text, GPS coordinates,
or map links) into lat/lng pairs stored against the user profile.

External service used: Nominatim (OpenStreetMap) — free, no API key.
Rate limit: 1 req/s enforced by this module via a simple asyncio.sleep.
"""
import re
import time
import logging
import urllib.parse
from typing import Optional, Tuple
import requests

logger = logging.getLogger(__name__)

# Respect Nominatim's usage policy: max 1 req/s, identify your app
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "NutriboxDelivery/1.0 (contact@nutribox.in)",
    "Accept-Language": "en",
}
_last_nominatim_call: float = 0.0


def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """Convert a free-text address string to (latitude, longitude).

    Uses Nominatim with a 1-second rate limit between calls.
    Returns None if geocoding fails or address is too vague.
    """
    global _last_nominatim_call
    if not address or not address.strip():
        return None

    # Enforce 1 req/s
    elapsed = time.monotonic() - _last_nominatim_call
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": address.strip(), "format": "json", "limit": 1},
            headers=NOMINATIM_HEADERS,
            timeout=8,
        )
        _last_nominatim_call = time.monotonic()
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as exc:
        logger.warning("Nominatim geocoding failed for %r: %s", address, exc)

    return None


def extract_coords_from_map_link(url: str) -> Optional[Tuple[float, float]]:
    """Parse latitude/longitude from a map URL without any API call.

    Handles the common formats customers paste:
      • Google Maps share:  https://maps.google.com/?q=lat,lng
      • Google Maps place:  https://www.google.com/maps/place/.../@lat,lng,zoom
      • Google short link:  https://goo.gl/maps/...  (followed to final URL)
      • Google app link:    https://maps.app.goo.gl/...
      • OsmAnd / OSM:       https://www.openstreetmap.org/?mlat=lat&mlon=lng
      • What3Words / Apple Maps fallback: falls through to geocode_address

    Returns None when no coordinates can be extracted.
    """
    if not url:
        return None

    url = url.strip()

    # 1. Google Maps ?q=lat,lng
    m = re.search(r"[?&]q=(-?\d+\.?\d*),(-?\d+\.?\d*)", url)
    if m:
        return float(m.group(1)), float(m.group(2))

    # 2. Google Maps /@lat,lng,zoom or /place/.../@lat,lng
    m = re.search(r"/@(-?\d+\.?\d*),(-?\d+\.?\d*)", url)
    if m:
        return float(m.group(1)), float(m.group(2))

    # 3. OpenStreetMap ?mlat=lat&mlon=lng
    m = re.search(r"mlat=(-?\d+\.?\d*).*mlon=(-?\d+\.?\d*)", url)
    if m:
        return float(m.group(1)), float(m.group(2))

    # 4. Generic lat,lng in URL path/query (fallback)
    m = re.search(r"(-?\d{1,3}\.\d{4,}),(-?\d{1,3}\.\d{4,})", url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng

    # 5. Short URLs (goo.gl, maps.app.goo.gl) — follow redirect to extract coords
    if "goo.gl" in url or "maps.app.goo.gl" in url:
        try:
            resp = requests.get(url, allow_redirects=True, timeout=8,
                                headers={"User-Agent": NOMINATIM_HEADERS["User-Agent"]})
            final_url = resp.url
            if final_url != url:
                return extract_coords_from_map_link(final_url)
        except Exception as exc:
            logger.warning("Failed to follow map short URL %r: %s", url, exc)

    return None


def geocode_user_location(
    address: Optional[str] = None,
    location_link: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Optional[Tuple[float, float]]:
    """Determine the best lat/lng from whichever location source is provided.

    Priority: explicit GPS > map link > address text.
    Returns (lat, lng) or None if no source yields coordinates.
    """
    # Already have explicit GPS coordinates
    if latitude is not None and longitude is not None:
        return latitude, longitude

    # Try extracting from map link
    if location_link:
        coords = extract_coords_from_map_link(location_link)
        if coords:
            return coords

    # Fall back to geocoding the text address
    if address:
        coords = geocode_address(address)
        if coords:
            return coords

    return None
