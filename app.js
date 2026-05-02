let map;
let currentView = null;
let userLocation = null;
let userLocationMarkerReady = false;
let choiceRouteAnimationFrameId = null;
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
    title: "Live Taxi Supply Hexmap",
    subtitle: "Available taxis grouped into translucent hexagons from LTA Taxi-Availability.",
    mode: "Live Supply"
  },
  forecast: {
    title: "Pickup Readiness",
    subtitle: "Use your current location to decide whether to book here, walk, or use an official taxi stand.",
    mode: "Pickup Readiness"
  },
  nearby: {
    title: "1km Mobility Choices",
    subtitle: "One local view to decide: wait for taxi, walk to bus stop, or walk to MRT.",
    mode: "Mobility Choices"
  },
  surge: {
    title: "Fare Pressure Proxy",
    subtitle: "Live taxi supply, road incidents and slow road segments used as a transparent pressure proxy.",
    mode: "Fare Pressure Proxy"
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
  drawUserLocation();

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
  stopChoiceRouteAnimation();
  const layers = [
    "taxi-heatmap-layer",
    "taxi-cluster-circles",
    "taxi-cluster-labels",
    "taxi-hex-fills",
    "taxi-hex-lines",
    "taxi-hex-labels",
    "taxi-points",
    "taxi-direction-labels",
    "bus-points",
    "mrt-points",
    "mrt-labels",
    "taxi-stand-points",
    "taxi-stand-labels",
    "incident-points",
    "incident-labels",
    "speed-lines",
    "slow-speed-lines",
    "readiness-ring-fills",
    "readiness-ring-lines",
    "readiness-ring-labels",
    "readiness-guidance-line",
    "guidance-lines",
    "guidance-line-labels",
    "choice-route-glow",
    "choice-routes",
    "choice-route-labels",
    "choice-route-pulses-glow",
    "choice-route-pulses",
    "choice-route-endpoints",
    "choice-route-endpoint-labels"
  ];

  const sources = [
    "taxi-clusters-source",
    "taxi-hex-source",
    "taxis-source",
    "bus-stops-source",
    "mrt-stations-source",
    "taxi-stands-source",
    "incidents-source",
    "speed-source",
    "readiness-rings-source",
    "readiness-line-source",
    "guidance-lines-source",
    "choice-routes-source",
    "choice-route-label-source",
    "choice-route-pulses-source",
    "choice-route-endpoints-source"
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
    if (viewName === "forecast") await renderPickupReadiness();
    if (viewName === "nearby") await renderNearby();
    if (viewName === "surge") await renderFarePressure();
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

  addTaxiHexSource(clusters);
  addTaxiHexagons();

  updateSheet(`
    ${summaryCard("Live Taxi Supply Hexmap", [
      ["Available taxis", response.taxi_count],
      ["Hexagons shown", response.count],
      ["Count meaning", "available taxis inside that approximate hex cell"],
      ["Source", "LTA Taxi-Availability"],
      ["Updated", formatTime(response.updated_at_utc)]
    ])}
    ${listCard("Top live taxi hexagons", clusters.slice(0, 5).map(cluster => `${cluster.name}: ${cluster.available_taxis} available taxis`))}
    ${noteCard("Each number is the count of taxis currently available for hire in that approximate hexagon. It is not demand, not Grab surge, not total fleet size, and not hired/busy taxis.")}
  `);
}

async function renderPickupReadiness() {
  if (!userLocation) {
    const mobility = await fetchJson("/mobility");
    addTaxiPoints(mobility.taxis || [], false);
    addTaxiStandPoints(mobility.taxi_stands || []);

    updateSheet(`
      ${summaryCard("Pickup Readiness", [
        ["Status", "Tap My Location"],
        ["Why location is needed", "readiness is calculated around your blue dot"],
        ["Available taxis shown", mobility.counts.available_taxis],
        ["Unavailable/busy taxi data", "not provided by LTA"]
      ])}
      ${noteCard("Tap ◎ My Location at the top. This view then shows 300m, 600m and 1km readiness circles around you, nearby available taxis, official taxi stands, road friction, a fare pressure proxy score, and a recommendation.")}
      ${noteCard("LTA Taxi-Availability only shows taxis currently available for hire. It does not expose hired, busy, booked, Grab-only, or unavailable taxi counts, so this app will not invent those values.")}
    `);
    return;
  }

  const readiness = await fetchJson(`/pickup-readiness?lat=${userLocation.lat}&lng=${userLocation.lng}`);
  const taxis = readiness.nearest_taxis || [];
  const stands = readiness.nearby_taxi_stands || [];
  const incidents = readiness.nearby_traffic_incidents || [];
  const slowSegments = readiness.nearby_slow_speed_segments || [];
  const pressure = readiness.fare_pressure_proxy || {};

  addReadinessRings(userLocation.lat, userLocation.lng);
  addTaxiPoints(taxis, true);
  addTaxiStandPoints(stands, true);
  addIncidentPoints(incidents);
  addSpeedLines(slowSegments, true);

  if (readiness.nearest_taxi_stand) {
    addReadinessLine(userLocation, readiness.nearest_taxi_stand, "Nearest taxi stand");
  } else if (readiness.nearest_supply_cluster) {
    addReadinessLine(userLocation, readiness.nearest_supply_cluster, "Nearest supply cluster");
  }

  map.flyTo({ center: [userLocation.lng, userLocation.lat], zoom: Math.max(map.getZoom(), 14), speed: 0.7 });

  updateSheet(`
    ${summaryCard("Pickup Readiness", [
      ["Readiness", readiness.readiness_level],
      ["Fare pressure proxy", `${pressure.level || "N/A"} · ${pressure.score ?? "N/A"}/100`],
      ["What pressure means", pressure.meaning || "N/A"],
      ["Available taxis within 300m", readiness.available_taxi_counts.within_300m],
      ["Available taxis within 600m", readiness.available_taxi_counts.within_600m],
      ["Available taxis within 1km", readiness.available_taxi_counts.within_1000m],
      ["Nearest taxi stand", readiness.nearest_taxi_stand ? `${readiness.nearest_taxi_stand.distance_m}m` : "N/A"],
      ["Road incidents within 1.5km", readiness.counts.traffic_incidents_1500m],
      ["Slow road segments within 1.5km", readiness.counts.slow_segments_1500m],
      ["Unavailable/busy taxis", "not available in LTA feed"]
    ])}
    ${listCard("Recommendation", [readiness.recommendation])}
    ${listCard("Fare pressure signals", pressure.signals || ["No fare pressure signals returned."])}
    ${legendCard([
      ["Blue dot", "your current location"],
      ["Blue circles", "300m / 600m / 1km readiness radius"],
      ["Green dots", "available-for-hire taxis only"],
      ["Yellow T", "official taxi stands/stops"],
      ["Red circles/lines", "road friction signals"]
    ])}
    ${noteCard(readiness.unavailable_taxis.message)}
  `);
}

async function renderNearby() {
  if (!userLocation) {
    const mobility = await fetchJson("/mobility");
    addTaxiPoints((mobility.taxis || []).slice(0, 500), false);
    addBusStopPoints((mobility.bus_stops || []).slice(0, 700));
    addTaxiStandPoints(mobility.taxi_stands || []);
    addMrtStationPoints(mobility.mrt_stations || []);

    updateSheet(`
      ${summaryCard("1km Mobility Choices", [
        ["Status", "Tap My Location"],
        ["Why location is needed", "to rank the top 3 options around your blue dot"],
        ["Available taxis shown", mobility.counts.available_taxis],
        ["Bus stops displayed", mobility.counts.bus_stops_displayed],
        ["Taxi stands/stops", mobility.counts.taxi_stands],
        ["MRT reference stations", mobility.counts.mrt_stations]
      ])}
      ${listCard("Once location is enabled, this view will map 3 decision flows", [
        "1) Best taxi option from your location",
        "2) Best bus-stop fallback with approximate walking time",
        "3) Best MRT fallback with approximate walking time and train-alert check"
      ])}
      ${noteCard("Tap ◎ My Location. This view will animate the top 3 mobility recommendation flows from your location to the recommended taxi, bus-stop and MRT endpoints within 1km.")}
    `);
    return;
  }

  const decision = await fetchJson(`/mobility-decision?lat=${userLocation.lat}&lng=${userLocation.lng}&radius_m=1000`);
  const nearby = decision.nearby || {};
  const taxis = nearby.available_taxis || [];
  const busStops = nearby.bus_stops || [];
  const taxiStands = nearby.taxi_stands || [];
  const mrtStations = nearby.mrt_stations || [];
  const incidents = nearby.traffic_incidents || [];
  const slowSegments = nearby.slow_speed_segments || [];
  const pressure = decision.fare_pressure_proxy || {};

  addReadinessRings(userLocation.lat, userLocation.lng);
  addTaxiPoints(taxis, true);
  addBusStopPoints(busStops);
  addTaxiStandPoints(taxiStands, true);
  addMrtStationPoints(mrtStations, true);
  addIncidentPoints(incidents);
  addSpeedLines(slowSegments, true);

  const rankedOptions = buildMobilityChoiceOptions(decision);
  addChoiceRouteFlows(userLocation, rankedOptions);

  map.flyTo({ center: [userLocation.lng, userLocation.lat], zoom: Math.max(map.getZoom(), 14.2), speed: 0.7 });

  updateSheet(`
    ${summaryCard("1km Mobility Choices", [
      ["Recommended action", decision.recommendation],
      ["Fare pressure proxy", `${pressure.level || "N/A"} · ${pressure.score ?? "N/A"}/100`],
      ["What pressure means", pressure.meaning || "N/A"],
      ["Available taxis within 300m", decision.counts.available_taxis_300m],
      ["Available taxis within 600m", decision.counts.available_taxis_600m],
      ["Available taxis within 1km", decision.counts.available_taxis_1000m],
      ["Road friction nearby", `${decision.counts.traffic_incidents_1500m} incidents · ${decision.counts.slow_segments_1500m} slow segments`],
      ["Train alerts", `${decision.counts.train_alerts} records · ${decision.counts.major_train_alerts} major`]
    ])}
    ${optionCards(rankedOptions)}
    ${listCard("Fare pressure signals", pressure.signals || ["No fare pressure signals returned."])}
    ${legendCard([
      ["Blue dot/circles", "your location and 300m / 600m / 1km radius"],
      ["Green flow", "best taxi option"],
      ["Blue flow", "best bus-stop fallback"],
      ["Purple flow", "best MRT fallback"],
      ["Red", "road incident or slow segment"]
    ])}
    ${noteCard("The animated flows show your top 3 local mobility options from your location. Walking time is approximate using 80m/min and straight-line distance. The taxi flow points to the strongest visible taxi option nearby; it is not an assigned vehicle route.")}
  `);
}

async function renderFarePressure() {
  const pressure = await fetchJson("/fare-pressure");
  const incidents = pressure.traffic_incidents || [];
  const slowSegments = pressure.slow_speed_segments || [];

  addIncidentPoints(incidents);
  addSpeedLines(slowSegments, true);

  updateSheet(`
    ${summaryCard("Fare Pressure Proxy", [
      ["Proxy level", pressure.pressure_level],
      ["Proxy score", `${pressure.fare_pressure_proxy_score}/100`],
      ["Available taxis", pressure.available_taxis],
      ["Traffic incidents", pressure.counts.traffic_incidents],
      ["Slow road segments", pressure.counts.slow_speed_segments],
      ["Updated", formatTime(pressure.updated_at_utc)]
    ])}
    ${listCard("Why this may feel expensive or slow", (pressure.explanations || []).map(item => item))}
    ${listCard("Current incidents", incidents.length ? incidents.slice(0, 6).map(item => `${item.type}: ${item.message || "No message"}`) : ["No road incident records returned at this time."])}
    ${noteCard("This is not actual Grab surge pricing. It is a transparent proxy derived only from live LTA taxi availability, traffic incidents, traffic speed bands and train alerts.")}
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
    ${noteCard("Public LTA data can show road friction; it cannot show actual Grab fare surge.")}
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
  const mobility = await fetchJson("/mobility");
  const incidents = disruptions.traffic_incidents || [];
  const trainAlerts = disruptions.train_alerts || [];
  const taxis = mobility.taxis || [];
  const busStops = mobility.bus_stops || [];
  const taxiStands = mobility.taxi_stands || [];

  addTaxiPoints(taxis, false);
  addBusStopPoints(busStops);
  addTaxiStandPoints(taxiStands);
  addIncidentPoints(incidents);

  updateSheet(`
    ${summaryCard("Traffic + Train Disruption", [
      ["Traffic incidents", disruptions.counts.traffic_incidents],
      ["Train alerts", disruptions.counts.train_alerts],
      ["Nearby taxis overlay", mobility.counts.available_taxis],
      ["Bus stops overlay", mobility.counts.bus_stops_displayed],
      ["Taxi stands overlay", mobility.counts.taxi_stands],
      ["Sources", "LTA TrafficIncidents + TrainServiceAlerts + mobility overlays"],
      ["Updated", formatTime(disruptions.updated_at_utc)]
    ])}
    ${listCard("Train alerts", trainAlerts.length ? trainAlerts.map(alert => trainAlertText(alert)) : ["No train service alert records returned at this time."])}
    ${listCard("Road incidents", incidents.length ? incidents.slice(0, 6).map(item => `${item.type}: ${item.message || "No message"}`) : ["No road incident records returned at this time."])}
    ${legendCard([
      ["Red circles", "Live road incidents"],
      ["Green dots", "Available taxis overlay"],
      ["Blue B", "Bus stops overlay"],
      ["Yellow T", "Taxi stands overlay"]
    ])}
  `);
}


function addReadinessRings(lat, lng) {
  const rings = [
    { radius_m: 300, label: "300m", level: 1 },
    { radius_m: 600, label: "600m", level: 2 },
    { radius_m: 1000, label: "1km", level: 3 }
  ];

  map.addSource("readiness-rings-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: rings.flatMap(ring => [
        circlePolygonFeature(lng, lat, ring.radius_m / 1000, {
          label: ring.label,
          radius_m: ring.radius_m,
          level: ring.level,
          kind: "ring"
        }),
        pointFeature(lng + metersToLng(ring.radius_m, lat), lat, {
          label: ring.label,
          level: ring.level,
          kind: "label"
        })
      ])
    }
  });

  map.addLayer({
    id: "readiness-ring-fills",
    type: "fill",
    source: "readiness-rings-source",
    filter: ["==", ["get", "kind"], "ring"],
    paint: {
      "fill-color": "#2563eb",
      "fill-opacity": ["interpolate", ["linear"], ["get", "level"], 1, 0.10, 3, 0.035]
    }
  });

  map.addLayer({
    id: "readiness-ring-lines",
    type: "line",
    source: "readiness-rings-source",
    filter: ["==", ["get", "kind"], "ring"],
    paint: {
      "line-color": "#93c5fd",
      "line-width": 1.6,
      "line-opacity": 0.82,
      "line-dasharray": [2, 2]
    }
  });

  map.addLayer({
    id: "readiness-ring-labels",
    type: "symbol",
    source: "readiness-rings-source",
    filter: ["==", ["get", "kind"], "label"],
    layout: {
      "text-field": ["get", "label"],
      "text-size": 11,
      "text-allow-overlap": true
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#1e3a8a",
      "text-halo-width": 1.6
    }
  });
}

function addReadinessLine(from, to, label) {
  if (!from || !to || to.lat === undefined || to.lng === undefined) return;

  map.addSource("readiness-line-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [[from.lng, from.lat], [to.lng, to.lat]]
        },
        properties: { label }
      }]
    }
  });

  map.addLayer({
    id: "readiness-guidance-line",
    type: "line",
    source: "readiness-line-source",
    paint: {
      "line-color": "#facc15",
      "line-width": 3,
      "line-opacity": 0.82,
      "line-dasharray": [1.2, 1.2]
    }
  });
}

function circlePolygonFeature(lng, lat, radiusKm, props) {
  const coordinates = [];
  const steps = 72;
  const latRadius = radiusKm / 111.32;
  const lngRadius = radiusKm / (111.32 * Math.cos(lat * Math.PI / 180));

  for (let i = 0; i <= steps; i++) {
    const angle = (Math.PI * 2 * i) / steps;
    coordinates.push([
      lng + lngRadius * Math.cos(angle),
      lat + latRadius * Math.sin(angle)
    ]);
  }

  return {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [coordinates]
    },
    properties: props
  };
}

function metersToLng(meters, lat) {
  return (meters / 1000) / (111.32 * Math.cos(lat * Math.PI / 180));
}

function addTaxiHexSource(clusters) {
  map.addSource("taxi-hex-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: clusters.map(cluster => {
        const count = Number(cluster.available_taxis || cluster.value || 1);
        const radiusKm = Math.max(0.28, Math.min(1.15, 0.28 + Math.sqrt(count) * 0.12));
        return hexagonFeature(cluster.lng, cluster.lat, radiusKm, {
          zone: cluster.name,
          value: count,
          available_taxis: count,
          radius_km: radiusKm
        });
      })
    }
  });
}

function addTaxiHexagons() {
  map.addLayer({
    id: "taxi-hex-fills",
    type: "fill",
    source: "taxi-hex-source",
    paint: {
      "fill-color": [
        "interpolate",
        ["linear"],
        ["get", "value"],
        1, "#22c55e",
        8, "#facc15",
        18, "#fb923c",
        30, "#ef4444"
      ],
      "fill-opacity": 0.42
    }
  });

  map.addLayer({
    id: "taxi-hex-lines",
    type: "line",
    source: "taxi-hex-source",
    paint: {
      "line-color": "rgba(255,255,255,0.72)",
      "line-width": 1.1,
      "line-opacity": 0.76
    }
  });

  map.addLayer({
    id: "taxi-hex-labels",
    type: "symbol",
    source: "taxi-hex-source",
    layout: {
      "text-field": ["to-string", ["get", "available_taxis"]],
      "text-size": 12,
      "text-allow-overlap": false
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#000000",
      "text-halo-width": 1.6
    }
  });
}

function addTaxiPoints(taxis, showRelativeDirection = false) {
  map.addSource("taxis-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: taxis.map(taxi => {
        let bearing = null;
        let compass = "";

        if (showRelativeDirection && userLocation) {
          bearing = bearingDegrees(userLocation.lat, userLocation.lng, taxi.lat, taxi.lng);
          compass = compassFromBearing(bearing);
        }

        return pointFeature(taxi.lng, taxi.lat, {
          type: "taxi",
          label: taxi.status,
          source: taxi.source,
          direction_label: compass,
          bearing: bearing ?? 0
        });
      })
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

  if (showRelativeDirection && userLocation) {
    map.addLayer({
      id: "taxi-direction-labels",
      type: "symbol",
      source: "taxis-source",
      layout: {
        "text-field": ["get", "direction_label"],
        "text-size": 9,
        "text-offset": [0, 1.25],
        "text-allow-overlap": false
      },
      paint: {
        "text-color": "#ffffff",
        "text-halo-color": "#064e3b",
        "text-halo-width": 1.5
      }
    });
  }
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


function addMrtStationPoints(stations, showLabels = false) {
  if (!stations || !stations.length) return;

  map.addSource("mrt-stations-source", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: stations.map(station => pointFeature(station.lng, station.lat, {
        type: "mrt",
        label: station.name,
        code: station.code,
        has_alert: station.has_relevant_train_alert ? "yes" : "no"
      }))
    }
  });

  map.addLayer({
    id: "mrt-points",
    type: "symbol",
    source: "mrt-stations-source",
    layout: {
      "text-field": "M",
      "text-size": 12,
      "text-allow-overlap": showLabels
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": ["case", ["==", ["get", "has_alert"], "yes"], "#ef4444", "#7c3aed"],
      "text-halo-width": 2.5
    }
  });

  if (showLabels) {
    map.addLayer({
      id: "mrt-labels",
      type: "symbol",
      source: "mrt-stations-source",
      layout: {
        "text-field": ["get", "label"],
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

function addGuidanceLines(from, lines) {
  if (!from || !lines || !lines.length) return;

  const features = lines
    .filter(line => line.to && line.to.lat !== undefined && line.to.lng !== undefined)
    .map(line => ({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [[from.lng, from.lat], [line.to.lng, line.to.lat]]
      },
      properties: { label: line.label || "Option" }
    }));

  if (!features.length) return;

  map.addSource("guidance-lines-source", {
    type: "geojson",
    data: { type: "FeatureCollection", features }
  });

  map.addLayer({
    id: "guidance-lines",
    type: "line",
    source: "guidance-lines-source",
    paint: {
      "line-color": "#facc15",
      "line-width": 2.4,
      "line-opacity": 0.78,
      "line-dasharray": [1.4, 1.2]
    }
  });

  map.addLayer({
    id: "guidance-line-labels",
    type: "symbol",
    source: "guidance-lines-source",
    layout: {
      "symbol-placement": "line-center",
      "text-field": ["get", "label"],
      "text-size": 10,
      "text-allow-overlap": false
    },
    paint: {
      "text-color": "#111827",
      "text-halo-color": "#facc15",
      "text-halo-width": 1.8
    }
  });
}


function buildMobilityChoiceOptions(decision) {
  const nearby = decision.nearby || {};
  const pressure = decision.fare_pressure_proxy || {};
  const taxiOption = decision.decision_options?.wait_for_taxi || {};
  const busOption = decision.decision_options?.walk_to_bus_stop || {};
  const mrtOption = decision.decision_options?.walk_to_mrt || {};

  const nearestTaxi = (nearby.available_taxis || [])[0] || null;
  const nearestStand = (nearby.taxi_stands || [])[0] || null;
  const busNearest = busOption.nearest || null;
  const mrtNearest = mrtOption.nearest || null;
  const taxi600 = Number(taxiOption.available_taxis_600m || 0);
  const taxi1000 = Number(taxiOption.available_taxis_1000m || 0);
  const pressureScore = Number(pressure.score || 0);

  const options = [];

  let taxiTarget = null;
  let taxiAction = "Wait / book taxi";
  let taxiDetails = `${taxi600} taxis within 600m · ${taxi1000} within 1km`;
  let taxiWhy = "Available taxi supply is the main signal for booking from here.";
  let taxiScore = 55 + Math.min(taxi600 * 8, 24) + Math.min(taxi1000 * 2, 10) - Math.round(pressureScore / 5);

  if (nearestStand && (taxi600 < 4 || pressureScore >= 55)) {
    taxiTarget = nearestStand;
    taxiAction = "Walk to taxi stand";
    taxiDetails = `${nearestStand.distance_m}m · ${nearestStand.walk_minutes} min walk`;
    taxiWhy = "Taxi supply is thinner nearby or fare pressure is elevated, so an official taxi stand is a stronger taxi option.";
    taxiScore += 8;
  } else if (nearestTaxi) {
    taxiTarget = nearestTaxi;
    taxiAction = "Wait / book taxi here";
    taxiDetails = taxi600 >= 4 ? `${taxi600} taxis within 600m · book from your current location` : `${nearestTaxi.distance_m}m to the nearest visible available taxi`;
    taxiWhy = taxi600 >= 4 ? "Supply looks reasonable around your location." : "Visible taxi supply exists nearby, but you may wait longer than usual.";
  } else if (nearestStand) {
    taxiTarget = nearestStand;
    taxiAction = "Walk to taxi stand";
    taxiDetails = `${nearestStand.distance_m}m · ${nearestStand.walk_minutes} min walk`;
    taxiWhy = "No visible nearby available taxi was returned, so the nearest official taxi stand is the strongest taxi fallback.";
  }

  if (taxiTarget) {
    options.push({
      key: 'taxi',
      color: '#22c55e',
      icon: '🚕',
      title: taxiAction,
      shortLabel: taxiAction.includes('stand') ? 'Taxi stand' : 'Taxi now',
      detail: taxiDetails,
      why: taxiWhy,
      endpoint: taxiTarget,
      score: clamp(Math.round(taxiScore), 1, 99)
    });
  }

  if (busNearest) {
    const busScore = 72 - Math.min(Math.round(busNearest.distance_m / 18), 35) + (pressureScore >= 55 ? 8 : 0);
    options.push({
      key: 'bus',
      color: '#38bdf8',
      icon: '🚌',
      title: 'Walk to bus stop',
      shortLabel: 'Bus stop',
      detail: `${busNearest.distance_m}m · ${busNearest.walk_minutes} min walk`,
      why: 'Bus is often the fastest fallback when taxi supply is weak or road friction is rising.',
      endpoint: busNearest,
      score: clamp(Math.round(busScore), 1, 99)
    });
  }

  if (mrtNearest) {
    const trainPenalty = mrtNearest.has_relevant_train_alert ? 18 : 0;
    const mrtScore = 68 - Math.min(Math.round(mrtNearest.distance_m / 20), 38) - trainPenalty;
    options.push({
      key: 'mrt',
      color: '#c084fc',
      icon: '🚇',
      title: mrtNearest.has_relevant_train_alert ? 'Walk to MRT carefully' : 'Walk to MRT',
      shortLabel: 'MRT',
      detail: `${mrtNearest.distance_m}m · ${mrtNearest.walk_minutes} min walk${mrtNearest.has_relevant_train_alert ? ' · check alert' : ''}`,
      why: mrtNearest.has_relevant_train_alert ? 'MRT is nearby, but a relevant train alert exists.' : 'MRT is a strong fallback when within walking distance and train service looks normal.',
      endpoint: mrtNearest,
      score: clamp(Math.round(mrtScore), 1, 99)
    });
  }

  options.sort((a, b) => b.score - a.score);
  return options.slice(0, 3).map((option, index) => ({ ...option, rank: index + 1 }));
}

function optionCards(options) {
  if (!options || !options.length) {
    return noteCard('No strong mobility options could be ranked from the current location.');
  }

  return options.map(option => `
    <div class="info-card" style="border:1px solid ${option.color}; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);">
      <h3>${escapeHtml(`${option.rank}. ${option.icon} ${option.title}`)}</h3>
      <div class="metric"><span>Why it ranks here</span><strong style="color:${option.color};">Score ${escapeHtml(option.score)}</strong></div>
      <div class="metric"><span>Route detail</span><strong>${escapeHtml(option.detail)}</strong></div>
      <div class="metric"><span>Endpoint</span><strong>${escapeHtml(option.endpoint.name || option.endpoint.description || option.endpoint.type || 'Nearby option')}</strong></div>
      <div class="metric"><span>Reason</span><strong>${escapeHtml(option.why)}</strong></div>
    </div>
  `).join('');
}

function addChoiceRouteFlows(origin, options) {
  if (!options || !options.length) return;

  const routeFeatures = [];
  const labelFeatures = [];
  const endpointFeatures = [];
  const animationRoutes = [];

  options.forEach(option => {
    if (!option.endpoint || option.endpoint.lat == null || option.endpoint.lng == null) return;

    const coords = curvedRouteCoordinates(origin.lng, origin.lat, option.endpoint.lng, option.endpoint.lat, option.rank);

    routeFeatures.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: coords },
      properties: {
        rank: option.rank,
        title: option.title,
        shortLabel: option.shortLabel,
        detail: option.detail,
        color: option.color
      }
    });

    const midpoint = pointAlongLine(coords, 0.58);
    labelFeatures.push(pointFeature(midpoint[0], midpoint[1], {
      text: `${option.rank}. ${option.shortLabel}`,
      color: option.color
    }));

    endpointFeatures.push(pointFeature(option.endpoint.lng, option.endpoint.lat, {
      rank: String(option.rank),
      title: option.title,
      color: option.color
    }));

    animationRoutes.push({
      id: option.rank,
      color: option.color,
      coordinates: coords,
      offset: option.rank * 0.19
    });
  });

  if (!routeFeatures.length) return;

  map.addSource('choice-routes-source', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: routeFeatures }
  });

  map.addSource('choice-route-label-source', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: labelFeatures }
  });

  map.addSource('choice-route-endpoints-source', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: endpointFeatures }
  });

  map.addSource('choice-route-pulses-source', {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] }
  });

  map.addLayer({
    id: 'choice-route-glow',
    type: 'line',
    source: 'choice-routes-source',
    paint: {
      'line-color': ['get', 'color'],
      'line-width': ['interpolate', ['linear'], ['zoom'], 10, 6, 14, 10],
      'line-opacity': 0.18,
      'line-blur': 2.3
    }
  });

  map.addLayer({
    id: 'choice-routes',
    type: 'line',
    source: 'choice-routes-source',
    paint: {
      'line-color': ['get', 'color'],
      'line-width': ['interpolate', ['linear'], ['zoom'], 10, 2.5, 14, 4],
      'line-opacity': 0.82,
      'line-dasharray': [1.6, 1.2]
    }
  });

  map.addLayer({
    id: 'choice-route-labels',
    type: 'symbol',
    source: 'choice-route-label-source',
    layout: {
      'text-field': ['get', 'text'],
      'text-size': 11,
      'text-offset': [0, -0.8],
      'text-allow-overlap': true
    },
    paint: {
      'text-color': ['get', 'color'],
      'text-halo-color': '#07111f',
      'text-halo-width': 1.8
    }
  });

  map.addLayer({
    id: 'choice-route-endpoints',
    type: 'circle',
    source: 'choice-route-endpoints-source',
    paint: {
      'circle-radius': 11,
      'circle-color': ['get', 'color'],
      'circle-opacity': 0.95,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1.5
    }
  });

  map.addLayer({
    id: 'choice-route-endpoint-labels',
    type: 'symbol',
    source: 'choice-route-endpoints-source',
    layout: {
      'text-field': ['get', 'rank'],
      'text-size': 11,
      'text-allow-overlap': true
    },
    paint: {
      'text-color': '#ffffff',
      'text-halo-color': '#07111f',
      'text-halo-width': 1.5
    }
  });

  map.addLayer({
    id: 'choice-route-pulses-glow',
    type: 'circle',
    source: 'choice-route-pulses-source',
    paint: {
      'circle-radius': 12,
      'circle-color': ['get', 'color'],
      'circle-opacity': 0.18,
      'circle-blur': 0.9
    }
  });

  map.addLayer({
    id: 'choice-route-pulses',
    type: 'circle',
    source: 'choice-route-pulses-source',
    paint: {
      'circle-radius': 4.5,
      'circle-color': ['get', 'color'],
      'circle-opacity': 0.98,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1.1
    }
  });

  startChoiceRouteAnimation(animationRoutes);
}

function startChoiceRouteAnimation(routes) {
  stopChoiceRouteAnimation();
  if (!routes || !routes.length || !map.getSource('choice-route-pulses-source')) return;

  function tick() {
    if (!map || !map.getSource('choice-route-pulses-source')) return;

    const now = performance.now() / 1000;
    const features = [];

    routes.forEach(route => {
      [0, 0.45].forEach(extra => {
        const fraction = (now * 0.16 + route.offset + extra) % 1;
        const coord = pointAlongLine(route.coordinates, fraction);
        features.push(pointFeature(coord[0], coord[1], { color: route.color }));
      });
    });

    map.getSource('choice-route-pulses-source').setData({
      type: 'FeatureCollection',
      features
    });

    choiceRouteAnimationFrameId = requestAnimationFrame(tick);
  }

  tick();
}

function stopChoiceRouteAnimation() {
  if (choiceRouteAnimationFrameId) {
    cancelAnimationFrame(choiceRouteAnimationFrameId);
    choiceRouteAnimationFrameId = null;
  }
}

function curvedRouteCoordinates(fromLng, fromLat, toLng, toLat, rank) {
  const midLng = (fromLng + toLng) / 2;
  const midLat = (fromLat + toLat) / 2;
  const dx = toLng - fromLng;
  const dy = toLat - fromLat;
  const length = Math.sqrt(dx * dx + dy * dy) || 0.001;
  const nx = -dy / length;
  const ny = dx / length;
  const offset = 0.01 * (rank === 2 ? -0.7 : rank === 3 ? 0.7 : 0.45);
  return [
    [fromLng, fromLat],
    [midLng + nx * offset, midLat + ny * offset],
    [toLng, toLat]
  ];
}

function pointAlongLine(coordinates, fraction) {
  if (!coordinates || coordinates.length === 0) return [0, 0];
  if (coordinates.length === 1) return coordinates[0];

  const segments = [];
  let total = 0;
  for (let i = 1; i < coordinates.length; i++) {
    const start = coordinates[i - 1];
    const end = coordinates[i];
    const dist = Math.hypot(end[0] - start[0], end[1] - start[1]);
    segments.push({ start, end, dist });
    total += dist;
  }

  const target = total * clamp(fraction, 0, 1);
  let covered = 0;

  for (const segment of segments) {
    if (covered + segment.dist >= target) {
      const inner = segment.dist === 0 ? 0 : (target - covered) / segment.dist;
      return [
        segment.start[0] + (segment.end[0] - segment.start[0]) * inner,
        segment.start[1] + (segment.end[1] - segment.start[1]) * inner
      ];
    }
    covered += segment.dist;
  }

  return coordinates[coordinates.length - 1];
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
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


function locateUser() {
  if (!navigator.geolocation) {
    addLog("Browser geolocation is not supported.", "error");
    updateSheet(errorCard("Browser geolocation is not supported.", "Enable location services in your browser or test on a supported mobile browser."));
    return;
  }

  addLog("Requesting current location", "request");

  navigator.geolocation.getCurrentPosition(
    position => {
      const lat = position.coords.latitude;
      const lng = position.coords.longitude;
      const accuracy = Math.round(position.coords.accuracy || 0);

      userLocation = { lat, lng, accuracy };
      drawUserLocation();
      map.flyTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), 14), speed: 0.8 });
      addLog(`Current location set: ${lat.toFixed(5)}, ${lng.toFixed(5)} · accuracy ${accuracy}m`, "success");

      if (currentView === "nearby" || currentView === "forecast") {
        clearMapLayers();
        renderView(currentView).then(drawUserLocation);
      }
    },
    error => {
      addLog(`Location permission failed: ${error.message}`, "error");
      updateSheet(errorCard(`Location permission failed: ${error.message}`));
    },
    {
      enableHighAccuracy: true,
      timeout: 12000,
      maximumAge: 60000
    }
  );
}

function drawUserLocation() {
  if (!map || !userLocation) return;

  const feature = pointFeature(userLocation.lng, userLocation.lat, {
    type: "user",
    accuracy: userLocation.accuracy || 0
  });

  const data = {
    type: "FeatureCollection",
    features: [feature]
  };

  if (map.getSource("user-location-source")) {
    map.getSource("user-location-source").setData(data);
    moveUserLocationLayersToTop();
    return;
  }

  map.addSource("user-location-source", {
    type: "geojson",
    data
  });

  map.addLayer({
    id: "user-location-pulse",
    type: "circle",
    source: "user-location-source",
    paint: {
      "circle-radius": 16,
      "circle-color": "#3b82f6",
      "circle-opacity": 0.22,
      "circle-stroke-color": "#bfdbfe",
      "circle-stroke-width": 1
    }
  });

  map.addLayer({
    id: "user-location-dot",
    type: "circle",
    source: "user-location-source",
    paint: {
      "circle-radius": 7,
      "circle-color": "#2563eb",
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2
    }
  });

  map.addLayer({
    id: "user-location-label",
    type: "symbol",
    source: "user-location-source",
    layout: {
      "text-field": "You",
      "text-size": 11,
      "text-offset": [0, 1.5],
      "text-allow-overlap": true
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#1e3a8a",
      "text-halo-width": 1.6
    }
  });
  moveUserLocationLayersToTop();
}

function moveUserLocationLayersToTop() {
  ["user-location-pulse", "user-location-dot", "user-location-label"].forEach(layerId => {
    if (map.getLayer(layerId)) {
      map.moveLayer(layerId);
    }
  });
}

function hexagonFeature(lng, lat, radiusKm, props) {
  const coordinates = [];
  const latRadius = radiusKm / 111.32;
  const lngRadius = radiusKm / (111.32 * Math.cos(lat * Math.PI / 180));

  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 180) * (60 * i + 30);
    coordinates.push([
      lng + lngRadius * Math.cos(angle),
      lat + latRadius * Math.sin(angle)
    ]);
  }
  coordinates.push(coordinates[0]);

  return {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [coordinates]
    },
    properties: props
  };
}

function bearingDegrees(fromLat, fromLng, toLat, toLng) {
  const phi1 = fromLat * Math.PI / 180;
  const phi2 = toLat * Math.PI / 180;
  const deltaLng = (toLng - fromLng) * Math.PI / 180;
  const y = Math.sin(deltaLng) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) -
    Math.sin(phi1) * Math.cos(phi2) * Math.cos(deltaLng);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

function compassFromBearing(bearing) {
  const directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return directions[Math.round(bearing / 45) % 8];
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
