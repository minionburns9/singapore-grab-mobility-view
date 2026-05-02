let map;
let currentView = null;

const VIEW_META = {
  heatmap: {
    title: "Demand Heatmap",
    subtitle: "Where ride demand is expected to be high right now.",
    mode: "Heatmap"
  },
  forecast: {
    title: "Taxi Demand Forecast",
    subtitle: "Demand and wait-time risk by time window.",
    mode: "Forecast"
  },
  nearby: {
    title: "Nearby Mobility",
    subtitle: "Taxis, MRT stations and bus stops across Singapore.",
    mode: "Nearby"
  },
  surge: {
    title: "Fare Shock / Surge Risk",
    subtitle: "Areas where pricing may be elevated due to demand pressure.",
    mode: "Surge Risk"
  },
  pickup: {
    title: "Pickup Reliability",
    subtitle: "Hard-to-pickup zones and pickup friction hotspots.",
    mode: "Pickup"
  },
  disruption: {
    title: "Event & Weather Disruption",
    subtitle: "Likely pressure zones from airport, rain, events and late-night movement.",
    mode: "Disruption"
  }
};

async function openView(viewName) {
  currentView = viewName;

  document.getElementById("home").style.display = "none";
  document.getElementById("mapView").style.display = "block";

  document.getElementById("viewTitle").innerText = VIEW_META[viewName].title;
  document.getElementById("viewSubtitle").innerText = VIEW_META[viewName].subtitle;
  document.getElementById("topMode").innerText = VIEW_META[viewName].mode;

  if (!map) {
    await initMap();
  }

  clearMapLayers();
  await renderView(viewName);

  setTimeout(function () {
    map.resize();
  }, 300);
}

function goHome() {
  document.getElementById("mapView").style.display = "none";
  document.getElementById("home").style.display = "block";
}

async function initMap() {
  const configResponse = await fetch("/config");
  const config = await configResponse.json();

  mapboxgl.accessToken = config.mapbox_token;

  map = new mapboxgl.Map({
    container: "map",
    style: "mapbox://styles/mapbox/dark-v11",
    center: [103.82, 1.35],
    zoom: 10.4
  });

  map.addControl(new mapboxgl.NavigationControl(), "bottom-right");

  await new Promise(resolve => {
    map.on("load", resolve);
  });
}

function clearMapLayers() {
  const layers = [
    "heatmap-layer",
    "zone-circles",
    "zone-labels",
    "taxi-points",
    "mrt-points",
    "bus-points",
    "risk-circles",
    "risk-labels"
  ];

  const sources = [
    "zones-source",
    "taxis-source",
    "mobility-source",
    "risk-source"
  ];

  layers.forEach(layer => {
    if (map.getLayer(layer)) {
      map.removeLayer(layer);
    }
  });

  sources.forEach(source => {
    if (map.getSource(source)) {
      map.removeSource(source);
    }
  });
}

async function renderView(viewName) {
  if (viewName === "heatmap") {
    await renderHeatmap();
  }

  if (viewName === "forecast") {
    await renderForecast();
  }

  if (viewName === "nearby") {
    await renderNearby();
  }

  if (viewName === "surge") {
    await renderSurge();
  }

  if (viewName === "pickup") {
    await renderPickup();
  }

  if (viewName === "disruption") {
    await renderDisruption();
  }
}

async function renderHeatmap() {
  const res = await fetch("/zones");
  const zones = await res.json();

  addZonesSource(zones, "demand");

  map.addLayer({
    id: "heatmap-layer",
    type: "heatmap",
    source: "zones-source",
    paint: {
      "heatmap-weight": ["interpolate", ["linear"], ["get", "value"], 0, 0, 100, 1],
      "heatmap-intensity": 1.2,
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 9, 25, 12, 60],
      "heatmap-opacity": 0.78,
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0, "rgba(0,0,0,0)",
        0.2, "#ffe680",
        0.4, "#ffb347",
        0.65, "#ff6b35",
        0.85, "#ff3b30",
        1, "#b30000"
      ]
    }
  });

  addZoneCircles(zones, "demand");

  updateSheet(`
    ${summaryCard("Current Demand", [
      ["Hotspots", topZones(zones, "demand")],
      ["Average demand", avg(zones, "demand") + "/100"],
      ["Best use", "Find likely high pickup demand"]
    ])}
  `);
}

async function renderForecast() {
  const res = await fetch("/forecast");
  const data = await res.json();

  const rows = data.map(item => `
    <div class="metric">
      <span>${item.time}</span>
      <strong>${item.demand_index}/100 · ${item.expected_wait} min · ${item.surge_risk}</strong>
    </div>
  `).join("");

  await renderHeatmap();

  updateSheet(`
    <div class="info-card">
      <h3>Demand Forecast</h3>
      ${rows}
    </div>
  `);
}

async function renderNearby() {
  const taxiRes = await fetch("/taxis");
  const taxis = await taxiRes.json();

  const mobilityRes = await fetch("/mobility");
  const mobility = await mobilityRes.json();

  map.addSource("taxis-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: taxis.map(taxi => pointFeature(taxi.lng, taxi.lat, {
        type: "taxi",
        label: taxi.vehicle_type,
        status: taxi.status,
        color: taxi.status === "Available" ? "#00d68f" : "#ffcc00"
      }))
    }
  });

  map.addLayer({
    id: "taxi-points",
    type: "circle",
    source: "taxis-source",
    paint: {
      "circle-radius": 5,
      "circle-color": ["get", "color"],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1,
      "circle-opacity": 0.9
    }
  });

  map.addSource("mobility-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: [
        ...mobility.mrt_stations.map(s => pointFeature(s.lng, s.lat, {
          type: "mrt",
          label: s.name,
          icon: "M"
        })),
        ...mobility.bus_stops.map(s => pointFeature(s.lng, s.lat, {
          type: "bus",
          label: s.name,
          icon: "B"
        }))
      ]
    }
  });

  map.addLayer({
    id: "mrt-points",
    type: "symbol",
    source: "mobility-source",
    filter: ["==", ["get", "type"], "mrt"],
    layout: {
      "text-field": "M",
      "text-size": 12,
      "text-allow-overlap": true
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#007aff",
      "text-halo-width": 2
    }
  });

  map.addLayer({
    id: "bus-points",
    type: "symbol",
    source: "mobility-source",
    filter: ["==", ["get", "type"], "bus"],
    layout: {
      "text-field": "B",
      "text-size": 10,
      "text-allow-overlap": true
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#34c759",
      "text-halo-width": 1.6
    }
  });

  updateSheet(`
    ${summaryCard("Nearby Mobility", [
      ["Taxis shown", taxis.length],
      ["MRT stations", mobility.mrt_stations.length],
      ["Bus stops", mobility.bus_stops.length],
      ["Green taxis", "Available"]
    ])}
  `);
}

async function renderSurge() {
  const res = await fetch("/zones");
  const zones = await res.json();

  addZonesSource(zones, "surge_score");

  map.addLayer({
    id: "risk-circles",
    type: "circle",
    source: "zones-source",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "value"], 0, 12, 100, 42],
      "circle-color": [
        "interpolate",
        ["linear"],
        ["get", "value"],
        0, "#ffe680",
        50, "#ff9500",
        80, "#ff3b30"
      ],
      "circle-opacity": 0.55,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1
    }
  });

  addZoneLabels();

  updateSheet(`
    ${summaryCard("Surge Risk", [
      ["Highest risk", topZones(zones, "surge_score")],
      ["Average risk", avg(zones, "surge_score") + "/100"],
      ["User insight", "Move pickup 300–600m away from hotspot"]
    ])}
  `);
}

async function renderPickup() {
  const res = await fetch("/pickup-risk");
  const risks = await res.json();

  map.addSource("risk-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: risks.map(risk => pointFeature(risk.lng, risk.lat, {
        zone: risk.zone,
        risk: risk.risk,
        reason: risk.reason,
        value: risk.risk_score
      }))
    }
  });

  map.addLayer({
    id: "risk-circles",
    type: "circle",
    source: "risk-source",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "value"], 0, 12, 100, 40],
      "circle-color": [
        "interpolate",
        ["linear"],
        ["get", "value"],
        0, "#34c759",
        45, "#ffcc00",
        75, "#ff3b30"
      ],
      "circle-opacity": 0.58,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1
    }
  });

  map.addLayer({
    id: "risk-labels",
    type: "symbol",
    source: "risk-source",
    layout: {
      "text-field": ["get", "zone"],
      "text-size": 11,
      "text-offset": [0, 1.4],
      "text-allow-overlap": false
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#000000",
      "text-halo-width": 1.4
    }
  });

  updateSheet(`
    ${summaryCard("Pickup Reliability", [
      ["High risk zones", risks.filter(r => r.risk === "High").length],
      ["Medium risk zones", risks.filter(r => r.risk === "Medium").length],
      ["Typical issue", "Pickup confusion / road constraints"]
    ])}
  `);
}

async function renderDisruption() {
  const res = await fetch("/zones");
  const zones = await res.json();

  const disruptionZones = zones.map(zone => ({
    ...zone,
    disruption_score: Math.min(100, zone.demand + Math.floor(Math.random() * 18))
  }));

  addZonesSource(disruptionZones, "disruption_score");

  map.addLayer({
    id: "heatmap-layer",
    type: "heatmap",
    source: "zones-source",
    paint: {
      "heatmap-weight": ["interpolate", ["linear"], ["get", "value"], 0, 0, 100, 1],
      "heatmap-intensity": 1.4,
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 9, 25, 12, 55],
      "heatmap-opacity": 0.75,
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0, "rgba(0,0,0,0)",
        0.2, "#7dd3fc",
        0.45, "#38bdf8",
        0.7, "#facc15",
        0.9, "#fb7185",
        1, "#dc2626"
      ]
    }
  });

  addZoneCircles(disruptionZones, "disruption_score");

  updateSheet(`
    ${summaryCard("Disruption View", [
      ["Likely pressure", topZones(disruptionZones, "disruption_score")],
      ["Signals simulated", "Rain, airport, events, late-night demand"],
      ["Best use", "Pre-position supply before spike"]
    ])}
  `);
}

function addZonesSource(zones, field) {
  map.addSource("zones-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: zones.map(zone => pointFeature(zone.lng, zone.lat, {
        zone: zone.name,
        value: zone[field],
        demand: zone.demand,
        supply: zone.supply,
        eta: zone.eta_minutes,
        surge: zone.surge
      }))
    }
  });
}

function addZoneCircles(zones, field) {
  map.addLayer({
    id: "zone-circles",
    type: "circle",
    source: "zones-source",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "value"], 0, 8, 100, 34],
      "circle-color": [
        "interpolate",
        ["linear"],
        ["get", "value"],
        0, "#34c759",
        45, "#ffcc00",
        75, "#ff3b30"
      ],
      "circle-opacity": 0.68,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1
    }
  });

  addZoneLabels();
}

function addZoneLabels() {
  map.addLayer({
    id: "zone-labels",
    type: "symbol",
    source: "zones-source",
    layout: {
      "text-field": ["get", "zone"],
      "text-size": 11,
      "text-offset": [0, 1.4],
      "text-allow-overlap": false
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#000000",
      "text-halo-width": 1.4
    }
  });
}

function updateSheet(html) {
  document.getElementById("sheetContent").innerHTML = html;
}

function summaryCard(title, rows) {
  return `
    <div class="info-card">
      <h3>${title}</h3>
      ${rows.map(row => `
        <div class="metric">
          <span>${row[0]}</span>
          <strong>${row[1]}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function pointFeature(lng, lat, props) {
  return {
    type: "Feature",
    geometry: {
      type: "Point",
      coordinates: [lng, lat]
    },
    properties: props
  };
}

function topZones(zones, field) {
  return zones
    .slice()
    .sort((a, b) => b[field] - a[field])
    .slice(0, 3)
    .map(z => z.name || z.zone)
    .join(", ");
}

function avg(items, field) {
  const value = items.reduce((sum, item) => sum + Number(item[field] || 0), 0) / items.length;
  return Math.round(value);
}