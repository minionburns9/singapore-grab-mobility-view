from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import time
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


app = FastAPI(title="Singapore Grab Mobility View - Live LTA Data Only")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LTA_BASE_URL = "https://datamall2.mytransport.sg/ltaodataservice"

CACHE: Dict[str, Dict[str, Any]] = {}
SERVER_LOGS: List[Dict[str, Any]] = []


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
        "message": "Singapore Grab Mobility View API is live",
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

    return {
        "source": "Derived only from live LTA Taxi-Availability, TaxiStands, TrafficIncidents and v4 TrafficSpeedBands",
        "live_only": True,
        "mock_data_used": False,
        "user_location": {"lat": lat, "lng": lng},
        "readiness_level": level,
        "recommendation": recommendation,
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
        "counts": {
            "available_taxis": taxi_response["count"],
            "bus_stops_displayed": bus_response["count"],
            "taxi_stands": stands_response["count"],
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
