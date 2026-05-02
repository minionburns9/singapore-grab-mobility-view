let map;
let currentView = null;
const APP_LOGS = [];

function addLog(message, level = "info", meta = null) {
  APP_LOGS.push({
    time: new Date().toLocaleTimeString(),
    level,
    message,
    meta
  });
  while (APP_LOGS.length > 40) APP_LOGS.shift();
}


const VIEW_META = {
  heatmap: {
    title: "Live Taxi Supply Heatmap",
    subtitle: "Available taxis currently reported by LTA Taxi-Availability.",
    mode: "Live Supply"
  },
  forecast: {
    title: "Live Supply Snapshot",
    subtitle: "Current available taxi count and strongest live supply clusters.",
    mode: "Snapshot"
  },
  nearby: {
    title: "Nearby Mobility",
    subtitle: "Available taxis, official bus stops and official taxi stands.",
    mode: "Nearby"
  },
  surge: {
    title: "Road Friction Signals",
    subtitle: "Live traffic incidents and slow road segments from LTA.",
    mode: "Road Friction"
  },
  pickup: {
    title: "Official Taxi Stands",
    subtitle: "Taxi stands and taxi stops, including barrier-free status where available.",
    mode: "Pickup"
  },
  disruption: {
    title: "Traffic + Train Disruption",
    subtitle: "Live road incidents and train service alerts.",
    mode: "Disruption"
  }
};

async function openView(viewName) {
  currentView = viewName;
  addLog(`Opening view: ${viewName}`, "info");

  document.getElementById("home").style.display = "none";
  document.getElementById("mapView").style.display = "block";

  document.getElementById("viewTitle").innerText = VIEW_META[viewName].title;
  document.getElementById("viewSubtitle").innerText = VIEW_META[viewName].subtitle;
  document.getElementById("topMode").innerText = VIEW_META[viewName].mode;

  updateSheet(loadingCard("Loading live LTA data..."));

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
  const config = await fetchJson("/config");

  if (!config.mapbox_token) {
    updateSheet(errorCard("MAPBOX_TOKEN is missing in Render environment variables."));
    throw new Error("MAPBOX_TOKEN missing");
  }

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
    "taxi-heatmap-layer",
    "taxi-cluster-circles",
    "taxi-cluster-labels",
    "taxi-points",
    "bus-points",
    "taxi-stand-points",
    "taxi-stand-labels",
    "incident-points",
    "incident-labels",
    "speed-lines",
    "slow-speed-lines"
  ];

  const sources = [
    "taxi-clusters-source",
    "taxis-source",
    "bus-stops-source",
    "taxi-stands-source",
    "incidents-source",
    "speed-source"
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
  try {
    if (viewName === "heatmap") await renderHeatmap();
    if (viewName === "forecast") await renderSupplySnapshot();
    if (viewName === "nearby") await renderNearby();
    if (viewName === "surge") await renderRoadFriction();
    if (viewName === "pickup") await renderTaxiStands();
    if (viewName === "disruption") await renderDisruption();
  } catch (error) {
    console.error(error);
    addLog(error.message || "Unable to load live data.", "error");
    updateSheet(errorCard(error.message || "Unable to load live data."));
  }
}

async function renderHeatmap() {
  const response = await fetchJson("/zones?limit=160");
  const clusters = response.data || [];

  addTaxiClusterSource(clusters);

  map.addLayer({
    id: "taxi-heatmap-layer",
    type: "heatmap",
    source: "taxi-clusters-source",
    paint: {
      "heatmap-weight": ["interpolate", ["linear"], ["get", "value"], 0, 0, 25, 1],
      "heatmap-intensity": 1.25,
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 9, 18, 12, 55],
      "heatmap-opacity": 0.8,
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0, "rgba(0,0,0,0)",
        0.2, "#7dd3fc",
        0.45, "#22c55e",
        0.7, "#facc15",
        0.9, "#fb923c",
        1, "#ef4444"
      ]
    }
  });

  addTaxiClusterCircles();

  updateSheet(`
    ${summaryCard("Live Taxi Supply Heatmap", [
      ["Available taxis", response.taxi_count],
      ["Live clusters shown", response.count],
      ["Source", "LTA Taxi-Availability"],
      ["Updated", formatTime(response.updated_at_utc)]
    ])}
    ${listCard("Top live taxi clusters", clusters.slice(0, 5).map(cluster => `${cluster.name}: ${cluster.available_taxis} taxis`))}
    ${noteCard("This is supply, not demand. LTA exposes available taxi locations; it does not expose Grab booking demand or fare surge.")}
  `);
}

async function renderSupplySnapshot() {
  const summary = await fetchJson("/supply-summary");
  const zones = await fetchJson("/zones?limit=80");
  const clusters = zones.data || [];

  addTaxiClusterSource(clusters);
  addTaxiClusterCircles();

  updateSheet(`
    ${summaryCard("Live Supply Snapshot", [
      ["Available taxis", summary.available_taxis],
      ["Visible clusters", summary.visible_clusters],
      ["Source", "LTA Taxi-Availability"],
      ["Updated", formatTime(summary.updated_at_utc)]
    ])}
    ${listCard("Strongest supply clusters", (summary.top_clusters || []).map(cluster => `${cluster.name}: ${cluster.available_taxis} taxis`))}
    ${noteCard("This replaces the earlier forecast view. Forecasting demand would require Grab booking data, which is not public.")}
  `);
}

async function renderNearby() {
  const mobility = await fetchJson("/mobility");
  const taxis = mobility.taxis || [];
  const busStops = mobility.bus_stops || [];
  const taxiStands = mobility.taxi_stands || [];

  addTaxiPoints(taxis);
  addBusStopPoints(busStops);
  addTaxiStandPoints(taxiStands);

  updateSheet(`
    ${summaryCard("Nearby Mobility", [
      ["Available taxis", mobility.counts.available_taxis],
      ["Bus stops displayed", mobility.counts.bus_stops_displayed],
      ["Taxi stands/stops", mobility.counts.taxi_stands],
      ["Updated", formatTime(mobility.updated_at_utc)]
    ])}
    ${legendCard([
      ["Green dots", "Available taxis"],
      ["Blue B", "Official bus stops"],
      ["Yellow T", "Official taxi stands/stops"]
    ])}
  `);
}

async function renderRoadFriction() {
  const friction = await fetchJson("/road-friction");
  const incidents = friction.traffic_incidents || [];
  const slowSegments = friction.slow_speed_segments || [];

  addIncidentPoints(incidents);
  addSpeedLines(slowSegments, true);

  updateSheet(`
    ${summaryCard("Road Friction Signals", [
      ["Traffic incidents", friction.counts.traffic_incidents],
      ["Slow road segments", friction.counts.slow_speed_segments],
      ["Sources", "LTA TrafficIncidents + TrafficSpeedBands"],
      ["Updated", formatTime(friction.updated_at_utc)]
    ])}
    ${listCard("Current incidents", incidents.slice(0, 6).map(item => `${item.type}: ${item.message || "No message"}`))}
    ${noteCard("This replaces the earlier surge-risk view. Public LTA data can show road friction; it cannot show Grab fare surge.")}
  `);
}

async function renderTaxiStands() {
  const response = await fetchJson("/taxi-stands");
  const stands = response.data || [];

  addTaxiStandPoints(stands, true);

  updateSheet(`
    ${summaryCard("Official Taxi Stands", [
      ["Taxi stands/stops", response.count],
      ["Source", "LTA TaxiStands"],
      ["Updated", formatTime(response.updated_at_utc)]
    ])}
    ${listCard("Examples", stands.slice(0, 8).map(stand => `${stand.type || "Taxi facility"} · ${stand.name} · BFA: ${stand.barrier_free || "N/A"}`))}
  `);
}

async function renderDisruption() {
  const disruptions = await fetchJson("/disruptions");
  const incidents = disruptions.traffic_incidents || [];
  const trainAlerts = disruptions.train_alerts || [];

  addIncidentPoints(incidents);

  updateSheet(`
    ${summaryCard("Traffic + Train Disruption", [
      ["Traffic incidents", disruptions.counts.traffic_incidents],
      ["Train alerts", disruptions.counts.train_alerts],
      ["Sources", "LTA TrafficIncidents + TrainServiceAlerts"],
      ["Updated", formatTime(disruptions.updated_at_utc)]
    ])}
    ${listCard("Train alerts", trainAlerts.length ? trainAlerts.map(alert => trainAlertText(alert)) : ["No train service alert records returned at this time."])}
    ${listCard("Road incidents", incidents.length ? incidents.slice(0, 6).map(item => `${item.type}: ${item.message || "No message"}`) : ["No road incident records returned at this time."])}
  `);
}

function addTaxiClusterSource(clusters) {
  map.addSource("taxi-clusters-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: clusters.map(cluster => pointFeature(cluster.lng, cluster.lat, {
        zone: cluster.name,
        value: cluster.value,
        available_taxis: cluster.available_taxis
      }))
    }
  });
}

function addTaxiClusterCircles() {
  map.addLayer({
    id: "taxi-cluster-circles",
    type: "circle",
    source: "taxi-clusters-source",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "value"], 1, 8, 25, 34],
      "circle-color": [
        "interpolate",
        ["linear"],
        ["get", "value"],
        1, "#22c55e",
        8, "#facc15",
        18, "#fb923c",
        30, "#ef4444"
      ],
      "circle-opacity": 0.72,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1
    }
  });

  map.addLayer({
    id: "taxi-cluster-labels",
    type: "symbol",
    source: "taxi-clusters-source",
    layout: {
      "text-field": ["to-string", ["get", "available_taxis"]],
      "text-size": 11,
      "text-allow-overlap": false
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#000000",
      "text-halo-width": 1.4
    }
  });
}

function addTaxiPoints(taxis) {
  map.addSource("taxis-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: taxis.map(taxi => pointFeature(taxi.lng, taxi.lat, {
        type: "taxi",
        label: taxi.status,
        source: taxi.source
      }))
    }
  });

  map.addLayer({
    id: "taxi-points",
    type: "circle",
    source: "taxis-source",
    paint: {
      "circle-radius": 4,
      "circle-color": "#00d68f",
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 0.8,
      "circle-opacity": 0.88
    }
  });
}

function addBusStopPoints(busStops) {
  map.addSource("bus-stops-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: busStops.map(stop => pointFeature(stop.lng, stop.lat, {
        type: "bus",
        label: stop.name,
        code: stop.bus_stop_code
      }))
    }
  });

  map.addLayer({
    id: "bus-points",
    type: "symbol",
    source: "bus-stops-source",
    layout: {
      "text-field": "B",
      "text-size": 10,
      "text-allow-overlap": false
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#2563eb",
      "text-halo-width": 2
    }
  });
}

function addTaxiStandPoints(stands, showLabels = false) {
  map.addSource("taxi-stands-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: stands.map(stand => pointFeature(stand.lng, stand.lat, {
        type: "taxi_stand",
        label: stand.name,
        facility_type: stand.type,
        barrier_free: stand.barrier_free
      }))
    }
  });

  map.addLayer({
    id: "taxi-stand-points",
    type: "symbol",
    source: "taxi-stands-source",
    layout: {
      "text-field": "T",
      "text-size": 12,
      "text-allow-overlap": showLabels
    },
    paint: {
      "text-color": "#000000",
      "text-halo-color": "#facc15",
      "text-halo-width": 2.4
    }
  });

  if (showLabels) {
    map.addLayer({
      id: "taxi-stand-labels",
      type: "symbol",
      source: "taxi-stands-source",
      layout: {
        "text-field": ["get", "facility_type"],
        "text-size": 10,
        "text-offset": [0, 1.6],
        "text-allow-overlap": false
      },
      paint: {
        "text-color": "#ffffff",
        "text-halo-color": "#000000",
        "text-halo-width": 1.2
      }
    });
  }
}

function addIncidentPoints(incidents) {
  map.addSource("incidents-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: incidents.map(incident => pointFeature(incident.lng, incident.lat, {
        type: incident.type,
        message: incident.message
      }))
    }
  });

  map.addLayer({
    id: "incident-points",
    type: "circle",
    source: "incidents-source",
    paint: {
      "circle-radius": 7,
      "circle-color": "#ef4444",
      "circle-opacity": 0.85,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1
    }
  });

  map.addLayer({
    id: "incident-labels",
    type: "symbol",
    source: "incidents-source",
    layout: {
      "text-field": ["get", "type"],
      "text-size": 10,
      "text-offset": [0, 1.3],
      "text-allow-overlap": false
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#000000",
      "text-halo-width": 1.3
    }
  });
}

function addSpeedLines(segments, slowOnly = false) {
  map.addSource("speed-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: segments.map(segment => ({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [segment.start_lng, segment.start_lat],
            [segment.end_lng, segment.end_lat]
          ]
        },
        properties: {
          road_name: segment.road_name,
          speed_band: segment.speed_band,
          minimum_speed: segment.minimum_speed,
          maximum_speed: segment.maximum_speed
        }
      }))
    }
  });

  map.addLayer({
    id: slowOnly ? "slow-speed-lines" : "speed-lines",
    type: "line",
    source: "speed-source",
    paint: {
      "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2, 13, 5],
      "line-color": [
        "interpolate",
        ["linear"],
        ["get", "speed_band"],
        1, "#ef4444",
        2, "#f97316",
        3, "#facc15",
        4, "#a3e635",
        8, "#22c55e"
      ],
      "line-opacity": 0.75
    }
  });
}

async function fetchJson(url) {
  addLog(`GET ${url}`, "request");

  let response;
  try {
    response = await fetch(url);
  } catch (networkError) {
    addLog(`Network error for ${url}: ${networkError.message}`, "error");
    throw networkError;
  }

  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    addLog(`Non-JSON response from ${url} · HTTP ${response.status}`, "error");
    throw new Error(`Non-JSON response from ${url} · HTTP ${response.status}`);
  }

  if (!response.ok) {
    const detail = payload.detail || response.statusText || "Request failed";
    const detailText = typeof detail === "string" ? detail : JSON.stringify(detail);
    addLog(`${url} failed · HTTP ${response.status} · ${detailText}`, "error");
    throw new Error(`${url}: ${detailText}`);
  }

  const count = payload.count ?? payload.available_taxis ?? payload.data?.length ?? payload.results?.length ?? "ok";
  addLog(`${url} success · ${count}`, "success");
  return payload;
}

function updateSheet(html) {
  document.getElementById("sheetContent").innerHTML = html + logBox();
}

function logBox() {
  const rows = APP_LOGS.slice().reverse().map(log => {
    const color = log.level === "error" ? "#fb7185" : log.level === "success" ? "#86efac" : log.level === "request" ? "#93c5fd" : "#cbd5e1";
    return `
      <div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.08);font-size:11px;line-height:1.35;">
        <span style="color:#94a3b8;">${escapeHtml(log.time)}</span>
        <span style="color:${color};font-weight:700;"> ${escapeHtml(log.level.toUpperCase())}</span>
        <div style="color:#e2e8f0;word-break:break-word;">${escapeHtml(log.message)}</div>
      </div>
    `;
  }).join("");

  return `
    <div class="info-card" style="background:#0b1727;border:1px solid rgba(125,211,252,0.18);">
      <h3>Live Debug Log</h3>
      <div class="metric">
        <span>Purpose</span>
        <strong>Copy errors from here</strong>
      </div>
      <div style="max-height:180px;overflow:auto;">
        ${rows || `<div style="font-size:12px;color:#94a3b8;">No frontend logs yet.</div>`}
      </div>
    </div>
  `;
}

function loadingCard(text) {
  return `
    <div class="info-card">
      <h3>${escapeHtml(text)}</h3>
      <div class="metric">
        <span>Status</span>
        <strong>Loading</strong>
      </div>
    </div>
  `;
}

function errorCard(message) {
  return `
    <div class="info-card">
      <h3>Unable to load data</h3>
      <div class="metric">
        <span>Error</span>
        <strong>${escapeHtml(message)}</strong>
      </div>
    </div>
  `;
}

function summaryCard(title, rows) {
  return `
    <div class="info-card">
      <h3>${escapeHtml(title)}</h3>
      ${rows.map(row => `
        <div class="metric">
          <span>${escapeHtml(row[0])}</span>
          <strong>${escapeHtml(String(row[1]))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function listCard(title, rows) {
  return `
    <div class="info-card">
      <h3>${escapeHtml(title)}</h3>
      ${rows.map(row => `
        <div class="metric">
          <span>${escapeHtml(String(row))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function legendCard(rows) {
  return summaryCard("Legend", rows);
}

function noteCard(text) {
  return `
    <div class="info-card">
      <h3>Note</h3>
      <div class="metric">
        <span>${escapeHtml(text)}</span>
      </div>
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

function trainAlertText(alert) {
  const status = alert.status === 1 ? "Normal/minor delay" : alert.status === 2 ? "Major disruption" : "Status unknown";
  const line = alert.line || "Line not specified";
  const stations = alert.stations || "Stations not specified";
  const message = alert.message && alert.message.Content ? alert.message.Content : "";
  return `${line} · ${status} · ${stations}${message ? " · " + message : ""}`;
}

function formatTime(value) {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
