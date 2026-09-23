#!/usr/bin/env python3
"""Look angles for a few open satellites, printed as one JSON object.

Orbital elements come from CelesTrak. Elevation and azimuth are computed
here from the observer's latitude and longitude, so the network request
never includes where you are.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))

from sgp4.api import Satrec, jday  # noqa: E402

SATELLITES = (
    (25544, "ISS", "ISS"),
    (20580, "Hubble", "HST"),
    (48274, "Tiangong", "TG"),
)
def tle_url(norad: int) -> str:
    return f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle"
USER_AGENT = "omarchy-satellite/1.0 (https://github.com/ashiskharel/omarchy-satellite)"
CACHE = Path.home() / ".cache" / "omarchy-satellite"
TLE_CACHE = CACHE / "tle.txt"
LOCATION_CACHE = CACHE / "location.json"
WEATHER = Path.home() / ".local" / "state" / "omarchy" / "settings" / "weather.json"
TLE_MAX_AGE = timedelta(hours=3)
HORIZON_DEG = 10.0
PASS_HOURS = 18
PASS_STEP = timedelta(seconds=30)
# One CelesTrak TLE is a few hundred bytes. The location lookup is one small JSON object.
TLE_BODY_LIMIT = 4 * 1024
LOCATION_BODY_LIMIT = 16 * 1024


def gmst(jd_full: float) -> float:
    tut1 = (jd_full - 2451545.0) / 36525.0
    seconds = (
        -6.2e-6 * tut1**3
        + 0.093104 * tut1**2
        + (876600.0 * 3600 + 8640184.812866) * tut1
        + 67310.54841
    )
    seconds %= 86400.0
    # One second of sidereal time is 1/240 of a degree.
    theta = (seconds * (math.pi / 180.0)) / 240.0
    if theta < 0:
        theta += 2 * math.pi
    return theta


def teme_to_ecef(r, jd_full: float):
    theta = gmst(jd_full)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    x, y, z = r
    return (x * cos_t + y * sin_t, -x * sin_t + y * cos_t, z)


def geodetic_to_ecef(lat_deg, lon_deg, alt_km):
    a = 6378.137
    e2 = 6.69437999014e-3
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    slat = math.sin(lat)
    clat = math.cos(lat)
    n = a / math.sqrt(1 - e2 * slat * slat)
    return (
        (n + alt_km) * clat * math.cos(lon),
        (n + alt_km) * clat * math.sin(lon),
        (n * (1 - e2) + alt_km) * slat,
    )


def look_angles(r_ecef, obs_ecef, lat_deg, lon_deg):
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    dx = r_ecef[0] - obs_ecef[0]
    dy = r_ecef[1] - obs_ecef[1]
    dz = r_ecef[2] - obs_ecef[2]
    east = -math.sin(lon) * dx + math.cos(lon) * dy
    north = (
        -math.sin(lat) * math.cos(lon) * dx
        - math.sin(lat) * math.sin(lon) * dy
        + math.cos(lat) * dz
    )
    up = (
        math.cos(lat) * math.cos(lon) * dx
        + math.cos(lat) * math.sin(lon) * dy
        + math.sin(lat) * dz
    )
    rng = math.sqrt(east * east + north * north + up * up)
    if rng == 0:
        return 0.0, 0.0, 0.0
    el = math.degrees(math.atan2(up, math.hypot(east, north)))
    az = math.degrees(math.atan2(east, north)) % 360.0
    return el, az, rng


def compass(az: float) -> str:
    names = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    return names[int((az + 11.25) // 22.5) % 16]


def propagate(sat, moment: datetime):
    moment = moment.astimezone(timezone.utc)
    jd, fr = jday(
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second + moment.microsecond / 1e6,
    )
    err, r, _v = sat.sgp4(jd, fr)
    if err != 0:
        return None
    return teme_to_ecef(r, jd + fr)


def angles_at(sat, obs_ecef, lat, lon, moment):
    r = propagate(sat, moment)
    if r is None:
        return None
    el, az, rng = look_angles(r, obs_ecef, lat, lon)
    return el, az, rng


def next_pass(sat, obs_ecef, lat, lon, start: datetime):
    """First pass that reaches HORIZON_DEG, skipping one already underway."""
    end = start + timedelta(hours=PASS_HOURS)
    moment = start
    in_pass = False
    skipped_current = False
    best_el = -90.0
    best_time = start
    started = start
    step = PASS_STEP
    while moment <= end:
        sample = angles_at(sat, obs_ecef, lat, lon, moment)
        el = sample[0] if sample else -90.0
        above = el >= HORIZON_DEG
        if above and not in_pass:
            if not skipped_current and moment == start:
                skipped_current = True
                in_pass = True
            else:
                in_pass = True
                started = moment
                best_el = el
                best_time = moment
        elif above and in_pass and not skipped_current:
            if el > best_el:
                best_el = el
                best_time = moment
        elif not above and in_pass:
            if skipped_current:
                skipped_current = False
                in_pass = False
            else:
                minutes = max(0, int((started - start).total_seconds() // 60))
                return {
                    "in_min": minutes,
                    "at": started.astimezone().strftime("%H:%M"),
                    "max_el": round(best_el),
                }
        moment += step
    return None


class ResponseTooLarge(RuntimeError):
    pass


def read_bounded(response, limit: int) -> bytes:
    """Read at most limit bytes. A longer body is rejected before it is decoded."""
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            size = int(declared)
        except (TypeError, ValueError) as exc:
            raise ResponseTooLarge("Content-Length was not a number") from exc
        if size < 0 or size > limit:
            raise ResponseTooLarge(f"response declared {size} bytes; limit is {limit}")
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ResponseTooLarge(f"response exceeded {limit} bytes")
    return body


def fetch_text(url: str, timeout: int = 12, limit: int = TLE_BODY_LIMIT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = read_bounded(response, limit)
    return body.decode("utf-8", "replace")


def load_tles(refresh: bool):
    CACHE.mkdir(parents=True, exist_ok=True)
    fresh = False
    if (
        not refresh
        and TLE_CACHE.exists()
        and datetime.now(timezone.utc) - datetime.fromtimestamp(TLE_CACHE.stat().st_mtime, timezone.utc) < TLE_MAX_AGE
    ):
        text = TLE_CACHE.read_text()
    else:
        chunks = []
        try:
            for norad, _full, _short in SATELLITES:
                chunks.append(fetch_text(tle_url(norad)))
            text = "\n".join(chunks)
            if "1 " not in text:
                raise RuntimeError(text.strip()[:180] or "CelesTrak returned no orbits")
            TLE_CACHE.write_text(text)
            fresh = True
        except Exception:
            if not TLE_CACHE.exists() or "1 " not in TLE_CACHE.read_text():
                raise
            text = TLE_CACHE.read_text()
    fetched = datetime.fromtimestamp(TLE_CACHE.stat().st_mtime, timezone.utc)
    return parse_tles(text), fetched, fresh


def parse_tles(text: str):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    found = {}
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            name = f"NORAD {lines[i][2:7].strip()}"
            found[int(lines[i][2:7])] = (name, lines[i], lines[i + 1])
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            norad = int(lines[i + 1][2:7])
            found[norad] = (lines[i], lines[i + 1], lines[i + 2])
            i += 3
        else:
            i += 1
    return found


def weather_location():
    if not WEATHER.exists():
        return None
    try:
        data = json.loads(WEATHER.read_text())
    except json.JSONDecodeError:
        return None
    lat = data.get("latitude")
    lon = data.get("longitude")
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if math.isnan(lat_f) or math.isnan(lon_f):
        return None
    return {"name": str(data.get("name") or "Weather location"), "latitude": lat_f, "longitude": lon_f, "source": "weather"}


def network_location():
    if LOCATION_CACHE.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(LOCATION_CACHE.stat().st_mtime, timezone.utc)
        if age < timedelta(days=7):
            try:
                cached = json.loads(LOCATION_CACHE.read_text())
                cached["source"] = "network"
                return cached
            except json.JSONDecodeError:
                pass
    raw = json.loads(fetch_text("https://ipwho.is/", timeout=8, limit=LOCATION_BODY_LIMIT))
    if not raw.get("success", True):
        raise RuntimeError(raw.get("message") or "location lookup failed")
    place = {"name": raw.get("city") or "This network", "latitude": float(raw["latitude"]), "longitude": float(raw["longitude"]), "source": "network"}
    CACHE.mkdir(parents=True, exist_ok=True)
    LOCATION_CACHE.write_text(json.dumps(place))
    return place


def observer():
    return weather_location() or network_location()


def build(refresh: bool):
    now = datetime.now(timezone.utc)
    place = observer()
    tles, fetched, fresh = load_tles(refresh)
    obs = geodetic_to_ecef(place["latitude"], place["longitude"], 0.0)
    satellites = []
    for norad, full, short in SATELLITES:
        record = tles.get(norad)
        if record is None:
            satellites.append({"norad": norad, "name": full, "short": short, "error": "No orbit data"})
            continue
        _name, line1, line2 = record
        sat = Satrec.twoline2rv(line1, line2)
        sample = angles_at(sat, obs, place["latitude"], place["longitude"], now)
        if sample is None:
            satellites.append({"norad": norad, "name": full, "short": short, "error": "Orbit did not solve"})
            continue
        el, az, rng = sample
        later = angles_at(sat, obs, place["latitude"], place["longitude"], now + timedelta(seconds=60))
        rising = later is not None and later[0] > el + 0.15
        upcoming = next_pass(sat, obs, place["latitude"], place["longitude"], now)
        satellites.append(
            {
                "norad": norad,
                "name": full,
                "short": short,
                "elevation": round(el, 1),
                "azimuth": round(az, 1),
                "compass": compass(az),
                "rising": rising,
                "range_km": round(rng),
                "overhead": el >= HORIZON_DEG,
                "next": upcoming,
            }
        )

    overhead = [sat for sat in satellites if sat.get("overhead")]
    if overhead:
        featured = max(overhead, key=lambda sat: sat["elevation"])
        label = f"{featured['short']} {round(featured['elevation'])}°"
    else:
        coming = [sat for sat in satellites if sat.get("next") and sat["next"]["in_min"] <= 12 * 60]
        if coming:
            featured = min(coming, key=lambda sat: sat["next"]["in_min"])
            minutes = featured["next"]["in_min"]
            label = f"{featured['short']} {minutes}m" if minutes < 90 else f"{featured['short']} {round(minutes / 60)}h"
        else:
            featured = satellites[0] if satellites else None
            label = "—"

    age_min = max(0, int((now - fetched).total_seconds() // 60))
    return {
        "label": label,
        "featured": featured["norad"] if featured else None,
        "location": place,
        "tle_age_min": age_min,
        "tle_fresh": fresh,
        "updated": now.astimezone().strftime("%H:%M"),
        "satellites": satellites,
    }


def main():
    refresh = "--refresh" in sys.argv
    try:
        payload = build(refresh)
    except Exception as exc:
        payload = {"label": "—", "error": str(exc), "satellites": [], "featured": None}
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
