from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import random
import math
from datetime import datetime

app = FastAPI(title="Singapore Grab Mobility View")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "message": "Singapore Grab Mobility View API is live"
    }


@app.get("/config")
def config():
    return JSONResponse({
        "mapbox_token": os.getenv("MAPBOX_TOKEN")
    })


SINGAPORE_ZONES = [
    {"name": "CBD / Raffles Place", "lat": 1.2838, "lng": 103.8514, "demand": 92, "surge": "High", "pickup_risk": "Medium"},
    {"name": "Marina Bay", "lat": 1.2830, "lng": 103.8600, "demand": 88, "surge": "High", "pickup_risk": "High"},
    {"name": "Orchard", "lat": 1.3048, "lng": 103.8318, "demand": 84, "surge": "High", "pickup_risk": "Medium"},
    {"name": "Changi Airport", "lat": 1.3644, "lng": 103.9915, "demand": 78, "surge": "Medium", "pickup_risk": "Low"},
    {"name": "Jurong East", "lat": 1.3329, "lng": 103.7436, "demand": 70, "surge": "Medium", "pickup_risk": "Medium"},
    {"name": "Tampines", "lat": 1.3496, "lng": 103.9568, "demand": 66, "surge": "Medium", "pickup_risk": "Medium"},
    {"name": "Woodlands", "lat": 1.4360, "lng": 103.7860, "demand": 58, "surge": "Low", "pickup_risk": "Medium"},
    {"name": "Punggol", "lat": 1.4052, "lng": 103.9023, "demand": 61, "surge": "Medium", "pickup_risk": "Medium"},
    {"name": "Sentosa", "lat": 1.2494, "lng": 103.8303, "demand": 55, "surge": "Medium", "pickup_risk": "High"},
    {"name": "Bugis", "lat": 1.3006, "lng": 103.8560, "demand": 72, "surge": "Medium", "pickup_risk": "Medium"},
    {"name": "Novena", "lat": 1.3204, "lng": 103.8439, "demand": 52, "surge": "Low", "pickup_risk": "Low"},
    {"name": "One-North", "lat": 1.2998, "lng": 103.7871, "demand": 64, "surge": "Medium", "pickup_risk": "Medium"},
]


MRT_STATIONS = [
    {"name": "Raffles Place MRT", "lat": 1.2839, "lng": 103.8514},
    {"name": "Orchard MRT", "lat": 1.3040, "lng": 103.8320},
    {"name": "City Hall MRT", "lat": 1.2932, "lng": 103.8520},
    {"name": "Bugis MRT", "lat": 1.3006, "lng": 103.8560},
    {"name": "Jurong East MRT", "lat": 1.3331, "lng": 103.7423},
    {"name": "Tampines MRT", "lat": 1.3533, "lng": 103.9451},
    {"name": "Woodlands MRT", "lat": 1.4369, "lng": 103.7865},
    {"name": "Punggol MRT", "lat": 1.4045, "lng": 103.9020},
    {"name": "Changi Airport MRT", "lat": 1.3575, "lng": 103.9878},
    {"name": "HarbourFront MRT", "lat": 1.2653, "lng": 103.8215},
]


@app.get("/zones")
def zones():
    hour = datetime.now().hour
    modifier = 1.0

    if 7 <= hour <= 9:
        modifier = 1.2
    elif 17 <= hour <= 20:
        modifier = 1.25
    elif 22 <= hour or hour <= 1:
        modifier = 1.15

    result = []

    for zone in SINGAPORE_ZONES:
        demand = min(100, int(zone["demand"] * modifier + random.randint(-8, 8)))

        result.append({
            **zone,
            "demand": demand,
            "supply": max(10, 100 - demand + random.randint(-8, 15)),
            "eta_minutes": max(2, int(12 - demand / 12 + random.randint(-2, 3))),
            "surge_score": min(100, int(demand * random.uniform(0.85, 1.15))),
        })

    return result


@app.get("/taxis")
def taxis():
    taxis_data = []

    for i in range(120):
        zone = random.choice(SINGAPORE_ZONES)
        lat = zone["lat"] + random.uniform(-0.018, 0.018)
        lng = zone["lng"] + random.uniform(-0.018, 0.018)

        taxis_data.append({
            "id": f"TX-{1000 + i}",
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "status": random.choice(["Available", "On Trip", "En Route", "Idle"]),
            "vehicle_type": random.choice(["JustGrab", "GrabCar", "Taxi", "Premium"]),
            "eta_minutes": random.randint(2, 12)
        })

    return taxis_data


@app.get("/mobility")
def mobility():
    bus_stops = []

    for i in range(80):
        zone = random.choice(SINGAPORE_ZONES)
        bus_stops.append({
            "name": f"Bus Stop {30000 + i}",
            "lat": round(zone["lat"] + random.uniform(-0.025, 0.025), 6),
            "lng": round(zone["lng"] + random.uniform(-0.025, 0.025), 6),
            "type": "Bus Stop"
        })

    return {
        "mrt_stations": MRT_STATIONS,
        "bus_stops": bus_stops
    }


@app.get("/forecast")
def forecast():
    windows = [
        "07:30", "07:45", "08:00", "08:15", "08:30", "08:45",
        "09:00", "12:00", "17:30", "18:00", "18:30", "19:00",
        "21:30", "22:00", "22:30", "23:00"
    ]

    data = []

    for window in windows:
        peak = 40

        if window.startswith("08") or window.startswith("18"):
            peak = 85
        elif window.startswith("22") or window.startswith("23"):
            peak = 70
        elif window.startswith("12"):
            peak = 55

        data.append({
            "time": window,
            "demand_index": min(100, max(10, peak + random.randint(-12, 12))),
            "expected_wait": max(2, int(14 - peak / 10 + random.randint(-2, 4))),
            "surge_risk": "High" if peak > 75 else "Medium" if peak > 55 else "Low"
        })

    return data


@app.get("/pickup-risk")
def pickup_risk():
    result = []

    for zone in SINGAPORE_ZONES:
        risk_score = {
            "Low": random.randint(20, 40),
            "Medium": random.randint(45, 70),
            "High": random.randint(72, 95)
        }[zone["pickup_risk"]]

        result.append({
            "zone": zone["name"],
            "lat": zone["lat"],
            "lng": zone["lng"],
            "risk": zone["pickup_risk"],
            "risk_score": risk_score,
            "reason": random.choice([
                "High pickup confusion",
                "Mall / taxi-stand congestion",
                "Road access constraints",
                "Event or crowd pressure",
                "Driver stopping restrictions"
            ])
        })

    return result