from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import time
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


app = FastAPI(title="Singapore Taxi & Mobility Decision View - Live LTA Data Only")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LTA_BASE_URL = "https://datamall2.mytransport.sg/ltaodataservice"

CACHE: Dict[str, Dict[str, Any]] = {}
SERVER_LOGS: List[Dict[str, Any]] = []


# Fixed MRT/LRT station reference layer for walking-distance guidance.
# LTA dynamic APIs provide live train alerts, but the dynamic API guide does not expose a simple MRT station coordinate endpoint.
# These are real station reference coordinates used only for nearest-station walking guidance; train disruption status still comes from live LTA TrainServiceAlerts.
MRT_STATIONS: List[Dict[str, Any]] = [
    {"code": "NS1/EW24", "name": "Jurong East MRT", "lat": 1.3331, "lng": 103.7423, "lines": ["NSL", "EWL"]},
    {"code": "EW23", "name": "Clementi MRT", "lat": 1.3151, "lng": 103.7652, "lines": ["EWL"]},
    {"code": "EW22", "name": "Dover MRT", "lat": 1.3114, "lng": 103.7786, "lines": ["EWL"]},
    {"code": "EW21/CC22", "name": "Buona Vista MRT", "lat": 1.3072, "lng": 103.7902, "lines": ["EWL", "CCL"]},
    {"code": "EW20", "name": "Commonwealth MRT", "lat": 1.3024, "lng": 103.7983, "lines": ["EWL"]},
    {"code": "EW19", "name": "Queenstown MRT", "lat": 1.2949, "lng": 103.8060, "lines": ["EWL"]},
    {"code": "EW18", "name": "Redhill MRT", "lat": 1.2896, "lng": 103.8168, "lines": ["EWL"]},
    {"code": "EW17", "name": "Tiong Bahru MRT", "lat": 1.2862, "lng": 103.8270, "lines": ["EWL"]},
    {"code": "EW16/NE3/TE17", "name": "Outram Park MRT", "lat": 1.2803, "lng": 103.8395, "lines": ["EWL", "NEL", "TEL"]},
    {"code": "EW15", "name": "Tanjong Pagar MRT", "lat": 1.2765, "lng": 103.8459, "lines": ["EWL"]},
    {"code": "EW14/NS26", "name": "Raffles Place MRT", "lat": 1.2840, "lng": 103.8513, "lines": ["EWL", "NSL"]},
    {"code": "NS25/EW13", "name": "City Hall MRT", "lat": 1.2931, "lng": 103.8521, "lines": ["NSL", "EWL"]},
    {"code": "EW12/DT14", "name": "Bugis MRT", "lat": 1.3006, "lng": 103.8564, "lines": ["EWL", "DTL"]},
    {"code": "EW11", "name": "Lavender MRT", "lat": 1.3074, "lng": 103.8628, "lines": ["EWL"]},
    {"code": "EW10", "name": "Kallang MRT", "lat": 1.3115, "lng": 103.8714, "lines": ["EWL"]},
    {"code": "EW9", "name": "Aljunied MRT", "lat": 1.3164, "lng": 103.8829, "lines": ["EWL"]},
    {"code": "EW8/CC9", "name": "Paya Lebar MRT", "lat": 1.3182, "lng": 103.8931, "lines": ["EWL", "CCL"]},
    {"code": "EW5", "name": "Bedok MRT", "lat": 1.3239, "lng": 103.9300, "lines": ["EWL"]},
    {"code": "EW2/DT32", "name": "Tampines MRT", "lat": 1.3533, "lng": 103.9451, "lines": ["EWL", "DTL"]},
    {"code": "CG2", "name": "Changi Airport MRT", "lat": 1.3575, "lng": 103.9878, "lines": ["EWL"]},
    {"code": "NS9/TE2", "name": "Woodlands MRT", "lat": 1.4369, "lng": 103.7865, "lines": ["NSL", "TEL"]},
    {"code": "NS13", "name": "Yishun MRT", "lat": 1.4295, "lng": 103.8350, "lines": ["NSL"]},
    {"code": "NS16", "name": "Ang Mo Kio MRT", "lat": 1.3699, "lng": 103.8496, "lines": ["NSL"]},
    {"code": "NS17/CC15", "name": "Bishan MRT", "lat": 1.3508, "lng": 103.8485, "lines": ["NSL", "CCL"]},
    {"code": "NS21/DT11", "name": "Newton MRT", "lat": 1.3126, "lng": 103.8381, "lines": ["NSL", "DTL"]},
    {"code": "NS22/TE14", "name": "Orchard MRT", "lat": 1.3040, "lng": 103.8318, "lines": ["NSL", "TEL"]},
    {"code": "NS23", "name": "Somerset MRT", "lat": 1.3002, "lng": 103.8390, "lines": ["NSL"]},
    {"code": "NS24/NE6/CC1", "name": "Dhoby Ghaut MRT", "lat": 1.2987, "lng": 103.8461, "lines": ["NSL", "NEL", "CCL"]},
    {"code": "NS27/CE2/TE20", "name": "Marina Bay MRT", "lat": 1.2764, "lng": 103.8546, "lines": ["NSL", "CCL", "TEL"]},
    {"code": "TE18", "name": "Maxwell MRT", "lat": 1.2805, "lng": 103.8439, "lines": ["TEL"]},
    {"code": "TE19", "name": "Shenton Way MRT", "lat": 1.2777, "lng": 103.8503, "lines": ["TEL"]},
    {"code": "DT17", "name": "Downtown MRT", "lat": 1.2795, "lng": 103.8528, "lines": ["DTL"]},
    {"code": "DT18", "name": "Telok Ayer MRT", "lat": 1.2822, "lng": 103.8489, "lines": ["DTL"]},
    {"code": "NE4/DT19", "name": "Chinatown MRT", "lat": 1.2845, "lng": 103.8435, "lines": ["NEL", "DTL"]},
    {"code": "NE5", "name": "Clarke Quay MRT", "lat": 1.2886, "lng": 103.8466, "lines": ["NEL"]},
    {"code": "NE1/CC29", "name": "HarbourFront MRT", "lat": 1.2653, "lng": 103.8215, "lines": ["NEL", "CCL"]},
    {"code": "NE7/DT12", "name": "Little India MRT", "lat": 1.3068, "lng": 103.8496, "lines": ["NEL", "DTL"]},
    {"code": "NE12/CC13", "name": "Serangoon MRT", "lat": 1.3505, "lng": 103.8728, "lines": ["NEL", "CCL"]},
    {"code": "NE14/CR8", "name": "Hougang MRT", "lat": 1.3713, "lng": 103.8924, "lines": ["NEL"]},
    {"code": "NE16/STC", "name": "Sengkang MRT", "lat": 1.3917, "lng": 103.8955, "lines": ["NEL", "STL"]},
    {"code": "NE17/PTC", "name": "Punggol MRT", "lat": 1.4045, "lng": 103.9020, "lines": ["NEL", "PTL"]},
    {"code": "CC4/DT15", "name": "Promenade MRT", "lat": 1.2932, "lng": 103.8604, "lines": ["CCL", "DTL"]},
    {"code": "CC5", "name": "Nicoll Highway MRT", "lat": 1.2998, "lng": 103.8636, "lines": ["CCL"]},
    {"code": "CC10/DT26", "name": "MacPherson MRT", "lat": 1.3261, "lng": 103.8892, "lines": ["CCL", "DTL"]},
    {"code": "CC14", "name": "Lorong Chuan MRT", "lat": 1.3515, "lng": 103.8648, "lines": ["CCL"]},
    {"code": "CC17/TE9", "name": "Caldecott MRT", "lat": 1.3377, "lng": 103.8396, "lines": ["CCL", "TEL"]},
    {"code": "CC19/DT9", "name": "Botanic Gardens MRT", "lat": 1.3225, "lng": 103.8154, "lines": ["CCL", "DTL"]},
    {"code": "DT1/BP6", "name": "Bukit Panjang MRT", "lat": 1.3790, "lng": 103.7615, "lines": ["DTL", "BPL"]},
    {"code": "DT5", "name": "Beauty World MRT", "lat": 1.3416, "lng": 103.7758, "lines": ["DTL"]},
    {"code": "DT6", "name": "King Albert Park MRT", "lat": 1.3357, "lng": 103.7832, "lines": ["DTL"]},
    {"code": "DT10/TE11", "name": "Stevens MRT", "lat": 1.3201, "lng": 103.8260, "lines": ["DTL", "TEL"]},
    {"code": "DT16/CE1", "name": "Bayfront MRT", "lat": 1.2819, "lng": 103.8591, "lines": ["DTL", "CCL"]},
    {"code": "DT21", "name": "Bencoolen MRT", "lat": 1.2989, "lng": 103.8503, "lines": ["DTL"]},
    {"code": "TE7", "name": "Bright Hill MRT", "lat": 1.3632, "lng": 103.8329, "lines": ["TEL"]},
    {"code": "TE8", "name": "Upper Thomson MRT", "lat": 1.3544, "lng": 103.8329, "lines": ["TEL"]},
    {"code": "TE13", "name": "Orchard Boulevard MRT", "lat": 1.3024, "lng": 103.8239, "lines": ["TEL"]},
    {"code": "TE15", "name": "Great World MRT", "lat": 1.2934, "lng": 103.8334, "lines": ["TEL"]},
    {"code": "TE16", "name": "Havelock MRT", "lat": 1.2885, "lng": 103.8336, "lines": ["TEL"]},
]


def add_server_log(event: str, details: Optional[Dict[str, Any]] = None) -> None:
    SERVER_LOGS.append({
        "time_utc": now_iso(),
        "event": event,
        "details": details or {},
    })
    del SERVER_LOGS[:-80]


def safe_account_key_status() -> Dict[str, Any]:
    raw = os.getenv("LTA_ACCOUNT_KEY", "")
    stripped = raw.strip()
    cleaned = stripped.strip('"')
    return {
        "configured": bool(cleaned),
        "raw_length": len(raw),
        "trimmed_length": len(stripped),
        "cleaned_length": len(cleaned),
        "has_leading_or_trailing_spaces": raw != stripped,
        "has_outer_quotes": stripped.startswith(("\"", "'")) and stripped.endswith(("\"", "'")),
        "value_is_hidden": True,
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_env_flag(name: str) -> bool:
    value = os.getenv(name)
    return bool(value and value.strip())


def lta_headers() -> Dict[str, str]:
    # Strip spaces and accidental quotes from Render env var values.
    # This fixes the common copy/paste issue: LTA_ACCOUNT_KEY="xxxxx".
    account_key = os.getenv("LTA_ACCOUNT_KEY", "").strip().strip('"')
    if not account_key:
        raise HTTPException(
            status_code=500,
            detail="LTA_ACCOUNT_KEY is not configured in Render environment variables.",
        )

    return {
        "AccountKey": account_key,
        "Accept": "application/json",
        "User-Agent": "SingaporeGrabMobilityView/1.0",
    }


def cache_get(key: str, ttl_seconds: int) -> Optional[Any]:
    item = CACHE.get(key)
    if not item:
        return None

    age = time.time() - item["created_at"]
    if age > ttl_seconds:
        return None

    return item["data"]


def cache_set(key: str, data: Any) -> Any:
    CACHE[key] = {
        "created_at": time.time(),
        "data": data,
    }
    return data


def extract_lta_value(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, list):
            return value
        if isinstance(payload.get("Services"), list):
            return payload["Services"]
        return []
    if isinstance(payload, list):
        return payload
    return []


def lta_get(endpoint: str, params: Optional[Dict[str, Any]] = None, ttl_seconds: int = 60) -> List[Dict[str, Any]]:
    params = params or {}
    cache_key = f"{endpoint}:{json_key(params)}"

    cached = cache_get(cache_key, ttl_seconds)
    if cached is not None:
        add_server_log("LTA cache hit", {"endpoint": endpoint, "params": params, "records": len(cached)})
        return cached

    url = f"{LTA_BASE_URL}/{endpoint}"
    add_server_log("LTA request started", {"endpoint": endpoint, "url": url, "params": params})

    try:
        response = requests.get(
            url,
            headers=lta_headers(),
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        add_server_log("LTA request exception", {"endpoint": endpoint, "error": str(exc)})
        raise HTTPException(status_code=502, detail=f"LTA request failed for {endpoint}: {exc}")

    body_preview = response.text[:500] if response.text else "<empty body>"
    response_details = {
        "endpoint": endpoint,
        "url": response.url,
        "status_code": response.status_code,
        "reason": response.reason,
        "content_type": response.headers.get("content-type"),
        "body_preview": body_preview,
    }

    if response.status_code != 200:
        add_server_log("LTA request failed", response_details)
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"LTA API error for {endpoint}",
                **response_details,
                "hint": "Check that LTA_ACCOUNT_KEY is correct, active, and pasted without quotes/spaces. If status is 401/403, the key is not being accepted by LTA DataMall or the source IP is blocked.",
            },
        )

    try:
        payload = response.json()
    except ValueError:
        add_server_log("LTA non-JSON response", response_details)
        raise HTTPException(
            status_code=502,
            detail={
                "message": f"LTA returned non-JSON response for {endpoint}",
                **response_details,
            },
        )

    data = extract_lta_value(payload)
    add_server_log("LTA request succeeded", {"endpoint": endpoint, "records": len(data), "status_code": response.status_code})
    return cache_set(cache_key, data)

def lta_get_paged(endpoint: str, ttl_seconds: int = 3600, max_pages: int = 30) -> List[Dict[str, Any]]:
    cache_key = f"{endpoint}:paged:{max_pages}"

    cached = cache_get(cache_key, ttl_seconds)
    if cached is not None:
        return cached

    all_rows: List[Dict[str, Any]] = []

    for page in range(max_pages):
        skip = page * 500
        rows = lta_get(endpoint, params={"$skip": skip}, ttl_seconds=ttl_seconds)
        all_rows.extend(rows)

        if len(rows) < 500:
            break

    return cache_set(cache_key, all_rows)


def json_key(params: Dict[str, Any]) -> str:
    if not params:
        return "none"
    return "&".join(f"{key}={params[key]}" for key in sorted(params.keys()))


def as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
        if number == 0:
            return None
        return number
    except (TypeError, ValueError):
        return None


def is_sg_coordinate(lat: Optional[float], lng: Optional[float]) -> bool:
    if lat is None or lng is None:
        return False
    return 1.15 <= lat <= 1.50 and 103.55 <= lng <= 104.10


def normalise_taxi(row: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    lat = as_float(row.get("Latitude"))
    lng = as_float(row.get("Longitude"))

    if not is_sg_coordinate(lat, lng):
        return None

    return {
        "id": f"LTA-AVAILABLE-TAXI-{index + 1}",
        "lat": lat,
        "lng": lng,
        "status": "Available for hire",
        "source": "LTA Taxi-Availability",
    }


def normalise_bus_stop(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lat = as_float(row.get("Latitude"))
    lng = as_float(row.get("Longitude"))

    if not is_sg_coordinate(lat, lng):
        return None

    return {
        "bus_stop_code": row.get("BusStopCode"),
        "road_name": row.get("RoadName"),
        "description": row.get("Description"),
        "name": f"{row.get('Description') or 'Bus Stop'} ({row.get('BusStopCode')})",
        "lat": lat,
        "lng": lng,
        "source": "LTA BusStops",
    }


def normalise_taxi_stand(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lat = as_float(row.get("Latitude"))
    lng = as_float(row.get("Longitude"))

    if not is_sg_coordinate(lat, lng):
        return None

    return {
        "taxi_code": row.get("TaxiCode"),
        "name": row.get("Name") or row.get("TaxiCode") or "Taxi Stand",
        "lat": lat,
        "lng": lng,
        "barrier_free": row.get("Bfa"),
        "ownership": row.get("Ownership"),
        "type": row.get("Type"),
        "source": "LTA TaxiStands",
    }


def normalise_traffic_incident(row: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    lat = as_float(row.get("Latitude"))
    lng = as_float(row.get("Longitude"))

    if not is_sg_coordinate(lat, lng):
        return None

    return {
        "id": f"LTA-INCIDENT-{index + 1}",
        "type": row.get("Type") or "Traffic Incident",
        "lat": lat,
        "lng": lng,
        "message": row.get("Message") or "",
        "source": "LTA TrafficIncidents",
    }


def normalise_speed_band(row: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    start_lat = as_float(row.get("StartLat"))
    start_lng = as_float(row.get("StartLon"))
    end_lat = as_float(row.get("EndLat"))
    end_lng = as_float(row.get("EndLon"))

    if not (is_sg_coordinate(start_lat, start_lng) and is_sg_coordinate(end_lat, end_lng)):
        return None

    speed_band = row.get("SpeedBand")
    min_speed = row.get("MinimumSpeed")
    max_speed = row.get("MaximumSpeed")

    try:
        speed_band_number = int(speed_band)
    except (TypeError, ValueError):
        speed_band_number = None

    return {
        "id": f"LTA-SPEEDBAND-{index + 1}",
        "link_id": row.get("LinkID"),
        "road_name": row.get("RoadName"),
        "road_category": row.get("RoadCategory"),
        "speed_band": speed_band_number,
        "minimum_speed": min_speed,
        "maximum_speed": max_speed,
        "start_lat": start_lat,
        "start_lng": start_lng,
        "end_lat": end_lat,
        "end_lng": end_lng,
        "source": "LTA v4 TrafficSpeedBands",
    }


def normalise_train_alert(row: Dict[str, Any], index: int) -> Dict[str, Any]:
    return {
        "id": f"LTA-TRAIN-ALERT-{index + 1}",
        "status": row.get("Status"),
        "line": row.get("Line"),
        "direction": row.get("Direction"),
        "stations": row.get("Stations"),
        "free_public_bus": row.get("FreePublicBus"),
        "free_mrt_shuttle": row.get("FreeMRTShuttle"),
        "mrt_shuttle_direction": row.get("MRTShuttleDirection"),
        "message": row.get("Message"),
        "source": "LTA TrainServiceAlerts",
    }


def cluster_taxis(taxis: List[Dict[str, Any]], grid_size: float = 0.015) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}

    for taxi in taxis:
        lat = taxi["lat"]
        lng = taxi["lng"]

        grid_lat = round(lat / grid_size) * grid_size
        grid_lng = round(lng / grid_size) * grid_size
        key = f"{grid_lat:.5f},{grid_lng:.5f}"

        if key not in buckets:
            buckets[key] = {
                "zone": f"Taxi supply cluster {len(buckets) + 1}",
                "lat": grid_lat,
                "lng": grid_lng,
                "available_taxis": 0,
            }

        buckets[key]["available_taxis"] += 1

    clusters = list(buckets.values())
    clusters.sort(key=lambda row: row["available_taxis"], reverse=True)

    for index, cluster in enumerate(clusters):
        cluster["name"] = f"Live taxi cluster {index + 1}"
        cluster["value"] = cluster["available_taxis"]

    return clusters

# --- Pickup Readiness helpers ---
def distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lam = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lam / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def with_distance(items: List[Dict[str, Any]], lat: float, lng: float) -> List[Dict[str, Any]]:
    enriched = []
    for item in items:
        item_lat = item.get("lat")
        item_lng = item.get("lng")
        if item_lat is None or item_lng is None:
            continue
        clone = dict(item)
        clone["distance_m"] = int(round(distance_meters(lat, lng, float(item_lat), float(item_lng))))
        enriched.append(clone)
    enriched.sort(key=lambda row: row["distance_m"])
    return enriched


def speed_segment_distance_m(segment: Dict[str, Any], lat: float, lng: float) -> int:
    # Lightweight proxy: nearest endpoint distance. Good enough for current map guidance without heavy geometry libs.
    d1 = distance_meters(lat, lng, segment["start_lat"], segment["start_lng"])
    d2 = distance_meters(lat, lng, segment["end_lat"], segment["end_lng"])
    return int(round(min(d1, d2)))




def walking_minutes(distance_m: Optional[int]) -> Optional[int]:
    if distance_m is None:
        return None
    # Approx. comfortable urban walking speed: 80 metres/minute (~4.8 km/h).
    return max(1, int(math.ceil(float(distance_m) / 80.0)))


def train_alert_matches_station(alert: Dict[str, Any], station: Dict[str, Any]) -> bool:
    try:
        status = int(alert.get("status") or 0)
    except (TypeError, ValueError):
        status = 0

    if status < 2:
        return False

    station_codes = str(station.get("code") or "")
    alert_stations = str(alert.get("stations") or "")
    alert_line = str(alert.get("line") or "")
    station_lines = station.get("lines") or []

    if alert_stations and any(code.strip() and code.strip() in alert_stations for code in station_codes.replace("/", "|").split("|")):
        return True

    return bool(alert_line and alert_line in station_lines)


def mobility_action_recommendation(taxi_600: int, taxi_1000: int, nearest_bus: Optional[Dict[str, Any]], nearest_mrt: Optional[Dict[str, Any]], nearest_stand: Optional[Dict[str, Any]], road_friction_count: int, major_train_alerts: int) -> str:
    bus_walk = nearest_bus.get("walk_minutes") if nearest_bus else None
    mrt_walk = nearest_mrt.get("walk_minutes") if nearest_mrt else None
    stand_walk = nearest_stand.get("walk_minutes") if nearest_stand else None

    if taxi_600 >= 4 and road_friction_count <= 2:
        return "Wait/book taxi here. Available taxi supply is reasonable within 600m and current nearby road friction is limited."

    if nearest_stand and stand_walk is not None and stand_walk <= 6 and taxi_1000 >= 2:
        return f"Walk about {stand_walk} min to the nearest official taxi {nearest_stand.get('type') or 'stand'} if the app match is slow."

    if nearest_bus and bus_walk is not None and bus_walk <= 5:
        return f"Walk about {bus_walk} min to the nearest bus stop as the fastest fallback if taxi matching is slow."

    if nearest_mrt and mrt_walk is not None and mrt_walk <= 12 and major_train_alerts == 0:
        return f"Walk about {mrt_walk} min to the nearest MRT station as the strongest fallback."

    if taxi_1000 >= 3:
        return "Taxi supply exists within 1km, but not very close. Wait briefly or move toward the nearest official taxi stand."

    return "No strong taxi supply is visible within 1km. Use the nearest bus stop or MRT fallback if timing matters."


def readiness_level(taxis_300: int, taxis_600: int, taxis_1000: int, incidents_1500: int, slow_segments_1500: int) -> str:
    if taxis_300 >= 3 and incidents_1500 == 0:
        return "High"
    if taxis_600 >= 4 or taxis_1000 >= 10:
        return "Medium"
    if taxis_1000 >= 3:
        return "Low-Medium"
    return "Low"


def readiness_recommendation(level: str, taxis_300: int, taxis_600: int, nearest_stand: Optional[Dict[str, Any]], nearest_cluster: Optional[Dict[str, Any]]) -> str:
    if level == "High":
        return "Book here. Available taxi supply is close enough around your current location."
    if taxis_600 >= 4:
        return "Book here or walk a short distance toward the nearest supply cluster if matching is slow."
    if nearest_stand and nearest_stand.get("distance_m", 999999) <= 700:
        return f"Walk to the nearest official taxi {nearest_stand.get('type') or 'stand'} around {nearest_stand['distance_m']}m away."
    if nearest_cluster:
        return f"Supply is thin at your exact location. Move toward {nearest_cluster.get('name', 'the nearest supply cluster')} around {nearest_cluster['distance_m']}m away."
    return "Taxi supply looks thin nearby. Consider MRT/bus fallback or wait before booking."

def local_fare_pressure_proxy(
    taxis_300: int,
    taxis_600: int,
    taxis_1000: int,
    incidents_1500: int,
    slow_segments_1500: int,
    nearest_stand: Optional[Dict[str, Any]] = None,
    major_train_alerts: int = 0,
) -> Dict[str, Any]:
    """
    Local pressure score built only from public LTA signals.

    This is not Grab pricing. It estimates whether a booking attempt from
    the user's area may feel harder, slower, or less reliable.
    """
    score = 0
    signals: List[str] = []

    if taxis_300 == 0:
        score += 28
        signals.append("No available taxis within 300m of the blue dot.")
    elif taxis_300 <= 2:
        score += 14
        signals.append(f"Only {taxis_300} available taxi/taxis within 300m.")
    else:
        signals.append(f"{taxis_300} available taxis within 300m supports local pickup.")

    if taxis_600 < 3:
        score += 20
        signals.append(f"Limited nearby supply: {taxis_600} available taxi/taxis within 600m.")
    elif taxis_600 < 6:
        score += 8
        signals.append(f"Moderate nearby supply: {taxis_600} available taxis within 600m.")
    else:
        signals.append(f"Healthy nearby supply: {taxis_600} available taxis within 600m.")

    if taxis_1000 < 5:
        score += 16
        signals.append(f"Thin 1km supply: {taxis_1000} available taxi/taxis within 1km.")
    else:
        signals.append(f"{taxis_1000} available taxis within 1km gives fallback supply.")

    if incidents_1500 > 0:
        score += min(18, incidents_1500 * 6)
        signals.append(f"{incidents_1500} road incident record(s) within 1.5km may slow pickup movement.")

    if slow_segments_1500 > 0:
        score += min(18, int(slow_segments_1500 * 1.5))
        signals.append(f"{slow_segments_1500} slow road segment(s) within 1.5km may increase pickup friction.")

    if nearest_stand:
        stand_distance = int(nearest_stand.get("distance_m", 999999))
        if stand_distance <= 500:
            score -= 8
            signals.append(f"Nearest official taxi stand/stop is about {stand_distance}m away, giving a safer pickup fallback.")
        elif stand_distance > 900:
            score += 8
            signals.append(f"Nearest official taxi stand/stop is about {stand_distance}m away, so the fallback is not very close.")

    if major_train_alerts > 0:
        score += min(10, major_train_alerts * 5)
        signals.append(f"{major_train_alerts} major train alert(s) may push more users toward taxis.")

    score = max(0, min(100, score))

    if score >= 70:
        level = "High"
        meaning = "Booking from here may be harder, slower, or less reliable. Consider walking to a better pickup point or public transport fallback."
    elif score >= 40:
        level = "Elevated"
        meaning = "Booking is possible, but nearby supply or road conditions are not ideal. Keep bus/MRT or taxi stand fallback in view."
    else:
        level = "Low"
        meaning = "Public signals do not show strong local pressure. Booking or waiting here is reasonable."

    return {
        "score": score,
        "level": level,
        "meaning": meaning,
        "not_actual_grab_pricing": True,
        "signals": signals + [
            "This is not actual Grab price, fare, demand, booking volume, cancellation risk, or surge multiplier."
        ],
    }



@app.get("/")
def serve_index():
    return FileResponse("index.html", media_type="text/html")


@app.get("/app.js")
def serve_js():
    return FileResponse("app.js", media_type="application/javascript")


@app.get("/health")
def health():
    return {
        "status": "running",
        "message": "Singapore Taxi & Mobility Decision View API is live",
        "live_only": True,
        "mock_data_used": False,
        "mapbox_token_configured": get_env_flag("MAPBOX_TOKEN"),
        "lta_account_key_configured": get_env_flag("LTA_ACCOUNT_KEY"),
        "lta_account_key_diagnostics": safe_account_key_status(),
        "server_time_utc": now_iso(),
    }


@app.get("/config")
def config():
    return JSONResponse({
        "mapbox_token": os.getenv("MAPBOX_TOKEN"),
    })


@app.get("/debug/logs")
def debug_logs():
    return {
        "status": "ok",
        "server_time_utc": now_iso(),
        "logs": SERVER_LOGS[-80:],
    }


@app.get("/debug/lta")
def debug_lta(endpoint: str = Query(default="Taxi-Availability")):
    allowed = {
        "Taxi-Availability",
        "BusStops",
        "TaxiStands",
        "TrafficIncidents",
        "v4/TrafficSpeedBands",
        "TrainServiceAlerts",
    }

    if endpoint not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Endpoint not allowed for debug. Use one of: {', '.join(sorted(allowed))}",
        )

    url = f"{LTA_BASE_URL}/{endpoint}"
    started = time.time()

    try:
        response = requests.get(url, headers=lta_headers(), timeout=20)
        elapsed_ms = int((time.time() - started) * 1000)
        body_preview = response.text[:800] if response.text else "<empty body>"

        diagnostic = {
            "endpoint": endpoint,
            "url": response.url,
            "status_code": response.status_code,
            "reason": response.reason,
            "elapsed_ms": elapsed_ms,
            "content_type": response.headers.get("content-type"),
            "body_preview": body_preview,
            "account_key_diagnostics": safe_account_key_status(),
            "server_time_utc": now_iso(),
        }
        add_server_log("Manual LTA debug", diagnostic)
        return diagnostic
    except requests.RequestException as exc:
        diagnostic = {
            "endpoint": endpoint,
            "url": url,
            "error": str(exc),
            "account_key_diagnostics": safe_account_key_status(),
            "server_time_utc": now_iso(),
        }
        add_server_log("Manual LTA debug exception", diagnostic)
        return diagnostic


@app.get("/debug/lta-all")
def debug_lta_all():
    endpoints = [
        "Taxi-Availability",
        "BusStops",
        "TaxiStands",
        "TrafficIncidents",
        "v4/TrafficSpeedBands",
        "TrainServiceAlerts",
    ]
    results = []

    for endpoint in endpoints:
        url = f"{LTA_BASE_URL}/{endpoint}"
        started = time.time()
        try:
            response = requests.get(url, headers=lta_headers(), timeout=20)
            elapsed_ms = int((time.time() - started) * 1000)
            results.append({
                "endpoint": endpoint,
                "status_code": response.status_code,
                "reason": response.reason,
                "elapsed_ms": elapsed_ms,
                "content_type": response.headers.get("content-type"),
                "body_preview": response.text[:300] if response.text else "<empty body>",
            })
        except requests.RequestException as exc:
            results.append({
                "endpoint": endpoint,
                "error": str(exc),
            })

    diagnostic = {
        "account_key_diagnostics": safe_account_key_status(),
        "server_time_utc": now_iso(),
        "results": results,
    }
    add_server_log("Manual LTA all-endpoints debug", diagnostic)
    return diagnostic


@app.get("/taxis")
def taxis():
    rows = lta_get("Taxi-Availability", ttl_seconds=60)
    result = []

    for index, row in enumerate(rows):
        taxi = normalise_taxi(row, index)
        if taxi:
            result.append(taxi)

    return {
        "source": "LTA Taxi-Availability",
        "live_only": True,
        "mock_data_used": False,
        "count": len(result),
        "updated_at_utc": now_iso(),
        "data": result,
    }


@app.get("/zones")
def zones(limit: int = Query(default=100, ge=1, le=300)):
    taxi_response = taxis()
    taxi_rows = taxi_response["data"]
    clusters = cluster_taxis(taxi_rows)[:limit]

    return {
        "source": "Derived only from live LTA Taxi-Availability",
        "live_only": True,
        "mock_data_used": False,
        "count": len(clusters),
        "taxi_count": len(taxi_rows),
        "updated_at_utc": now_iso(),
        "data": clusters,
    }


@app.get("/supply-summary")
def supply_summary():
    zone_response = zones(limit=20)
    taxi_count = zone_response["taxi_count"]
    clusters = zone_response["data"]

    return {
        "source": "Derived only from live LTA Taxi-Availability",
        "live_only": True,
        "mock_data_used": False,
        "available_taxis": taxi_count,
        "visible_clusters": len(clusters),
        "top_clusters": clusters[:5],
        "updated_at_utc": now_iso(),
    }


@app.get("/pickup-readiness")
def pickup_readiness(
    lat: float = Query(..., ge=1.15, le=1.50),
    lng: float = Query(..., ge=103.55, le=104.10),
):
    """
    User-location-first readiness view.

    Important: LTA Taxi-Availability only exposes available-for-hire taxis.
    It does not expose hired, busy, booked, Grab-only, driver destination, or taxi heading data.
    This endpoint therefore makes a transparent decision recommendation from available supply,
    official taxi stands, road incidents, and slow road segments only.
    """
    taxi_response = taxis()
    taxi_rows = taxi_response["data"]
    clusters = zones(limit=80)["data"]
    stands = taxi_stands()["data"]
    incidents = traffic_incidents()["data"]
    speed_response = traffic_speed_bands(limit=1500)

    taxis_by_distance = with_distance(taxi_rows, lat, lng)
    stands_by_distance = with_distance(stands, lat, lng)
    incidents_by_distance = with_distance(incidents, lat, lng)
    clusters_by_distance = with_distance(clusters, lat, lng)

    slow_segments = []
    for segment in speed_response["data"]:
        if segment.get("speed_band") is not None and segment["speed_band"] <= 3:
            clone = dict(segment)
            clone["distance_m"] = speed_segment_distance_m(clone, lat, lng)
            slow_segments.append(clone)
    slow_segments.sort(key=lambda row: row["distance_m"])

    taxis_300 = [row for row in taxis_by_distance if row["distance_m"] <= 300]
    taxis_600 = [row for row in taxis_by_distance if row["distance_m"] <= 600]
    taxis_1000 = [row for row in taxis_by_distance if row["distance_m"] <= 1000]
    stands_1000 = [row for row in stands_by_distance if row["distance_m"] <= 1000]
    incidents_1500 = [row for row in incidents_by_distance if row["distance_m"] <= 1500]
    slow_segments_1500 = [row for row in slow_segments if row["distance_m"] <= 1500]

    nearest_stand = stands_by_distance[0] if stands_by_distance else None
    nearest_cluster = clusters_by_distance[0] if clusters_by_distance else None
    level = readiness_level(len(taxis_300), len(taxis_600), len(taxis_1000), len(incidents_1500), len(slow_segments_1500))
    recommendation = readiness_recommendation(level, len(taxis_300), len(taxis_600), nearest_stand, nearest_cluster)
    fare_pressure_proxy = local_fare_pressure_proxy(
        taxis_300=len(taxis_300),
        taxis_600=len(taxis_600),
        taxis_1000=len(taxis_1000),
        incidents_1500=len(incidents_1500),
        slow_segments_1500=len(slow_segments_1500),
        nearest_stand=nearest_stand,
    )

    return {
        "source": "Derived only from live LTA Taxi-Availability, TaxiStands, TrafficIncidents and v4 TrafficSpeedBands",
        "live_only": True,
        "mock_data_used": False,
        "user_location": {"lat": lat, "lng": lng},
        "readiness_level": level,
        "recommendation": recommendation,
        "fare_pressure_proxy": fare_pressure_proxy,
        "available_taxi_counts": {
            "within_300m": len(taxis_300),
            "within_600m": len(taxis_600),
            "within_1000m": len(taxis_1000),
            "total_available_from_lta": taxi_response["count"],
        },
        "unavailable_taxis": {
            "available_from_lta": False,
            "message": "LTA Taxi-Availability excludes hired/busy taxis. Hired, busy, booked and platform-specific Grab vehicle statuses are not available in this public feed."
        },
        "nearest_taxis": taxis_by_distance[:60],
        "nearby_taxi_stands": stands_1000[:40],
        "nearest_taxi_stand": nearest_stand,
        "nearest_supply_cluster": nearest_cluster,
        "nearby_traffic_incidents": incidents_1500[:20],
        "nearby_slow_speed_segments": slow_segments_1500[:80],
        "counts": {
            "nearby_taxi_stands_1000m": len(stands_1000),
            "traffic_incidents_1500m": len(incidents_1500),
            "slow_segments_1500m": len(slow_segments_1500),
        },
        "updated_at_utc": now_iso(),
    }


@app.get("/bus-stops")
def bus_stops(limit: int = Query(default=700, ge=1, le=6000)):
    rows = lta_get_paged("BusStops", ttl_seconds=86400, max_pages=20)
    result = []

    for row in rows:
        bus_stop = normalise_bus_stop(row)
        if bus_stop:
            result.append(bus_stop)

    return {
        "source": "LTA BusStops",
        "live_only": True,
        "mock_data_used": False,
        "count": min(len(result), limit),
        "total_available_from_lta": len(result),
        "updated_at_utc": now_iso(),
        "data": result[:limit],
    }


@app.get("/taxi-stands")
def taxi_stands():
    rows = lta_get("TaxiStands", ttl_seconds=86400)
    result = []

    for row in rows:
        stand = normalise_taxi_stand(row)
        if stand:
            result.append(stand)

    return {
        "source": "LTA TaxiStands",
        "live_only": True,
        "mock_data_used": False,
        "count": len(result),
        "updated_at_utc": now_iso(),
        "data": result,
    }


@app.get("/traffic-incidents")
def traffic_incidents():
    rows = lta_get("TrafficIncidents", ttl_seconds=120)
    result = []

    for index, row in enumerate(rows):
        incident = normalise_traffic_incident(row, index)
        if incident:
            result.append(incident)

    return {
        "source": "LTA TrafficIncidents",
        "live_only": True,
        "mock_data_used": False,
        "count": len(result),
        "updated_at_utc": now_iso(),
        "data": result,
    }


@app.get("/traffic-speed-bands")
def traffic_speed_bands(limit: int = Query(default=1200, ge=1, le=5000)):
    rows = lta_get_paged("v4/TrafficSpeedBands", ttl_seconds=300, max_pages=10)
    result = []

    for index, row in enumerate(rows):
        speed_band = normalise_speed_band(row, index)
        if speed_band:
            result.append(speed_band)

    return {
        "source": "LTA v4 TrafficSpeedBands",
        "live_only": True,
        "mock_data_used": False,
        "count": min(len(result), limit),
        "total_available_from_lta": len(result),
        "updated_at_utc": now_iso(),
        "data": result[:limit],
    }


@app.get("/train-alerts")
def train_alerts():
    rows = lta_get("TrainServiceAlerts", ttl_seconds=120)
    result = [normalise_train_alert(row, index) for index, row in enumerate(rows)]

    return {
        "source": "LTA TrainServiceAlerts",
        "live_only": True,
        "mock_data_used": False,
        "count": len(result),
        "updated_at_utc": now_iso(),
        "data": result,
    }



@app.get("/mrt-stations")
def mrt_stations():
    return {
        "source": "Static MRT/LRT station reference layer for walking guidance; train alert status uses live LTA TrainServiceAlerts",
        "live_only": True,
        "mock_data_used": False,
        "count": len(MRT_STATIONS),
        "updated_at_utc": now_iso(),
        "data": MRT_STATIONS,
    }


@app.get("/mobility-decision")
def mobility_decision(
    lat: float = Query(..., ge=1.15, le=1.50),
    lng: float = Query(..., ge=103.55, le=104.10),
    radius_m: int = Query(default=1000, ge=300, le=2000),
):
    taxi_response = taxis()
    bus_response = bus_stops(limit=6000)
    stand_response = taxi_stands()
    incident_response = traffic_incidents()
    speed_response = traffic_speed_bands(limit=1500)
    train_response = train_alerts()

    taxis_by_distance = with_distance(taxi_response["data"], lat, lng)
    buses_by_distance = with_distance(bus_response["data"], lat, lng)
    stands_by_distance = with_distance(stand_response["data"], lat, lng)
    mrt_by_distance = with_distance(MRT_STATIONS, lat, lng)
    incidents_by_distance = with_distance(incident_response["data"], lat, lng)

    slow_segments = []
    for segment in speed_response["data"]:
        if segment.get("speed_band") is not None and segment["speed_band"] <= 3:
            clone = dict(segment)
            clone["distance_m"] = speed_segment_distance_m(clone, lat, lng)
            slow_segments.append(clone)
    slow_segments.sort(key=lambda row: row["distance_m"])

    taxis_300 = [row for row in taxis_by_distance if row["distance_m"] <= 300]
    taxis_600 = [row for row in taxis_by_distance if row["distance_m"] <= 600]
    taxis_radius = [row for row in taxis_by_distance if row["distance_m"] <= radius_m]
    buses_radius = [row for row in buses_by_distance if row["distance_m"] <= radius_m]
    stands_radius = [row for row in stands_by_distance if row["distance_m"] <= radius_m]
    mrt_radius = [row for row in mrt_by_distance if row["distance_m"] <= radius_m]
    incidents_1500 = [row for row in incidents_by_distance if row["distance_m"] <= 1500]
    slow_segments_1500 = [row for row in slow_segments if row["distance_m"] <= 1500]

    train_alerts_data = train_response["data"]
    major_train_alerts = []
    for alert in train_alerts_data:
        try:
            status = int(alert.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        if status >= 2:
            major_train_alerts.append(alert)

    for row in buses_radius:
        row["walk_minutes"] = walking_minutes(row["distance_m"])
    for row in stands_radius:
        row["walk_minutes"] = walking_minutes(row["distance_m"])
    for row in mrt_radius:
        row["walk_minutes"] = walking_minutes(row["distance_m"])
        row["has_relevant_train_alert"] = any(train_alert_matches_station(alert, row) for alert in train_alerts_data)

    nearest_bus = buses_by_distance[0] if buses_by_distance else None
    nearest_stand = stands_by_distance[0] if stands_by_distance else None
    nearest_mrt = mrt_by_distance[0] if mrt_by_distance else None

    if nearest_bus:
        nearest_bus = dict(nearest_bus)
        nearest_bus["walk_minutes"] = walking_minutes(nearest_bus["distance_m"])
    if nearest_stand:
        nearest_stand = dict(nearest_stand)
        nearest_stand["walk_minutes"] = walking_minutes(nearest_stand["distance_m"])
    if nearest_mrt:
        nearest_mrt = dict(nearest_mrt)
        nearest_mrt["walk_minutes"] = walking_minutes(nearest_mrt["distance_m"])
        nearest_mrt["has_relevant_train_alert"] = any(train_alert_matches_station(alert, nearest_mrt) for alert in train_alerts_data)

    road_friction_count = len(incidents_1500) + len(slow_segments_1500)
    recommendation = mobility_action_recommendation(
        taxi_600=len(taxis_600),
        taxi_1000=len(taxis_radius),
        nearest_bus=nearest_bus,
        nearest_mrt=nearest_mrt,
        nearest_stand=nearest_stand,
        road_friction_count=road_friction_count,
        major_train_alerts=len(major_train_alerts),
    )
    fare_pressure_proxy = local_fare_pressure_proxy(
        taxis_300=len(taxis_300),
        taxis_600=len(taxis_600),
        taxis_1000=len(taxis_radius),
        incidents_1500=len(incidents_1500),
        slow_segments_1500=len(slow_segments_1500),
        nearest_stand=nearest_stand,
        major_train_alerts=len(major_train_alerts),
    )

    return {
        "source": "Live LTA Taxi-Availability, BusStops, TaxiStands, TrafficIncidents, v4 TrafficSpeedBands and TrainServiceAlerts; MRT station coordinates are fixed reference points for walking guidance",
        "live_only": True,
        "mock_data_used": False,
        "user_location": {"lat": lat, "lng": lng},
        "radius_m": radius_m,
        "walking_speed_assumption": "80 metres/minute, approximate walking time only",
        "recommendation": recommendation,
        "fare_pressure_proxy": fare_pressure_proxy,
        "decision_options": {
            "wait_for_taxi": {
                "available_taxis_300m": len(taxis_300),
                "available_taxis_600m": len(taxis_600),
                "available_taxis_1000m": len(taxis_radius),
                "status": "Strong" if len(taxis_600) >= 4 else "Moderate" if len(taxis_radius) >= 3 else "Weak",
            },
            "walk_to_bus_stop": {
                "nearest": nearest_bus,
                "count_within_1km": len(buses_radius),
                "status": "Available" if nearest_bus and nearest_bus.get("distance_m", 999999) <= radius_m else "Not within 1km",
            },
            "walk_to_mrt": {
                "nearest": nearest_mrt,
                "count_within_1km": len(mrt_radius),
                "major_train_alerts": len(major_train_alerts),
                "status": "Available" if nearest_mrt and nearest_mrt.get("distance_m", 999999) <= radius_m else "Not within 1km",
            },
        },
        "nearby": {
            "available_taxis": taxis_radius[:80],
            "bus_stops": buses_radius[:80],
            "taxi_stands": stands_radius[:60],
            "mrt_stations": mrt_radius[:20],
            "traffic_incidents": incidents_1500[:30],
            "slow_speed_segments": slow_segments_1500[:120],
            "train_alerts": train_alerts_data,
        },
        "counts": {
            "available_taxis_300m": len(taxis_300),
            "available_taxis_600m": len(taxis_600),
            "available_taxis_1000m": len(taxis_radius),
            "bus_stops_1000m": len(buses_radius),
            "taxi_stands_1000m": len(stands_radius),
            "mrt_stations_1000m": len(mrt_radius),
            "traffic_incidents_1500m": len(incidents_1500),
            "slow_segments_1500m": len(slow_segments_1500),
            "train_alerts": len(train_alerts_data),
            "major_train_alerts": len(major_train_alerts),
        },
        "updated_at_utc": now_iso(),
    }


@app.get("/mobility")
def mobility():
    taxi_response = taxis()
    bus_response = bus_stops(limit=700)
    stands_response = taxi_stands()

    return {
        "source": "Live LTA Taxi-Availability, BusStops and TaxiStands",
        "live_only": True,
        "mock_data_used": False,
        "updated_at_utc": now_iso(),
        "taxis": taxi_response["data"],
        "bus_stops": bus_response["data"],
        "taxi_stands": stands_response["data"],
        "mrt_stations": MRT_STATIONS,
        "counts": {
            "available_taxis": taxi_response["count"],
            "bus_stops_displayed": bus_response["count"],
            "taxi_stands": stands_response["count"],
            "mrt_stations": len(MRT_STATIONS),
        },
    }


@app.get("/fare-pressure")
def fare_pressure():
    """
    Transparent fare-pressure proxy derived only from live LTA inputs.

    This does NOT return actual Grab fares, surge multipliers, or pricing.
    It combines live public signals that can make a ride feel harder, slower,
    or potentially more expensive: available taxi supply, road incidents,
    slow road segments, and train alerts.
    """
    taxi_response = taxis()
    zone_response = zones(limit=8)
    incidents_response = traffic_incidents()
    speed_response = traffic_speed_bands(limit=1500)
    train_response = train_alerts()

    available_taxis = int(taxi_response["count"])
    traffic_incidents_count = int(incidents_response["count"])
    train_alerts_count = int(train_response["count"])
    slow_segments = [
        row for row in speed_response["data"]
        if row.get("speed_band") is not None and row["speed_band"] <= 3
    ]

    # Deterministic scoring model. No random values and no private Grab pricing.
    # Lower live taxi availability contributes to pressure; road/train friction adds pressure.
    supply_scarcity_points = max(0, min(40, int((2200 - available_taxis) / 55)))
    incident_points = min(25, traffic_incidents_count * 4)
    slow_segment_points = min(25, int(len(slow_segments) / 10))
    train_alert_points = min(10, train_alerts_count * 5)

    score = max(0, min(100, supply_scarcity_points + incident_points + slow_segment_points + train_alert_points))

    if score >= 70:
        pressure_level = "High"
    elif score >= 40:
        pressure_level = "Medium"
    else:
        pressure_level = "Low"

    explanations = [
        f"{available_taxis} available taxis currently reported by LTA Taxi-Availability.",
        f"{traffic_incidents_count} current road incident records from LTA TrafficIncidents.",
        f"{len(slow_segments)} slow road segments from LTA v4 TrafficSpeedBands where SpeedBand <= 3.",
        f"{train_alerts_count} current train alert records from LTA TrainServiceAlerts.",
        "No Grab fare, demand, booking, cancellation, or surge multiplier data is used."
    ]

    return {
        "source": "Derived only from live LTA Taxi-Availability, TrafficIncidents, v4 TrafficSpeedBands and TrainServiceAlerts",
        "live_only": True,
        "mock_data_used": False,
        "not_actual_grab_pricing": True,
        "fare_pressure_proxy_score": score,
        "pressure_level": pressure_level,
        "available_taxis": available_taxis,
        "top_supply_clusters": zone_response["data"],
        "traffic_incidents": incidents_response["data"],
        "slow_speed_segments": slow_segments,
        "train_alerts": train_response["data"],
        "counts": {
            "traffic_incidents": traffic_incidents_count,
            "slow_speed_segments": len(slow_segments),
            "train_alerts": train_alerts_count,
        },
        "explanations": explanations,
        "updated_at_utc": now_iso(),
    }


@app.get("/road-friction")
def road_friction():
    incidents_response = traffic_incidents()
    speed_response = traffic_speed_bands(limit=1500)

    slow_segments = [
        row for row in speed_response["data"]
        if row.get("speed_band") is not None and row["speed_band"] <= 3
    ]

    return {
        "source": "Live LTA TrafficIncidents and v4 TrafficSpeedBands",
        "live_only": True,
        "mock_data_used": False,
        "updated_at_utc": now_iso(),
        "traffic_incidents": incidents_response["data"],
        "slow_speed_segments": slow_segments,
        "counts": {
            "traffic_incidents": incidents_response["count"],
            "slow_speed_segments": len(slow_segments),
        },
    }


@app.get("/disruptions")
def disruptions():
    incidents_response = traffic_incidents()
    train_response = train_alerts()

    return {
        "source": "Live LTA TrafficIncidents and TrainServiceAlerts",
        "live_only": True,
        "mock_data_used": False,
        "updated_at_utc": now_iso(),
        "traffic_incidents": incidents_response["data"],
        "train_alerts": train_response["data"],
        "counts": {
            "traffic_incidents": incidents_response["count"],
            "train_alerts": train_response["count"],
        },
    }


# Compatibility endpoint retained so old browser tabs do not break.
# It no longer returns forecasted or simulated data.
@app.get("/forecast")
def forecast():
    summary = supply_summary()
    return {
        "source": "No live public Grab demand forecast is available. This endpoint returns current live taxi supply only.",
        "live_only": True,
        "mock_data_used": False,
        "updated_at_utc": now_iso(),
        "available_taxis": summary["available_taxis"],
        "top_clusters": summary["top_clusters"],
    }


# Compatibility endpoint retained so old browser tabs do not break.
# It no longer returns simulated pickup risk.
@app.get("/pickup-risk")
def pickup_risk():
    stands = taxi_stands()
    return {
        "source": "No live public pickup-risk API is available. This endpoint returns official live LTA TaxiStands only.",
        "live_only": True,
        "mock_data_used": False,
        "updated_at_utc": now_iso(),
        "data": stands["data"],
    }
