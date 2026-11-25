import gzip
import json
from pathlib import Path
from shiny import App, ui, reactive, render

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"

# 1. Load routes GeoJSON & points manifest once at startup
with open(DATA_DIR / "routes_lines.geojson", "r", encoding="utf-8") as f:
    ROUTES_GEOJSON = json.load(f)

MANIFEST_PATH = DATA_DIR / "points_manifest.json"
if MANIFEST_PATH.exists():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        POINTS_MANIFEST = json.load(f)
else:
    POINTS_MANIFEST = {}

# Read precomputed dataset totals from points_manifest.json (with fallback)
_totals = POINTS_MANIFEST.get("_totals", {})
TOTAL_UNIQUE_RIDES = _totals.get(
    "total_unique_trips",
    len({
        tid
        for info in POINTS_MANIFEST.values()
        if isinstance(info, dict) and "trips" in info
        for tid in info.get("trips", [])
    }),
)
_total_secs = int(_totals.get("total_duration_sec", 0))
_hrs, _mins = _total_secs // 3600, (_total_secs % 3600) // 60
TOTAL_RECORDED_TIME = f"{_hrs:,} hrs {_mins} mins" if _hrs > 0 else f"{_mins} mins"

# Extract sorted unique route names and trip counts (excluding metadata keys like "_totals")
if POINTS_MANIFEST:
    route_counts = {
        r: len(set(info.get("trips", [])))
        for r, info in POINTS_MANIFEST.items()
        if isinstance(info, dict) and "trips" in info
    }
else:
    route_counts = {}
    for feat in ROUTES_GEOJSON.get("features", []):
        r = feat["properties"].get("route", "Unknown")
        route_counts[r] = route_counts.get(r, 0) + 1

PREFERRED_ORDER = [
    "City Loop",
    "Mt Eden Loop",
    "Epsom",
    "Parnell Loop",
    "Tamaki Drive Loop",
    "Ponsonby Loop",
    "Orakei Loop",
    "Northwestern Cycleway",
]

ROUTE_NAMES = [r for r in PREFERRED_ORDER if r in route_counts] + [
    r for r in sorted(route_counts.keys()) if r not in PREFERRED_ORDER
]

PALETTE = [
    "#00b4d8",  # Electric Cyan
    "#2563eb",  # Cobalt Blue
    "#059669",  # Emerald Green
    "#7c3aed",  # Royal Violet
    "#e11d48",  # Crimson Rose
    "#0d9488",  # Deep Teal
    "#4f46e5",  # Indigo
    "#d97706",  # Amber Gold
]
ROUTE_COLORS = {r: PALETTE[i % len(PALETTE)] for i, r in enumerate(ROUTE_NAMES)}

COLOR_MATCH_EXPR = ["match", ["get", "route"]]
for r, c in ROUTE_COLORS.items():
    COLOR_MATCH_EXPR.extend([r, c])
COLOR_MATCH_EXPR.append("#64748b")

# Chronological order & exact hour definitions for time_of_day
TIME_OF_DAY_ORDER = [
    "Early Morning",
    "Morning Peak",
    "Midday",
    "PM Peak",
    "Evening Off-Peak",
    "Night",
]

TIME_RANGE_MAP = {
    "Early Morning": "5:00 AM - 6:30 AM",
    "Morning Peak": "6:30 AM - 9:30 AM",
    "Midday": "9:30 AM - 3:00 PM",
    "PM Peak": "3:00 PM - 6:30 PM",
    "Evening Off-Peak": "6:30 PM - 10:00 PM",
    "Night": "10:00 PM - 5:00 AM",
}

SEASON_ORDER = ["Summer", "Autumn", "Winter", "Spring"]

# Sensor metadata: column -> (Display Label, Unit, Decimal Places)
SENSOR_META = {
    "pt_conc_pt_cc": ("Ultrafine Particles (UFP)", "pt/cm³", 0),
    "pm2_5_ug_m3": ("PM₂.₅", "µg/m³", 1),
    "pm1_ug_m3": ("PM₁", "µg/m³", 1),
    "pm10_ug_m3": ("PM₁₀", "µg/m³", 1),
    "co2_ppm": ("CO₂", "ppm", 0),
    "voc_ppm": ("VOC", "ppm", 2),
    "aqs": ("Air Quality Score (AQS)", "", 1),
    "temperature_c": ("Ambient Temperature", "°C", 1),
    "humidity_pct": ("Relative Humidity", "%", 1),
    "pressure_mbar": ("Barometric Pressure", "mbar", 1),
    "tgas_c": ("Gas Sensor Temp", "°C", 1),
}

# Viridis-inspired 6-stop palette for map sensor values
VIRIDIS_STOPS = ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"]

# Distinct palette for multi-pollutant time-series lines
TS_COLORS = ["#0284c7", "#e11d48", "#059669", "#7c3aed", "#d97706", "#0d9488"]

# In-memory cache so each route .geojson.gz is only decompressed once per session
_POINTS_CACHE: dict[str, dict] = {}


def load_route_points(route_name: str) -> dict:
    if route_name in _POINTS_CACHE:
        return _POINTS_CACHE[route_name]

    info = POINTS_MANIFEST.get(route_name)
    if not isinstance(info, dict) or "file" not in info:
        return {"type": "FeatureCollection", "features": []}

    file_path = APP_DIR / info["file"]
    if not file_path.exists():
        return {"type": "FeatureCollection", "features": []}

    if str(file_path).endswith(".gz"):
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    else:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    _POINTS_CACHE[route_name] = data
    return data


def clean_tag(val: str) -> str:
    """Formats tags cleanly while preserving uppercase AM/PM."""
    text = str(val).strip().replace("_", " ").title()
    return (
        text.replace("Am ", "AM ")
        .replace("Pm ", "PM ")
        .replace(" Am", " AM")
        .replace(" Pm", " PM")
    )


def format_ride_label(ride_num: int, sample_props: dict) -> str:
    """Builds a human-readable ride label like: Ride 01 · Autumn · Weekday · PM Peak (e-bike)"""
    parts = [f"Ride {ride_num:02d}"]

    for key in ("season", "day_type", "time_of_day"):
        val = sample_props.get(key)
        if val is not None and str(val).strip():
            parts.append(clean_tag(val))

    base = " · ".join(parts)

    ebike_val = sample_props.get("ebike")
    if isinstance(ebike_val, bool):
        if ebike_val:
            base += " (e-bike)"
    elif isinstance(ebike_val, (int, float)) and ebike_val == 1:
        base += " (e-bike)"
    elif isinstance(ebike_val, str) and ebike_val.strip().lower() in ("true", "yes", "1", "ebike", "e-bike"):
        base += " (e-bike)"

    return base


def compute_quantile_stops(values: list[float]) -> tuple[list[float], float, float]:
    """Computes 6 quantile stops between p5 and p95 so outliers don't wash out the scale."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return [0, 1, 2, 3, 4, 5], 0.0, 0.0

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return s[idx]

    v_min, v_max = s[0], s[-1]
    lo, hi = pct(0.05), pct(0.95)
    if hi <= lo:
        lo, hi = v_min, v_max
    if hi <= lo:
        hi = lo + 1.0

    stops = [lo + (hi - lo) * (i / 5.0) for i in range(6)]
    return stops, v_min, v_max


app_ui = ui.page_fillable(
    ui.tags.head(
        ui.tags.link(
            rel="stylesheet",
            href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
        ),
        ui.tags.script(
            src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"
        ),
        ui.tags.script(
            src="https://cdn.plot.ly/plotly-2.35.2.min.js"
        ),
        ui.tags.style(
            """
            body, html { margin: 0; padding: 0; height: 100%; font-family: system-ui, -apple-system, sans-serif; }
            .main-workspace {
                display: flex; flex-direction: column; height: 100%; gap: 8px;
            }
            #map-container {
                position: relative; width: 100%; flex: 1 1 auto; min-height: 320px;
            }
            #map { width: 100%; height: 100%; border-radius: 8px; }
            .ts-drawer {
                flex: 0 0 auto; background: #ffffff; border: 1px solid #e2e8f0;
                border-radius: 8px; padding: 10px 14px;
                box-shadow: 0 -1px 6px rgba(0,0,0,0.04);
            }
            .ts-header {
                display: flex; flex-wrap: wrap; align-items: center;
                justify-content: space-between; gap: 10px; margin-bottom: 4px;
            }
            .ts-tabs {
                display: flex; gap: 6px;
            }
            .ts-tab-btn {
                border: 1px solid #cbd5e1; background: #f8fafc; color: #475569;
                font-size: 12px; font-weight: 600; padding: 4px 12px;
                border-radius: 6px; cursor: pointer; transition: all 0.15s;
            }
            .ts-tab-btn:hover { background: #e2e8f0; color: #0f172a; }
            .ts-tab-btn.active {
                background: #0f172a; border-color: #0f172a; color: #ffffff;
            }
            .legend-item {
                display: flex; align-items: center; justify-content: space-between;
                padding: 5px 8px; border-radius: 6px; cursor: pointer;
                font-size: 13px; color: #334155; transition: background 0.15s;
            }
            .legend-item:hover { background: #f1f5f9; }
            .legend-item.active {
                background: #e2e8f0; font-weight: 600; color: #0f172a;
            }
            .legend-swatch {
                width: 18px; height: 5px; border-radius: 3px;
                margin-right: 8px; flex-shrink: 0;
            }
            .map-overlay-legend {
                position: absolute; bottom: 24px; right: 14px; z-index: 10;
                background: rgba(255, 255, 255, 0.94); backdrop-filter: blur(4px);
                padding: 10px 14px; border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.12);
                font-size: 12px; min-width: 210px; border: 1px solid #e2e8f0;
            }
            .colorbar {
                height: 10px; border-radius: 4px; margin: 6px 0 4px 0;
                background: linear-gradient(to right, #440154, #414487, #2a788e, #22a884, #7ad151, #fde725);
            }
            .colorbar-labels {
                display: flex; justify-content: space-between;
                font-size: 11px; color: #475569; font-variant-numeric: tabular-nums;
            }
            .sidebar-section-title {
                font-size: 13.5px;
                font-weight: 700;
                text-transform: uppercase;
                color: #334155;
                letter-spacing: 0.01em;
            }
            .sidebar-section-sub {
                font-size: 12px;
                font-weight: 400;
                text-transform: none;
                color: #475569;
            }
            .stat-grid {
                display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px;
            }
            .stat-box {
                background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
                padding: 6px 8px;
            }
            .stat-label { font-size: 10.5px; color: #64748b; text-transform: uppercase; }
            .stat-val { font-size: 13px; font-weight: 700; color: #0f172a; }
            .subfilter-row {
                display: grid; grid-template-columns: 1fr 1.25fr; gap: 8px;
            }
            .subfilter-row .form-group { margin-bottom: 10px; }
            .ufp-qc-box {
                margin-top: -6px; margin-bottom: 10px; padding: 6px 10px;
                background: #f8fafc; border-left: 3px solid #2a788e;
                border-radius: 0 6px 6px 0; font-size: 12.5px;
            }
            .ufp-qc-box .form-group { margin-bottom: 0; }
            .maplibregl-popup-content {
                font-family: system-ui, sans-serif; font-size: 12.5px; padding: 8px 12px; line-height: 1.45;
            }
            """
        ),
    ),
    ui.layout_sidebar(
        ui.sidebar(
            ui.h4("Safer Cycling in Tāmaki Makaurau Auckland", style="margin-top:0; font-weight:700;"),
            ui.p(
                "Select a cycling route to explore point-level air quality measurements.",
                style="font-size: 12.5px; color: #475569; margin: -2px 0 10px 0;",
            ),
            ui.output_ui("route_selector_ui"),
            ui.hr(style="margin: 10px 0;"),
            ui.output_ui("drilldown_controls_ui"),
            ui.output_ui("route_summary"),
            width=355,
        ),
        ui.div(
            ui.div(
                ui.div(id="map"),
                ui.output_ui("map_colorbar"),
                id="map-container",
            ),
            ui.div(
                ui.div(
                    ui.output_ui("ride_ts_title_ui"),
                    ui.div(
                        ui.tags.button(
                            "P-Trak (UFP)",
                            id="tab-btn-ptrak",
                            class_="ts-tab-btn active",
                            onclick="window.switchInstrumentTab('ptrak')",
                        ),
                        ui.tags.button(
                            "Vaisala (CO₂ & Gas Temp)",
                            id="tab-btn-vaisala",
                            class_="ts-tab-btn",
                            onclick="window.switchInstrumentTab('vaisala')",
                        ),
                        ui.tags.button(
                            "Atmotube (PM, VOC & Met)",
                            id="tab-btn-atmotube",
                            class_="ts-tab-btn",
                            onclick="window.switchInstrumentTab('atmotube')",
                        ),
                        class_="ts-tabs",
                    ),
                    class_="ts-header",
                ),
                ui.div(id="ride-ts-plot", style="width: 100%; height: 255px;"),
                id="ts-drawer-wrapper",
                class_="ts-drawer",
                style="display: none;",
            ),
            class_="main-workspace",
        ),
        ui.tags.script(
            f"""
            const routesData = {json.dumps(ROUTES_GEOJSON)};
            const colorExpr = {json.dumps(COLOR_MATCH_EXPR)};
            const viridisStops = {json.dumps(VIRIDIS_STOPS)};

            const map = new maplibregl.Map({{
                container: 'map',
                style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
                center: [174.768, -36.855],
                zoom: 12.2
            }});

            document.title = "Safer Cycling Dashboard";

            map.addControl(new maplibregl.NavigationControl(), 'top-right');

            let currentSelected = 'ALL';
            let activeSensor = 'pt_conc_pt_cc';
            let activeSensorLabel = 'Ultrafine Particles (UFP)';
            let activeSensorUnit = 'pt/cm³';
            let activeDecimals = 0;
            let rideLabelsMap = {{}};
            let allRoutesBounds = null;

            map.on('load', () => {{
                // 1. Route lines source & layer (shown only in ALL overview mode)
                map.addSource('routes', {{
                    type: 'geojson',
                    data: routesData
                }});

                map.addLayer({{
                    id: 'routes-lines',
                    type: 'line',
                    source: 'routes',
                    layout: {{
                        'line-join': 'round',
                        'line-cap': 'round',
                        'visibility': 'visible'
                    }},
                    paint: {{
                        'line-color': colorExpr,
                        'line-width': ['interpolate', ['linear'], ['zoom'], 10, 2.0, 13, 3.5, 16, 6.0],
                        'line-opacity': 0.25
                    }}
                }});

                // 2. Sensor points source & layer (shown when a route is selected)
                map.addSource('sensor-points', {{
                    type: 'geojson',
                    data: {{ type: 'FeatureCollection', features: [] }}
                }});

                map.addLayer({{
                    id: 'sensor-circles',
                    type: 'circle',
                    source: 'sensor-points',
                    layout: {{ 'visibility': 'none' }},
                    paint: {{
                        'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 2.2, 13, 3.8, 16, 6.5],
                        'circle-color': '#2a788e',
                        'circle-opacity': 0.85,
                        'circle-stroke-width': 0
                    }}
                }});

                // 3. Highlight marker synced with Plotly time-series hover
                map.addSource('hover-point', {{
                    type: 'geojson',
                    data: {{ type: 'FeatureCollection', features: [] }}
                }});

                map.addLayer({{
                    id: 'hover-highlight',
                    type: 'circle',
                    source: 'hover-point',
                    paint: {{
                        'circle-radius': 8.5,
                        'circle-color': '#f97316',
                        'circle-stroke-width': 3,
                        'circle-stroke-color': '#ffffff',
                        'circle-opacity': 1
                    }}
                }});

                // Fit map bounds to all routes
                const bounds = new maplibregl.LngLatBounds();
                routesData.features.forEach(f => {{
                    f.geometry.coordinates.forEach(coord => bounds.extend(coord));
                }});
                if (!bounds.isEmpty()) {{
                    allRoutesBounds = bounds;
                    map.fitBounds(allRoutesBounds, {{ padding: 45, maxZoom: 14 }});
                }}

                const popup = new maplibregl.Popup({{ closeButton: false, closeOnClick: false }});

                // Hover tooltip for sensor points
                map.on('mousemove', 'sensor-circles', (e) => {{
                    map.getCanvas().style.cursor = 'pointer';
                    if (e.features && e.features.length > 0) {{
                        const p = e.features[0].properties;
                        const rawVal = p[activeSensor];
                        const valStr = (rawVal !== undefined && rawVal !== null)
                            ? Number(rawVal).toFixed(activeDecimals) + (activeSensorUnit ? ' ' + activeSensorUnit : '')
                            : 'N/A';
                        const road = p.road_name || 'Unnamed road';
                        const cyc = p.cycleway ? ` · Cycleway: ${{p.cycleway}}` : '';
                        const rideTitle = rideLabelsMap[p.trip_id] || p.trip_id || '';
                        popup
                            .setLngLat(e.lngLat)
                            .setHTML(
                                `<strong>${{activeSensorLabel}}: ${{valStr}}</strong><br>` +
                                `<span style="color:#334155">${{road}}${{cyc}}</span><br>` +
                                `<span style="color:#64748b; font-size:11.5px">${{rideTitle}}</span>`
                            )
                            .addTo(map);
                    }}
                }});

                map.on('mouseleave', 'sensor-circles', () => {{
                    map.getCanvas().style.cursor = '';
                    popup.remove();
                }});

                // Hover tooltip for route lines (when in ALL overview mode)
                map.on('mousemove', 'routes-lines', (e) => {{
                    if (currentSelected !== 'ALL') return;
                    map.getCanvas().style.cursor = 'pointer';
                    if (e.features && e.features.length > 0) {{
                        const props = e.features[0].properties;
                        popup
                            .setLngLat(e.lngLat)
                            .setHTML(`<strong>${{props.route}}</strong><br><span style="color:#64748b">Click route to view air quality measurements</span>`)
                            .addTo(map);
                    }}
                }});

                map.on('mouseleave', 'routes-lines', () => {{
                    if (currentSelected !== 'ALL') return;
                    map.getCanvas().style.cursor = '';
                    popup.remove();
                }});

                // Click a route on the map to filter to that route
                map.on('click', 'routes-lines', (e) => {{
                    if (currentSelected !== 'ALL') return;
                    if (e.features && e.features.length > 0) {{
                        const clickedRoute = e.features[0].properties.route;
                        Shiny.setInputValue('selected_route', clickedRoute, {{ priority: 'event' }});
                    }}
                }});
            }});

            window.highlightRoute = function(routeName) {{
                if (!map.getLayer('routes-lines') || currentSelected !== 'ALL') return;
                if (!routeName) {{
                    map.setPaintProperty('routes-lines', 'line-opacity', 0.25);
                }} else {{
                    map.setPaintProperty('routes-lines', 'line-opacity', [
                        'case',
                        ['==', ['get', 'route'], routeName], 0.55,
                        0.05
                    ]);
                }}
            }};

            function setMapHoverPoint(coords) {{
                const src = map.getSource('hover-point');
                if (!src) return;
                if (!coords || !Array.isArray(coords) || coords.length < 2) {{
                    src.setData({{ type: 'FeatureCollection', features: [] }});
                    return;
                }}
                src.setData({{
                    type: 'FeatureCollection',
                    features: [{{
                        type: 'Feature',
                        geometry: {{ type: 'Point', coordinates: coords }},
                        properties: {{}}
                    }}]
                }});
            }}

            Shiny.addCustomMessageHandler('set_route', function(routeName) {{
                Shiny.setInputValue('selected_route', routeName, {{ priority: 'event' }});
            }});

            // Update route lines & sensor points from Shiny
            Shiny.addCustomMessageHandler('update_map_points', function(msg) {{
                currentSelected = msg.route;
                setMapHoverPoint(null);
                if (!map.getLayer('routes-lines') || !map.getSource('sensor-points')) return;

                if (msg.route === 'ALL') {{
                    map.setLayoutProperty('routes-lines', 'visibility', 'visible');
                    map.setFilter('routes-lines', null);
                    map.setPaintProperty('routes-lines', 'line-opacity', 0.25);

                    map.setLayoutProperty('sensor-circles', 'visibility', 'none');
                    map.getSource('sensor-points').setData({{ type: 'FeatureCollection', features: [] }});
                    setTimeout(() => {{
                        map.resize();
                        if (allRoutesBounds && !allRoutesBounds.isEmpty()) {{
                            map.fitBounds(allRoutesBounds, {{ padding: 45, maxZoom: 14 }});
                        }}
                    }}, 60);
                }} else {{
                    map.setLayoutProperty('routes-lines', 'visibility', 'none');
                    map.setLayoutProperty('sensor-circles', 'visibility', 'visible');

                    activeSensor = msg.sensor;
                    activeSensorLabel = msg.sensor_label;
                    activeSensorUnit = msg.sensor_unit;
                    activeDecimals = msg.decimals;
                    rideLabelsMap = msg.ride_labels || {{}};

                    const stops = msg.stops;
                    const colorRamp = ['interpolate', ['linear'], ['coalesce', ['get', msg.sensor], stops[0]]];
                    for (let i = 0; i < stops.length; i++) {{
                        colorRamp.push(stops[i], viridisStops[i]);
                    }}

                    map.setPaintProperty('sensor-circles', 'circle-color', colorRamp);
                    map.getSource('sensor-points').setData(msg.geojson);

                    setTimeout(() => {{
                        map.resize();
                        if (msg.geojson.features && msg.geojson.features.length > 0) {{
                            const bounds = new maplibregl.LngLatBounds();
                            msg.geojson.features.forEach(f => bounds.extend(f.geometry.coordinates));
                            if (!bounds.isEmpty()) {{
                                map.fitBounds(bounds, {{ padding: 55, maxZoom: 15 }});
                            }}
                        }}
                    }}, 60);
                }}
            }});

            // Instrument tab state & Plotly rendering for single-ride time-series drawer
            let cachedTripCharts = null;
            let activeInstrumentTab = 'ptrak';

            window.switchInstrumentTab = function(tabName) {{
                activeInstrumentTab = tabName;
                setMapHoverPoint(null);
                ['ptrak', 'vaisala', 'atmotube'].forEach(t => {{
                    const btn = document.getElementById('tab-btn-' + t);
                    if (btn) {{
                        btn.classList.toggle('active', t === tabName);
                    }}
                }});
                renderActiveInstrumentTab(0);
            }};

            function renderActiveInstrumentTab(attempt) {{
                const wrapper = document.getElementById('ts-drawer-wrapper');
                const el = document.getElementById('ride-ts-plot');
                if (!wrapper || !el || !window.Plotly) {{
                    if (cachedTripCharts && !cachedTripCharts.hide_drawer && attempt < 15) {{
                        setTimeout(() => renderActiveInstrumentTab(attempt + 1), 80);
                    }}
                    return;
                }}

                if (!cachedTripCharts || cachedTripCharts.hide_drawer) {{
                    wrapper.style.display = 'none';
                    setMapHoverPoint(null);
                    Plotly.purge(el);
                    return;
                }}

                wrapper.style.display = 'block';
                const tabPayload = cachedTripCharts.tabs[activeInstrumentTab];
                if (!tabPayload || !tabPayload.traces || tabPayload.traces.length === 0) {{
                    Plotly.react(el, [], {{
                        height: 255,
                        paper_bgcolor: 'rgba(0,0,0,0)',
                        plot_bgcolor: '#f8fafc',
                        annotations: [{{
                            text: 'No valid data recorded by this instrument on the selected ride.',
                            xref: 'paper', yref: 'paper', x: 0.5, y: 0.5,
                            showarrow: false, font: {{ size: 13, color: '#64748b' }}
                        }}],
                        xaxis: {{ visible: false }},
                        yaxis: {{ visible: false }}
                    }}, {{ responsive: true, displaylogo: false }});
                    setTimeout(() => map.resize(), 50);
                    return;
                }}

                const plotHeight = activeInstrumentTab === 'atmotube' ? 310 : 240;
                el.style.height = plotHeight + 'px';

                const layout = Object.assign({{
                    height: plotHeight,
                    hovermode: 'x unified',
                    paper_bgcolor: 'rgba(0,0,0,0)',
                    plot_bgcolor: '#f8fafc',
                    font: {{ family: 'system-ui, sans-serif', size: 11.5, color: '#334155' }}
                }}, tabPayload.layout);

                Plotly.react(el, tabPayload.traces, layout, {{
                    responsive: true,
                    displaylogo: false,
                    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d']
                }});

                if (typeof el.removeAllListeners === 'function') {{
                    el.removeAllListeners('plotly_hover');
                    el.removeAllListeners('plotly_unhover');
                }}

                el.on('plotly_hover', function(evt) {{
                    if (!evt || !evt.points || evt.points.length === 0) return;
                    const ptWithCoords = evt.points.find(
                        p => Array.isArray(p.customdata) && Array.isArray(p.customdata[2])
                    );
                    if (ptWithCoords) {{
                        setMapHoverPoint(ptWithCoords.customdata[2]);
                    }}
                }});

                el.on('plotly_unhover', function() {{
                    setMapHoverPoint(null);
                }});

                setTimeout(() => map.resize(), 50);
            }}

            Shiny.addCustomMessageHandler('update_ts_chart', function(msg) {{
                cachedTripCharts = msg;
                if (msg.auto_tab) {{
                    window.switchInstrumentTab(msg.auto_tab);
                }} else {{
                    renderActiveInstrumentTab(0);
                }}
            }});
            """
        ),
    ),
    title="Safer Cycling Dashboard",
)


def server(input, output, session):
    def active_route() -> str:
        return input.selected_route() if "selected_route" in input else "ALL"

    @render.ui
    def route_selector_ui():
        active_r = active_route()

        all_item = ui.div(
            ui.div(
                ui.span(
                    class_="legend-swatch",
                    style="background: linear-gradient(90deg, #00b4d8, #7c3aed, #e11d48, #d97706);",
                ),
                ui.span("Show All Routes"),
                style="display:flex; align-items:center;",
            ),
            ui.span(
                f"{TOTAL_UNIQUE_RIDES}",
                style="color:#64748b; font-size:12px; font-weight:600;",
            ),
            class_="legend-item active" if active_r == "ALL" else "legend-item",
            onclick="Shiny.setInputValue('selected_route', 'ALL', {priority: 'event'});",
        )

        route_items = [
            ui.div(
                ui.div(
                    ui.span(
                        class_="legend-swatch",
                        style=f"background-color: {ROUTE_COLORS[r]};",
                    ),
                    ui.span(r),
                    style="display:flex; align-items:center;",
                ),
                ui.span(
                    f"{route_counts[r]}",
                    style="color:#64748b; font-size:12px; font-weight:600;",
                ),
                class_="legend-item active" if active_r == r else "legend-item",
                onclick=f"Shiny.setInputValue('selected_route', {json.dumps(r)}, {{priority: 'event'}});",
                onmouseenter=f"window.highlightRoute && window.highlightRoute({json.dumps(r)});",
                onmouseleave="window.highlightRoute && window.highlightRoute(null);",
            )
            for r in ROUTE_NAMES
        ]

        return ui.div(
            ui.div(
                ui.span("1. Cycling Routes ", class_="sidebar-section-title"),
                ui.span("(click to select)", class_="sidebar-section-sub"),
            ),
            ui.div(all_item, *route_items, style="margin-top: 4px;"),
        )

    @reactive.calc
    def route_ride_info() -> tuple[dict[str, str], dict[str, dict]]:
        """Returns (trip_id -> formatted ride label, trip_id -> sample properties) for the selected route."""
        r = active_route()
        if r == "ALL":
            return {}, {}

        raw_fc = load_route_points(r)
        sample_by_trip: dict[str, dict] = {}

        for feat in raw_fc.get("features", []):
            props = feat.get("properties", {})
            tid = props.get("trip_id")
            if tid and tid not in sample_by_trip:
                sample_by_trip[tid] = props

        sorted_tids = sorted(sample_by_trip.keys())
        labels = {
            tid: format_ride_label(idx + 1, sample_by_trip[tid])
            for idx, tid in enumerate(sorted_tids)
        }
        return labels, sample_by_trip

    @render.ui
    def drilldown_controls_ui():
        r = active_route()
        if r == "ALL":
            return None

        _, sample_by_trip = route_ride_info()

        # Available seasons on this route
        raw_seasons = {
            clean_tag(p["season"])
            for p in sample_by_trip.values()
            if p.get("season") is not None and str(p["season"]).strip()
        }
        ordered_seasons = [s for s in SEASON_ORDER if s in raw_seasons] + [
            s for s in sorted(raw_seasons) if s not in SEASON_ORDER
        ]
        season_choices = {"ALL": "All Seasons"} | {s: s for s in ordered_seasons}
        prev_season = input.selected_season() if "selected_season" in input else "ALL"
        selected_season = prev_season if prev_season in season_choices else "ALL"

        # Available times of day on this route (formatted with exact hour ranges)
        raw_times = {
            clean_tag(p["time_of_day"])
            for p in sample_by_trip.values()
            if p.get("time_of_day") is not None and str(p["time_of_day"]).strip()
        }
        ordered_times = [t for t in TIME_OF_DAY_ORDER if t in raw_times] + [
            t for t in sorted(raw_times) if t not in TIME_OF_DAY_ORDER
        ]
        time_choices = {"ALL": "All Times"} | {
            t: f"{t} ({TIME_RANGE_MAP[t]})" if t in TIME_RANGE_MAP else t
            for t in ordered_times
        }
        prev_time = input.selected_time_of_day() if "selected_time_of_day" in input else "ALL"
        selected_time = prev_time if prev_time in time_choices else "ALL"

        return ui.div(
            ui.div(
                ui.input_select(
                    "selected_season",
                    ui.span("2a. Time of Year", class_="sidebar-section-title"),
                    choices=season_choices,
                    selected=selected_season,
                ),
                ui.input_select(
                    "selected_time_of_day",
                    ui.span("2b. Time of Day", class_="sidebar-section-title"),
                    choices=time_choices,
                    selected=selected_time,
                ),
                class_="subfilter-row",
            ),
            ui.output_ui("ride_selector_ui"),
            ui.output_ui("sensor_selector_ui"),
            ui.output_ui("ufp_qc_ui"),
            ui.hr(style="margin: 10px 0;"),
        )

    @reactive.calc
    def matching_trip_ids() -> list[str]:
        """Returns sorted trip_ids on the selected route that match 2a (season) and 2b (time_of_day)."""
        r = active_route()
        if r == "ALL":
            return []

        labels_map, sample_by_trip = route_ride_info()
        sel_season = input.selected_season() if "selected_season" in input else "ALL"
        sel_time = input.selected_time_of_day() if "selected_time_of_day" in input else "ALL"

        matched = []
        for tid in sorted(labels_map.keys()):
            props = sample_by_trip.get(tid, {})
            if sel_season != "ALL":
                s_val = clean_tag(props["season"]) if props.get("season") else ""
                if s_val != sel_season:
                    continue
            if sel_time != "ALL":
                t_val = clean_tag(props["time_of_day"]) if props.get("time_of_day") else ""
                if t_val != sel_time:
                    continue
            matched.append(tid)
        return matched

    @render.ui
    def ride_selector_ui():
        """3. Select Ride — filtered by the selected route, season, and time of day."""
        r = active_route()
        if r == "ALL":
            return None

        labels_map, _ = route_ride_info()
        matched_tids = matching_trip_ids()

        sel_season = input.selected_season() if "selected_season" in input else "ALL"
        sel_time = input.selected_time_of_day() if "selected_time_of_day" in input else "ALL"
        all_label = (
            f"Filtered Rides ({len(matched_tids)})"
            if (sel_season != "ALL" or sel_time != "ALL")
            else "All Rides"
        )

        if not matched_tids:
            ride_choices = {"NONE": "No rides match selected season/time"}
        else:
            ride_choices = {"ALL": all_label} | {
                tid: labels_map[tid] for tid in matched_tids
            }

        prev_tid = input.selected_trip() if "selected_trip" in input else "ALL"
        selected_tid = (
            prev_tid
            if prev_tid in ride_choices
            else next(iter(ride_choices.keys()))
        )

        label_block = (
            ui.div(
                ui.div("3. Select Ride", class_="sidebar-section-title"),
                ui.div(
                    "Select one ride to view air quality plots.",
                    class_="sidebar-section-sub",
                    style="margin-top: 2px;",
                ),
            )
            if selected_tid == "ALL"
            else ui.span("3. Select Ride", class_="sidebar-section-title")
        )

        return ui.input_select(
            "selected_trip",
            label_block,
            choices=ride_choices,
            selected=selected_tid,
        )

    @reactive.calc
    def trip_filtered_features() -> list[dict]:
        """Features on the selected route narrowed down by season, time of day, and selected_trip."""
        r = active_route()
        if r == "ALL":
            return []

        matched_set = set(matching_trip_ids())
        if not matched_set:
            return []

        trip = input.selected_trip() if "selected_trip" in input else "ALL"
        if trip == "NONE":
            return []

        raw_fc = load_route_points(r)
        feats = []
        for feat in raw_fc.get("features", []):
            props = feat.get("properties", {})
            tid = props.get("trip_id")
            if tid not in matched_set:
                continue
            if trip != "ALL" and tid != trip:
                continue
            feats.append(feat)
        return feats

    @render.ui
    def sensor_selector_ui():
        """4. Air Quality Measure — only lists measures with valid measurements for the active selection."""
        r = active_route()
        if r == "ALL":
            return None

        feats = trip_filtered_features()
        exclude_warn = input.exclude_low_alc() if "exclude_low_alc" in input else True
        available_sensors: dict[str, str] = {}

        for key, (lbl, unit, _) in SENSOR_META.items():
            has_data = False
            for feat in feats:
                props = feat.get("properties", {})
                if exclude_warn and key == "pt_conc_pt_cc" and props.get("ptconc_lowalcwarning") is not None:
                    continue
                val = props.get(key)
                if val is not None:
                    try:
                        float(val)
                        has_data = True
                        break
                    except (TypeError, ValueError):
                        pass
            if has_data:
                available_sensors[key] = f"{lbl} ({unit})" if unit else lbl

        if not available_sensors:
            available_sensors = {"NONE": "No air quality measurements available"}

        prev_sensor = input.selected_sensor() if "selected_sensor" in input else "pt_conc_pt_cc"
        selected_val = (
            prev_sensor
            if prev_sensor in available_sensors
            else next(iter(available_sensors.keys()))
        )

        return ui.input_select(
            "selected_sensor",
            ui.span("4. Air Quality Measure", class_="sidebar-section-title"),
            choices=available_sensors,
            selected=selected_val,
        )

    @render.ui
    def ufp_qc_ui():
        """Appears directly underneath dropdown #4 ONLY when UFP is selected AND warnings exist in the active selection."""
        r = active_route()
        if r == "ALL":
            return None
        sensor = input.selected_sensor() if "selected_sensor" in input else None
        if sensor != "pt_conc_pt_cc":
            return None

        feats = trip_filtered_features()
        has_warnings = any(
            feat.get("properties", {}).get("ptconc_lowalcwarning") is not None
            for feat in feats
        )
        if not has_warnings:
            return None

        prev_val = input.exclude_low_alc() if "exclude_low_alc" in input else True
        return ui.div(
            ui.input_checkbox(
                "exclude_low_alc",
                "Exclude UFP low-alcohol warnings",
                value=prev_val,
            ),
            class_="ufp-qc-box",
        )

    @reactive.calc
    def filtered_point_data():
        r = active_route()
        if r == "ALL":
            return None

        trip = input.selected_trip() if "selected_trip" in input else "ALL"
        sensor = input.selected_sensor() if "selected_sensor" in input else "pt_conc_pt_cc"
        exclude_warn = input.exclude_low_alc() if "exclude_low_alc" in input else True

        feats = trip_filtered_features()
        filtered_features = []
        values = []

        if sensor and sensor != "NONE":
            for feat in feats:
                props = feat.get("properties", {})
                if exclude_warn and sensor == "pt_conc_pt_cc" and props.get("ptconc_lowalcwarning") is not None:
                    continue

                val = props.get(sensor)
                if val is not None:
                    try:
                        fval = float(val)
                        values.append(fval)
                        filtered_features.append(feat)
                    except (TypeError, ValueError):
                        pass

        stops, v_min, v_max = compute_quantile_stops(values)
        lbl, unit, decimals = SENSOR_META.get(sensor, (sensor or "", "", 2))
        labels_map, _ = route_ride_info()

        median_val = sorted(values)[len(values) // 2] if values else None
        mean_val = (sum(values) / len(values)) if values else None

        return {
            "route": r,
            "trip": trip,
            "sensor": sensor,
            "sensor_label": lbl,
            "sensor_unit": unit,
            "decimals": decimals,
            "stops": stops,
            "v_min": v_min,
            "v_max": v_max,
            "median": median_val,
            "mean": mean_val,
            "count": len(filtered_features),
            "ride_labels": labels_map,
            "geojson": {"type": "FeatureCollection", "features": filtered_features},
        }

    @reactive.effect
    async def _push_map_update():
        r = active_route()
        if r == "ALL":
            await session.send_custom_message("update_map_points", {"route": "ALL"})
            return

        payload = filtered_point_data()
        if payload:
            await session.send_custom_message("update_map_points", payload)

    @render.ui
    def ride_ts_title_ui():
        r = active_route()
        trip = input.selected_trip() if "selected_trip" in input else "ALL"
        if r == "ALL" or trip in ("ALL", "NONE", None):
            return None
        labels_map, _ = route_ride_info()
        ride_title = labels_map.get(trip, trip)
        return ui.div(
            ui.strong("Ride Time-Series Profile", style="font-size: 13px; color: #0f172a;"),
            ui.span(f" · {ride_title}", style="font-size: 12px; color: #64748b;"),
        )

    SENSOR_TO_TAB = {
        "pt_conc_pt_cc": "ptrak",
        "co2_ppm": "vaisala",
        "tgas_c": "vaisala",
        "pm2_5_ug_m3": "atmotube",
        "pm1_ug_m3": "atmotube",
        "pm10_ug_m3": "atmotube",
        "voc_ppm": "atmotube",
        "aqs": "atmotube",
        "temperature_c": "atmotube",
        "humidity_pct": "atmotube",
        "pressure_mbar": "atmotube",
    }

    @reactive.effect
    async def _push_ts_update():
        r = active_route()
        trip = input.selected_trip() if "selected_trip" in input else "ALL"
        if r == "ALL" or trip in ("ALL", "NONE", None):
            await session.send_custom_message("update_ts_chart", {"hide_drawer": True})
            return

        exclude_warn = input.exclude_low_alc() if "exclude_low_alc" in input else True
        active_sensor = input.selected_sensor() if "selected_sensor" in input else None
        auto_tab = SENSOR_TO_TAB.get(active_sensor)

        feats = trip_filtered_features()
        ordered_feats = sorted(
            feats,
            key=lambda ft: float(ft.get("properties", {}).get("elapsed_secs") or 0.0),
        )

        x_mins = [
            round(float(ft.get("properties", {}).get("elapsed_secs") or 0.0) / 60.0, 2)
            for ft in ordered_feats
        ]

        def format_cycleway(val) -> str:
            if val is None or str(val).strip() == "":
                return "No"
            if isinstance(val, bool):
                return "Yes" if val else "No"
            return str(val).strip()

        context_text = [
            format_cycleway(ft.get("properties", {}).get("cycleway"))
            for ft in ordered_feats
        ]

        def build_trace(key: str, color: str, mode: str, yaxis: str = "y", xaxis: str = "x"):
            lbl, unit, dec = SENSOR_META.get(key, (key, "", 2))
            fmt = f"{{:.{dec}f}}"

            xs: list[float] = []
            ys: list[float] = []
            customs: list[list] = []

            for i, ft in enumerate(ordered_feats):
                props = ft.get("properties", {})
                if exclude_warn and key == "pt_conc_pt_cc" and props.get("ptconc_lowalcwarning") is not None:
                    continue
                val = props.get(key)
                if val is None:
                    continue
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    continue

                coords = ft.get("geometry", {}).get("coordinates")
                xs.append(x_mins[i])
                ys.append(fval)
                native_str = f"{fmt.format(fval)} {unit}".strip()
                customs.append([native_str, context_text[i], coords])

            if not ys:
                return None

            tr = {
                "type": "scatter",
                "mode": mode,
                "name": f"{lbl} ({unit})" if unit else lbl,
                "x": xs,
                "y": ys,
                "xaxis": xaxis,
                "yaxis": yaxis,
                "customdata": customs,
                "hovertemplate": (
                    f"<b>{lbl}</b>: %{{customdata[0]}}<br>"
                    "Cycleway: %{customdata[1]}<extra></extra>"
                ),
            }
            if mode == "lines":
                tr["line"] = {"width": 2, "color": color}
            elif mode == "lines+markers":
                tr["line"] = {"width": 1.8, "color": color}
                tr["marker"] = {"size": 4.5, "color": color, "opacity": 0.9}
            else:
                tr["marker"] = {"size": 5.5, "color": color, "opacity": 0.9}
            return tr

        # 1. P-Trak Tab (1 continuous line)
        ptrak_traces = [t for t in [build_trace("pt_conc_pt_cc", "#0284c7", "lines")] if t]
        ptrak_layout = {
            "margin": {"l": 65, "r": 25, "t": 12, "b": 38},
            "showlegend": False,
            "xaxis": {"title": {"text": "Elapsed Ride Time (minutes)", "font": {"size": 11.5}}, "gridcolor": "#e2e8f0", "zeroline": False},
            "yaxis": {"title": {"text": "Ultrafine Particles (pt/cm³)", "font": {"size": 11.5}}, "gridcolor": "#e2e8f0", "zeroline": False},
        }

        # 2. Vaisala Tab (CO2 left axis + Gas Sensor Temp right axis)
        vaisala_traces = [
            t for t in [
                build_trace("co2_ppm", "#059669", "lines+markers", yaxis="y"),
                build_trace("tgas_c", "#e11d48", "lines+markers", yaxis="y2"),
            ] if t
        ]
        vaisala_layout = {
            "margin": {"l": 60, "r": 60, "t": 28, "b": 38},
            "legend": {"orientation": "h", "y": 1.15, "x": 0},
            "xaxis": {"title": {"text": "Elapsed Ride Time (minutes)", "font": {"size": 11.5}}, "gridcolor": "#e2e8f0", "zeroline": False},
            "yaxis": {
                "title": {"text": "CO₂ (ppm)", "font": {"size": 11.5, "color": "#059669"}},
                "tickfont": {"color": "#059669"},
                "gridcolor": "#e2e8f0",
                "zeroline": False,
            },
            "yaxis2": {
                "title": {"text": "Gas Sensor Temp (°C)", "font": {"size": 11.5, "color": "#e11d48"}},
                "tickfont": {"color": "#e11d48"},
                "overlaying": "y",
                "side": "right",
                "showgrid": False,
                "zeroline": False,
            },
        }

        # 3. Atmotube Tab (2x2 synchronized line+marker subplots sharing Elapsed Ride Time)
        atmo_traces = [
            t for t in [
                build_trace("pm1_ug_m3", "#0284c7", "lines+markers", yaxis="y", xaxis="x"),
                build_trace("pm2_5_ug_m3", "#e11d48", "lines+markers", yaxis="y", xaxis="x"),
                build_trace("pm10_ug_m3", "#7c3aed", "lines+markers", yaxis="y", xaxis="x"),
                build_trace("voc_ppm", "#d97706", "lines+markers", yaxis="y2", xaxis="x2"),
                build_trace("aqs", "#059669", "lines+markers", yaxis="y3", xaxis="x2"),
                build_trace("temperature_c", "#dc2626", "lines+markers", yaxis="y4", xaxis="x3"),
                build_trace("humidity_pct", "#0d9488", "lines+markers", yaxis="y5", xaxis="x3"),
                build_trace("pressure_mbar", "#4f46e5", "lines+markers", yaxis="y6", xaxis="x4"),
            ] if t
        ]
        atmo_layout = {
            "margin": {"l": 55, "r": 55, "t": 28, "b": 36},
            "legend": {"orientation": "h", "y": 1.13, "x": 0, "font": {"size": 10.5}},
            "xaxis": {"domain": [0.0, 0.44], "anchor": "y", "matches": "x3", "showticklabels": False, "gridcolor": "#e2e8f0"},
            "yaxis": {"domain": [0.56, 1.0], "anchor": "x", "title": {"text": "PM (µg/m³)", "font": {"size": 10.5}}, "gridcolor": "#e2e8f0", "zeroline": False},
            "xaxis2": {"domain": [0.54, 0.94], "anchor": "y2", "matches": "x4", "showticklabels": False, "gridcolor": "#e2e8f0"},
            "yaxis2": {"domain": [0.56, 1.0], "anchor": "x2", "title": {"text": "VOC (ppm)", "font": {"size": 10.5, "color": "#d97706"}}, "tickfont": {"color": "#d97706"}, "gridcolor": "#e2e8f0", "zeroline": False},
            "yaxis3": {"domain": [0.56, 1.0], "anchor": "x2", "overlaying": "y2", "side": "right", "title": {"text": "AQS", "font": {"size": 10.5, "color": "#059669"}}, "tickfont": {"color": "#059669"}, "showgrid": False, "zeroline": False},
            "xaxis3": {"domain": [0.0, 0.44], "anchor": "y4", "title": {"text": "Elapsed Time (min)", "font": {"size": 10.5}}, "gridcolor": "#e2e8f0"},
            "yaxis4": {"domain": [0.0, 0.44], "anchor": "x3", "title": {"text": "Temp (°C)", "font": {"size": 10.5, "color": "#dc2626"}}, "tickfont": {"color": "#dc2626"}, "gridcolor": "#e2e8f0", "zeroline": False},
            "yaxis5": {"domain": [0.0, 0.44], "anchor": "x3", "overlaying": "y4", "side": "right", "title": {"text": "Humidity (%)", "font": {"size": 10.5, "color": "#0d9488"}}, "tickfont": {"color": "#0d9488"}, "showgrid": False, "zeroline": False},
            "xaxis4": {"domain": [0.54, 0.94], "anchor": "y6", "matches": "x3", "title": {"text": "Elapsed Time (min)", "font": {"size": 10.5}}, "gridcolor": "#e2e8f0"},
            "yaxis6": {"domain": [0.0, 0.44], "anchor": "x4", "title": {"text": "Pressure (mbar)", "font": {"size": 10.5, "color": "#4f46e5"}}, "tickfont": {"color": "#4f46e5"}, "gridcolor": "#e2e8f0", "zeroline": False},
        }

        await session.send_custom_message(
            "update_ts_chart",
            {
                "hide_drawer": False,
                "auto_tab": auto_tab,
                "tabs": {
                    "ptrak": {"traces": ptrak_traces, "layout": ptrak_layout},
                    "vaisala": {"traces": vaisala_traces, "layout": vaisala_layout},
                    "atmotube": {"traces": atmo_traces, "layout": atmo_layout},
                },
            },
        )

    @render.ui
    def map_colorbar():
        payload = filtered_point_data()
        if not payload or payload["count"] == 0:
            return None

        dec = payload["decimals"]
        unit = payload["sensor_unit"]
        lo, hi = payload["stops"][0], payload["stops"][-1]
        fmt = f"{{:.{dec}f}}"

        return ui.div(
            ui.strong(
                f"{payload['sensor_label']} {f'({unit})' if unit else ''}",
                style="font-size: 12px; color: #0f172a;",
            ),
            ui.div(class_="colorbar"),
            ui.div(
                ui.span(f"≤ {fmt.format(lo)} (P5)"),
                ui.span(f"≥ {fmt.format(hi)} (P95)"),
                class_="colorbar-labels",
            ),
            class_="map-overlay-legend",
        )

    @render.ui
    def route_summary():
        r = active_route()
        if r == "ALL":
            return ui.div(
                ui.p(
                    ui.strong("Viewing: "),
                    f"All Routes ({len(ROUTE_COLORS)} routes · {TOTAL_UNIQUE_RIDES} unique rides · {TOTAL_RECORDED_TIME} recorded)",
                    style="margin-bottom: 0; font-size: 12.5px;",
                ),
                class_="stats-box",
            )

        payload = filtered_point_data()
        if not payload or payload["count"] == 0:
            return ui.div(
                ui.strong(r, style=f"color: {ROUTE_COLORS.get(r, '#0f172a')};"),
                ui.p("No valid measurements for this selection.", style="font-size: 12px; color: #64748b;"),
                ui.input_action_button("reset_route", "Show All Routes", class_="btn-sm btn-outline-secondary w-100"),
            )

        dec = payload["decimals"]
        unit = f" {payload['sensor_unit']}" if payload["sensor_unit"] else ""
        fmt = f"{{:.{dec}f}}"

        return ui.div(
            ui.strong(r, style=f"color: {ROUTE_COLORS.get(r, '#0f172a')};"),
            ui.div(
                f"{payload['count']:,} GPS points · {payload['sensor_label']}",
                style="font-size: 11.5px; color: #475569; margin-top: 2px;",
            ),
            ui.div(
                ui.div(
                    ui.div("Median", class_="stat-label"),
                    ui.div(f"{fmt.format(payload['median'])}{unit}", class_="stat-val"),
                    class_="stat-box",
                ),
                ui.div(
                    ui.div("Mean", class_="stat-label"),
                    ui.div(f"{fmt.format(payload['mean'])}{unit}", class_="stat-val"),
                    class_="stat-box",
                ),
                ui.div(
                    ui.div("Min", class_="stat-label"),
                    ui.div(f"{fmt.format(payload['v_min'])}{unit}", class_="stat-val"),
                    class_="stat-box",
                ),
                ui.div(
                    ui.div("Max", class_="stat-label"),
                    ui.div(f"{fmt.format(payload['v_max'])}{unit}", class_="stat-val"),
                    class_="stat-box",
                ),
                class_="stat-grid",
            ),
            ui.input_action_button(
                "reset_route",
                "Show All Routes",
                class_="btn-sm btn-outline-secondary w-100",
                style="margin-top: 10px;",
            ),
        )

    @reactive.effect
    @reactive.event(input.reset_route)
    async def _reset():
        await session.send_custom_message("set_route", "ALL")


app = App(app_ui, server)